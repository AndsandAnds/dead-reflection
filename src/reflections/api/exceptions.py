from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette import status

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


def configure_global_exception_handlers(app: FastAPI) -> FastAPI:
    @app.exception_handler(BaseServiceException)
    async def service_exception_handler(
        request: Request, exc: BaseServiceException
    ) -> JSONResponse:
        if isinstance(exc, BaseServiceNotFoundException):
            code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, BaseServiceUnProcessableException):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        else:
            code = status.HTTP_400_BAD_REQUEST

        return JSONResponse(
            status_code=code,
            content={
                "exception": {
                    "code": code,
                    "message": exc.message,
                    "details": exc.details,
                    "path": request.url.path,
                    "method": request.method,
                }
            },
        )

    return app
