import base64
import json

import httpx
import pytest
import yaml
from dify_plugin.entities.tool import ToolProviderConfiguration
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin.file.file import File

from provider.resend import ResendProvider, validate_api_key
from tools import send_email
from tools.send_email import SendEmailTool, ToolInvokeError, build_payload


@pytest.fixture
def parameters():
    return {"from": "Sender <sender@example.com>", "to": "to@example.com", "subject": "Report", "html": "<h1>Hello</h1>"}


def make_file(content=b"example", **metadata):
    file = File(url="https://files.example.test/report", type="document", **metadata)
    file._blob = content
    return file


def mock_api(monkeypatch, status=200, result=None, error=None):
    requests = []
    original_client = httpx.Client

    def handler(request):
        requests.append(request)
        if error:
            raise error
        return httpx.Response(status, json=result if result is not None else {"id": "email-123"})

    monkeypatch.setattr(send_email.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    return requests


@pytest.mark.parametrize("key", [None, "", "sk_secret", "re_bad\nkey", 123, "re_"])
def test_reject_invalid_key(key):
    with pytest.raises(ToolProviderCredentialValidationError):
        validate_api_key(key)


def test_provider_validation_does_not_send(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Credential setup must not call the API"))
    assert validate_api_key(" re_test-key ") == "re_test-key"
    ResendProvider()._validate_credentials({"api_key": "re_test"})


def test_html_attachments_and_recipients(monkeypatch, parameters):
    parameters.update({
        "to": "one@example.com; two@example.com\nthree@example.com",
        "cc": "cc@example.com", "bcc": "hidden@example.com", "reply_to": "reply@example.com",
        "text": "Hello", "idempotency_key": "report/123",
        "attachments": [make_file(b"\x00\xffPDF", filename="report.pdf", mime_type="application/pdf"), make_file(b"", filename="empty.txt")],
    })
    requests = mock_api(monkeypatch)
    messages = list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer re_test"
    assert request.headers["Idempotency-Key"] == "report/123"
    payload = json.loads(request.content)
    assert payload["html"] == "<h1>Hello</h1>"
    assert payload["text"] == "Hello"
    assert len(payload["to"]) == 3
    assert payload["bcc"] == ["hidden@example.com"]
    assert payload["cc"] == ["cc@example.com"]
    assert payload["reply_to"] == ["reply@example.com"]
    assert base64.b64decode(payload["attachments"][0]["content"]) == b"\x00\xffPDF"
    assert payload["attachments"][0]["content_type"] == "application/pdf"
    assert payload["attachments"][1]["content"] == ""
    assert messages[0].message.json_object == {"id": "email-123", "status": "accepted", "attachment_count": 2}
    assert "re_test" not in str(messages)
    assert "hidden@example.com" not in str(messages)


def test_text_only_and_optional_fields(parameters):
    parameters.pop("html")
    parameters["text"] = "Plain email"
    payload = build_payload(parameters)
    assert payload["text"] == "Plain email"
    assert not {"html", "attachments", "cc", "bcc", "reply_to"} & payload.keys()


@pytest.mark.parametrize("field,value", [("from", ""), ("to", "; ,"), ("subject", ""), ("html", " "), ("subject", "bad\nheader"), ("from", "bad\rheader"), ("to", ["a@example.com"]), ("attachments", ["/etc/passwd"])])
def test_invalid_parameters(parameters, field, value):
    parameters[field] = value
    with pytest.raises(ToolInvokeError):
        build_payload(parameters)


def test_recipient_limit(parameters):
    parameters["to"] = ",".join(f"user{index}@example.com" for index in range(50))
    assert len(build_payload(parameters)["to"]) == 50
    parameters["cc"] = "extra@example.com"
    with pytest.raises(ToolInvokeError, match="50"):
        build_payload(parameters)


def test_attachment_names(parameters):
    parameters["attachments"] = [make_file(filename="../report.pdf"), make_file(extension=".txt")]
    attachments = build_payload(parameters)["attachments"]
    assert attachments[0]["filename"] == "report.pdf"
    assert attachments[1]["filename"] == "attachment-2.txt"


def test_attachment_size_before_read(parameters, monkeypatch):
    monkeypatch.setattr(File, "blob", property(lambda self: pytest.fail("Oversized file must not be downloaded")))
    parameters["attachments"] = [make_file(size=send_email.MAX_FILE_BYTES + 1)]
    with pytest.raises(ToolInvokeError, match="28 MB"):
        build_payload(parameters)


def test_attachment_actual_total_size(parameters, monkeypatch):
    monkeypatch.setattr(send_email, "MAX_FILE_BYTES", 5)
    parameters["attachments"] = [make_file(b"123"), make_file(b"456", size=1)]
    with pytest.raises(ToolInvokeError, match="28 MB"):
        build_payload(parameters)


def test_attachment_failure_is_sanitized(parameters, monkeypatch):
    def fail(self):
        raise ValueError("signed URL secret")
    monkeypatch.setattr(File, "blob", property(fail))
    parameters["attachments"] = [make_file()]
    with pytest.raises(ToolInvokeError, match="Cannot read") as error:
        build_payload(parameters)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("status", [400, 401, 403, 409, 413, 422, 429, 500, 302])
def test_api_errors_are_safe_and_not_retried(monkeypatch, parameters, status):
    requests = mock_api(monkeypatch, status, {"message": "re_secret and private HTML"})
    with pytest.raises(ToolInvokeError, match=f"HTTP {status}") as error:
        list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))
    assert len(requests) == 1
    assert "re_secret" not in str(error.value)


def test_timeout_has_unknown_delivery_status(monkeypatch, parameters):
    requests = mock_api(monkeypatch, error=httpx.ReadTimeout("sensitive details"))
    with pytest.raises(ToolInvokeError, match="delivery is unknown"):
        list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))
    assert len(requests) == 1


@pytest.mark.parametrize("result", [{}, [], {"id": ""}, {"id": 12}])
def test_missing_response_id(monkeypatch, parameters, result):
    mock_api(monkeypatch, result=result)
    with pytest.raises(ToolInvokeError, match="no email ID"):
        list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))


@pytest.mark.parametrize("key", ["bad\nkey", "has space", "x" * 257, "non-ascii-é"])
def test_bad_idempotency_key(monkeypatch, parameters, key):
    parameters["idempotency_key"] = key
    requests = mock_api(monkeypatch)
    with pytest.raises(ToolInvokeError, match="Idempotency key"):
        list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))
    assert not requests


def test_request_size_checked_before_send(monkeypatch, parameters):
    monkeypatch.setattr(send_email, "MAX_PAYLOAD_BYTES", 1)
    requests = mock_api(monkeypatch)
    with pytest.raises(ToolInvokeError, match="39 MB"):
        list(SendEmailTool.from_credentials({"api_key": "re_test"})._invoke(parameters))
    assert not requests


def test_sdk_provider_schema():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    provider = ToolProviderConfiguration.model_validate(yaml.safe_load((root / "provider/resend.yaml").read_text()))
    assert provider.identity.name == "resend"
