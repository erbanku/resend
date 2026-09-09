# Resend

Native Dify tool plugin `erbanku/resend`, version `0.0.1`. Send HTML or plain-text email with uploaded Dify files using your own Resend API key. No OAuth or Microsoft account is needed.

## Install and configure

1. In Dify, open **Plugins → Install from local package** and select `artifacts/resend-0.0.1.difypkg`.
2. Authorize the Resend provider with your API key (`re_...`). Sending-access keys, including domain-restricted keys, and full-access keys are supported.
3. Add the **Resend → Send Email** tool to a workflow.
4. Fill **From**, **To**, **Subject**, and **HTML Body** or **Plain Text Body**. Use a sender on a domain verified in your Resend account. Account testing restrictions still apply.
5. To attach files, add a file-list input to your workflow and bind its file variable (or a previous node's file output) to **Attachments**. Do not paste local paths or arbitrary URLs into this field.
6. Run the workflow. The JSON output contains `id`, `status: accepted`, and `attachment_count`. Accepted means Resend accepted the request, not that the email reached the inbox.

Credential setup checks key format locally and never sends a test message. Because sending-only keys cannot access read-only administrative endpoints, API authorization and sender-domain permissions are checked by Resend on the first send. A revoked but well-formed key can therefore be saved and will fail when used.

## Inputs

| Field | Required | Description |
| --- | --- | --- |
| From | Yes | `Reports <reports@example.com>` or a sender address on your verified domain |
| To | Yes | Bare addresses separated by commas, semicolons or newlines |
| Subject | Yes | Email subject, without line breaks |
| HTML Body | One body required | HTML is sent as provided, without escaping or rewriting |
| Plain Text Body | One body required | Optional alternative to HTML, or a text-only message |
| Attachments | No | Dify file-list variable; files are read through the SDK and Base64 encoded |
| CC / BCC | No | Optional addresses using the same separators as To |
| Reply To | No | Optional reply-to addresses |
| Idempotency Key | No | Stable unique key per logical email, e.g. `monthly-report/2026-09/customer-123` |

The plugin leaves the user's sender, subject and message unchanged; it does not add branding or a subject prefix. HTML and text can both be supplied for multipart alternatives. There is a conservative limit of 50 combined To/CC/BCC recipients, 28 MB total raw attachments and 39 MB encoded JSON per request. Resend applies its own final message-size and attachment-type restrictions. The plugin runtime must be able to reach both `api.resend.com` and Dify's file URLs; expired or inaccessible files fail the entire send before contacting Resend.

## Retry safety and errors

Use a stable idempotency key whenever a workflow might retry. Resend retains keys for 24 hours; the same key must only be reused with the identical email payload. Keys are limited here to 256 printable ASCII characters without spaces. There are no automatic retries. A timeout or malformed success response can mean the email was accepted even though the response was lost; check Resend logs and retry with the original key rather than inventing a new one.

API failures raise workflow errors with the HTTP status and actionable guidance. Raw response bodies, API keys, email content, attachment download URLs and BCC addresses are not echoed into errors or success outputs. This plugin only sends email; it does not implement delivery tracking, inbound email, draft management or batch sending.

## Development and packaging

From the repository root:

```bash
uv sync --directory ai-pkgs/resend --all-groups --python 3.12
python .agents/skills/dify-plugin-generator-by-erbanku/scripts/validate_plugin.py ai-pkgs/resend --with-pytest --with-offline-check
python .agents/skills/dify-plugin-generator-by-erbanku/scripts/package_plugin.py ai-pkgs/resend --cli-path /usr/local/bin/dify
```

Runtime wheels are bundled for Linux amd64 and arm64 with Python 3.12. The deployment package uses `requirements.txt` with the wheelhouse, excluding the development `pyproject.toml`, virtual environment and lockfile. Offline installation does not mean offline email sending. Packaging preserves existing versioned artifacts and bumps the patch version if necessary.

Tests mock the Resend HTTP API and Dify file contents; they do not send real email. They cover provider validation, SDK YAML schemas, HTML/text bodies, multiple binary files, limits, recipient parsing, safe failures and idempotency headers.

## References and branding

- Resend send API: https://resend.com/docs/api-reference/emails/send-email
- API key permissions: https://resend.com/docs/api-reference/api-keys/create-api-key
- Idempotency: https://resend.com/docs/dashboard/emails/idempotency-keys
- Official brand page: https://resend.com/brand
- Light-mode icon downloaded from https://cdn.resend.com/brand/resend-icon-black.svg
- Dark-mode icon downloaded from https://cdn.resend.com/brand/resend-icon-white.svg

Icons were retrieved on September 6, 2026; the Resend name and marks belong to their owners. This is an independent integration, not an official Resend plugin. The local Outlook send and attachment tools provided the Dify reference pattern; `outlook-next` was not present in this checkout.

See `PRIVACY.md` for data handling.
