from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from typing import Any
from typing import Callable
from typing import Optional

import httpx

from .ai import build_client
from .config import get_env
from .errors import FlowGenerationError, InvalidRequestError, ProxyError, TimeoutError
from .model_availability import get_available_models, mark_model_unavailable
from .model_strategy import SIMPLE_MODELS, STRONG_MODELS

ALLOWED_SUBJECTS = {"math", "language", "physics", "chemistry", "other"}
ALLOWED_TASK_TYPES = {"note", "test", "true_false", "file", "match_cards", "word_list", "fill_gaps"}
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
UNSAFE_HTML_RE = re.compile(r"(<script|<iframe|<object|<embed|javascript:|on\w+\s*=)", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
UNDERSCORE_GAP_RE = re.compile(r"_{3,}")


class FlowService:
    def __init__(self, *, simple_model: Optional[str] = None, strong_model: Optional[str] = None):
        self.client = build_client()
        self.simple_pool = [simple_model] if simple_model else list(SIMPLE_MODELS)
        self.strong_pool = [strong_model] if strong_model else list(STRONG_MODELS)

    async def form_topic(self, user_request: str) -> dict[str, str]:
        topic = await self._call_json(
            step_name="topic_form",
            model_pool=self.simple_pool,
            prompt=(
                "User request is provided. Form short lesson topic. Return strict JSON only: "
                '{"topic":"Present Continuous: Form and Usage"}. Topic must be clear and <= 120 chars.'
            ),
            payload={"user_request": user_request},
            validator=self._validate_topic,
        )
        return {"topic": topic}

    async def define_subject(self, topic: str) -> dict[str, str]:
        subject = await self._call_json(
            step_name="subject_define",
            model_pool=self.simple_pool,
            prompt=(
                "Lesson topic is provided. Define subject: math, language, physics, chemistry, other. "
                'Return strict JSON only: {"subject":"language"}.'
            ),
            payload={"topic": topic},
            validator=self._validate_subject,
        )
        return {"subject": subject}

    async def form_sections(self, *, topic: str, subject: str) -> dict[str, list[dict[str, str]]]:
        sections = await self._call_json(
            step_name="sections_form",
            model_pool=self.strong_pool,
            prompt=(
                "Form a list of interactive lesson sections. Return strict JSON only: "
                '{"sections":[{"title":"Form Basics"}]}. '
                "Sections count must be 3-8. Each title must be 1-2 words. Duplicate titles are forbidden."
            ),
            payload={"topic": topic, "subject": subject},
            validator=self._validate_sections,
        )
        return {"sections": sections}

    async def form_references(
        self,
        *,
        topic: str,
        subject: str,
        sections: list[dict[str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        section_titles = self._validate_sections_input(sections)
        references = await self._call_json(
            step_name="references_form",
            model_pool=self.strong_pool,
            prompt=(
                "Form lesson references for each section. Return strict JSON only: "
                '{"references":[{"section":"Form Basics","reference":"Subject + am/is/are + Verb-ing"}]}. '
                "Each section must have exactly one short teaching-focused reference."
            ),
            payload={
                "topic": topic,
                "subject": subject,
                "sections": [{"title": title} for title in section_titles],
            },
            validator=lambda parsed: self._validate_references(parsed, section_titles),
        )
        return {"references": references}

    async def define_task_types(
        self,
        *,
        topic: str,
        subject: str,
        sections: list[dict[str, str]],
        available_task_types: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        allowed_types = self._normalize_task_types(available_task_types)
        if not allowed_types:
            raise InvalidRequestError("No valid available_task_types provided")

        normalized_sections = self._validate_sections_with_references_input(sections)
        task_types_by_section = await self._call_json(
            step_name="task_types_define",
            model_pool=self.strong_pool,
            prompt=(
                "Define from 2 to 4 task types for each section and return strict JSON only: "
                '{"sections":[{"section":"Form Basics","task_types":["note","fill_gaps"]}]}. '
                "Task types per section must be from available_task_types, unique, and count must be 1-4."
            ),
            payload={
                "topic": topic,
                "subject": subject,
                "sections": normalized_sections,
                "available_task_types": allowed_types,
            },
            validator=lambda parsed: self._validate_task_types_result(parsed, normalized_sections, allowed_types),
        )
        return {"sections": task_types_by_section}

    async def generate_section(
        self,
        *,
        topic: str,
        subject: str,
        section: dict[str, Any],
        previous_sections: list[dict[str, str]],
        next_sections: list[dict[str, str]],
    ) -> dict[str, list[dict[str, dict[str, Any]]]]:
        validated_section = self._validate_section_for_generation(section)
        validated_previous = self._validate_sections_with_references_input(previous_sections)
        validated_next = self._validate_sections_with_references_input(next_sections)

        tasks = await self._call_json(
            step_name=f"section_generate:{validated_section['title']}",
            model_pool=self.strong_pool,
            prompt=(
                "You are creating an interactive textbook. Return strict JSON only: "
                '{"tasks":[{"note":{"title":"...","content":"..."}}]}. '
                "Each task object must contain exactly one key from section.task_types. "
                "Allowed keys: note, test, true_false, file, match_cards, word_list, fill_gaps."
            ),
            payload={
                "topic": topic,
                "subject": subject,
                "section": validated_section,
                "previous_sections": validated_previous,
                "next_sections": validated_next,
            },
            validator=lambda parsed: self._validate_section_generate_result(parsed, validated_section["task_types"]),
        )
        return {"tasks": tasks}

    async def generate_image(
        self,
        *,
        topic: str,
        subject: str,
        section: dict[str, str],
        image_goal: str,
        style: str,
        aspect_ratio: str,
    ) -> dict[str, dict[str, str]]:
        validated_section = self._validate_section_reference_input(section, field="section")
        goal = image_goal.strip()
        if not goal:
            raise InvalidRequestError("image_goal must be non-empty", details={"field": "image_goal"})

        api_key = get_env("POLLINATIONS_API_KEY") or get_env("IMAGE_GENERATOR_API_KEY")
        if not api_key:
            raise InvalidRequestError(
                "POLLINATIONS_API_KEY is not configured",
                details={"field": "POLLINATIONS_API_KEY", "reason": "set api key from enter.pollinations.ai"},
            )

        endpoint = get_env("POLLINATIONS_IMAGE_API_URL", "https://gen.pollinations.ai/v1/images/generations")
        model = get_env("POLLINATIONS_IMAGE_MODEL", "flux")
        size = self._size_from_aspect_ratio(aspect_ratio)

        composed_prompt = (
            f"Create an educational image for an English lesson. Topic: {topic}. Subject: {subject}. "
            f"Section: {validated_section['title']}. Reference: {validated_section['reference']}. "
            f"Goal: {goal}. Style: {style}. Aspect ratio: {aspect_ratio}."
        )
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
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                generation_response = await client.post(endpoint, json=request_payload, headers=headers)
                generation_response.raise_for_status()
                generation_body = generation_response.json()
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Image generation timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ProxyError(f"Image provider HTTP error {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise ProxyError(f"Image provider request error: {exc}") from exc
        except ValueError as exc:
            raise ProxyError("Image provider returned invalid JSON") from exc

        image_url = self._extract_pollinations_url(generation_body)

        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                image_response = await client.get(image_url)
                image_response.raise_for_status()
                image_bytes = image_response.content
                header_mime = image_response.headers.get("content-type", "")
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Image download timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ProxyError(f"Image download HTTP error {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise ProxyError(f"Image download request error: {exc}") from exc

        mime_type = self._detect_image_mime(image_bytes, header_mime)
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise FlowGenerationError(
                "Unsupported image mime type",
                details={"field": "file.mime_type", "reason": f"mime type must be one of {sorted(ALLOWED_IMAGE_MIME_TYPES)}"},
            )

        if not image_bytes:
            raise FlowGenerationError("Image provider returned empty image bytes")

        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        alt = self._clean_text_for_alt(goal)
        return {"file": {"image_base64": image_base64, "mime_type": mime_type, "alt": alt}}

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
    def _is_rate_limited_error(exc: Exception) -> bool:
        if isinstance(exc, ProxyError) and "429" in str(exc):
            return True
        lowered = str(exc).lower()
        return "rate limit" in lowered or "status_code\":429" in lowered

    @staticmethod
    def _validate_topic(parsed: dict[str, Any]) -> str:
        topic = str(parsed.get("topic", "")).strip()
        if not topic:
            raise FlowGenerationError("topic is required", details={"field": "topic"})
        if len(topic) > 120:
            raise FlowGenerationError(
                "topic is too long",
                details={"field": "topic", "reason": "topic must not exceed 120 characters"},
            )
        return topic

    @staticmethod
    def _validate_subject(parsed: dict[str, Any]) -> str:
        subject = str(parsed.get("subject", "")).strip().lower()
        if subject not in ALLOWED_SUBJECTS:
            raise FlowGenerationError(
                "subject is invalid",
                details={"field": "subject", "reason": "subject must be one of math, language, physics, chemistry, other"},
            )
        return subject

    @staticmethod
    def _validate_sections(parsed: dict[str, Any]) -> list[dict[str, str]]:
        raw_sections = parsed.get("sections")
        if not isinstance(raw_sections, list):
            raise FlowGenerationError("sections must be a list", details={"field": "sections"})
        if not (3 <= len(raw_sections) <= 8):
            raise FlowGenerationError(
                "sections count is invalid",
                details={"field": "sections", "reason": "count must be between 3 and 8"},
            )

        validated: list[dict[str, str]] = []
        used_titles: set[str] = set()
        for idx, item in enumerate(raw_sections):
            if not isinstance(item, dict):
                raise FlowGenerationError(
                    "section must be object",
                    details={"field": f"sections[{idx}]", "reason": "section item must be object"},
                )
            title = str(item.get("title", "")).strip()
            title_key = title.lower()
            words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", title)
            if not (1 <= len(words) <= 2):
                raise FlowGenerationError(
                    "title must contain 1-2 words",
                    details={"field": f"sections[{idx}].title", "reason": "invalid title length"},
                )
            if title_key in used_titles:
                raise FlowGenerationError(
                    "duplicate section titles are forbidden",
                    details={"field": f"sections[{idx}].title", "reason": "duplicate title"},
                )
            used_titles.add(title_key)
            validated.append({"title": title})

        return validated

    @staticmethod
    def _validate_sections_input(raw_sections: list[dict[str, str]]) -> list[str]:
        parsed = FlowService._validate_sections({"sections": raw_sections})
        return [item["title"] for item in parsed]

    @staticmethod
    def _validate_section_reference_input(raw: dict[str, Any], *, field: str) -> dict[str, str]:
        if not isinstance(raw, dict):
            raise InvalidRequestError("section must be an object", details={"field": field})

        title = str(raw.get("title", "")).strip()
        reference = str(raw.get("reference", "")).strip()

        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", title)
        if not (1 <= len(words) <= 2):
            raise InvalidRequestError(
                "section title must contain 1-2 words",
                details={"field": f"{field}.title"},
            )
        if not reference or len(reference) > 240:
            raise InvalidRequestError(
                "section reference must be short and non-empty",
                details={"field": f"{field}.reference"},
            )
        return {"title": title, "reference": reference}

    @staticmethod
    def _validate_sections_with_references_input(raw_sections: list[dict[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(raw_sections, list):
            raise InvalidRequestError("sections must be array", details={"field": "sections"})

        validated: list[dict[str, str]] = []
        used_titles: set[str] = set()
        for idx, item in enumerate(raw_sections):
            parsed = FlowService._validate_section_reference_input(item, field=f"sections[{idx}]")
            title_key = parsed["title"].lower()
            if title_key in used_titles:
                raise InvalidRequestError(
                    "duplicate section titles are forbidden",
                    details={"field": f"sections[{idx}].title", "reason": "duplicate title"},
                )
            used_titles.add(title_key)
            validated.append(parsed)

        return validated

    @staticmethod
    def _validate_references(parsed: dict[str, Any], section_titles: list[str]) -> list[dict[str, str]]:
        raw_references = parsed.get("references")
        if not isinstance(raw_references, list):
            raise FlowGenerationError("references must be a list", details={"field": "references"})

        expected = {title.lower(): title for title in section_titles}
        used: set[str] = set()
        validated: list[dict[str, str]] = []

        for idx, item in enumerate(raw_references):
            if not isinstance(item, dict):
                raise FlowGenerationError(
                    "reference item must be object",
                    details={"field": f"references[{idx}]"},
                )
            section = str(item.get("section", "")).strip()
            reference = str(item.get("reference", "")).strip()
            section_key = section.lower()

            if section_key not in expected:
                raise FlowGenerationError(
                    "reference section is unknown",
                    details={"field": f"references[{idx}].section", "reason": "section not found in input sections"},
                )
            if section_key in used:
                raise FlowGenerationError(
                    "reference section is duplicated",
                    details={"field": f"references[{idx}].section", "reason": "duplicate section"},
                )
            if not reference or len(reference) > 240:
                raise FlowGenerationError(
                    "reference must be short and non-empty",
                    details={"field": f"references[{idx}].reference", "reason": "invalid reference"},
                )

            used.add(section_key)
            validated.append({"section": expected[section_key], "reference": reference})

        if used != set(expected.keys()):
            missing = [expected[key] for key in expected.keys() - used]
            raise FlowGenerationError(
                "each section must have exactly one reference",
                details={"field": "references", "reason": f"missing references for sections: {missing}"},
            )

        return validated

    @staticmethod
    def _normalize_task_types(task_types: list[str]) -> list[str]:
        valid: list[str] = []
        for task_type in task_types:
            normalized = str(task_type).strip()
            if normalized in ALLOWED_TASK_TYPES and normalized not in valid:
                valid.append(normalized)
        return valid

    @staticmethod
    def _validate_task_types_result(
        parsed: dict[str, Any],
        sections: list[dict[str, str]],
        available_task_types: list[str],
    ) -> list[dict[str, Any]]:
        raw_sections = parsed.get("sections")
        if not isinstance(raw_sections, list):
            raise FlowGenerationError("sections must be a list", details={"field": "sections"})

        expected_sections = {item["title"].lower(): item["title"] for item in sections}
        used_sections: set[str] = set()
        allowed = set(available_task_types)
        validated: list[dict[str, Any]] = []

        for idx, item in enumerate(raw_sections):
            if not isinstance(item, dict):
                raise FlowGenerationError(
                    "section task_types item must be object",
                    details={"field": f"sections[{idx}]"},
                )

            section_name = str(item.get("section", "")).strip()
            section_key = section_name.lower()
            if section_key not in expected_sections:
                raise FlowGenerationError(
                    "section is unknown",
                    details={"field": f"sections[{idx}].section", "reason": "section not found in input"},
                )
            if section_key in used_sections:
                raise FlowGenerationError(
                    "section is duplicated",
                    details={"field": f"sections[{idx}].section", "reason": "duplicate section"},
                )

            raw_task_types = item.get("task_types")
            if not isinstance(raw_task_types, list):
                raise FlowGenerationError(
                    "task_types must be list",
                    details={"field": f"sections[{idx}].task_types", "reason": "task_types must be an array"},
                )

            normalized: list[str] = []
            for t_idx, task_type in enumerate(raw_task_types):
                task_name = str(task_type).strip()
                if task_name not in allowed:
                    raise FlowGenerationError(
                        "task type is not allowed",
                        details={"field": f"sections[{idx}].task_types[{t_idx}]", "reason": "must belong to available_task_types"},
                    )
                if task_name in normalized:
                    raise FlowGenerationError(
                        "duplicate task types are forbidden",
                        details={"field": f"sections[{idx}].task_types[{t_idx}]", "reason": "duplicate task type"},
                    )
                normalized.append(task_name)

            if not (1 <= len(normalized) <= 4):
                raise FlowGenerationError(
                    "task_types count is invalid",
                    details={"field": f"sections[{idx}].task_types", "reason": "each section must have 1-4 task types"},
                )

            used_sections.add(section_key)
            validated.append({"section": expected_sections[section_key], "task_types": normalized})

        if used_sections != set(expected_sections.keys()):
            missing = [expected_sections[key] for key in expected_sections.keys() - used_sections]
            raise FlowGenerationError(
                "each section must have task types",
                details={"field": "sections", "reason": f"missing task types for sections: {missing}"},
            )

        return validated

    @staticmethod
    def _validate_section_for_generation(raw: dict[str, Any]) -> dict[str, Any]:
        base = FlowService._validate_section_reference_input(raw, field="section")
        raw_task_types = raw.get("task_types")
        if not isinstance(raw_task_types, list):
            raise InvalidRequestError("section.task_types must be array", details={"field": "section.task_types"})

        normalized = []
        for idx, task_type in enumerate(raw_task_types):
            task_name = str(task_type).strip()
            if task_name not in ALLOWED_TASK_TYPES:
                raise InvalidRequestError(
                    "task type is invalid",
                    details={"field": f"section.task_types[{idx}]", "reason": "unsupported task type"},
                )
            if task_name in normalized:
                raise InvalidRequestError(
                    "duplicate task types are forbidden",
                    details={"field": f"section.task_types[{idx}]", "reason": "duplicate task type"},
                )
            normalized.append(task_name)

        if not (1 <= len(normalized) <= 4):
            raise InvalidRequestError(
                "section.task_types count is invalid",
                details={"field": "section.task_types", "reason": "must contain 1-4 task types"},
            )

        base["task_types"] = normalized
        return base

    @staticmethod
    def _validate_section_generate_result(
        parsed: dict[str, Any],
        selected_task_types: list[str],
    ) -> list[dict[str, dict[str, Any]]]:
        raw_tasks = parsed.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise FlowGenerationError(
                "tasks must be non-empty list",
                details={"field": "tasks", "reason": "tasks must be an array with at least one task"},
            )

        validated_tasks: list[dict[str, dict[str, Any]]] = []
        used_task_types: set[str] = set()

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
                    "task type not requested for section",
                    details={"field": f"tasks[{task_index}].{task_type}", "reason": "task type is not in section.task_types"},
                )

            FlowService._validate_task_payload(task_type=task_type, data=data, task_index=task_index)
            validated_tasks.append({task_type: data})
            used_task_types.add(task_type)

        missing_types = set(selected_task_types) - used_task_types
        if missing_types:
            raise FlowGenerationError(
                "tasks do not cover requested task types",
                details={"field": "tasks", "reason": f"missing task types: {sorted(missing_types)}"},
            )

        return validated_tasks

    @staticmethod
    def _normalize_task_object(task: Any) -> dict[str, dict[str, Any]] | None:
        if not isinstance(task, dict) or len(task) != 1:
            return None
        task_type, payload = next(iter(task.items()))
        task_name = str(task_type).strip()
        if task_name not in ALLOWED_TASK_TYPES or not isinstance(payload, dict):
            return None
        return {task_name: payload}

    @staticmethod
    def _validate_task_payload(*, task_type: str, data: dict[str, Any], task_index: int) -> None:
        if task_type == "note":
            title = str(data.get("title", "")).strip()
            content = str(data.get("content", "")).strip()
            if not title:
                raise FlowGenerationError(
                    "note.title is required",
                    details={"field": f"tasks[{task_index}].note.title", "reason": "title must be non-empty"},
                )
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
            image_base64 = str(data.get("image_base64", "")).strip()
            mime_type = str(data.get("mime_type", "")).strip().lower()
            alt = str(data.get("alt", "")).strip()

            if not image_base64:
                raise FlowGenerationError(
                    "image_base64 is required",
                    details={"field": f"tasks[{task_index}].file.image_base64", "reason": "image_base64 must be non-empty"},
                )
            try:
                base64.b64decode(image_base64, validate=True)
            except Exception as exc:
                raise FlowGenerationError(
                    "image_base64 is invalid",
                    details={"field": f"tasks[{task_index}].file.image_base64", "reason": "invalid base64"},
                ) from exc

            if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                raise FlowGenerationError(
                    "mime_type is invalid",
                    details={"field": f"tasks[{task_index}].file.mime_type", "reason": "mime_type must be image/png, image/jpeg or image/webp"},
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
            if not isinstance(answers, list) or not answers or not all(isinstance(item, str) and item.strip() for item in answers):
                raise FlowGenerationError(
                    "fill_gaps.answers must be a non-empty string list",
                    details={"field": f"tasks[{task_index}].fill_gaps.answers", "reason": "answers format is invalid"},
                )

            normalized_answers = [item.strip() for item in answers]
            placeholder_answers = [match.group(1).strip() for match in PLACEHOLDER_RE.finditer(content)]
            if placeholder_answers:
                if len(normalized_answers) != len(placeholder_answers):
                    raise FlowGenerationError(
                        "answers count does not match placeholders count",
                        details={
                            "field": f"tasks[{task_index}].fill_gaps.answers",
                            "reason": "answers count does not match blanks count",
                        },
                    )
                if normalized_answers != placeholder_answers:
                    raise FlowGenerationError(
                        "answers order does not match placeholders order",
                        details={
                            "field": f"tasks[{task_index}].fill_gaps.answers",
                            "reason": "answers must match blanks in order",
                        },
                    )
                return

            underscore_gaps = UNDERSCORE_GAP_RE.findall(content)
            if not underscore_gaps:
                raise FlowGenerationError(
                    "fill_gaps.content must contain blanks",
                    details={"field": f"tasks[{task_index}].fill_gaps.content", "reason": "expected blanks like ___ or {{answer}}"},
                )
            if len(normalized_answers) != len(underscore_gaps):
                raise FlowGenerationError(
                    "answers count does not match blanks count",
                    details={
                        "field": f"tasks[{task_index}].fill_gaps.answers",
                        "reason": "answers count does not match blanks count",
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
    def _extract_pollinations_url(body: dict[str, Any]) -> str:
        if not isinstance(body, dict):
            raise FlowGenerationError("Image provider returned invalid response format")
        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise FlowGenerationError("Image provider response does not contain image data")
        first = data[0] if isinstance(data[0], dict) else {}
        image_url = str(first.get("url", "")).strip()
        if not image_url:
            raise FlowGenerationError("Image provider response does not contain image url")
        return image_url

    @staticmethod
    def _detect_image_mime(image_bytes: bytes, header_content_type: str) -> str:
        header_mime = header_content_type.split(";", 1)[0].strip().lower()
        if header_mime in ALLOWED_IMAGE_MIME_TYPES:
            return header_mime

        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return header_mime or ""

    @staticmethod
    def _clean_text_for_alt(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        clean = re.sub(r"[{}*#`_]+", "", clean)
        if len(clean) > 180:
            clean = clean[:180].rstrip() + "..."
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
