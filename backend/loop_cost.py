"""Source-to-note loop cost preflight + cap enforcement.

The #4 live run proved the loop works, but the per-job / daily cost caps were
advisory only — nothing refused a job that would exceed them. This module makes
the cap enforceable BEFORE any paid provider call: estimate translate (chunked,
~1:1 token ratio) + summary cost from transcript size, then raise if the
estimate exceeds the per-job cap. Pure functions, no provider/network/cost.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass


def _prices() -> tuple[float, float]:
    return (
        float(os.getenv("OPENAI_INPUT_USD_PER_MTOK", "0.15")),
        float(os.getenv("OPENAI_OUTPUT_USD_PER_MTOK", "0.60")),
    )


def _usd(input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = _prices()
    return (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)


SUMMARY_INPUT_CHAR_CAP = 24000  # summarize prompt truncates transcript to this
SUMMARY_OUTPUT_TOKENS = 1200    # bounded JSON note summary


@dataclass(frozen=True)
class LoopCostEstimate:
    translate_usd: float
    summary_usd: float
    total_usd: float
    transcript_chars: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "translate_usd": round(self.translate_usd, 6),
            "summary_usd": round(self.summary_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "transcript_chars": self.transcript_chars,
        }


class CostCapExceeded(RuntimeError):
    """Raised when an estimated job cost exceeds the approved per-job cap."""


def estimate_source_to_note_cost(transcript_chars: int) -> LoopCostEstimate:
    chars = max(0, int(transcript_chars))
    # translate processes the whole transcript, output zh is ~1:1 with input tokens
    tr_in = math.ceil(chars / 4)
    tr_out = tr_in
    translate_usd = _usd(tr_in, tr_out)
    # summary truncates input and emits a bounded note
    sum_in = math.ceil(min(chars, SUMMARY_INPUT_CHAR_CAP) / 4)
    summary_usd = _usd(sum_in, SUMMARY_OUTPUT_TOKENS)
    total = translate_usd + summary_usd
    return LoopCostEstimate(translate_usd, summary_usd, total, chars)


def enforce_cost_cap(estimate: LoopCostEstimate, per_job_cap_usd: float) -> None:
    if per_job_cap_usd <= 0:
        raise CostCapExceeded("per-job cost cap must be positive")
    if estimate.total_usd > per_job_cap_usd:
        raise CostCapExceeded(
            f"estimated ${estimate.total_usd:.4f} exceeds per-job cap ${per_job_cap_usd:.4f}"
        )
