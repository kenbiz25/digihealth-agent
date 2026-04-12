"""Base agent class with shared AI client logic."""
import anthropic
import json
import time
from typing import Any
from backend.config import (
    AI_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY,
    CLAUDE_MODELS, OPENAI_MODELS,
)


def get_ai_client(provider: str = None):
    """Return the appropriate AI client."""
    provider = provider or AI_PROVIDER
    if provider == "claude":
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    elif provider == "openai":
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_API_KEY)
    raise ValueError(f"Unknown provider: {provider}")


def get_model_name(tier: str, provider: str = None) -> str:
    """Resolve model tier to actual model name."""
    provider = provider or AI_PROVIDER
    models = CLAUDE_MODELS if provider == "claude" else OPENAI_MODELS
    return models.get(tier, models["balanced"])


def call_claude(
    client: anthropic.Anthropic,
    system: str,
    user: str,
    model_tier: str = "balanced",
    max_tokens: int = 4096,
    tools: list = None,
) -> tuple[str, int]:
    """Call Claude and return (text_response, tokens_used)."""
    model = get_model_name(model_tier, "claude")
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if tools:
        kwargs["tools"] = tools

    for attempt in range(4):
        try:
            response = client.messages.create(**kwargs)
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            tokens = response.usage.input_tokens + response.usage.output_tokens
            return text, tokens
        except anthropic.RateLimitError:
            if attempt < 3:
                wait = 60 * (attempt + 1)   # 60s, 120s, 180s
                print(f"[AI] Rate limit hit. Waiting {wait}s before retry {attempt + 2}/4...")
                time.sleep(wait)
            else:
                raise


def call_openai(
    client,
    system: str,
    user: str,
    model_tier: str = "balanced",
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """Call OpenAI and return (text_response, tokens_used)."""
    model = get_model_name(model_tier, "openai")
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return text, tokens


def call_ai(
    client,
    system: str,
    user: str,
    model_tier: str = "balanced",
    max_tokens: int = 4096,
    provider: str = None,
) -> tuple[str, int]:
    """Unified AI call dispatcher."""
    provider = provider or AI_PROVIDER
    if provider == "claude":
        return call_claude(client, system, user, model_tier, max_tokens)
    return call_openai(client, system, user, model_tier, max_tokens)


def parse_json_response(text: str) -> Any:
    """Extract JSON from AI response even if wrapped in markdown code block."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)
