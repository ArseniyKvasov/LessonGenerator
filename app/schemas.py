from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    simple_available: list[str]
    strong_available: list[str]
    simple_unavailable: list[dict[str, Any]]
    strong_unavailable: list[dict[str, Any]]


class TopicNormalizeRequest(BaseModel):
    user_request: str = Field(min_length=1)


class TopicNormalizeResponse(BaseModel):
    topic: str
    subject: str


class LessonSection(BaseModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class OutlineCreateRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    language: str = Field(min_length=1)
    level: str = Field(min_length=1)
    lesson_format: str = Field(min_length=1)


class OutlineCreateResponse(BaseModel):
    sections: list[LessonSection]


class OutlineImproveRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    language: str = Field(min_length=1)
    level: str = Field(min_length=1)
    lesson_format: str = Field(min_length=1)
    current_sections: list[LessonSection]
    improvement_prompt: str = Field(min_length=1)


class OutlineImproveResponse(BaseModel):
    sections: list[LessonSection]


class SectionTaskTypesRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    language: str = Field(min_length=1)
    level: str = Field(min_length=1)
    section: LessonSection
    available_task_types: list[str] = Field(min_length=1)


class SectionTaskTypesResponse(BaseModel):
    section_id: str
    task_types: list[str]


class SectionWithTaskTypes(LessonSection):
    task_types: list[str] = Field(min_length=1)


class SectionGenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    language: str = Field(min_length=1)
    level: str = Field(min_length=1)
    section: SectionWithTaskTypes
    previous_sections: list[LessonSection]
    task_schemas: dict[str, Any]


class ImageRequestItem(BaseModel):
    task_index: int
    image_prompt: str = Field(min_length=1)


class SectionGenerateResponse(BaseModel):
    section_id: str
    tasks: list[dict[str, dict[str, Any]]]
    image_requests: list[ImageRequestItem] = Field(default_factory=list)


class ImageGenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    language: str = Field(min_length=1)
    level: str = Field(min_length=1)
    section: LessonSection
    image_prompt: str = Field(min_length=1)
    style: str = Field(min_length=1)
    aspect_ratio: str = Field(min_length=1)


class ImageGenerateResponse(BaseModel):
    file: dict[str, str]
