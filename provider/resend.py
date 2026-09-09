from typing import Any
import re

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


def validate_api_key(api_key: Any) -> str:
    if not isinstance(api_key, str) or not re.fullmatch(r"re_[A-Za-z0-9_-]+", api_key.strip()):
        raise ToolProviderCredentialValidationError("Enter a Resend API key beginning with re_.")
    return api_key.strip()


class ResendProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        validate_api_key(credentials.get("api_key"))
