# Privacy

This plugin sends the sender, recipients, subject, HTML/text body and selected attachment contents to Resend over HTTPS, authenticated with the API key configured in Dify. Optional reply-to addresses and an idempotency key are also sent when supplied.

Files are fetched through the Dify SDK from the file URLs provided by Dify, then encoded in memory for transmission. Use only trusted Dify file variables. No separate credential or message store is created by the plugin, and no analytics or telemetry is added. Dify and Resend may retain workflow execution records, email data and logs according to their own configuration and policies.

The API key is used only for requests to the fixed Resend API endpoint, never for attachment downloads. HTTP redirects from the Resend endpoint are not followed. Provider setup performs local key-format validation without an API call or test email. Runtime errors omit raw API responses and file URLs; success outputs contain only the email ID, acceptance status and attachment count.

Use a sending-only, domain-restricted key where possible. Configure retention and access controls in Dify and Resend to match the sensitivity of your email contents and attachments.
