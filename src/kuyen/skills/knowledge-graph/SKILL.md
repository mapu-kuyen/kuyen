---
name: knowledge-graph
description: Produce source-grounded native files plus inline evidence for a KÜYEN Antü. Read the source first, extract only facts it states, compute offsets mechanically, and never copy schema placeholders as data.
---

# KÜYEN knowledge-graph Skill 1.3.0

## Read this first

The source is the only origin of facts. Before writing any artifact, read the
source:

- if the Antü instruction gives a pristine MAPU file path, read that file;
- otherwise read the supplied OpenViking resource and its chunks.

The JSON in this document is a **shape illustration**, not data. Its placeholder
values (`<...>`, `ev-example`, `0`, `1`) must never appear in an output. Copying
the illustration instead of extracting the source is a failure.

## Required order

1. Read the source completely before writing.
2. Enumerate the named entities the source actually names.
3. Enumerate the relations the source actually states between them.
4. Enumerate the numbers, dates, units and negative claims the source states.
5. For each fact, choose an exact quote and compute its offsets mechanically.
6. Write one YAML entity file per entity, with inline evidence.
7. Write `relations.jsonl` and `assertions.jsonl`, one JSON object per line.
8. Do not write a sidecar; KÜYEN materializes the canonical candidate.
9. Optionally report no-fact units from the exact inventory; KÜYEN derives coverage.

Do not write in a different order: a graph without verifiable evidence is a
failure even if it is valid JSON.

## Entities

- First enumerate every named person, organization, place, event, product, route and
  concept in the source, including names that appear only as the object of a
  relation or assertion. Write one entity file for each.
- A relation endpoint or assertion subject without an entity file is an orphan and
  KÜYEN rejects the graph. If the source names the endpoint, create its entity with
  the evidence from the sentence that names it; do not leave it undeclared.
- Create one entity per distinct named thing: a person, organization, place,
  event, product, industry, route, concept. Do not create an entity for a
  pronoun, a generic noun or the Antü itself.
- `entity_type` must be one of the Antü `entity_types`.
- `provider_id` is lowercase and stable (`asociacion-rio-claro`). Do not reuse
  the same `provider_id` for two different things, and do not submit two entity
  objects with the same `provider_id`.
- Never merge two distinct source identities into one entity. If the source names
  both "9" and "nueve integrantes", they are two identities; preserve both.
- Do not create an entity for a number, date, quantity, percentage or unit.
  Represent it as an assertion value instead.

## Relations

- Use only predicates allowed by the Antü `relation_types`.
- The direction must match the source: if the text says "A coordina B", the
  relation is `A --coordinates--> B`, not the reverse.
- `label` is the source-language label declared by the ontology; one predicate
  must use one consistent label.
- Every endpoint must be an entity declared in the same result. Create the
  endpoint entity file if it is missing; never submit an undeclared endpoint.
- Do not invent a relation for an absent fact. If the source only negates the
  relation, use a NEGATIVE assertion instead of a relation.

## Assertions: numbers, dates, negatives

- A quantity becomes an assertion with `value.value_type`, `value.value` and
  `value.unit` when the source states a unit. Preserve the exact numeric value:
  `12.500 litros` is 12500 litres, not 12.5 and not 125000.
- A date or year becomes an assertion with the temporal value in `value`;
  `temporal_scope` carries the period when the source states one.
- A negative statement must remain negative: `polarity: "NEGATIVE"` and an
  evidence quote that contains the negation. Never turn "no exporta a Asia"
  into a positive export relation.
- Every assertion subject must have an entity file. If the source names the
  subject only in the assertion sentence, create it.
- If a fact is not in the source, it must not appear anywhere: not as an entity,
  not as a relation, not as an assertion, not in a description.

## Evidence: mechanical offsets

Every entity, relation and assertion needs at least one evidence object.

- `source_uri` must be the exact string given in the Antü instruction.
- `source_sha256` must be the SHA-256 of the pristine MAPU file named in the
  instruction.
- `quote` must be an exact slice of that file. `char_start` and `char_end` are
  zero-based Unicode code-point offsets, start inclusive, end exclusive, and
  `quote == source_text[char_start:char_end]`.
- Never estimate an offset. Compute it with a script against the pristine file:

```python
source = open(pristine_path, encoding="utf-8").read()
def locate(quote: str) -> tuple[int, int]:
    start = source.find(quote)
    if start < 0:
        raise SystemExit(f"quote not found: {quote!r}")
    if source.find(quote, start + 1) != -1:
        raise SystemExit(f"ambiguous quote, extend it: {quote!r}")
    return start, start + len(quote)
```

- If a quote is not unique, extend it with adjacent source text until it is
  unique. If it cannot be made unique, use a different quote that still fully
  supports the fact, or drop the fact.
- One entity may repeat the same quote as a relation; KÜYEN assigns canonical
  evidence IDs and deduplicates exact spans.
- A description must not add facts that the evidence does not state.

## Coverage units

KÜYEN derives coverage from the deterministic unit inventory and from where your
verified evidence falls. Do not invent units, and do not grant yourself a state.

- You MAY include a `coverage` array using only the `unit_id` values listed in the
  instruction.
- Use `PROCESSED_NO_GRAPH_FACTS` only when you examined the unit and found no
  graphable fact; give a short reason.
- Use `SKIPPED_WITH_REASON` or `FAILED` only with a reason.
- Do not send `entity_ids` or `relation_ids`; KÜYEN derives membership from
  evidence spans.
- Omitting `coverage` is allowed; KÜYEN will not assume the unit was processed.

## Output: fixed native files

Write exactly these paths. KÜYEN materializes the canonical candidate from them.

### `entities/<provider_id>.md`

One file per distinct entity. Use YAML frontmatter and a short body:

```yaml
---
id: cooperativa-los-aromos
name: Cooperativa Agrícola Los Aromos
entity_type: organization
description: ONE SENTENCE FROM THE SOURCE
aliases: []
sources:
  - EXACT_SOURCE_URI
evidence:
  - quote: "EXACT SOURCE SLICE"
    char_start: 0
    char_end: 1
    source_uri: EXACT_SOURCE_URI
    source_sha256: SOURCE_SHA256
    mapu_id: MAPU-SYN-01
---

Short body.
```

Do not write a second file for the same `id`. The path is exactly
`entities/<provider_id>.md`.

### `relations.jsonl`

One JSON object per line, not a JSON list and not a Markdown file:

```json
{"from":"ENTITY_ID","to":"OTHER_ID","relation":"located_in","label":"se ubica en","polarity":"POSITIVE","scope":"document","temporal_scope":null,"sources":["EXACT_SOURCE_URI"],"evidence":[{"quote":"EXACT SOURCE SLICE","char_start":0,"char_end":1}]}
```

### `assertions.jsonl`

One JSON object per line:

```json
{"subject":"ENTITY_ID","predicate":"has_member_count","value":{"value_type":"integer","value":"EXACT VALUE","unit":"UNIT OR NULL","context":null},"polarity":"POSITIVE","scope":"document","temporal_scope":null,"sources":["EXACT_SOURCE_URI"],"evidence":[{"quote":"EXACT SOURCE SLICE","char_start":0,"char_end":1}]}
```

### `coverage.json` (optional)

A JSON array; use only the `unit_id` values from the instruction:

```json
[{"unit_id":"u00","state":"PROCESSED_NO_GRAPH_FACTS","reason":"SHORT REASON"}]
```

Rules:

- Do not write `kuyen_result.json`, `kuyen_candidates.json`, `relations/`,
  `assertions/`, `coverage/` or one file per relation/assertion.
- One entity path per `provider_id`; never submit the same path twice.
- Every relation and assertion is one line in its JSONL file.
- Evidence is inline in the entity, relation or assertion object.
- If you cannot compute offsets, omit them; KÜYEN resolves a quote only if unique.

## Output ownership

KÜYEN materializes `entities/*.md`, `relations.jsonl` and the canonical
`kuyen_candidates.json` from `kuyen_result.json`. You do not write them. The only
provider-owned artifact in this revision is `kuyen_result.json`.

## Prohibitions

- Do not copy the illustration, its placeholder IDs or placeholder evidence.
- Do not create an entity from the Antü, the task or the Skill itself.
- Do not invent endpoints, entities, predicates, sources, quotes or facts.
- Do not convert a negative statement into a positive relation.
- Do not drop temporal, polarity or unit information.
- Do not resolve contradictory sources by preference; preserve the conflict.
- Do not mark a unit complete just because it was read; KÜYEN derives coverage.
- Do not add fields outside the schema.
- Do not write any file other than `kuyen_result.json`. KÜYEN rejects a result
  without it and rejects every additional path it did not ask for.
- Do not write a relation whose endpoints are not declared entities.
- Do not write a self-relation unless the source explicitly relates an entity to
  itself; KÜYEN rejects it otherwise.

