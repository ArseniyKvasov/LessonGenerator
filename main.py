from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_env
from app.errors import AppError, InvalidRequestError
from app.flow_service import FlowService
from app.model_availability import ensure_base_capacity, get_unavailable_models
from app.model_strategy import SIMPLE_MODELS, STRONG_MODELS
from app.schemas import (
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    ReferencesFormRequest,
    ReferencesFormResponse,
    SectionGenerateRequest,
    SectionGenerateResponse,
    SectionsFormRequest,
    SectionsFormResponse,
    SubjectDefineRequest,
    SubjectDefineResponse,
    TaskTypesDefineRequest,
    TaskTypesDefineResponse,
    TopicFormRequest,
    TopicFormResponse,
)

logging.basicConfig(
    level=getattr(logging, get_env("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lesson-generator")

app = FastAPI(
    title="Lesson Generator ML API",
    version="3.0.0",
    description="Stateless ML service for lesson generation flow.",
)


def _error_response(*, status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(code=code, message=message, details=details)).model_dump()
    return JSONResponse(status_code=status_code, content=payload)


@app.middleware("http")
async def optional_auth_middleware(request: Request, call_next):
    expected_api_key = get_env("APP_API_KEY")
    if expected_api_key:
        provided_api_key = request.headers.get("X-API-Key", "").strip()
        auth_header = request.headers.get("Authorization", "")
        if not provided_api_key and auth_header.lower().startswith("bearer "):
            provided_api_key = auth_header[7:].strip()
        if provided_api_key != expected_api_key:
            return _error_response(
                status_code=401,
                code="invalid_request",
                message="Valid API key is required",
            )
    return await call_next(request)


@app.exception_handler(InvalidRequestError)
async def invalid_request_handler(_: Request, exc: InvalidRequestError):
    return _error_response(status_code=400, code=exc.code, message=exc.message, details=exc.details)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return _error_response(status_code=exc.status_code, code=exc.code, message=exc.message, details=exc.details)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return _error_response(
        status_code=400,
        code="invalid_request",
        message="Request payload is invalid",
        details={"validation_errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    logger.exception("unhandled_error", exc_info=exc)
    return _error_response(
        status_code=500,
        code="internal_error",
        message="Unexpected internal error",
    )


@app.get("/health/", response_model=HealthResponse)
async def health():
    capacity = ensure_base_capacity()
    return {
        "status": "ok",
        "simple_available": capacity["simple_available"],
        "strong_available": capacity["strong_available"],
        "simple_unavailable": get_unavailable_models(list(SIMPLE_MODELS)),
        "strong_unavailable": get_unavailable_models(list(STRONG_MODELS)),
    }


@app.post("/ml/lesson/topic/form/", response_model=TopicFormResponse)
async def form_topic(payload: TopicFormRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.form_topic(payload.user_request.strip())


@app.post("/ml/lesson/subject/define/", response_model=SubjectDefineResponse)
async def define_subject(payload: SubjectDefineRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.define_subject(payload.topic.strip())


@app.post("/ml/lesson/sections/form/", response_model=SectionsFormResponse)
async def form_sections(payload: SectionsFormRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.form_sections(
        topic=payload.topic.strip(),
        subject=payload.subject.strip().lower(),
    )


@app.post("/ml/lesson/references/form/", response_model=ReferencesFormResponse)
async def form_references(payload: ReferencesFormRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.form_references(
        topic=payload.topic.strip(),
        subject=payload.subject.strip().lower(),
        sections=[section.model_dump() for section in payload.sections],
    )


@app.post("/ml/lesson/task-types/define/", response_model=TaskTypesDefineResponse)
async def define_task_types(payload: TaskTypesDefineRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.define_task_types(
        topic=payload.topic.strip(),
        subject=payload.subject.strip().lower(),
        sections=[section.model_dump() for section in payload.sections],
        available_task_types=[task_type.strip() for task_type in payload.available_task_types],
    )


@app.post("/ml/lesson/section/generate/", response_model=SectionGenerateResponse)
async def generate_section(payload: SectionGenerateRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.generate_section(
        topic=payload.topic.strip(),
        subject=payload.subject.strip().lower(),
        section=payload.section.model_dump(),
        previous_sections=[section.model_dump() for section in payload.previous_sections],
        next_sections=[section.model_dump() for section in payload.next_sections],
    )


@app.post("/ml/lesson/image/generate/", response_model=ImageGenerateResponse)
async def generate_image(payload: ImageGenerateRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.generate_image(
        topic=payload.topic.strip(),
        subject=payload.subject.strip().lower(),
        section=payload.section.model_dump(),
        image_goal=payload.image_goal.strip(),
        style=payload.style.strip(),
        aspect_ratio=payload.aspect_ratio.strip(),
    )
