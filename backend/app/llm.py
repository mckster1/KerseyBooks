import json
import os
from dataclasses import dataclass
from typing import Optional
from urllib import error, request

from fastapi import HTTPException
import sqlite3


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None


DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4.1-mini",
    "openai-compatible": "gpt-4.1-mini",
}


def _setting(db: sqlite3.Connection, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return row["value"]
    return None


def get_llm_config(
    db: sqlite3.Connection,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMConfig:
    resolved_provider = (
        provider
        or _setting(db, "llm_provider")
        or os.getenv("LLM_PROVIDER")
        or "anthropic"
    ).strip().lower()

    if resolved_provider == "openai_compatible":
        resolved_provider = "openai-compatible"

    if resolved_provider not in DEFAULT_MODELS:
        raise HTTPException(
            400,
            "Unsupported AI provider. Use anthropic, openai, or openai-compatible.",
        )

    resolved_model = (
        model
        or _setting(db, "llm_model")
        or os.getenv("LLM_MODEL")
        or os.getenv("AGENT_MODEL")
        or DEFAULT_MODELS[resolved_provider]
    ).strip()

    if resolved_provider == "anthropic":
        api_key = (
            _setting(db, "anthropic_api_key")
            or _setting(db, "llm_api_key")
            or os.getenv("ANTHROPIC_API_KEY")
            or ""
        )
        base_url = None
    else:
        api_key = (
            _setting(db, "openai_api_key")
            or _setting(db, "llm_api_key")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("AGENT_API_KEY")
            or ""
        )
        base_url = (
            _setting(db, "openai_base_url")
            or _setting(db, "llm_base_url")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("AGENT_API_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")

    if not api_key:
        raise HTTPException(
            503,
            f"{resolved_provider} API key is not configured. Add it in Settings or .env.",
        )

    return LLMConfig(
        provider=resolved_provider,
        model=resolved_model,
        api_key=api_key,
        base_url=base_url,
    )


def complete_text(
    config: LLMConfig,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
) -> str:
    if config.provider == "anthropic":
        return _complete_anthropic(config, system_prompt, user_message, max_tokens)
    return _complete_openai_compatible(config, system_prompt, user_message, max_tokens)


def complete_json(
    config: LLMConfig,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 512,
) -> dict:
    raw = complete_text(config, system_prompt, user_message, max_tokens).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


def _complete_anthropic(
    config: LLMConfig,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> str:
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "anthropic package is not installed")

    client = anthropic.Anthropic(api_key=config.api_key)
    message = client.messages.create(
        model=config.model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


def _complete_openai_compatible(
    config: LLMConfig,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> str:
    payload = json.dumps(
        {
            "model": config.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
    ).encode("utf-8")
    http_request = request.Request(
        f"{config.base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(exc.code, f"AI provider request failed: {detail}")
    except error.URLError as exc:
        raise HTTPException(503, f"AI provider is unavailable: {exc.reason}")

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(502, "AI provider returned an unexpected response")
