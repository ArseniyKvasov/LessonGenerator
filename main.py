from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_env
from app.errors import AppError, ConfigError
from app.flow_service import FlowService
from app.model_availability import ensure_base_capacity, get_unavailable_models
from app.model_strategy import SIMPLE_MODELS, STRONG_MODELS
from app.schemas import ErrorResponse, HealthResponse, LessonFlowRequest, LessonFlowResponse

logging.basicConfig(
    level=getattr(logging, get_env("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lesson-generator")

app = FastAPI(
    title="Lesson Generator API",
    version="1.1.0",
    description="Production-ready API for generating structured lesson flows.",
)


def _error_payload(request_id: str, code: str, message: str) -> dict:
    return ErrorResponse(code=code, message=message, request_id=request_id).model_dump()


@app.middleware("http")
async def request_context_and_auth_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id

    expected_api_key = get_env("APP_API_KEY")
    if not expected_api_key:
        logger.error("config_error request_id=%s message=APP_API_KEY is not configured", request_id)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request_id=request_id,
                code="config_error",
                message="APP_API_KEY is not configured",
            ),
        )

    provided_api_key = request.headers.get("X-API-Key", "").strip()
    auth_header = request.headers.get("Authorization", "")
    if not provided_api_key and auth_header.lower().startswith("bearer "):
        provided_api_key = auth_header[7:].strip()

    if provided_api_key != expected_api_key:
        logger.warning(
            "auth_error request_id=%s method=%s path=%s message=invalid API key",
            request_id,
            request.method,
            request.url.path,
        )
        response = JSONResponse(
            status_code=401,
            content=_error_payload(
                request_id=request_id,
                code="unauthorized",
                message="Valid API key is required",
            ),
        )
        response.headers["X-Request-ID"] = request_id
        return response

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    request_id = getattr(request.state, "request_id", "unknown")
    status_code = 500 if isinstance(exc, ConfigError) else 503
    logger.error("app_error request_id=%s code=%s message=%s", request_id, exc.code, exc.message)
    return JSONResponse(
        status_code=status_code,
        content=_error_payload(request_id=request_id, code=exc.code, message=exc.message),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("validation_error request_id=%s details=%s", request_id, exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            request_id=request_id,
            code="validation_error",
            message="Request payload is invalid",
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("unhandled_error request_id=%s", request_id, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            request_id=request_id,
            code="internal_server_error",
            message="Unexpected server error",
        ),
    )


@app.get(
    "/health/",
    response_model=HealthResponse,
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def health():
    capacity = ensure_base_capacity()
    return {
        "status": "ok",
        "simple_available": capacity["simple_available"],
        "strong_available": capacity["strong_available"],
        "simple_unavailable": get_unavailable_models(list(SIMPLE_MODELS)),
        "strong_unavailable": get_unavailable_models(list(STRONG_MODELS)),
    }


@app.post(
    "/generate/",
    response_model=LessonFlowResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def generate_flow(payload: LessonFlowRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.generate(payload.request.strip())
