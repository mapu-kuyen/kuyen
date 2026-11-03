# CHANGELOG

## Unreleased — productive graph and Antu versioning

KUYEN_PRODUCTIVE_GRAPH_11. Two additive capabilities and the hardening they required. No
persisted-format change: every store written before this work remains readable.

### Added
* **Direct Antü graph editing.** `KuyenMemory.apply_antu` interprets a literal instruction
  with a model that only proposes, validates the proposal deterministically and commits it
  through the existing canonical protocol. Nine operation types, clarification and conflict
  states, retraction and supersession that never delete, and a reproducible diff between
  versions (`memory.diff`). OpenViking is never executed on this path.
* **Statement origin.** Every relation and assertion can declare where it comes from
  (`DOCUMENT_EVIDENCE`, `ANTU_INSTRUCTION`, `PRIOR_VERSION`, `INFERENCE_PENDING`) and the
  canonical validator refuses an instruction that claims documentary verification.
* **Statement semantics.** `modality` (`FACT`…`UNKNOWN`) and `attribution` are first-class;
  absence is `UNKNOWN`, never `FACT`.
* **`kuyen-provider-result-v2`**, accepted alongside v1, plus three optional evidence fields
  (`context`, `source_unit_id`, `declared_offsets`).
* **`kuyen.product`**: `classify_antu`, `incorporate_document` and `apply_graph_edit`, so the
  two kinds of Antü cannot execute the wrong engine.
* `memory.current_objects` and `AntuEditResult`; new ledger events `ANTU_EDIT_PROPOSED` and
  `ANTU_CLARIFICATION_REQUIRED`.

### Changed
* **MAPU identity is checked, not guessed.** A declared `mapu_id` that does not belong to
  the context is refused as `MAPU_ID_NOT_IN_CONTEXT`; the single-MAPU fallback no longer
  covers an invented identity.
* **The quote is the authority for the offsets.** A verifiable exact quote is no longer
  discarded because the model wrote wrong offsets: the span is located deterministically
  and the declared offsets are kept as auxiliary information (`QUOTE_AUTHORITATIVE`). A
  quote that does not exist is still refused, and an ambiguous one is never guessed.
* **No silent `POSITIVE`.** An undeclared polarity is `UNKNOWN` and the object is not
  admitted, in the materializer and in the normalizer alike.
* `SdkOpenVikingAdapter.read_candidate` delegates to `CandidateMaterializer` instead of
  re-implementing a lossy parser: assertions and every declared evidence entry are kept.
* **The compile instruction asks for the native tree**, not for an aggregate
  `kuyen_result.json`. A live compilation of a real document produced a malformed aggregate
  that blocked an otherwise valid tree; a malformed aggregate is now recorded
  (`structured_result_ignored`) and the tree is materialized
  (`native_structured_after_invalid_structured_result`).
* **A declared native predicate is preserved, not rejected.** The `relation`/`predicate`
  field of a native row is recorded as `source_predicate`; a term the ontology does not know
  becomes `NATIVE_PREDICATE_PRESERVED_UNMAPPED` (relations) or
  `SCALAR_PREDICATE_PRESERVED_UNMAPPED` (assertions) with `mapping_status: UNMAPPED` and a
  WARNING. An undeclared unknown predicate is still an error.
* **`DOCUMENT_REFERENCE` origin** for an object that comes from a MAPU without a verified
  quote (`evidence_policy: "document"`, or a producer that only declares the source URI):
  documentary provenance without documentary verification. `DOCUMENT_EVIDENCE` without
  evidence and `DOCUMENT_REFERENCE` without a MAPU are refused by the canonical validator.
* **`expected` is a declaration, not a copy.** For object-valued fields of an ANTÜ
  operation, every declared key must match the current value; a partial declaration is
  accepted and an empty one is refused. Measured: a real model declared `value` without
  `unit`/`context` and a correct operation was being refused.
* **Metering never enters the knowledge record.** `usage` stays in the ledger and in the
  result; the provenance that feeds the canonical hash carries provider, model and proposal
  hash only, so the identity of a version does not depend on token counts.

### Tests
377 → 450 collected (375 → 447 passed, 3 skipped, 0 failed).

## 0.2.1rc1 — release candidate (unpublished)

Candidate built on the 0.2.0 line after four hardening campaigns plus the corrections of
`KUYEN_RELEASE_CANDIDATE_05`. **Nothing has been published**: no upload, no tag, no release.
The version is a PEP 440 pre-release because the accumulated change is additive and
compatible (no persisted-format change, no removed public name), with exactly two documented
contract changes: `append_event` no longer re-validates the whole chain before writing, and
`VALIDATED`/`verify()` report shape is richer.

### Fixed
* **M6 — the cost of recording history grew with the history.** Every `append_event`
  re-parsed the whole ledger twice (`repair_ledger` + `events`): 1.1 ms per event with 100
  events, 9.8 ms with 2 000, i.e. quadratic; building a 1 600-event ledger took 6.0 s and
  now takes 0.29 s. Appending reads the tail record (`canonical.read_last_line`) and the
  index lookup walks the file from its end (`canonical.iter_lines_reverse`). A commit now
  performs **zero** full ledger reads (was 9).
* **B1 — `recover_pending` misclassified published staging.** It asked `INTENT.json` for an
  `identity_core` key the writer never writes, so `version_id` was always `None` and every
  staging was reported as unpublished, then deleted. Staging is now classified from the
  store (`NOT_PUBLISHED`, `PUBLISHED_COMPLETE`, `PUBLISHED_PARTIAL`, `UNCLASSIFIED`), only
  classified directories are removed, unattributable ones are kept, and a published version
  whose `CURRENT` was never written adopts it (`current_adopted`).
* **B2 — restore failed on an existing empty directory** (`FileExistsError` from
  `copytree`). An existing empty destination is now used; non-empty destinations, files,
  symbolic links, the backup itself, a destination inside it and a destination containing it
  are refused before anything is touched, with the destination left byte-for-byte intact.
* **M7 — the `[dev]` extra could not run the suite**: `tests/unit/test_adapter.py` and
  `tests/unit/test_013_ingestion.py` import `kuyen.adapters.openviking` at module level,
  which needs `httpx`. `httpx` and `pytest-cov` are now part of `[dev]`; `httpx` stays out of
  the base install.
* **B5 — the declared build minimum was false.** `setuptools>=68` cannot read this metadata
  (`project.license` as a PEP 639 SPDX expression plus `license-files`): 68.0.0, 75.3.2,
  76.0.0 and 76.1.0 all reject it, 77.0.1 is the first published version that accepts it.
  The floor is now `setuptools>=77.0.1`, verified by building with exactly that version.

### Changed
* `KuyenMemory.verify()` also reports `registry` and `objects` blocks (additive).
* `KuyenMemory.recover()` also reports `current_adopted`, `current_ambiguous` and
  `staging_kept` (additive); `staging_discarded` entries now carry `state`, `reason`,
  `evidence` and `actions_completed`.
* `kuyen.storage.commit.classify_staging` is available for tooling; `ledger.read_tail`,
  `canonical.read_last_line` and `canonical.iter_lines_reverse` are the new primitives.

### Documented limits (unchanged)
* No root of trust: a consistent full-store rewrite and a `CURRENT` rollback are still not
  detectable (see `SECURITY.md`).
* `flock` is unreliable on network filesystems.
* A commit still costs one pass over the whole graph (schema validation, object hashing and
  the re-verification of every existing object blob). That is inherent to full-snapshot
  versions and is measured, not hidden.

## 0.2.0 — release candidate (unpublished)

Productisation of the consolidated 0.1.9 engine line. Nothing has been published.

### Licensed
* Apache License 2.0 (`Apache-2.0`): unmodified official text in `LICENSE`, SPDX
  expression in the distribution metadata, `License-File: LICENSE` in wheel and sdist,
  and the licence documented in `README.md` and `QUICKSTART.md`. No `NOTICE` file is
  added because the distribution contains no third-party component that requires one.

### Added
* `KuyenMemory`: high-level governed memory API (`create`, `open`, `current`, `versions`,
  `history`, `graph`, `sidecar`, `source_unit`, `evidence_of`, `trace`, `status`).
* Two-phase Antü lifecycle: `execute_antu` (validate) then `commit` (persist), plus
  `record_failed_antu`, replay of a repeated `antu_id` and `STALE_BASE` conflicts.
* Canonical storage: content-addressed blobs, immutable versions, single commit point,
  version registry, compare-and-set `CURRENT`, single-writer advisory lock.
* Canonical sidecar, native projection, correspondence mapping, outbox, projection
  registry and reconciliation.
* Verified backup/restore and store-only recovery (`recover_from_store`).
* `kuyen.contracts`: seven independent version domains, contract snapshot,
  packaged asset resolution.
* `build_document`: canonical document from an accepted graph plus MAPU texts.
* Product documentation set, CI workflow, security policy and platform statement.

### Changed
* Schemas, ontology profiles and the versioned Skill ship as package data resolved from
  the installed package instead of `Path.cwd()`.
* `verify()` reports uniform string problems and treats an empty memory as valid.
* `verify_backup()` fails closed; the ledger reader reports a damaged line instead of
  raising during verification.

### Unchanged
* The 0.1.9 canonical model, validators, materialisation, semantics, coverage and governed
  publication. Regression: 132 passed, 2 skipped of the inherited suite (one research
  fixture is not distributed and is skipped by design).

## 0.1.9

Consolidated engine line: canonical model, deterministic validation, materialisation,
coverage, governed publication, packaging provenance and credential containment.
