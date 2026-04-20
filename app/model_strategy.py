from __future__ import annotations

AVAILABLE_MODELS = {
    "allam-2-7b": "Allam 2 7B",
    "canopylabs/orpheus-arabic-saudi": "Canopy Labs Orpheus Arabic Saudi",
    "canopylabs/orpheus-v1-english": "Canopy Labs Orpheus V1 English",
    "groq/compound": "Groq Compound",
    "groq/compound-mini": "Groq Compound Mini",
    "llama-3.1-8b-instant": "Llama 3.1 8B Instant",
    "llama-3.3-70b-versatile": "Llama 3.3 70B Versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct": "Meta Llama 4 Scout 17B 16E Instruct",
    "meta-llama/llama-prompt-guard-2-22m": "Meta Llama Prompt Guard 2 22M",
    "meta-llama/llama-prompt-guard-2-86m": "Meta Llama Prompt Guard 2 86M",
    "moonshotai/kimi-k2-instruct": "Moonshot AI Kimi K2 Instruct",
    "moonshotai/kimi-k2-instruct-0905": "Moonshot AI Kimi K2 Instruct 0905",
    "openai/gpt-oss-120b": "OpenAI GPT-OSS 120B",
    "openai/gpt-oss-20b": "OpenAI GPT-OSS 20B",
    "openai/gpt-oss-safeguard-20b": "OpenAI GPT-OSS Safeguard 20B",
    "qwen/qwen3-32b": "Qwen Qwen3 32B",
    "whisper-large-v3": "Whisper Large V3",
    "whisper-large-v3-turbo": "Whisper Large V3 Turbo",
}

SIMPLE_MODELS = [
    "llama-3.1-8b-instant",
    "groq/compound-mini",
    "openai/gpt-oss-20b",
]

STRONG_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "moonshotai/kimi-k2-instruct",
]

MODEL_CANDIDATES_BY_TASK = {
    "normalize_input": SIMPLE_MODELS + STRONG_MODELS,
    "subject_routing": SIMPLE_MODELS,
    "archetype_routing": SIMPLE_MODELS,
    "section_spec": STRONG_MODELS + SIMPLE_MODELS,
    "task_generation": SIMPLE_MODELS + STRONG_MODELS,
}


def get_model_candidates(task_name: str) -> list[str]:
    candidates = MODEL_CANDIDATES_BY_TASK.get(task_name, SIMPLE_MODELS + STRONG_MODELS)
    valid = [model for model in candidates if model in AVAILABLE_MODELS]
    return valid
