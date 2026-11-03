# GRAPH EDITING WITH AN ANTÜ (EN)

This document describes the second way of evolving a KÜYEN: the direct instruction. It is
written for the people who use it and for the people who audit it.

Spanish version: [`GRAPH_EDIT_ANTU.md`](GRAPH_EDIT_ANTU.md).

---

## 1. The two ways of evolving a KÜYEN

| | Path A — document | Path B — instruction |
| --- | --- | --- |
| Input | a free-form document (MAPU) | a literal ANTÜ instruction |
| Engine | **OpenViking** + the `knowledge-graph` Skill | an **LLM** that only proposes |
| Produces | entities, relations, assertions and textual evidence | structured operations on the existing graph |
| Decides | KÜYEN (deterministic gate) | KÜYEN (deterministic validator) |
| Provenance | `DOCUMENT_EVIDENCE` | `ANTU_INSTRUCTION` |
| May declare `SOURCE_VERIFIED` | **yes** | **never** |
| Entry point | `kuyen.incorporate_document` | `kuyen.apply_graph_edit` / `KuyenMemory.apply_antu` |

`kuyen.product.classify_antu` classifies the instruction and **fails** on an unknown kind.
An edit Antü never starts OpenViking; a document Antü never uses the editor.

One Antü may need two stages (incorporate a document, then correct the graph). Those are two
operations, two versions and two lineages: they are never mixed.

## 2. Flow of one edit

```
instruction + current version
   → deterministic context        (editing.context)
   → hashed request to the model  (editing.prompt, editing.editors)
   → parsed proposal              (editing.operations)
   → deterministic validation     (editing.validator)
   → deterministic application    (editing.applier)
   → canonical commit             (storage.commit, the very same one)
```

Interpretation happens **outside** the writer lock; validation and commit happen **inside**
it and re-check the base version. If another Antü advanced the graph in between, the commit
is refused with `STALE_BASE` and nothing is written.

## 3. The proposal contract (`kuyen-graph-edit-v1`)

```json
{
  "schema_version": "kuyen-graph-edit-v1",
  "status": "PROPOSED | CLARIFICATION_REQUIRED | CONFLICT | NO_CHANGES",
  "operations": [
    {
      "operation_id": "op-1",
      "op": "UPDATE_ASSERTION",
      "target": {"assertion_id": "asrt_..."},
      "expected": {"value": {"value_type": "integer", "value": 12}},
      "value": {"value": {"value_type": "integer", "value": 18}},
      "reason": "why the knowledge changes",
      "antu_ref": "literal fragment of the instruction"
    }
  ]
}
```

Operation types: `ADD_ENTITY`, `UPDATE_ENTITY`, `ADD_ASSERTION`, `UPDATE_ASSERTION`,
`RETRACT_ASSERTION`, `ADD_RELATION`, `UPDATE_RELATION`, `RETRACT_RELATION`,
`UPDATE_ATTRIBUTE`.

Rules KÜYEN enforces:

* every operation that **changes or retracts** declares `expected`; a mismatch is refused;
* every operation cites the instruction in `antu_ref`; a literal fragment or a faithful
  paraphrase (≥80 % of its words present) passes, an invented justification does not;
* additions propose a **local** reference (`value.ref`); KÜYEN generates the canonical

## 4. Result states

| State | Meaning | New version? |
| --- | --- | --- |
| `COMMITTED` | the proposal was validated and confirmed | yes |
| `VALIDATED` | `dry_run=True`: validated, not written | no |
| `REJECTED` | an operation or the whole candidate breaks the contract | no |
| `CLARIFICATION_REQUIRED` | the instruction is ambiguous; the model asks | no |
| `CONFLICT` | the instruction contradicts the graph, or the base moved (`STALE_BASE`) | no |
| `NO_CHANGES` | the interpretation produces no operation | no |
| `INTERPRETATION_FAILED` | the model output is not the contract | no |
| `REPLAYED` | that `antu_id` already finished; the earlier result is returned | no |

A rejection leaves the graph untouched and stays in the ledger forever.

## 5. Provenance

Every object created or modified by an instruction carries an `origin` of kind
`ANTU_INSTRUCTION` with the literal instruction, its hash, the Antü id, the base version,
the actor, the model and the reason, plus `documentary_verification: false` and
`status: "INSTRUCTED"`. `kuyen.validation.canonical` **refuses** any object with an
`ANTU_INSTRUCTION` origin that declares `SOURCE_VERIFIED`.

## 6. Corrections and retractions

* correcting an assertion or relation does **not** delete the previous one: it becomes
  `SUPERSEDED` with `superseded_by`, the new one points back with `supersedes`, and it does
  not inherit evidence;
* retracting leaves the object with `status: "RETRACTED"`, `retracted: true` and a
  `retraction` record (Antü, reason, date, instruction hash);
* `memory.current_objects(group)` returns only what is current; `memory.graph()` returns
  the full record, history included.

## 7. Differences between versions

`memory.diff(before, after)` returns, per collection: `added`, `modified` (with the fields
that changed), `removed_from_current_view` (retracted or superseded), `restored`,
`deleted` (always empty: KÜYEN never deletes) and `unchanged`. It is deterministic: the
same pair of versions always produces the same document. Without arguments it compares the
current version with its parent.

## 8. Editor configuration

| Variable | Meaning |
| --- | --- |
| `KUYEN_EDITOR_PROVIDER` | today only `openai-compatible` |
| `KUYEN_EDITOR_MODEL` | required: there is no default model and no fallback |
| `KUYEN_EDITOR_ENDPOINT` | endpoint base (`/chat/completions` is appended) |
| `KUYEN_EDITOR_API_KEY_ENV` | name of the variable holding the credential |
| `KUYEN_EDITOR_TEMPERATURE`, `KUYEN_EDITOR_MAX_TOKENS`, `KUYEN_EDITOR_TIMEOUT_S` | parameters |
| `KUYEN_EDITOR_JSON_MODE` | `true` to request `response_format: json_object` |

The credential is read at call time, never stored in the configuration, never sent inside
the prompt and never written to the ledger or to a result (only provider, model, proposal
hash and usage when the provider reports it).

`RecordedGraphEditor` replays an already recorded proposal, keyed by `prompt_sha256`: it
makes an edit auditable and demonstrable without calling any model.

## 9. The context the model receives

* small graph (≤200 objects): the full index, so nothing relevant is missing;
* large graph: keyword selection from the instruction plus a one-hop closure, with an
  explicit report of what was left out (`selection.truncated`);
* in both cases the included set is the **authorised scope**: an operation on an object
  that exists but is outside the context is refused with `TARGET_NOT_IN_CONTEXT` (different
  from `TARGET_NOT_FOUND`, which means the object does not exist in that version).

## 10. What this path does not do

* it does not read documents or MAPUs;
* it does not fill in evidence or quotations;
* it does not turn a forecast into a fact;
* it never applies partially: one invalid operation refuses the whole Antü;
* it never rewrites or deletes previous versions.

  identity, deterministically, so repeating the instruction never duplicates;
* `polarity` is mandatory on relations and assertions (`POSITIVE` or `NEGATIVE`);
* `modality` is `FACT`, `FORECAST`, `ESTIMATE`, `OPINION`, `CONDITIONAL` or `UNKNOWN`;
  when absent it is stored as `UNKNOWN`, never `FACT`;
* no operation may invent evidence: there is no MAPU, quote, offset or hash in this path.
