from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigError(AppError):
    code = "internal_error"
    status_code = 500


class ProxyError(AppError):
    code = "provider_error"
    status_code = 502


class TimeoutError(AppError):
    code = "timeout"
    status_code = 504


class FlowGenerationError(AppError):
    code = "invalid_generation_result"
    status_code = 422


class ModelUnavailableError(AppError):
    code = "internal_error"
    status_code = 500


class InvalidRequestError(AppError):
    code = "invalid_request"
    status_code = 400
