# KÜYEN

**Versioned, verifiable canonical memory for knowledge systems and intelligent agents.**

[Versión en español](README.md) · [Documentation](#documentation) · [Installation](#installation) · [Quick start](#quick-start) · [Contributing](CONTRIBUTING.md)

KÜYEN is a Python library for building and maintaining knowledge graphs as canonical memories, with immutable versions, deterministic validation, and traceability back to original sources.

It allows an application or agent to incorporate knowledge, inspect its evolution, propose changes, and preserve verifiable evidence of how each claim was constructed.

**KÜYEN separates knowledge interpretation from knowledge preservation.** A language model may interpret documents or instructions; KÜYEN validates, governs, and persists accepted changes.

## What problem does it solve?

Systems built around documents, language models, and agents often struggle to answer fundamental questions:

- Where did a claim come from?
- Which source passage supports it?
- What changed between two versions of the knowledge?
- Which actor or process produced a modification?
- Can a previous version be recovered?
- Can we check that the memory keeps its integrity?

KÜYEN addresses these problems through canonical memory whose content, provenance, and evolution can be inspected and verified.

## What is KÜYEN?

KÜYEN is a governed memory library. It is neither an agent nor an artificial intelligence model.

Its main components include:

- **Canonical graph:** structured entities, relations, claims, and evidence.
- **MAPU:** a record of the source document and its original content.
- **SOURCE_UNIT:** an identifiable passage within a document, used to locate and verify evidence.
- **Immutable versions:** every accepted change creates a new version without rewriting previous ones.
- **Traceability:** claims can be traced back to their evidence, source passage, and original document.
- **Deterministic validation:** proposed changes must satisfy integrity contracts before being persisted.
- **ANTÜ ledger:** records instructions and their execution outcomes.
- **Recovery:** supports memory verification, backup, restoration, and reconstruction.

## How does it work?

KÜYEN supports two main paths for evolving a memory.

### 1. Incorporating knowledge from documents

An external process interprets or transforms documents into a graph representation. KÜYEN receives the resulting canonical document, validates its contracts, and stores a new version.

OpenViking can participate as an external processing and ingestion engine through the corresponding adapter. It is not required to use the KÜYEN core.

### 2. Editing existing memory through ANTÜ

An ANTÜ instruction describes a change to be made to existing knowledge.

An external model or component may interpret the instruction and propose graph operations. KÜYEN validates those operations, checks integrity constraints, and persists accepted changes as a new version.

Direct graph editing through ANTÜ does not require reprocessing the original document with OpenViking.

In both paths, KÜYEN preserves provenance and the history of knowledge evolution, and both end in the same canonical commit protocol.

## Key features

| Capability | What it provides |
|---|---|
| Canonical memory | Structured entities, relations, claims, and evidence |
| Versioning | Immutable history and version lineage |
| Provenance | Verifiable links between claims and sources |
| Validation | Writes governed by deterministic contracts |
| Integrity | Hash, reference, and structure verification |
| ANTÜ | Recorded, validated, controlled instruction execution |
| Backup and restore | Verifiable backup and restoration |
| Recovery | Reconstruction of versions from canonical storage |
| Projections | Optional integration with external engines |

## What KÜYEN does not do

Its responsibilities are deliberately bounded:

- KÜYEN is not an LLM and does not interpret document meaning by itself.
- It does not generate knowledge autonomously: it receives representations and proposals produced by external processes.
- It does not require OpenViking, embeddings, model providers, or a network connection to operate its canonical memory.
- It does not replace source-quality assessment or guarantee that a claim is true merely because it has been stored.
- Native semantic retrieval and native OpenViking compilation are not claimed as core capabilities.
- It provides no external root of trust and no signatures: verification detects an alteration that breaks the hashes, the references or the ledger chain, but it cannot tell a complete and consistent rewrite of the store from an authorised one. The exact limits are in [SECURITY.md](SECURITY.md).

KÜYEN guarantees preservation and validation contracts. The quality of interpretation depends on the process that produces the information supplied to it.

## Installation

### Requirements

- Python 3.10 or later.
- Linux or macOS (POSIX systems).
- A filesystem supporting the required atomic operations.
- Single-writer concurrency model: one writer per store.

Windows and network filesystems have not been validated and are not supported in this release. See [platform compatibility](PLATFORM_COMPATIBILITY.md).

### Install from GitHub

```bash
git clone https://github.com/mapu-kuyen/kuyen.git
cd kuyen

python -m venv .venv
source .venv/bin/activate

python -m pip install .
```

To install the optional OpenViking adapter:

```bash
python -m pip install ".[openviking]"
```

For development:

```bash
python -m pip install ".[dev]"
```

Installing from the repository is the supported path for version 0.3.0: there is no release
published on PyPI yet, so `pip install kuyen` is not available.

## Quick start

Create a KÜYEN memory:

```python
from kuyen import KuyenMemory

memory = KuyenMemory.create(
    "./memory",
    leftraru_id="LR-0001",
    purpose="Knowledge memory"
)

print(memory.status())
```

The store is associated with its responsible unit. Creation does not invent or ingest
knowledge: it establishes the canonical space where knowledge can be persisted, and
`memory.current()` still returns `None`.

To incorporate an accepted graph:

```python
from kuyen import build_document

document = build_document(
    accepted_graph,
    {mapu_id: source_text},
    source_uris={mapu_id: source_uri},
)

result = memory.import_canonical(document)

print(result.version.version_id)
```

`accepted_graph`, `mapu_id`, `source_text`, and `source_uri` represent data prepared by the
ingestion process. Every evidence record must cite exactly the `source_uri` of its MAPU: when
none is declared, `build_document` uses `viking://resources/<mapu_id>`, and a different citation
is refused at commit time (`EVIDENCE_URI_MISMATCH`). See the [Quickstart](QUICKSTART.md) for the
complete runnable workflow.

### Read and verify

```python
current = memory.current()
graph = memory.graph()
history = memory.history()

report = memory.verify()
assert report["ok"], report["problems"]
```

`verify()` never raises: it returns `ok` and the list of `problems`, so an operator can see
exactly what is wrong.

### Apply an ANTÜ instruction

Execution and persistence are separate operations:

```python
execution = memory.execute_antu(
    antu,
    mapu_source="MAPU-02.txt"
)

if execution.status == "VALIDATED":
    result = memory.commit(execution)
```

`execute_antu` validates and prepares, and writes no version. `commit` only persists a
`VALIDATED` execution; a `REPLAYED` execution returns the already committed version, and any
other state (`REJECTED`, `NO_SEMANTIC_CHANGE`, `CONFLICT`) raises `CommitError`. Validation does
not mean automatic persistence.

For direct graph editing through an editor, see the `apply_antu` contract in
[PUBLIC_API.md](PUBLIC_API.md).

## Documentation

| Document | Contents |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Practical walkthrough from installation to verification |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, modules, and system boundaries |
| [PUBLIC_API.md](PUBLIC_API.md) | Public API, operations, and contracts |
| [DATA_MODEL.md](DATA_MODEL.md) | Entities, relations, claims, and evidence |
| [VERSIONING.md](VERSIONING.md) | Version domains and immutability |
| [ANTU_LIFECYCLE.md](ANTU_LIFECYCLE.md) | ANTÜ instruction lifecycle |
| [CANONICAL_STORAGE.md](CANONICAL_STORAGE.md) | Canonical storage and commit protocol |
| [SIDECAR.md](SIDECAR.md) | Version reconstruction contract |
| [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) | Backup, restoration, and recovery |
| [ADAPTERS.md](ADAPTERS.md) | Projections and external engine integration |
| [docs/GRAPH_EDIT_ANTU.en.md](docs/GRAPH_EDIT_ANTU.en.md) | Graph editing through ANTÜ |
| [docs/PRODUCT_MAPU_KUYEN_ANTU.en.md](docs/PRODUCT_MAPU_KUYEN_ANTU.en.md) | MAPU, KÜYEN and ANTÜ: what each one is |
| [SECURITY.md](SECURITY.md) | Security model and vulnerability reporting |
| [PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md) | Platform compatibility and limitations |
| [CHANGELOG.md](CHANGELOG.md) | Changes between versions |

The ANTÜ graph-editing documentation is also available in
[Spanish](docs/GRAPH_EDIT_ANTU.md), and this README in [Spanish](README.md).

## Testing

From the repository:

```bash
python -m pytest
```

The product test suite runs without requiring external provider credentials or network
services. Tests that need a real OpenViking instance or a model provider are skipped unless they
are enabled explicitly (`KUYEN_RUN_OPENVIKING=1`, `KUYEN_RUN_REAL_MODEL=1`), according to the
instructions for their respective experiments or adapters.

## Project status

**Product version: 0.3.0**

KÜYEN has a distribution that can be rebuilt from a clean Git clone, automated tests, and a CI
matrix for Python 3.10, 3.11, 3.12, and 3.13.

The project is actively evolving. External integration capabilities must be evaluated against
their specific contracts and tests; not all of them are part of the core guarantees.

See [CHANGELOG.md](CHANGELOG.md) for changes between versions and
[PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md) for current guarantees and limitations.

## Contributing

KÜYEN is an open-source software project. Contributions, bug reports, proposals, and reviews are
welcome.

- [Contributing guide](CONTRIBUTING.md)
- [Report an issue](https://github.com/mapu-kuyen/kuyen/issues)
- [Security policy](SECURITY.md)

Before proposing changes, review the public contracts and existing tests. Compatibility,
provenance, and memory integrity are core project properties.

## License

KÜYEN is distributed under the [Apache License 2.0](LICENSE). The full, unmodified text is in
[`LICENSE`](LICENSE), and the SPDX identifier `Apache-2.0` is declared in the distribution
metadata.

The license covers the software. It does not grant rights to the KÜYEN name or marks, and no
copyright holder is asserted here that the owner of the project has not declared.

---

**KÜYEN — structured knowledge, verifiable memory, traceable evolution.**

Repository: https://github.com/mapu-kuyen/kuyen
