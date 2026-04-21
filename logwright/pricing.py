from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRICING_AS_OF = "2026-04-20"


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    canonical_model: str
    input_cost_per_million: float
    output_cost_per_million: float
    source_url: str
    aliases: tuple[str, ...] = ()
    prefix_aliases: tuple[str, ...] = ()
    note: str = "standard text-token pricing"


MODEL_PRICING: tuple[ModelPricing, ...] = (
    ModelPricing(
        provider="openai",
        canonical_model="gpt-5.4-mini",
        input_cost_per_million=0.75,
        output_cost_per_million=4.50,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.4-mini",
        aliases=("gpt-5.4-mini",),
        prefix_aliases=("gpt-5.4-mini-",),
    ),
    ModelPricing(
        provider="anthropic",
        canonical_model="claude-sonnet-4-6",
        input_cost_per_million=3.00,
        output_cost_per_million=15.00,
        source_url="https://www.anthropic.com/claude/sonnet",
        aliases=("claude-sonnet-4-6",),
        prefix_aliases=("claude-sonnet-4-6-",),
    ),
    ModelPricing(
        provider="gemini",
        canonical_model="gemini-2.5-flash",
        input_cost_per_million=0.30,
        output_cost_per_million=2.50,
        source_url="https://ai.google.dev/gemini-api/docs/pricing",
        aliases=("gemini-2.5-flash",),
        prefix_aliases=("gemini-2.5-flash-",),
    ),
)


def resolve_model_pricing(provider: str, model: str) -> ModelPricing | None:
    for pricing in MODEL_PRICING:
        if pricing.provider != provider:
            continue
        if model == pricing.canonical_model or model in pricing.aliases:
            return pricing
        if any(model.startswith(prefix) for prefix in pricing.prefix_aliases):
            return pricing
    return None


def estimate_usage_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    if provider == "heuristic":
        return {
            "estimated_cost_usd": 0.0,
            "cost_note": "heuristic mode",
            "cost_pricing_as_of": PRICING_AS_OF,
            "cost_source_url": None,
        }

    pricing = resolve_model_pricing(provider, model)
    if not pricing:
        return {
            "estimated_cost_usd": None,
            "cost_note": f"no pricing data for {model}",
            "cost_pricing_as_of": PRICING_AS_OF,
            "cost_source_url": None,
        }

    estimated_cost = (
        (input_tokens / 1_000_000) * pricing.input_cost_per_million
        + (output_tokens / 1_000_000) * pricing.output_cost_per_million
    )
    return {
        "estimated_cost_usd": round(estimated_cost, 6),
        "cost_note": f"{pricing.note} for {pricing.canonical_model}",
        "cost_pricing_as_of": PRICING_AS_OF,
        "cost_source_url": pricing.source_url,
    }
