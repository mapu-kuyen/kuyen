"""The operational outcome of one Antü and of each of its operations (§7).

KÜYEN distinguishes *what the knowledge became* from *what the run did*. A run that changed
nothing can be an honest `NO_CHANGES`, an `ALREADY_SATISFIED` request, a permission block, or a
model that could not interpret the instruction. Those are different facts and the caller must
be able to tell them apart, so this module maps the internal statuses onto one closed
vocabulary and never lets a limitation look like an absence of change.

The vocabulary is the one the operational-coverage experiment requires:

    COMMITTED, ALREADY_SATISFIED, NOT_APPLICABLE, REQUIRES_DATA_ACCESS, NEEDS_CLARIFICATION,
    OUT_OF_SCOPE, BLOCKED_BY_PERMISSION, INVALID_PROPOSAL, EXECUTION_FAILED

plus two internal values that exist because a *mixed* Antü cannot be reduced to one state:
`NO_CHANGES` (several declarative declines with different reasons) and `NOT_EVALUATED` (a dry
run, or nothing the engine could classify).

Nothing here writes, validates or calls a model: it is a pure projection of a finished run.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

COMMITTED = "COMMITTED"
ALREADY_SATISFIED = "ALREADY_SATISFIED"
NOT_APPLICABLE = "NOT_APPLICABLE"
REQUIRES_DATA_ACCESS = "REQUIRES_DATA_ACCESS"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
BLOCKED_BY_PERMISSION = "BLOCKED_BY_PERMISSION"
INVALID_PROPOSAL = "INVALID_PROPOSAL"
EXECUTION_FAILED = "EXECUTION_FAILED"
#: Several declarative declines with different reasons: no single state describes the Antü.
NO_CHANGES = "NO_CHANGES"
#: A dry run, or a state the engine cannot classify. Never a success and never "no change".
NOT_EVALUATED = "NOT_EVALUATED"

OUTCOMES = (COMMITTED, ALREADY_SATISFIED, NOT_APPLICABLE, REQUIRES_DATA_ACCESS,
            NEEDS_CLARIFICATION, OUT_OF_SCOPE, BLOCKED_BY_PERMISSION, INVALID_PROPOSAL,
            EXECUTION_FAILED, NO_CHANGES, NOT_EVALUATED)

#: Applicability states the model may declare on a single operation, reused verbatim as
#: per-operation outcomes: a decline says exactly what the model claimed and KÜYEN verified.
DECLINED_OUTCOMES = (ALREADY_SATISFIED, NOT_APPLICABLE, REQUIRES_DATA_ACCESS,
                     NEEDS_CLARIFICATION, OUT_OF_SCOPE, BLOCKED_BY_PERMISSION)

_STATUS_OUTCOME = {
    # A validated candidate is only `COMMITTED` once the canonical commit happened; the
    # caller passes `committed` and this module does not assume it.
    "VALIDATED": COMMITTED,
    "NO_CHANGES": NO_CHANGES,
    "CLARIFICATION_REQUIRED": NEEDS_CLARIFICATION,
    # A stale base or a proposal that contradicts the current knowledge is not knowledge:
    # nothing was written and the proposal has to be produced again.
    "CONFLICT": INVALID_PROPOSAL,
    "REJECTED": INVALID_PROPOSAL,
    # The model failed to interpret (no JSON, no content) or returned nothing without saying
    # why. That is a limitation of the interpretation, never an absence of changes.
    "INTERPRETATION_FAILED": EXECUTION_FAILED,
    "INTERPRETATION_INCOMPLETE": EXECUTION_FAILED,
    # Idempotent replay of an Antü that already reached a terminal state: the request is
    # satisfied by the history, so it is reported as satisfied and not as a new change.
    "REPLAYED": ALREADY_SATISFIED,
}


def is_declining(outcome: str) -> bool:
    """True when the outcome states that no change is required or possible."""
    return outcome in DECLINED_OUTCOMES or outcome == NO_CHANGES


def decline_outcome(declined: Iterable[Mapping[str, Any]]) -> str:
    """The single outcome of a set of declarative declines, or `NO_CHANGES` when mixed."""
    states = [str(item.get("applicability") or "") for item in declined]
    states = [item for item in states if item in DECLINED_OUTCOMES]
    if not states:
        return NO_CHANGES
    return states[0] if len(set(states)) == 1 else NO_CHANGES


def run_outcome(status: str, *, committed: bool = False,
                declined: Iterable[Mapping[str, Any]] = ()) -> str:
    """The outcome of a whole Antü: what happened to this KÜYEN's memory.

    `committed` is authoritative for a validated run: an Antü whose candidate never reached a
    canonical version is `NOT_EVALUATED`, not `COMMITTED` (§7: an operation applied to a
    working state is not a persistent change).
    """
    state = str(status or "").strip().upper()
    if state == "VALIDATED":
        return COMMITTED if committed else NOT_EVALUATED
    if state == "NO_CHANGES" and declined:
        # Every operation was declined with a verifiable reason: the Antü is *satisfied*,
        # *not applicable*, *blocked*, ... and that is a different fact from "no change".
        return decline_outcome(declined)
    return _STATUS_OUTCOME.get(state, NOT_EVALUATED)


def operation_outcomes(*, status: str, committed: bool = False,
                       accepted: Iterable[Mapping[str, Any]] = (),
                       declined: Iterable[Mapping[str, Any]] = (),
                       rejected: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Per-operation outcomes, so a mixed Antü is legible instead of uniform.

    An operation that passed validation is `COMMITTED` only if the version was committed; a
    rejected operation is `INVALID_PROPOSAL`; a declined one keeps the state KÜYEN verified.
    """
    overall = run_outcome(status, committed=committed, declined=declined)
    accepted_outcome = COMMITTED if committed else NOT_EVALUATED
    records: list[dict[str, Any]] = []
    for item in accepted:
        records.append({"operation_id": str(item.get("operation_id") or ""),
                        "op": str(item.get("op") or ""), "outcome": accepted_outcome})
    for item in declined:
        records.append({"operation_id": str(item.get("operation_id") or ""),
                        "op": str(item.get("op") or ""),
                        "outcome": str(item.get("applicability") or NOT_EVALUATED),
                        "verified": bool(item.get("verified")),
                        "detail": item.get("explanation") or item.get("detail")})
    for item in rejected:
        records.append({"operation_id": str(item.get("operation_id") or ""),
                        "op": str(item.get("op") or ""), "outcome": INVALID_PROPOSAL,
                        "detail": f"{item.get('code')}: {item.get('message')}".strip(": ")})
    if not records:
        # A run-level failure (unreadable proposal, stale base) has no operation to report.
        records.append({"operation_id": None, "op": None, "outcome": overall})
    return records


def summarize(outcomes: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Counts per outcome, for reporting and for the run record."""
    summary: dict[str, int] = {}
    for item in outcomes:
        state = str(item.get("outcome") or NOT_EVALUATED)
        summary[state] = summary.get(state, 0) + 1
    return dict(sorted(summary.items()))

