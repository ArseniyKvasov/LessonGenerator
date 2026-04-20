class AppError(Exception):
    code = "app_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigError(AppError):
    code = "config_error"


class ProxyError(AppError):
    code = "proxy_error"


class FlowGenerationError(AppError):
    code = "flow_generation_error"


class ModelUnavailableError(AppError):
    code = "model_unavailable_error"
