from __future__ import annotations


class A2AError(Exception):
    """Base class for all A2A protocol errors."""

    code: str
    http_status: int

    def __init__(self, message: str, code: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    def to_wire(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "details": [],
            }
        }


class VersionNotSupportedError(A2AError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "VERSION_NOT_SUPPORTED", 400)


class ParseError(A2AError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "INVALID_ARGUMENT", 400)


class ValidationError(A2AError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "INVALID_ARGUMENT", 400)


class AuthError(A2AError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "AUTHENTICATION_REQUIRED", 401)


class UnsupportedOperationError(A2AError):
    def __init__(self, message: str = "Operation not supported in v0.1") -> None:
        super().__init__(message, "UNSUPPORTED_OPERATION", 501)


class ToolNotFoundError(A2AError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "NOT_FOUND", 404)
