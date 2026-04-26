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
    OutlineCreateRequest,
    OutlineCreateResponse,
    OutlineImproveRequest,
    OutlineImproveResponse,
    SectionGenerateRequest,
    SectionGenerateResponse,
    SectionTaskTypesRequest,
    SectionTaskTypesResponse,
    TopicNormalizeRequest,
    TopicNormalizeResponse,
)

logging.basicConfig(
    level=getattr(logging, get_env("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lesson-generator")

app = FastAPI(
    title="Lesson Generator ML API",
    version="2.0.0",
    description="Stateless ML service for lesson topic normalization, outline and section generation.",
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
                code="unauthorized",
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


@app.post("/ml/lesson/topic/normalize/", response_model=TopicNormalizeResponse)
async def normalize_topic(payload: TopicNormalizeRequest):
    ensure_base_capacity()
    service = FlowService()
    return await service.normalize_topic(payload.user_request.strip())


@app.post("/ml/lesson/outline/create/", response_model=OutlineCreateResponse)
async def create_outline(payload: OutlineCreateRequest):
    ensure_base_capacity()
    service = FlowService()
    sections = await service.create_outline(
        topic=payload.topic.strip(),
        subject=payload.subject.strip(),
        language=payload.language.strip(),
        level=payload.level.strip(),
        lesson_format=payload.lesson_format.strip(),
    )
    return {"sections": sections}


@app.post("/ml/lesson/outline/improve/", response_model=OutlineImproveResponse)
async def improve_outline(payload: OutlineImproveRequest):
    ensure_base_capacity()
    service = FlowService()
    sections = await service.improve_outline(
        topic=payload.topic.strip(),
        subject=payload.subject.strip(),
        language=payload.language.strip(),
        level=payload.level.strip(),
        lesson_format=payload.lesson_format.strip(),
        current_sections=[section.model_dump() for section in payload.current_sections],
        improvement_prompt=payload.improvement_prompt.strip(),
    )
    return {"sections": sections}


@app.post("/ml/lesson/section/task-types/", response_model=SectionTaskTypesResponse)
async def define_section_task_types(payload: SectionTaskTypesRequest):
    ensure_base_capacity()
    service = FlowService()
    task_types = await service.section_task_types(
        topic=payload.topic.strip(),
        subject=payload.subject.strip(),
        language=payload.language.strip(),
        level=payload.level.strip(),
        section=payload.section.model_dump(),
        available_task_types=[item.strip() for item in payload.available_task_types],
    )
    return {"section_id": payload.section.section_id, "task_types": task_types}


@app.post("/ml/lesson/section/generate/", response_model=SectionGenerateResponse)
async def generate_section(payload: SectionGenerateRequest):
    ensure_base_capacity()
    service = FlowService()
    generated = await service.generate_section(
        topic=payload.topic.strip(),
        subject=payload.subject.strip(),
        language=payload.language.strip(),
        level=payload.level.strip(),
        section=payload.section.model_dump(),
        previous_sections=[section.model_dump() for section in payload.previous_sections],
        task_schemas=payload.task_schemas,
    )
    return generated


@app.post("/ml/lesson/file/image/generate/", response_model=ImageGenerateResponse)
async def generate_image(payload: ImageGenerateRequest):
    ensure_base_capacity()
    service = FlowService()
    file_data = await service.generate_image(
        topic=payload.topic.strip(),
        subject=payload.subject.strip(),
        language=payload.language.strip(),
        level=payload.level.strip(),
        section=payload.section.model_dump(),
        image_prompt=payload.image_prompt.strip(),
        style=payload.style.strip(),
        aspect_ratio=payload.aspect_ratio.strip(),
    )
    return {"file": file_data}
