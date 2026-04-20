from __future__ import annotations

import threading
import time
from typing import Any

from .errors import ModelUnavailableError
from .model_strategy import SIMPLE_MODELS, STRONG_MODELS

_LOCK = threading.Lock()
_UNAVAILABLE_UNTIL: dict[str, float] = {}
COOLDOWN_SECONDS = 5 * 60


def _is_available_unlocked(model: str, now: float) -> bool:
    until = _UNAVAILABLE_UNTIL.get(model)
    if until is None:
        return True
    if until <= now:
        del _UNAVAILABLE_UNTIL[model]
        return True
    return False


def mark_model_unavailable(model: str, cooldown_seconds: int = COOLDOWN_SECONDS) -> None:
    now = time.time()
    with _LOCK:
        _UNAVAILABLE_UNTIL[model] = now + max(1, int(cooldown_seconds))


def get_available_models(pool: list[str]) -> list[str]:
    now = time.time()
    with _LOCK:
        return [model for model in pool if _is_available_unlocked(model, now)]


def get_unavailable_models(pool: list[str]) -> list[dict[str, Any]]:
    now = time.time()
    result: list[dict[str, Any]] = []
    with _LOCK:
        for model in pool:
            until = _UNAVAILABLE_UNTIL.get(model)
            if until is None:
                continue
            if until <= now:
                del _UNAVAILABLE_UNTIL[model]
                continue
            result.append(
                {
                    "model": model,
                    "available_in_seconds": max(1, int(until - now)),
                }
            )
    return result


def ensure_base_capacity() -> dict[str, Any]:
    simple_available = get_available_models(list(SIMPLE_MODELS))
    strong_available = get_available_models(list(STRONG_MODELS))

    if not simple_available or not strong_available:
        raise ModelUnavailableError(
            "No available models in required pool(s). "
            f"simple_available={simple_available}, strong_available={strong_available}"
        )

    return {
        "simple_available": simple_available,
        "strong_available": strong_available,
    }
