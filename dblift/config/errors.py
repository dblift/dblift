"""Shared configuration exceptions."""


class ConfigurationError(ValueError, AttributeError):
    """Raised when configuration cannot be built or validated."""
