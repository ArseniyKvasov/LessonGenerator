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


class TopicFormRequest(BaseModel):
    user_request: str = Field(min_length=1)


class TopicFormResponse(BaseModel):
    topic: str


class SubjectDefineRequest(BaseModel):
    topic: str = Field(min_length=1)


class SubjectDefineResponse(BaseModel):
    subject: str


class SectionTitle(BaseModel):
    title: str = Field(min_length=1)


class SectionsFormRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)


class SectionsFormResponse(BaseModel):
    sections: list[SectionTitle]


class ReferencesFormRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    sections: list[SectionTitle]


class SectionReference(BaseModel):
    section: str
    reference: str


class ReferencesFormResponse(BaseModel):
    references: list[SectionReference]


class SectionWithReference(BaseModel):
    title: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class TaskTypesDefineRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    sections: list[SectionWithReference]
    available_task_types: list[str] = Field(min_length=1)


class SectionTaskTypes(BaseModel):
    section: str
    task_types: list[str]


class TaskTypesDefineResponse(BaseModel):
    sections: list[SectionTaskTypes]


class SectionWithTaskTypes(BaseModel):
    title: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    task_types: list[str] = Field(min_length=1)


class SectionGenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    section: SectionWithTaskTypes
    previous_sections: list[SectionWithReference]
    next_sections: list[SectionWithReference]


class SectionGenerateResponse(BaseModel):
    tasks: list[dict[str, dict[str, Any]]]


class ImageGenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    section: SectionWithReference
    image_goal: str = Field(min_length=1)
    style: str = Field(min_length=1)
    aspect_ratio: str = Field(min_length=1)


class ImageFile(BaseModel):
    image_base64: str
    mime_type: str
    alt: str


class ImageGenerateResponse(BaseModel):
    file: ImageFile
