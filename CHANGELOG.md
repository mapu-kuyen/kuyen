# CHANGELOG

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
