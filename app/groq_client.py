import json
from typing import Any
from typing import Optional

import httpx

from .errors import ProxyError, TimeoutError


class GroqClient:
    def __init__(self, api_key: str, api_url: str, default_max_tokens: int = 4096):
        self.api_key = api_key
        self.api_url = api_url
        self.default_max_tokens = default_max_tokens

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
        parts = []
        for message in messages:
            role = message.get("role", "user").upper()
            content = message.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n".join(parts).strip()

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        seed: Optional[int] = None,
    ) -> str:
        prompt = self._messages_to_prompt(messages)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": self.default_max_tokens,
        }
        if seed is not None:
            payload["seed"] = seed

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Proxy timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            details = exc.response.text
            raise ProxyError(f"Proxy HTTP error {exc.response.status_code}: {details}") from exc
        except httpx.RequestError as exc:
            raise ProxyError(f"Proxy connection error: {exc}") from exc

        try:
            response_data = response.json()
        except json.JSONDecodeError as exc:
            raise ProxyError("Proxy returned non-JSON response") from exc

        if isinstance(response_data, dict):
            for key in ("response", "text", "content", "output"):
                value = response_data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            try:
                return response_data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, AttributeError):
                pass

        raise ProxyError("Unexpected proxy response format")
