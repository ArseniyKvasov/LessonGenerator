from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any
from typing import Callable
from typing import Optional

import httpx

from .ai import build_client
from .config import get_env
from .errors import FlowGenerationError, InvalidRequestError, ProxyError
from .model_availability import get_available_models, mark_model_unavailable
from .model_strategy import SIMPLE_MODELS, STRONG_MODELS

ALLOWED_SUBJECTS = {"math", "language", "physics", "chemistry", "other"}
ALLOWED_TASK_TYPES = {"note", "test", "true_false", "file", "match_cards", "word_list", "fill_gaps"}
TASK_TYPE_TO_MODEL = {"file": "image"}
TASK_TYPE_FROM_MODEL = {value: key for key, value in TASK_TYPE_TO_MODEL.items()}
SECTION_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
UNSAFE_HTML_RE = re.compile(r"(<script|<iframe|<object|<embed|javascript:|on\w+\s*=)", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")


class FlowService:
    def __init__(self, *, simple_model: Optional[str] = None, strong_model: Optional[str] = None):
        self.client = build_client()
        self.simple_pool = [simple_model] if simple_model else list(SIMPLE_MODELS)
        self.strong_pool = [strong_model] if strong_model else list(STRONG_MODELS)

    async def normalize_topic(self, user_request: str) -> dict[str, str]:
        topic = await self._step_topic(user_request)
        subject = await self._step_subject(topic)
        return {"topic": topic, "subject": subject}

    async def create_outline(
        self,
        *,
        topic: str,
        subject: str,
        language: str,
        level: str,
        lesson_format: str,
    ) -> list[dict[str, str]]:
        return await self._step_outline(
            step_name="outline_create",
            payload={
                "topic": topic,
                "subject": subject,
                "language": language,
                "level": level,
                "lesson_format": lesson_format,
            },
            prompt=(
                "Create lesson outline. Return strict JSON only: "
                '{"sections":[{"section_id":"form_basics","title":"Form Basics","reference":"..."}]}. '
                "Sections count must be 3-8. section_id must be a unique slug. title must contain 1-3 words."
            ),
        )

    async def improve_outline(
        self,
        *,
        topic: str,
        subject: str,
        language: str,
        level: str,
        lesson_format: str,
        current_sections: list[dict[str, str]],
        improvement_prompt: str,
    ) -> list[dict[str, str]]:
        return await self._step_outline(
            step_name="outline_improve",
            payload={
                "topic": topic,
                "subject": subject,
                "language": language,
                "level": level,
                "lesson_format": lesson_format,
                "current_sections": current_sections,
                "improvement_prompt": improvement_prompt,
            },
            prompt=(
                "Improve lesson outline. Return strict JSON only: "
                '{"sections":[{"section_id":"form_basics","title":"Form Basics","reference":"..."}]}. '
                "Sections count must be 3-8. Keep ids unique slugs and titles 1-3 words."
            ),
        )

    async def section_task_types(
        self,
        *,
        topic: str,
        subject: str,
        language: str,
        level: str,
        section: dict[str, str],
        available_task_types: list[str],
    ) -> list[str]:
        allowed = self._normalize_task_types(available_task_types)
        if not allowed:
            raise InvalidRequestError("No valid available_task_types provided")

        available_for_model = [self._to_model_task_type(task_type) for task_type in allowed]
        return await self._call_json(
            step_name=f"section_task_types:{section.get('section_id', 'unknown')}",
            model_pool=self.strong_pool,
            prompt=(
                "Select task types for this lesson section. Return strict JSON only: "
                '{"task_types":["note","fill_gaps"]}. Pick 1-3 items and use only allowed types.'
            ),
            payload={
                "topic": topic,
                "subject": subject,
                "language": language,
                "level": level,
                "section": section,
                "available_task_types": available_for_model,
            },
            validator=lambda parsed: self._validate_section_task_types(parsed, allowed),
        )

    async def generate_section(
        self,
        *,
        topic: str,
        subject: str,
        language: str,
        level: str,
        section: dict[str, Any],
        previous_sections: list[dict[str, str]],
        task_schemas: dict[str, Any],
    ) -> dict[str, Any]:
        section_id = str(section.get("section_id", "")).strip()
        selected_task_types = self._normalize_task_types([str(item) for item in section.get("task_types", [])])
        if not section_id or not selected_task_types:
            raise InvalidRequestError("Section must contain section_id and at least one valid task_type")

        section_for_model = dict(section)
        section_for_model["task_types"] = [self._to_model_task_type(task_type) for task_type in selected_task_types]
        schema_for_model = self._schemas_for_selected_task_types(selected_task_types, task_schemas)
        schema_for_model = {
            self._to_model_task_type(task_type): schema
            for task_type, schema in schema_for_model.items()
        }

        result = await self._call_json(
            step_name=f"section_generate:{section_id}",
            model_pool=self.strong_pool,
            prompt=(
                "Generate section tasks for an educational lesson. Return strict JSON only: "
                '{"tasks":[{"note":{"content":"..."}}],"image_requests":[{"task_index":0,"image_prompt":"..."}]}. '
                "Each task object must contain exactly one key from section.task_types. "
                "Use task_schemas. If image content is needed and file is among task types, "
                "you may return image_requests with prompts."
            ),
            payload={
                "topic": topic,
                "subject": subject,
                "language": language,
                "level": level,
                "section": section_for_model,
                "previous_sections": previous_sections,
                "task_schemas": schema_for_model,
            },
            validator=lambda parsed: self._validate_section_generate_result(
                parsed=parsed,
                section_id=section_id,
                selected_task_types=selected_task_types,
            ),
        )
        return result

    async def generate_image(
        self,
        *,
        topic: str,
        subject: str,
        language: str,
        level: str,
        section: dict[str, str],
        image_prompt: str,
        style: str,
        aspect_ratio: str,
    ) -> dict[str, str]:
        prompt = image_prompt.strip()
        if not prompt:
            raise InvalidRequestError("image_prompt must be non-empty")
        api_key = get_env("POLLINATIONS_API_KEY") or get_env("IMAGE_GENERATOR_API_KEY")
        if not api_key:
            raise InvalidRequestError(
                "POLLINATIONS_API_KEY is not configured",
                details={"field": "POLLINATIONS_API_KEY", "reason": "set api key from enter.pollinations.ai"},
            )

        endpoint = get_env("POLLINATIONS_IMAGE_API_URL", "https://gen.pollinations.ai/v1/images/generations")
        model = get_env("POLLINATIONS_IMAGE_MODEL", "flux")
        size = self._size_from_aspect_ratio(aspect_ratio)
        composed_prompt = f"{prompt}. Style: {style}. Topic: {topic}. Subject: {subject}. Level: {level}. Language: {language}."
        request_payload = {
            "model": model,
            "prompt": composed_prompt,
            "size": size,
            "response_format": "url",
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(endpoint, json=request_payload, headers=headers)
                response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise FlowGenerationError(f"Pollinations image generation failed: {exc}") from exc

        if not isinstance(body, dict):
            raise FlowGenerationError("Pollinations returned invalid response format")
        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise FlowGenerationError("Pollinations response does not contain image data")
        first = data[0] if isinstance(data[0], dict) else {}
        file_url = str(first.get("url", "")).strip()
        if not file_url:
            raise FlowGenerationError("Pollinations response does not contain image url")

        alt = self._clean_text_for_alt(prompt)
        _ = (section,)
        return {"file_url": file_url, "file_type": "image", "alt": alt}

    async def _step_topic(self, user_request: str) -> str:
        return await self._call_json(
            step_name="topic",
            model_pool=self.simple_pool,
            prompt=(
                "User request is provided. Produce normalized lesson topic and return strict JSON only: "
                '{"topic":"Present Continuous: Form and Usage"}.'
            ),
            payload={"user_request": user_request},
            validator=self._validate_topic,
        )

    async def _step_subject(self, topic: str) -> str:
        return await self._call_json(
            step_name="subject",
            model_pool=self.simple_pool,
            prompt=(
                "Lesson topic is provided. Return strict JSON only: "
                '{"subject":"language"}. Allowed values: math, language, physics, chemistry, other.'
            ),
            payload={"topic": topic},
            validator=self._validate_subject,
        )

    async def _step_outline(
        self,
        *,
        step_name: str,
        payload: dict[str, Any],
        prompt: str,
    ) -> list[dict[str, str]]:
        return await self._call_json(
            step_name=step_name,
            model_pool=self.strong_pool,
            prompt=prompt,
            payload=payload,
            validator=self._validate_outline_sections,
        )

    async def _call_json(
        self,
        *,
        step_name: str,
        model_pool: list[str],
        prompt: str,
        payload: dict[str, Any],
        validator: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> Any:
        if not model_pool:
            raise FlowGenerationError(f"Step {step_name} has empty model pool")

        last_error: Exception | None = None
        used_models: list[str] = []
        for attempt in range(3):
            available_pool = get_available_models(model_pool)
            if not available_pool:
                raise FlowGenerationError(f"Step {step_name} has no available models in pool")

            unused_pool = [model for model in available_pool if model not in used_models]
            pick_pool = unused_pool or available_pool
            model = random.choice(pick_pool)
            used_models.append(model)
            try:
                raw = await self.client.chat_completion(
                    model=model,
                    temperature=0.2,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                parsed = self._extract_json(raw)
                if validator is None:
                    return parsed
                return validator(parsed)
            except Exception as exc:
                last_error = exc
                if self._is_rate_limited_error(exc):
                    mark_model_unavailable(model)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))

        raise FlowGenerationError(f"Step {step_name} failed after 3 attempts: {last_error}")

    @staticmethod
    def _to_model_task_type(task_type: str) -> str:
        return TASK_TYPE_TO_MODEL.get(task_type, task_type)

    @staticmethod
    def _to_user_task_type(task_type: str) -> str:
        return TASK_TYPE_FROM_MODEL.get(task_type, task_type)

    @staticmethod
    def _normalize_task_type(task_type: str) -> str:
        normalized = FlowService._to_user_task_type(str(task_type).strip())
        return normalized

    @staticmethod
    def _normalize_task_types(task_types: list[str]) -> list[str]:
        valid: list[str] = []
        for task_type in task_types:
            normalized = FlowService._normalize_task_type(task_type)
            if normalized in ALLOWED_TASK_TYPES and normalized not in valid:
                valid.append(normalized)
        return valid

    @staticmethod
    def _schemas_for_selected_task_types(selected_task_types: list[str], task_schemas: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for task_type in selected_task_types:
            schema = task_schemas.get(task_type) or task_schemas.get(FlowService._to_model_task_type(task_type))
            if schema is None:
                continue
            result[task_type] = schema
        return result

    @staticmethod
    def _is_rate_limited_error(exc: Exception) -> bool:
        if isinstance(exc, ProxyError) and "429" in str(exc):
            return True
        lowered = str(exc).lower()
        return "rate limit" in lowered or "status_code\":429" in lowered

    @staticmethod
    def _validate_topic(parsed: dict[str, Any]) -> str:
        topic = str(parsed.get("topic", "")).strip()
        if not topic:
            raise FlowGenerationError("Topic is empty")
        return topic

    @staticmethod
    def _validate_subject(parsed: dict[str, Any]) -> str:
        subject = str(parsed.get("subject", "")).strip().lower()
        if subject not in ALLOWED_SUBJECTS:
            subject = "other"
        return subject

    @staticmethod
    def _validate_outline_sections(parsed: dict[str, Any]) -> list[dict[str, str]]:
        raw_sections = parsed.get("sections")
        if not isinstance(raw_sections, list):
            raise FlowGenerationError("sections must be a list")
        if not (3 <= len(raw_sections) <= 8):
            raise FlowGenerationError(
                "sections must contain 3-8 items",
                details={"field": "sections", "reason": "count must be between 3 and 8"},
            )

        validated: list[dict[str, str]] = []
        used_ids: set[str] = set()
        for idx, item in enumerate(raw_sections):
            if not isinstance(item, dict):
                raise FlowGenerationError(
                    "section must be object",
                    details={"field": f"sections[{idx}]", "reason": "section item must be object"},
                )
            section_id = str(item.get("section_id", "")).strip()
            title = str(item.get("title", "")).strip()
            reference = str(item.get("reference", "")).strip()

            if not section_id:
                section_id = FlowService._slugify_section_id(title)

            if not section_id or not SECTION_ID_RE.fullmatch(section_id):
                raise FlowGenerationError(
                    "section_id must be a slug",
                    details={"field": f"sections[{idx}].section_id", "reason": "invalid slug format"},
                )
            if section_id in used_ids:
                raise FlowGenerationError(
                    "section_id must be unique",
                    details={"field": f"sections[{idx}].section_id", "reason": "duplicate section_id"},
                )
            used_ids.add(section_id)

            words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", title)
            if not (1 <= len(words) <= 3):
                raise FlowGenerationError(
                    "title must contain 1-3 words",
                    details={"field": f"sections[{idx}].title", "reason": "invalid title length"},
                )
            if not reference or len(reference) > 240:
                raise FlowGenerationError(
                    "reference must be a short teaching reference",
                    details={"field": f"sections[{idx}].reference", "reason": "reference is empty or too long"},
                )

            validated.append({"section_id": section_id, "title": title, "reference": reference})

        return validated

    @staticmethod
    def _validate_section_task_types(parsed: dict[str, Any], available_task_types: list[str]) -> list[str]:
        raw = parsed.get("task_types")
        if not isinstance(raw, list):
            raise FlowGenerationError(
                "task_types must be list",
                details={"field": "task_types", "reason": "task_types must be an array"},
            )

        normalized = []
        allowed_set = set(available_task_types)
        for idx, task_type in enumerate(raw):
            task_name = FlowService._normalize_task_type(str(task_type))
            if task_name not in allowed_set:
                raise FlowGenerationError(
                    "task_type is not allowed",
                    details={"field": f"task_types[{idx}]", "reason": "must belong to available_task_types"},
                )
            if task_name not in normalized:
                normalized.append(task_name)

        if not (1 <= len(normalized) <= 3):
            raise FlowGenerationError(
                "task_types must contain 1-3 items",
                details={"field": "task_types", "reason": "invalid number of selected task types"},
            )
        return normalized

    @staticmethod
    def _validate_section_generate_result(
        *,
        parsed: dict[str, Any],
        section_id: str,
        selected_task_types: list[str],
    ) -> dict[str, Any]:
        raw_tasks = parsed.get("tasks")
        if not isinstance(raw_tasks, list):
            raise FlowGenerationError(
                "tasks must be list",
                details={"field": "tasks", "reason": "tasks must be an array"},
            )

        validated_tasks: list[dict[str, dict[str, Any]]] = []
        for task_index, task in enumerate(raw_tasks):
            normalized_task = FlowService._normalize_task_object(task)
            if normalized_task is None:
                raise FlowGenerationError(
                    "task object must contain exactly one task type key",
                    details={"field": f"tasks[{task_index}]", "reason": "invalid task object shape"},
                )
            task_type, data = next(iter(normalized_task.items()))
            if task_type not in selected_task_types:
                raise FlowGenerationError(
                    "task type not selected for section",
                    details={"field": f"tasks[{task_index}].{task_type}", "reason": "task type is not in section.task_types"},
                )
            FlowService._validate_task_payload(task_type=task_type, data=data, task_index=task_index)
            validated_tasks.append({task_type: data})

        image_requests = FlowService._validate_image_requests(parsed.get("image_requests"), len(validated_tasks))
        return {"section_id": section_id, "tasks": validated_tasks, "image_requests": image_requests}

    @staticmethod
    def _validate_image_requests(raw: Any, task_count: int) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise FlowGenerationError(
                "image_requests must be list",
                details={"field": "image_requests", "reason": "image_requests must be an array"},
            )
        result: list[dict[str, Any]] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise FlowGenerationError(
                    "image_request must be object",
                    details={"field": f"image_requests[{idx}]", "reason": "item must be object"},
                )
            task_index = item.get("task_index")
            image_prompt = str(item.get("image_prompt", "")).strip()
            if not isinstance(task_index, int) or task_index < 0:
                raise FlowGenerationError(
                    "task_index must be a non-negative integer",
                    details={"field": f"image_requests[{idx}].task_index", "reason": "invalid task index"},
                )
            if task_count > 0 and task_index > task_count:
                raise FlowGenerationError(
                    "task_index is out of range",
                    details={"field": f"image_requests[{idx}].task_index", "reason": "task_index points outside tasks"},
                )
            if not image_prompt:
                raise FlowGenerationError(
                    "image_prompt is required",
                    details={"field": f"image_requests[{idx}].image_prompt", "reason": "image_prompt must be non-empty"},
                )
            result.append({"task_index": task_index, "image_prompt": image_prompt})
        return result

    @staticmethod
    def _normalize_task_object(task: Any) -> dict[str, dict[str, Any]] | None:
        if not isinstance(task, dict):
            return None

        if "type" in task and "data" in task:
            task_type = FlowService._normalize_task_type(str(task.get("type", "")).strip())
            payload = task.get("data")
            if task_type and isinstance(payload, dict):
                return {task_type: payload}
            return None

        if len(task) != 1:
            return None
        task_type, payload = next(iter(task.items()))
        task_name = FlowService._normalize_task_type(str(task_type).strip())
        if task_name not in ALLOWED_TASK_TYPES or not isinstance(payload, dict):
            return None
        return {task_name: payload}

    @staticmethod
    def _validate_task_payload(*, task_type: str, data: dict[str, Any], task_index: int) -> None:
        if task_type == "note":
            content = str(data.get("content", "")).strip()
            if not content:
                raise FlowGenerationError(
                    "note.content is required",
                    details={"field": f"tasks[{task_index}].note.content", "reason": "content must be non-empty"},
                )
            FlowService._ensure_safe_markdown(content, field=f"tasks[{task_index}].note.content")
            return

        if task_type == "test":
            questions = data.get("questions")
            if not isinstance(questions, list) or not (1 <= len(questions) <= 5):
                raise FlowGenerationError(
                    "test.questions must contain 1-5 items",
                    details={"field": f"tasks[{task_index}].test.questions", "reason": "invalid questions count"},
                )
            for q_idx, question in enumerate(questions):
                if not isinstance(question, dict):
                    raise FlowGenerationError(
                        "question must be object",
                        details={"field": f"tasks[{task_index}].test.questions[{q_idx}]", "reason": "question must be object"},
                    )
                text = str(question.get("question", "")).strip()
                options = question.get("options")
                if not text:
                    raise FlowGenerationError(
                        "question text is required",
                        details={"field": f"tasks[{task_index}].test.questions[{q_idx}].question", "reason": "question must be non-empty"},
                    )
                if not isinstance(options, list) or not (2 <= len(options) <= 4):
                    raise FlowGenerationError(
                        "options must contain 2-4 items",
                        details={"field": f"tasks[{task_index}].test.questions[{q_idx}].options", "reason": "invalid options count"},
                    )
                correct = 0
                for opt_idx, option in enumerate(options):
                    if not isinstance(option, dict):
                        raise FlowGenerationError(
                            "option must be object",
                            details={"field": f"tasks[{task_index}].test.questions[{q_idx}].options[{opt_idx}]", "reason": "option must be object"},
                        )
                    option_text = str(option.get("option", "")).strip()
                    is_correct = option.get("is_correct")
                    if not option_text or not isinstance(is_correct, bool):
                        raise FlowGenerationError(
                            "invalid option format",
                            details={"field": f"tasks[{task_index}].test.questions[{q_idx}].options[{opt_idx}]", "reason": "option and is_correct are required"},
                        )
                    if is_correct:
                        correct += 1
                if correct != 1:
                    raise FlowGenerationError(
                        "each question must have exactly one correct option",
                        details={"field": f"tasks[{task_index}].test.questions[{q_idx}].options", "reason": "invalid correct options count"},
                    )
            return

        if task_type == "true_false":
            statements = data.get("statements")
            if not isinstance(statements, list) or not (2 <= len(statements) <= 8):
                raise FlowGenerationError(
                    "true_false.statements must contain 2-8 items",
                    details={"field": f"tasks[{task_index}].true_false.statements", "reason": "invalid statements count"},
                )
            for s_idx, statement in enumerate(statements):
                if not isinstance(statement, dict):
                    raise FlowGenerationError(
                        "statement must be object",
                        details={"field": f"tasks[{task_index}].true_false.statements[{s_idx}]", "reason": "statement must be object"},
                    )
                text = str(statement.get("statement", "")).strip()
                is_true = statement.get("is_true")
                if not text or not isinstance(is_true, bool):
                    raise FlowGenerationError(
                        "invalid true_false statement",
                        details={"field": f"tasks[{task_index}].true_false.statements[{s_idx}]", "reason": "statement and is_true are required"},
                    )
            return

        if task_type == "file":
            file_url = str(data.get("file_url", "")).strip()
            file_type = str(data.get("file_type", "")).strip().lower()
            alt = str(data.get("alt", "")).strip()
            if not file_url:
                raise FlowGenerationError(
                    "file_url is required",
                    details={"field": f"tasks[{task_index}].file.file_url", "reason": "file_url must be non-empty"},
                )
            if file_type != "image":
                raise FlowGenerationError(
                    "file_type must be image",
                    details={"field": f"tasks[{task_index}].file.file_type", "reason": "file_type must be 'image'"},
                )
            if not alt:
                raise FlowGenerationError(
                    "alt is required",
                    details={"field": f"tasks[{task_index}].file.alt", "reason": "alt must be non-empty"},
                )
            return

        if task_type == "match_cards":
            pairs = data.get("pairs")
            if not isinstance(pairs, list) or not (2 <= len(pairs) <= 8):
                raise FlowGenerationError(
                    "match_cards.pairs must contain 2-8 items",
                    details={"field": f"tasks[{task_index}].match_cards.pairs", "reason": "invalid pairs count"},
                )
            for p_idx, pair in enumerate(pairs):
                if not isinstance(pair, dict):
                    raise FlowGenerationError(
                        "pair must be object",
                        details={"field": f"tasks[{task_index}].match_cards.pairs[{p_idx}]", "reason": "pair must be object"},
                    )
                left = str(pair.get("left", "")).strip()
                right = str(pair.get("right", "")).strip()
                if not left or not right:
                    raise FlowGenerationError(
                        "pair.left and pair.right are required",
                        details={"field": f"tasks[{task_index}].match_cards.pairs[{p_idx}]", "reason": "left/right must be non-empty"},
                    )
            return

        if task_type == "word_list":
            pairs = data.get("pairs")
            if not isinstance(pairs, list) or not (3 <= len(pairs) <= 12):
                raise FlowGenerationError(
                    "word_list.pairs must contain 3-12 items",
                    details={"field": f"tasks[{task_index}].word_list.pairs", "reason": "invalid pairs count"},
                )
            for p_idx, pair in enumerate(pairs):
                if not isinstance(pair, dict):
                    raise FlowGenerationError(
                        "pair must be object",
                        details={"field": f"tasks[{task_index}].word_list.pairs[{p_idx}]", "reason": "pair must be object"},
                    )
                word = str(pair.get("word", "")).strip()
                translation = str(pair.get("translation", "")).strip()
                if not word or not translation:
                    raise FlowGenerationError(
                        "word and translation are required",
                        details={"field": f"tasks[{task_index}].word_list.pairs[{p_idx}]", "reason": "word/translation must be non-empty"},
                    )
            return

        if task_type == "fill_gaps":
            content = str(data.get("content", "")).strip()
            answers = data.get("answers")
            if not content:
                raise FlowGenerationError(
                    "fill_gaps.content is required",
                    details={"field": f"tasks[{task_index}].fill_gaps.content", "reason": "content must be non-empty"},
                )
            FlowService._ensure_safe_markdown(content, field=f"tasks[{task_index}].fill_gaps.content")
            placeholders = [match.group(1).strip() for match in PLACEHOLDER_RE.finditer(content)]
            if not placeholders:
                raise FlowGenerationError(
                    "fill_gaps.content must contain placeholders",
                    details={"field": f"tasks[{task_index}].fill_gaps.content", "reason": "expected {{answer}} placeholders"},
                )
            if not isinstance(answers, list) or not all(isinstance(item, str) and item.strip() for item in answers):
                raise FlowGenerationError(
                    "fill_gaps.answers must be a non-empty string list",
                    details={"field": f"tasks[{task_index}].fill_gaps.answers", "reason": "answers format is invalid"},
                )
            normalized_answers = [item.strip() for item in answers]
            if len(normalized_answers) != len(placeholders):
                raise FlowGenerationError(
                    "answers count does not match placeholders count",
                    details={
                        "field": f"tasks[{task_index}].fill_gaps.answers",
                        "reason": "answers count does not match placeholders count",
                    },
                )
            if normalized_answers != placeholders:
                raise FlowGenerationError(
                    "answers order does not match placeholders order",
                    details={
                        "field": f"tasks[{task_index}].fill_gaps.answers",
                        "reason": "answers order must follow placeholders order",
                    },
                )
            return

        raise FlowGenerationError(
            "Unsupported task type",
            details={"field": f"tasks[{task_index}]", "reason": f"unsupported task type {task_type}"},
        )

    @staticmethod
    def _ensure_safe_markdown(content: str, *, field: str) -> None:
        if UNSAFE_HTML_RE.search(content):
            raise FlowGenerationError(
                "markdown contains unsafe HTML",
                details={"field": field, "reason": "unsafe html is forbidden"},
            )

    @staticmethod
    def _slugify_section_id(raw: str) -> str:
        value = raw.strip().lower()
        if not value:
            return ""
        value = re.sub(r"[^a-z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value

    @staticmethod
    def _clean_text_for_alt(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        clean = re.sub(r"[{}*#`_]+", "", clean)
        if len(clean) > 140:
            clean = clean[:140].rstrip() + "..."
        return clean or "Generated educational image."

    @staticmethod
    def _size_from_aspect_ratio(aspect_ratio: str) -> str:
        ratio = aspect_ratio.strip()
        if ratio == "16:9":
            return "1280x720"
        if ratio == "9:16":
            return "720x1280"
        if ratio == "4:3":
            return "1152x864"
        if ratio == "3:4":
            return "864x1152"
        return "1024x1024"

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed

        raise FlowGenerationError("Model response does not contain valid JSON object")
