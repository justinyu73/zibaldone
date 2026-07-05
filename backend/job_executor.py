"""Approved paid-stage executor for the job worker (block #5-live, gated).

The worker stops at the paid/durable boundary; this executor performs the real
work once a boundary is approved. Its safety contract: a paid stage runs a cost
preflight and enforces the per-job cap BEFORE any provider call, so an over-cap
job is refused without spending. Provider/writer functions are injected, so the
wiring + cap gate are fully testable with stubs (no network, no spend); live
runs pass the real translate / summarize / save callables.
"""
from __future__ import annotations

from typing import Any, Callable

from loop_cost import enforce_cost_cap, estimate_source_to_note_cost


class JobExecutor:
    def __init__(
        self,
        *,
        translator_fn: Callable[[str], str],
        summarizer_fn: Callable[[str, str, str], dict[str, Any]],
        writer_fn: Callable[..., dict[str, Any]],
        per_job_cap_usd: float = 0.03,
    ):
        self.translator_fn = translator_fn
        self.summarizer_fn = summarizer_fn
        self.writer_fn = writer_fn
        self.per_job_cap_usd = per_job_cap_usd

    def preflight(self, en_text: str) -> dict[str, Any]:
        """Estimate cost and enforce the per-job cap before any paid call."""
        estimate = estimate_source_to_note_cost(len(en_text))
        enforce_cost_cap(estimate, self.per_job_cap_usd)
        return estimate.as_dict()

    def run_translate(self, en_text: str) -> str:
        self.preflight(en_text)  # refuses (raises) before calling the provider
        return self.translator_fn(en_text)

    def run_summarize(self, en_text: str, title: str, source_url: str) -> dict[str, Any]:
        self.preflight(en_text)
        return self.summarizer_fn(en_text, title, source_url)

    def run_write(self, **kwargs: Any) -> dict[str, Any]:
        return self.writer_fn(**kwargs)
