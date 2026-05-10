"""Project-level exceptions."""


class OpenPilotError(Exception):
    """Base exception for OpenPilot errors."""


class MissingAPIKeyError(OpenPilotError):
    """Raised when an LLM request is attempted without an API key."""


class LLMTimeoutError(OpenPilotError):
    """Raised when the configured LLM provider times out."""


class LLMProviderError(OpenPilotError):
    """Raised when the configured LLM provider returns an error."""


class InvalidLLMResponseError(OpenPilotError):
    """Raised when an LLM response cannot be parsed or validated."""


