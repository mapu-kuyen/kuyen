# CHANGELOG

## 0.3.0

First stable release after `0.2.0`. Everything from here down to the `0.2.1rc1` section is
the change set of this version: the document path through OpenViking and the
`knowledge-graph` Skill, the canonical model with evidence and provenance, the versioned
memory with its ledger and recovery, and the direct editing of the graph through an Antü.
`0.2.1rc1` was never published; its content is part of this release, so the four sections
below that were written as *Unreleased* are now sections of `0.3.0`.

### operational coverage of Antü operations

KUYEN_ANTU_OPERATIONAL_COVERAGE_15. Twelve real evaluations on the ten memories of experiment
13 (no document recompilation, same model, no fallback) completed the operations experiments 13
and 14 left open: relation addition, `UPDATE_ENTITY`, `UPDATE_ATTRIBUTE` and long
multi-operation instructions. Additive: existing stores remain readable and verifiable.

### Added
* **`AntuEditResult.outcome` and `outcome` per operation.** One closed vocabulary
  (`COMMITTED`, `ALREADY_SATISFIED`, `NOT_APPLICABLE`, `REQUIRES_DATA_ACCESS`,
  `NEEDS_CLARIFICATION`, `OUT_OF_SCOPE`, `BLOCKED_BY_PERMISSION`, `INVALID_PROPOSAL`,
  `EXECUTION_FAILED`, plus `NO_CHANGES`/`NOT_EVALUATED` for a mixed or unevaluated Antü) so a
  mixed answer is legible and a limitation is never reported as an absence of change
  (`kuyen.editing.outcome`).
* **`UPDATE_ENTITY` keeps the identity and the history.** The revision stores the previous
  values *and* the origin the entity had; a documentary entity keeps its evidence, records
  `amended: true` and its `instruction_edits`, and gains a `DOCUMENT_EVIDENCE` origin derived
  from the evidence it already had when the compiled record carried none.
* **`UPDATE_ATTRIBUTE` is typed.** The attribute must exist on the entity or be declared in the
  schema (an `ADD_FIELD` in the same Antü counts): `ATTRIBUTE_NOT_DECLARED`,
  `ATTRIBUTE_TYPE_MISMATCH`. The revision keeps the previous value, the new one and the origin.
* **`ADD_RELATION` compares statements, not identifiers.** Duplicates are detected from
  endpoints, predicate, polarity and temporal scope, and the opposite direction of an existing
  predicate is refused as ambiguous (`RELATION_DIRECTION_CONFLICT`) unless that relation is
  retracted in the same Antü.
* **Declines that KÜYEN can verify without an identifier.** An `ALREADY_SATISFIED` claim on a
  relation (endpoints + predicate) or on an entity (name + type) is checked against the graph
  instead of being refused for lack of a `target`.

### Fixed
* **A valid proposal nested inside another object is read instead of discarded.** The real model
  answered `{"status": ..., "contract": {"operations": [...]}}`, mirroring the request envelope;
  KÜYEN looked for `operations` only at the root and recorded zero operations. That is what
  experiments 13 and 14 reported as "`NO_CHANGES` on long instructions". The normaliser now
  reads the nested form (with a warning) and the request no longer names the reference
  `contract`, so the answer shape does not collide with it.
* **`NO_CHANGES` is no longer inferred.** An empty proposal that explains nothing is
  `INTERPRETATION_INCOMPLETE` (`NO_OPERATION_WITHOUT_EXPLANATION`); `NO_CHANGES` requires the
  editor to say so or every operation to be declined with a verifiable reason. A proposal that
  declares `NO_CHANGES` *and* operations is validated instead of having its operations ignored.
* An `ALREADY_SATISFIED` claim that says `retracted: false` for a record without that key is
  verifiable (`None` means "not retracted") instead of being refused.

### semantic fidelity of Antü operations

KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14. Ten real memories, no document recompilation. The
editor now patches what the instruction names and preserves everything else. Additive: stores
written before this change remain readable and verifiable.

### Changed
* **`UPDATE_ASSERTION` / `UPDATE_RELATION` are partial updates.** The fields of `value` are
  merged one by one and `modality`, `polarity`, `scope` and `attribution` are inherited unless
  the operation names them. Changing only the modality or the attribution keeps the statement
  identity, its evidence and (for documentary statements) its `DOCUMENT_EVIDENCE` origin,
  recording the edit in `instruction_edits` with `amended: true`.
* **A replaced statement keeps its history.** The new object carries `previous_evidence_ids`
  and `previous_attribution`; the superseded one keeps its own evidence.
* **Operation lifecycle is explicit.** `AntuEditResult.operations[].status` is `VALIDATED` until
  the canonical commit and `COMMITTED` after; `AntuEditResult.applied` exposes what the applier
  did with the previous value and is `DISCARDED` when the Antü did not commit.
* **`VersionRecord` listing is ordered by creation**, not by the content hash of its directory.

### Fixed
* A malformed `ADD_FIELD` (no `value.field.name`) is a rejection, never a `KeyError`.
* An in-place patch of a documentary statement no longer turns it into an instruction without
  evidence, which the canonical validator refuses (`ORIGIN_ANTU_CANNOT_BE_SOURCE_VERIFIED`).
* An `UPDATE_ASSERTION` on an existing target no longer forces the model to modify the value:
  `VALUE_INCOMPLETE` is gone for modality/attribution-only patches.

### ten real MAPU and real Antu operations

KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13. Ten public documents were materialised into ten
independent memories through OpenViking 0.5.0 and the real Skill, and each memory then received
free-text Antu instructions interpreted by the same inference model. Additive and backward
compatible: no persisted format changed.

### Added
* **Embedding provider configuration.** `VlmProviderConfig` may declare its own
  `embedding_api_base` and `embedding_api_key_env` when the inference provider publishes no
  embedding endpoint (DeepSeek returns 404 on `/v1/embeddings`). It is the same configuration
  object: the inference model is still one, and the embedding credential travels only in the
  child environment as `${KUYEN_EMBEDDING_API_KEY}`.
* **Provider execution identity.** `DocumentIncorporation` exposes `request_key` and
  `candidate_uri`, so the native artifacts of a real compilation can be archived and audited
  after the server is gone without guessing a URI.
* **The document title reaches the compile instruction** when it is declared on the MAPU.
* `docs/PRODUCT_MAPU_KUYEN_ANTU.md` and its English counterpart: what a MAPU, a KUYEN and an
  Antu are, who decides what, which permissions exist and where the limits are.

### Fixed
* **A clarifying Antu no longer breaks `verify()`.** The unit revision of a
  `CLARIFICATION_REQUIRED` execution recorded that state, which the unit-history verifier did
  not accept; it now records `NO_SEMANTIC_CHANGE` (nothing changed in the graph) while the
  ledger keeps the exact Antu status in the event and in `detail.edit_status`. Regression test
  added.

### productive graph and Antu versioning

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
