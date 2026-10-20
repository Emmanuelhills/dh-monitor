"""Structured error responses: ``{"error": {"code", "message", "details"}}``."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | list | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(what: str = "Record") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")),
                "message": err.get("msg", "Invalid value").removeprefix("Value error, "),
            }
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_body("validation_error", "Invalid request.", details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        details = None
        if exc.status_code == 404:
            # Helps diagnose proxy/rewrite setups: which path did the app actually receive?
            details = {
                "path": request.scope.get("path"),
                "root_path": request.scope.get("root_path") or "",
                "query_keys": sorted(request.query_params.keys()),
            }
        return JSONResponse(
            status_code=exc.status_code, content=_body(f"http_{exc.status_code}", str(exc.detail), details)
        )
