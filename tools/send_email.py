from collections.abc import Generator
import base64
import json
import mimetypes
import re
from typing import Any

import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File

from provider.resend import validate_api_key


MAX_PAYLOAD_BYTES = 39_000_000
MAX_FILE_BYTES = 28_000_000


class ToolInvokeError(ValueError):
    pass


def text_parameter(parameters: dict[str, Any], name: str, required: bool = False) -> str:
    value = parameters.get(name) or ""
    if not isinstance(value, str):
        raise ToolInvokeError(f"{name} must be text.")
    if required and not value.strip():
        raise ToolInvokeError(f"{name} is required.")
    return value


def recipients(value: str) -> list[str]:
    return [address.strip() for address in re.split(r"[,;\n]+", value) if address.strip()]


def build_payload(parameters: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "from": text_parameter(parameters, "from", True).strip(),
        "to": recipients(text_parameter(parameters, "to", True)),
        "subject": text_parameter(parameters, "subject", True),
    }
    if not payload["to"]:
        raise ToolInvokeError("At least one To recipient is required.")
    for name in ("from", "subject"):
        if any(character in payload[name] for character in ("\r", "\n")):
            raise ToolInvokeError(f"{name} must not contain line breaks.")
    for name in ("cc", "bcc", "reply_to"):
        addresses = recipients(text_parameter(parameters, name))
        if addresses:
            payload[name] = addresses
    if sum(len(payload.get(name, [])) for name in ("to", "cc", "bcc")) > 50:
        raise ToolInvokeError("Use at most 50 combined To, CC and BCC recipients.")
    for name in ("html", "text"):
        value = text_parameter(parameters, name)
        if value.strip():
            payload[name] = value
    if not payload.get("html") and not payload.get("text"):
        raise ToolInvokeError("Provide an HTML body or a plain text body.")
    attachments = parameters.get("attachments") or []
    if not isinstance(attachments, list) or any(not isinstance(file, File) for file in attachments):
        raise ToolInvokeError("Attachments must be Dify file variables, not paths or URLs.")
    encoded_files = []
    total_bytes = 0
    for index, file in enumerate(attachments, start=1):
        if file.size is not None and file.size > MAX_FILE_BYTES - total_bytes:
            raise ToolInvokeError("Attachments exceed the plugin's 28 MB total raw-file limit.")
        try:
            content = file.blob
        except Exception:
            raise ToolInvokeError("Cannot read an attachment. Check the Dify file URL and its availability.") from None
        total_bytes += len(content)
        if total_bytes > MAX_FILE_BYTES:
            raise ToolInvokeError("Attachments exceed the plugin's 28 MB total raw-file limit.")
        filename = (file.filename or f"attachment-{index}{file.extension or ''}").replace("\\", "/").rsplit("/", 1)[-1]
        if not filename or any(ord(character) < 32 for character in filename):
            raise ToolInvokeError("Attachment filename is empty or contains control characters.")
        encoded_files.append({
            "filename": filename,
            "content": base64.b64encode(content).decode("ascii"),
            "content_type": file.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        })
    if encoded_files:
        payload["attachments"] = encoded_files
    return payload


class SendEmailTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        api_key = validate_api_key(self.runtime.credentials.get("api_key"))
        idempotency_key = text_parameter(tool_parameters, "idempotency_key").strip()
        if idempotency_key and (len(idempotency_key) > 256 or not all(33 <= ord(character) <= 126 for character in idempotency_key)):
            raise ToolInvokeError("Idempotency key must contain 1–256 printable ASCII characters without spaces.")
        payload = build_payload(tool_parameters)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ToolInvokeError("Encoded email exceeds the plugin's 39 MB request limit. Reduce attachments or body size.")
        headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with httpx.Client(timeout=60.0, follow_redirects=False) as client:
                response = client.post("https://api.resend.com/emails", headers=headers, content=body)
        except httpx.RequestError:
            raise ToolInvokeError("Resend request failed; delivery is unknown. Retry with the same idempotency key to avoid duplicates.") from None
        if not 200 <= response.status_code < 300:
            reasons = {
                400: "Check recipients, sender, body and attachment types.",
                401: "The API key is invalid or revoked.",
                403: "Check the API key permissions, verified sender domain and account sending restrictions.",
                409: "Idempotency conflict: reuse the key only with the identical email payload.",
                413: "Email is too large; reduce body or attachment sizes.",
                422: "Check email fields, attachment types and idempotency key.",
                429: "Rate or sending quota limit reached. Retry later with the same idempotency key.",
            }
            reason = reasons.get(response.status_code, "Check Resend status and logs; retry with the same idempotency key if needed.")
            raise ToolInvokeError(f"Resend HTTP {response.status_code}: {reason}")
        try:
            result = response.json()
        except ValueError:
            raise ToolInvokeError("Resend returned an unreadable response; delivery is unknown. Reuse the same idempotency key for retries.") from None
        if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
            raise ToolInvokeError("Resend returned no email ID; delivery is unknown. Reuse the same idempotency key for retries.")
        yield self.create_json_message({"id": result["id"], "status": "accepted", "attachment_count": len(payload.get("attachments", []))})
        yield self.create_text_message(f"Email accepted by Resend. ID: {result['id']}")
