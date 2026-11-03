# ANTÜ LIFECYCLE

An **Antü** is an instruction to KÜYEN from a Leftraru agent. It is not a fact. It becomes
knowledge only if the deterministic validator accepts it and the caller commits it.

## States

| State | Meaning | Version created |
| --- | --- | --- |
| `VALIDATED` | The candidate is structurally valid, its evidence resolves and it already passes the commit validation | no (until `commit`) |
| `REJECTED` | A validator found a defect; reasons are returned and recorded | no |
| `NO_SEMANTIC_CHANGE` | The Antü declares no new knowledge (e.g. verify only) | no |
| `CONFLICT` | The Antü targets a base version that is not current (`STALE_BASE`) | no |
| `REPLAYED` | This `antu_id` was already resolved; the earlier outcome is returned | no new one |
| `COMMITTED` | `commit()` persisted the validated candidate | yes |

## Flow

```python
execution = memory.execute_antu(antu, mapu_source="MAPU-02.txt")
if execution.status == "VALIDATED":
    result = memory.commit(execution)
```

`execute_antu` records `ANTU_RECEIVED` in the ledger. `commit` records `VERSION_COMMITTED`,
one unit revision and one outbox request. A rejected or conflicting Antü records its
reason and stays in the ledger forever.

## What the validator checks

* structure: `antu_id`, `kind`, `mapu`, `unit`, `coverage` and `proposal` are present and of
  the right type, before anything is written. A malformed Antü raises `ValidationRejected`
  (with `report["problems"]`) and, when it carries a usable `antu_id`, the rejection is
  recorded as `ANTU_REJECTED`;
* identity: stable ids, no merge by name collision;
* predicates: `source_predicate` preserved, no silent `related_to` degradation;
* polarity and temporal scope present and coherent;
* evidence: quote present at its offsets in the declared MAPU, hash matches;
* coverage: every processed unit is accounted for;
* referential integrity: every referenced entity, MAPU and unit exists;
* schema conformance of the resulting graph — the same check `commit` runs, so a contract
  defect is a `REJECTED` Antü, never a `VALIDATED` one that fails later.

## VALIDATED is not COMMITTED

`VALIDATED` means "this candidate would be accepted by the commit validation *now*". It does
not promise that the commit will succeed: between the two calls another writer can move
`CURRENT` (the commit then fails its compare-and-swap with `StoreError`) or the disk can fail.
What it does promise is that the failure is not a hidden contract defect, and that a failed
commit changes nothing: no version, no unit revision, no completed operation, and the
execution stays `VALIDATED` so it can be retried.

## Idempotency

`antu_id` is the idempotency key. Repeating an Antü returns `REPLAYED` with the previously
committed version; it never creates a second version and never rewrites history.

## Failures

A failed execution is not a lost instruction: `record_failed_antu` writes the reason to the
ledger and a `REJECTED` unit revision, so the unit history shows what was attempted.

## Two kinds of Antü (0.2.1)

`kuyen.product.classify_antu` separates the two, and each entry point refuses the other
kind, so the wrong engine cannot run:

| Kind | Entry point | Engine | Result |
| --- | --- | --- | --- |
| `DOCUMENT_INGESTION` | `kuyen.incorporate_document` | OpenViking + Skill | a canonical version, or a recorded rejection |
| `GRAPH_EDIT` | `kuyen.apply_graph_edit` / `memory.apply_antu` | an LLM that only proposes | a canonical version, or a recorded rejection |

### States of a graph-edit Antü

| State | Meaning | Version |
| --- | --- | --- |
| `COMMITTED` | validated and confirmed through the canonical commit | yes |
| `VALIDATED` | `dry_run=True`: validated, nothing written | no |
| `REJECTED` | an operation or the candidate broke the contract | no |
| `CLARIFICATION_REQUIRED` | the instruction is ambiguous | no |
| `CONFLICT` | contradiction, or `STALE_BASE` | no |
| `NO_CHANGES` | the interpretation produced no operation | no |
| `INTERPRETATION_FAILED` | the model output is not the contract | no |
| `REPLAYED` | that `antu_id` already finished | no |

One refused operation refuses the whole Antü: a single instruction never commits partially.
An Antü is identified by `antu_id` (derived from the literal instruction when not given), so
repeating it returns the earlier outcome instead of creating a second version. The
interpretation runs outside the writer lock; the commit re-checks the base version inside
it, so an edit computed on a version that already moved is refused with `STALE_BASE`.
