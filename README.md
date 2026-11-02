# KÜYEN

**Governed canonical memory and knowledge for Leftraru agents.**

KÜYEN is a Python library, not an agent and not a language model. It gives an agent a
place to keep knowledge it can trust: versioned, content-addressed, traceable back to
the exact characters of the source that supports it.

```python
from kuyen import KuyenMemory

memory = KuyenMemory.create("./memory", leftraru_id="LR-0001")
```

## What KÜYEN is

* A **canonical model** of entities, relations, assertions and evidence, with MAPU
  (document) and SOURCE_UNIT (passage) provenance.
* A **canonical memory**: immutable versions, content addressing, one commit point,
  append-only Antü ledger, unit revisions, outbox, projection registry, backup, restore
  and independent recovery.
* A **deterministic validator**: an Antü proposal is checked against the canonical
  contracts *before* anything is committed.
* A **sidecar contract**: every version carries its own canonical record, so the memory
  can be rebuilt from the store alone.

## What KÜYEN is not

* It is not an LLM and it does not produce knowledge by itself. Extraction, judgement
  and instruction live outside the core; KÜYEN validates and governs what it is given.
* It does not require OpenViking, a model provider, an embedding service or a network
  connection to create, store, version, read, back up or recover its memory.
* It does not claim native OpenViking compilation or semantic retrieval: those were
  measured and are **not** capabilities of the product.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install kuyen            # core, no external services
pip install "kuyen[openviking]"   # optional HTTP client extra
```

Requires Python 3.10+ on a POSIX system (see [PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md)).

## Five-minute tour

```python
from kuyen import KuyenMemory, build_document

memory = KuyenMemory.create("./memory", leftraru_id="LR-0001")

document = build_document(accepted_graph, {mapu_id: source_text})
memory.import_canonical(document)          # first version

current = memory.current()
execution = memory.execute_antu(antu, mapu_source="MAPU-02.txt")   # validates
result = memory.commit(execution)                                  # persists

memory.graph()            # canonical objects of the current version
memory.graph(older_id)    # any historical version
memory.history()          # unit revisions
memory.trace(claim_id)    # claim -> evidence -> SOURCE_UNIT -> MAPU
```

See [QUICKSTART.md](QUICKSTART.md) for a runnable example and [PUBLIC_API.md](PUBLIC_API.md)
for the full contract.

## Documentation

| Document | Contents |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | Create a memory, commit an Antü, read history |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Modules, boundaries, why the core is independent |
| [PUBLIC_API.md](PUBLIC_API.md) | Every public operation, guarantee and exception |
| [DATA_MODEL.md](DATA_MODEL.md) | Entities, relations, assertions, evidence, MAPU, SOURCE_UNIT |
| [VERSIONING.md](VERSIONING.md) | The seven version domains and immutability |
| [ANTU_LIFECYCLE.md](ANTU_LIFECYCLE.md) | Instruction, validation, acceptance, rejection, replay |
| [CANONICAL_STORAGE.md](CANONICAL_STORAGE.md) | Layout, content addressing, commit protocol, single writer |
| [SIDECAR.md](SIDECAR.md) | The canonical sidecar contract and reconstruction |
| [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) | Backup, restore, store-only recovery |
| [ADAPTERS.md](ADAPTERS.md) | Projections and the optional OpenViking adapter |
| [SECURITY.md](SECURITY.md) | Threat model and vulnerability reporting |
| [PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md) | Guaranteed and untested platforms |
| [LICENSE](LICENSE) | Apache License 2.0 (unmodified official text) |

## Licence

Licensed under the Apache License, Version 2.0.

```
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

The full, unmodified licence text is in [`LICENSE`](LICENSE) and the official copy is at
<https://www.apache.org/licenses/LICENSE-2.0.txt>. The SPDX identifier is `Apache-2.0` and the
distribution metadata declares it.

No copyright holder is asserted in this file: the owner of the work has not stated an exact
legal identity to attribute, and inventing one would be wrong. Adding a `Copyright <holder>`
line is a decision for that owner and belongs in `LICENSE`, `NOTICE` or the file headers once
the exact wording is authorised.

Apache-2.0 licenses **the software**. It grants no right to use the KÜYEN name, logo or
imagery as if a fork, a derived distribution or a hosted service were the official KÜYEN
project (Apache-2.0, section 6, Trademarks). Modified versions must not be presented as the
original product.

## Status

Engine contracts `0.1.9`, package candidate `0.2.0`, licensed `Apache-2.0`, **unpublished**.
Applying the licence does not publish anything: no commit, tag, push, package index upload or
release exists yet, and publication still requires the owner's authorisation.

## Testing

```bash
python -m pytest            # product suite (no network, no credentials)
```
