# DATA MODEL

Canonical objects are JSON documents with deterministic identifiers. Nothing is
normalized for display in a way that changes the stored text.

## Identity

* `kuyen_id` — `KUY-` plus 12 hex characters, stable for the life of the memory.
* `entity_id`, `relation_id`, `assertion_id`, `evidence_id` — prefixed stable ids
  (`ent_`, `rel_`, `asrt_`, `ev_`) derived from the object payload.
* `source_entity_id` / `source_namespace` — the identifier the producer used, kept as-is.
* `identity_status` — how a source object was matched (`SAME_STABLE_ID`, …). Two objects
  are never merged because their names look alike; a merge needs a stable id or an
explicit identity group.

## Entity

`entity_type`, `name`, `aliases`, `description`, `evidence_ids`, `sources`,
`normalization_status`, `status`.

## Relation

The relation is the object where semantic loss happens, so it keeps every layer:

| Field | Meaning |
| --- | --- |
| `source_predicate` | The predicate as the source expressed it |
| `canonical_predicate` | The canonical predicate KÜYEN governs |
| `provider_predicate` / `provider_label` | What a projection engine would call it |
| `polarity` | `POSITIVE` / `NEGATIVE` / `UNKNOWN` |
| `scope` | The scope the claim holds in (`document`, …) |
| `temporal_scope` / `temporal` | The temporal expression and its structured form |
| `mapping_status` | `MAPPED` / `UNMAPPED` / `LOSSY` … |
| `provider_projection_status` | What the projection preserves |
| `evidence_ids`, `sources` | Support |

A relation never degrades silently to `related_to`: the generic predicate survives in
`provider_predicate`, and the canonical predicate keeps the meaning.

## Assertion

`subject_entity`, `predicate`, optional `object_entity`, a typed `value`
(`string`, `quantity`, `boolean`, …), `polarity`, `scope`, temporal fields, evidence,
and an explicit support status (`proposed_status`, `evidence_status`, `status`).

## Evidence

`evidence_id`, `mapu_id`, `source_uri`, `quote`, `char_start`, `char_end`,
`offset_unit` (code points), `extraction_method`, `validation_status`, `source_sha256`.
Offsets address the source text directly: a quote that does not appear at its offsets is
rejected.

## MAPU

A source document: `mapu_id`, `version`, `source_uri`, `content`, `content_sha256`,
`trust_level`, `access_policy`, plus provenance metadata. The text is stored verbatim and
hashed; it is never rewritten.

Provenance fields (KUYEN_SEMANTIC_SECURITY_HARDENING_04): `source_bytes_sha256` is the hash
of the original file bytes, `content_sha256` the hash of the decoded text that the offsets
address, `encoding` the declared encoding, `newline_policy` (`PRESERVED` or `UNKNOWN`) and
`source_hash_scope` (`SOURCE_BYTES` or `DECODED_TEXT`). A record without these fields predates
this hardening pass and its hash addresses the decoded text. See `SECURITY.md`.

## SOURCE_UNIT

A passage of a MAPU: `unit_id`, `mapu_id`, `section`, `order`, `char_start`, `char_end`,
`content_sha256`, and the verified `content` slice. Evidence points into units; units
point into MAPUs; MAPUs carry the source hash.

`unit_id` is **local to its MAPU**: two documents of the same version may both declare
`u00`. A unit is identified by the pair `(mapu_id, unit_id)` and is resolved inside its
own document — `memory.source_unit(unit_id, mapu_id=...)`. An unscoped lookup is accepted
only while the identifier is unique; with more than one match it fails with
`AmbiguousSourceUnit` rather than returning the first one, so evidence can never be
attributed to another document by accident.

## Coverage

Per SOURCE_UNIT state (`PROCESSED_WITH_OUTPUT`, …) with the ids produced from it. Coverage
is part of the canonical record, so "what was read but produced nothing" is auditable.

## Mapu-level provenance

`provenance.actor` records who instructed the execution (`leftraru_id`, `antu_author`,
`candidate_producer`); `provenance.coverage_inventory` holds the unit inventory as the
producer delivered it.

## Statement semantics (0.2.1)

Every relation and assertion may declare three dimensions that are *data*, not decoration:

| Field | Domain | When absent |
| --- | --- | --- |
| `polarity` | `POSITIVE`, `NEGATIVE` | the object is **not admitted** to the canonical set (never stored as POSITIVE) |
| `modality` | `FACT`, `FORECAST`, `ESTIMATE`, `OPINION`, `CONDITIONAL`, `UNKNOWN` | `UNKNOWN` — silence is not a fact |
| `attribution` | literal name of the actor the claim is credited to | `null` — the emitter is never invented |

A candidate whose polarity was never declared stays `UNKNOWN` in the candidate domain and
the materializer records the refusal (`POLARITY_UNKNOWN`) instead of guessing it.

## Statement origin (0.2.1)

`origin` records where a statement comes from, and the four values are not interchangeable:

| `kind` | Meaning | May be `SOURCE_VERIFIED` |
| --- | --- | --- |
| `DOCUMENT_EVIDENCE` | derived from a MAPU through OpenViking, with quote and SOURCE_UNIT | **yes** |
| `ANTU_INSTRUCTION` | declared by an authorised instruction on an existing version | **no** |
| `PRIOR_VERSION` | carried over unchanged from an earlier version | inherited |
| `INFERENCE_PENDING` | proposed, not admitted | no |

An object with an `ANTU_INSTRUCTION` origin carries the literal instruction, its SHA-256,
the Antü id, the base version, the actor (when known), the model and the reason — and never
a MAPU, SOURCE_UNIT, quote or hash it does not have. The canonical validator refuses an
`ANTU_INSTRUCTION` object that declares `SOURCE_VERIFIED`.

## Supersession and retraction (0.2.1)

KÜYEN never deletes. A correction leaves the previous statement with `status: SUPERSEDED`
and `superseded_by`, and the new one with `supersedes`. A removal leaves the object with
`status: RETRACTED`, `retracted: true` and a `retraction` record. Both remain readable in
the version that contains them and in every earlier version.

## Evidence additions (0.2.1)

Three optional evidence fields were added to `evidence.schema.json` (`context`,
`source_unit_id`, `declared_offsets`). They are additive: every document written before
this change remains valid and no storage migration was performed.
