from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PaymentRequired(AppError):
    status_code = 402
    code = "insufficient_credits"


class IntegrationRequired(AppError):
    status_code = 409
    code = "integration_required"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Invalid request", "details": {"errors": errors}}},
        )
