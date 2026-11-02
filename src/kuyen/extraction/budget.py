"""Hard budget accounting for OpenAI calls.

Prices are supplied by the experiment as a snapshot. The engine never hardcodes
tariffs. A call must be authorized before it is sent; actual usage is recorded
afterwards. No hidden SDK retries are allowed by the provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..errors import OpenAIBudgetExceededError


@dataclass(frozen=True)
class PricingSnapshot:
    model: str
    input_usd_per_million: float
    output_usd_per_million: float
    embedding_usd_per_million: float
    currency: str = "USD"
    source_url: str = ""
    retrieved_at: str = ""
    processing: str = "standard"
    surcharge_pct: float = 0.0

    def cost(self, *, input_tokens: int, output_tokens: int, embedding_tokens: int = 0) -> float:
        base = (
            max(0, input_tokens) * self.input_usd_per_million
            + max(0, output_tokens) * self.output_usd_per_million
            + max(0, embedding_tokens) * self.embedding_usd_per_million
        ) / 1_000_000
        return round(base * (1.0 + self.surcharge_pct), 10)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_usd_per_million": self.input_usd_per_million,
            "output_usd_per_million": self.output_usd_per_million,
            "embedding_usd_per_million": self.embedding_usd_per_million,
            "currency": self.currency,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "processing": self.processing,
            "surcharge_pct": self.surcharge_pct,
        }


@dataclass
class BudgetEntry:
    phase: str
    operation: str
    reserved_usd: float
    actual_usd: float
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    embedding_tokens: int
    response_id: str | None
    model: str | None
    status: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase, "operation": self.operation,
            "reserved_usd": self.reserved_usd, "actual_usd": self.actual_usd,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens, "embedding_tokens": self.embedding_tokens,
            "response_id": self.response_id, "model": self.model,
            "status": self.status, "created_at": self.created_at,
        }


class BudgetLedger:
    def __init__(
        self,
        *,
        total_usd: float,
        warning_ratio: float = 0.8,
        phase_caps: dict[str, float] | None = None,
    ) -> None:
        if total_usd <= 0:
            raise ValueError("budget total must be positive")
        self.total_usd = float(total_usd)
        self.warning_ratio = float(warning_ratio)
        self.phase_caps = dict(phase_caps or {})
        self.spent_usd = 0.0
        self.entries: list[BudgetEntry] = []

    @property
    def warning_threshold_usd(self) -> float:
        return round(self.total_usd * self.warning_ratio, 10)

    @property
    def remaining_usd(self) -> float:
        return round(max(0.0, self.total_usd - self.spent_usd), 10)

    def phase_spent(self, phase: str) -> float:
        return round(sum(item.actual_usd for item in self.entries if item.phase == phase), 10)

    def authorize(self, *, phase: str, operation: str, estimated_usd: float) -> dict[str, Any]:
        """Reject before a call if it could exceed the total, phase or 80% line."""
        estimated = max(0.0, float(estimated_usd))
        if self.spent_usd >= self.warning_threshold_usd:
            raise OpenAIBudgetExceededError(
                f"OpenAI budget warning threshold reached: spent ${self.spent_usd:.6f} of ${self.total_usd:.2f}"
            )
        if self.spent_usd + estimated > self.total_usd:
            raise OpenAIBudgetExceededError(
                f"OpenAI budget would be exceeded: spent ${self.spent_usd:.6f}, estimate ${estimated:.6f}, total ${self.total_usd:.2f}"
            )
        cap = self.phase_caps.get(phase)
        if cap is not None and self.phase_spent(phase) + estimated > cap:
            raise OpenAIBudgetExceededError(
                f"OpenAI phase budget would be exceeded: {phase} spent ${self.phase_spent(phase):.6f}, estimate ${estimated:.6f}, cap ${cap:.2f}"
            )
        return {
            "phase": phase, "operation": operation, "estimated_usd": estimated,
            "remaining_before_usd": self.remaining_usd,
        }

    def record(
        self,
        *,
        phase: str,
        operation: str,
        reserved_usd: float,
        actual_usd: float,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        embedding_tokens: int = 0,
        response_id: str | None = None,
        model: str | None = None,
        status: str = "completed",
    ) -> BudgetEntry:
        entry = BudgetEntry(
            phase=phase, operation=operation, reserved_usd=round(reserved_usd, 10),
            actual_usd=round(float(actual_usd), 10), input_tokens=int(input_tokens),
            output_tokens=int(output_tokens), reasoning_tokens=int(reasoning_tokens),
            embedding_tokens=int(embedding_tokens), response_id=response_id,
            model=model, status=status,
        )
        self.entries.append(entry)
        self.spent_usd = round(self.spent_usd + entry.actual_usd, 10)
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_usd": self.total_usd,
            "warning_ratio": self.warning_ratio,
            "warning_threshold_usd": self.warning_threshold_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "phase_caps": self.phase_caps,
            "entries": [item.to_dict() for item in self.entries],
        }
