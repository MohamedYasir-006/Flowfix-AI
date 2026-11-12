"""Application errors with machine-readable reason codes."""


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 400, reason_codes: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reason_codes = reason_codes or []


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404, reason_codes=["NOT_FOUND"])


class ConflictError(ApiError):
    def __init__(self, message: str, reason_codes: list[str] | None = None):
        super().__init__(message, status_code=409, reason_codes=reason_codes or ["CONFLICT"])


class UnauthorizedError(ApiError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, status_code=401, reason_codes=["UNAUTHORIZED"])


class ForbiddenError(ApiError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, status_code=403, reason_codes=["FORBIDDEN"])
