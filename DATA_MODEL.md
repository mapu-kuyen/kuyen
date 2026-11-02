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

## SOURCE_UNIT

A passage of a MAPU: `unit_id`, `mapu_id`, `section`, `order`, `char_start`, `char_end`,
`content_sha256`, and the verified `content` slice. Evidence points into units; units
point into MAPUs; MAPUs carry the source hash.

## Coverage

Per SOURCE_UNIT state (`PROCESSED_WITH_OUTPUT`, …) with the ids produced from it. Coverage
is part of the canonical record, so "what was read but produced nothing" is auditable.

## Mapu-level provenance

`provenance.actor` records who instructed the execution (`leftraru_id`, `antu_author`,
`candidate_producer`); `provenance.coverage_inventory` holds the unit inventory as the
producer delivered it.
