from __future__ import annotations

import random
from typing import Optional

from .config import get_env
from .errors import ConfigError
from .groq_client import GroqClient
from .model_strategy import AVAILABLE_MODELS, SIMPLE_MODELS


def build_client() -> GroqClient:
    api_key = get_env("PROXY_API_KEY")
    if not api_key:
        raise ConfigError("PROXY_API_KEY is not configured")
    api_url = get_env("PROXY_API_URL", "http://91.103.253.236/generate")
    max_tokens = int(get_env("PROXY_MAX_TOKENS", "4096"))
    return GroqClient(api_key=api_key, api_url=api_url, default_max_tokens=max_tokens)


async def ask_ai(prompt: str, model: Optional[str] = None) -> dict[str, str]:
    selected_model = (model or random.choice(SIMPLE_MODELS)).strip()
    if selected_model not in AVAILABLE_MODELS:
        raise ConfigError(f"Unsupported model: {selected_model}")

    client = build_client()
    response = await client.chat_completion(
        model=selected_model,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"model": selected_model, "response": response}
