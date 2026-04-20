from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Optional

from .ai import build_client
from .errors import FlowGenerationError, ProxyError
from .model_availability import get_available_models, mark_model_unavailable
from .model_strategy import SIMPLE_MODELS, STRONG_MODELS

ALLOWED_SUBJECTS = {"math", "language", "physics", "chemistry", "other"}
ALLOWED_TASK_TYPES = {"note", "test", "true_false", "file", "match_cards", "fill_gaps"}

TASK_TYPE_CONTRACTS = {
    "note": {"content": "str markdown"},
    "test": {"questions": [{
        "question": "str",
        "options": [{"option": "str", "is_correct": "bool"}],
    }]},
    "true_false": {"statements": [{"statement": "str", "is_true": "bool"}]},
    "file": {"image_detailed_description": "str"},
    "match_cards": {"pairs": [{"left": "str", "right": "str"}]},
    "word_list": {"pairs": [{"word": "str", "translation": "str"}]},
    "fill_gaps": {"content": "str markdown", "answers": ["str"]},
}


class FlowService:
    def __init__(self, *, simple_model: Optional[str] = None, strong_model: Optional[str] = None):
        self.client = build_client()
        self.simple_pool = [simple_model] if simple_model else list(SIMPLE_MODELS)
        self.strong_pool = [strong_model] if strong_model else list(STRONG_MODELS)

    async def generate(self, user_request: str) -> dict[str, Any]:
        topic = await self._step_topic(user_request)
        subject = await self._step_subject(topic)
        sections = await self._step_sections(topic, subject)
        references = await self._step_references(topic, sections, user_request)
        section_task_types = await self._step_task_types(topic, references)
        tasks_by_section = await self._step_tasks(topic, references, section_task_types)

        return {
            "topic": topic,
            "subject": subject,
            "sections": [{"title": item["title"]} for item in sections],
            "references": references,
            "section_task_types": section_task_types,
            "tasks_by_section": tasks_by_section,
            "task_contracts": TASK_TYPE_CONTRACTS,
            "models": {
                "simple": "random_from_simple_pool",
                "strong": "random_from_strong_pool",
            },
        }

    async def _step_topic(self, user_request: str) -> str:
        return await self._call_json(
            step_name="topic",
            model_pool=self.simple_pool,
            prompt=(
                "User request is provided. Form a short lesson topic and return strict JSON only: "
                '{"topic": "..."}. Topic must be concise and suitable for a lesson title.'
            ),
            payload={"request": user_request},
            validator=self._validate_topic,
        )

    async def _step_subject(self, topic: str) -> str:
        return await self._call_json(
            step_name="subject",
            model_pool=self.simple_pool,
            prompt=(
                "Lesson topic is provided. Define subject and return strict JSON only: "
                '{"subject":"..."}. Allowed: math, language, physics, chemistry, other.'
            ),
            payload={"topic": topic},
            validator=self._validate_subject,
        )

    async def _step_sections(self, topic: str, subject: str) -> list[dict[str, str]]:
        return await self._call_json(
            step_name="sections",
            model_pool=self.strong_pool,
            prompt=(
                "Lesson topic and subject are provided. Form a list of interactive lesson sections. "
                "Each section title must be 1-2 words. Consider each section has theory and practice. "
                'Return strict JSON only: {"section":[{"title":"..."}]}'
            ),
            payload={"topic": topic, "subject": subject},
            validator=self._validate_sections,
        )

    async def _step_references(
        self, topic: str, sections: list[dict[str, str]], user_request: str
    ) -> list[dict[str, str]]:
        return await self._call_json(
            step_name="references",
            model_pool=self.strong_pool,
            prompt=(
                "User request, lesson topic, and section titles are provided. Form lesson reference per section. "
                'Return strict JSON only: {"reference":[{"section":"...","reference":"..."}]}'
            ),
            payload={"request": user_request, "topic": topic, "sections": sections},
            validator=lambda parsed: self._validate_references(parsed, sections, topic),
        )

    async def _step_task_types(self, topic: str, references: list[dict[str, str]]) -> list[dict[str, Any]]:
        return await self._call_json(
            step_name="task_types",
            model_pool=self.strong_pool,
            prompt=(
                "Lesson topic and section references are provided. Define from 1 to 3 task types for each section. "
                'Return strict JSON only: {"section":[{"section":"...","task_types":["note"]}]}. '
                "Allowed task_types: note, test, true_false, file, match_cards, fill_gaps."
            ),
            payload={"topic": topic, "references": references},
            validator=lambda parsed: self._validate_task_types(parsed, references),
        )

    async def _step_tasks(
        self,
        topic: str,
        references: list[dict[str, str]],
        section_task_types: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ref_map = {item["section"]: item["reference"] for item in references}

        async def generate_for_section(item: dict[str, Any]) -> dict[str, Any]:
            section = item["section"]
            task_types = item["task_types"]
            validated_tasks = await self._call_json(
                step_name=f"tasks:{section}",
                model_pool=self.strong_pool,
                prompt=(
                    "You are creating an interactive textbook. "
                    "Generate tasks for the section and return strict JSON only: {\"tasks\":[{\"note\":{...}}]}. "
                    "Each task object must contain exactly one key from task_types. "
                    "Use provided JSON contracts per task type."
                ),
                payload={
                    "topic": topic,
                    "section_title": section,
                    "reference": ref_map.get(section, ""),
                    "task_types": task_types,
                    "contracts": {k: v for k, v in TASK_TYPE_CONTRACTS.items() if k in task_types},
                },
                validator=lambda parsed, s=section, t=task_types: self._validate_tasks_json(parsed, t, s),
            )
            return {
                "section": section,
                "reference": ref_map.get(section, ""),
                "task_types": task_types,
                "tasks": validated_tasks,
            }

        jobs: list[Awaitable[dict[str, Any]]] = [generate_for_section(item) for item in section_task_types]
        return list(await asyncio.gather(*jobs))

    def _validate_tasks(self, *, tasks: list[Any], allowed_task_types: list[str], section: str) -> list[dict[str, Any]]:
        validated: list[dict[str, Any]] = []
        allowed_set = set(allowed_task_types)
        for task in tasks:
            if not isinstance(task, dict) or len(task) != 1:
                continue
            task_type, payload = next(iter(task.items()))
            if task_type not in allowed_set or not isinstance(payload, dict):
                continue
            validated.append({task_type: payload})

        if not validated:
            raise FlowGenerationError(f"No valid tasks generated for section '{section}'")
        return validated

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
                raise FlowGenerationError(
                    f"Step {step_name} has no available models in pool"
                )

            unused_pool = [m for m in available_pool if m not in used_models]
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
                if not isinstance(parsed, dict):
                    raise FlowGenerationError(f"Step {step_name} returned non-object JSON")
                if validator is None:
                    return parsed
                return validator(parsed)
            except Exception as exc:
                last_error = exc
                if self._is_rate_limited_error(exc):
                    mark_model_unavailable(model)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))

        raise FlowGenerationError(
            f"Step {step_name} failed after 3 attempts (models={used_models}): {last_error}"
        )

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
            raise FlowGenerationError("Step topic returned empty topic")
        return topic

    @staticmethod
    def _validate_subject(parsed: dict[str, Any]) -> str:
        subject = str(parsed.get("subject", "")).strip().lower()
        if subject not in ALLOWED_SUBJECTS:
            subject = "other"
        return subject

    @staticmethod
    def _validate_sections(parsed: dict[str, Any]) -> list[dict[str, str]]:
        raw_sections = parsed.get("section")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise FlowGenerationError("Step sections returned invalid section list")

        sections: list[dict[str, str]] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", title)
            if len(words) > 2:
                title = " ".join(words[:2])
            sections.append({"title": title})

        if not sections:
            raise FlowGenerationError("Step sections produced no valid titles")
        return sections

    @staticmethod
    def _validate_references(
        parsed: dict[str, Any], sections: list[dict[str, str]], topic: str
    ) -> list[dict[str, str]]:
        raw_references = parsed.get("reference")
        if not isinstance(raw_references, list):
            raise FlowGenerationError("Step references returned invalid list")

        by_section = {item["title"]: "" for item in sections}
        for item in raw_references:
            if not isinstance(item, dict):
                continue
            section = str(item.get("section", "")).strip()
            reference = str(item.get("reference", "")).strip()
            if section in by_section and reference:
                by_section[section] = reference

        result = []
        for section in sections:
            title = section["title"]
            reference = by_section.get(title) or f"Practice and explain {title} in context of {topic}."
            result.append({"section": title, "reference": reference})
        return result

    @staticmethod
    def _validate_task_types(parsed: dict[str, Any], references: list[dict[str, str]]) -> list[dict[str, Any]]:
        raw_section = parsed.get("section")
        if not isinstance(raw_section, list):
            raise FlowGenerationError("Step task_types returned invalid list")

        mapped: dict[str, list[str]] = {item["section"]: [] for item in references}
        for item in raw_section:
            if not isinstance(item, dict):
                continue
            section = str(item.get("section", "")).strip()
            task_types = item.get("task_types")
            if section not in mapped or not isinstance(task_types, list):
                continue
            valid = [str(task).strip() for task in task_types if str(task).strip() in ALLOWED_TASK_TYPES]
            mapped[section] = list(dict.fromkeys(valid))

        result = []
        for item in references:
            section = item["section"]
            task_types = mapped.get(section) or ["note"]
            result.append({"section": section, "task_types": task_types})
        return result

    def _validate_tasks_json(self, parsed: dict[str, Any], allowed_task_types: list[str], section: str) -> list[dict[str, Any]]:
        tasks = parsed.get("tasks")
        if not isinstance(tasks, list):
            raise FlowGenerationError(f"Step tasks for section '{section}' returned invalid tasks list")
        return self._validate_tasks(tasks=tasks, allowed_task_types=allowed_task_types, section=section)

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
            snippet = cleaned[start: end + 1]
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed

        raise FlowGenerationError("Model response does not contain valid JSON object")
