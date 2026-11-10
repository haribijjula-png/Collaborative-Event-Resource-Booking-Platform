import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message=None, code=None, status_code=None, details=None):
        self.message = message or "Request failed."
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        super().__init__(self.message)


def _err(status, code, message, details=None):
    body = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


class BadRequest(AppError): status_code, code = 400, "BAD_REQUEST"
class Unauthorized(AppError): status_code, code = 401, "UNAUTHORIZED"
class Forbidden(AppError): status_code, code = 403, "FORBIDDEN"
class NotFound(AppError): status_code, code = 404, "NOT_FOUND"
class Conflict(AppError): status_code, code = 409, "CONFLICT"


def E(status: int, code: str, message: str) -> AppError:
    return AppError(message, code=code, status_code=status)


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _err(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        codes = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 409: "CONFLICT"}
        return _err(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return _err(422, "VALIDATION_ERROR", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return _err(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred.")
