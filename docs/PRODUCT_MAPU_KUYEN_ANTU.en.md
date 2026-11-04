# MAPU, KÜYEN and ANTÜ: what each one is

Product note. It describes the behaviour implemented in KÜYEN 0.3.0 and claims no capability
that has only been simulated.

## MAPU — the document

A **MAPU** is the source document or content: the ingested text, its identity (`mapu_id`), its
version, its `source_uri`, its hash and its provenance (origin, date, licence). KÜYEN stores
the text as delivered and addresses it by source units (`SOURCE_UNIT`), so every statement can
be cited with exact offsets.

The MAPU is **not** rewritten: when the original is an HTML page or a PDF, the text rendition
that is ingested is a declared, hashed artifact and the original is kept next to it. A MAPU
with no locatable evidence produces no admitted knowledge.

## KÜYEN — the memory

A **KÜYEN** is an independent graph memory: its own canonical store, its own graph (entities,
relations, assertions, evidence), its schema, its ledger, its versions and its ANTÜ history.
Two KÜYEN share no identifiers and no knowledge, even when their MAPUs look alike: the same
instruction may apply in one and not in the other.

The memory is not an application: it runs no business rules and stores no operational logic.

## ANTÜ — the instruction

An **ANTÜ** is a request to modify, correct or evolve the knowledge of one KÜYEN, written in
free, portable text. It is not an operation list: the LLM interprets it with the context that
KÜYEN authorises for that instance and proposes zero or more operations (`ADD_ENTITY`,
`UPDATE_ASSERTION`, `RETRACT_RELATION`, `ADD_FIELD`, …).

Each operation is classified separately: `APPLICABLE`, `ALREADY_SATISFIED`, `NOT_APPLICABLE`,
`REQUIRES_DATA_ACCESS`, `NEEDS_CLARIFICATION`, `OUT_OF_SCOPE` or `BLOCKED_BY_PERMISSION`.
KÜYEN keeps those outcomes apart and **creates no version when no operation changes the
graph**.

## Who does what

| actor | responsibility | cannot |
| --- | --- | --- |
| OpenViking 0.5.0 + `knowledge-graph` Skill | materialise the MAPU into native artifacts (entities, relations, assertions, evidence) | decide canonical admission |
| inference LLM | interpret the ANTÜ and propose structured operations | write to the graph, validate permissions, invent data |
| KÜYEN (deterministic) | validate structure, identity, values, permissions, evidence and provenance; apply; version; verify | trust the model's proposal blindly |

## Permissions and limits

Four permissions, evaluated separately and enforced twice (when the context is built and when
each operation is authorised): `SCHEMA_READ`, `SCHEMA_WRITE`, `DATA_READ`, `DATA_WRITE`. When
an ANTÜ may only see the schema, the context says so and operations that need data are refused
or marked `BLOCKED_BY_PERMISSION`; restricted data is never sent.

## Versioning and provenance

`ANTÜ → LLM → OPERATIONS → VALIDATION → EXECUTION → VERIFICATION → NEW VERSION`. Both paths
(document and edit) end in the **same** canonical commit: same ledger, same lineage, same
recovery. The previous version is preserved and the exact change is recorded (old and new
values, affected nodes, reasons, refused operations).

Provenance separates documentary knowledge from instructed knowledge: `DOCUMENT_EVIDENCE`
requires a quote and a source unit; `ANTU_INSTRUCTION` records the literal request, its hash,
the base version and the model, and is **never** presented as verified by the MAPU.

## What this note does not claim

KÜYEN does not broadcast ANTÜ across memories, does not coordinate a global graph and does not
turn one instruction into a new memory: each KÜYEN decides locally and versions its own
history.

## Partial updates

When an ANTÜ corrects a single value, KÜYEN changes that value and nothing else: the unit,
context, modality, polarity, scope and attribution the ANTÜ did not name are preserved. The
previous statement stays `SUPERSEDED` with its evidence and the new one records the previous
value. Changing only the modality or the attribution does not create another statement: it is
recorded in that statement's history. Adding a schema field (`ADD_FIELD`) is structure and is
versioned like any other change; it runs no validators and creates no application logic.
