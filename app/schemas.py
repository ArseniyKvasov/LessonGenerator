from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str
    request_id: str


class HealthResponse(BaseModel):
    status: str
    simple_available: list[str]
    strong_available: list[str]
    simple_unavailable: list[dict[str, Any]]
    strong_unavailable: list[dict[str, Any]]


class AIRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: Optional[str] = None


class AIResponse(BaseModel):
    model: str
    response: str


class LessonFlowRequest(BaseModel):
    request: str = Field(min_length=1)


class LessonFlowResponse(BaseModel):
    topic: str
    subject: str
    sections: list[dict[str, str]]
    references: list[dict[str, str]]
    section_task_types: list[dict[str, Any]]
    tasks_by_section: list[dict[str, Any]]
    task_contracts: dict[str, Any]
    models: dict[str, str]
