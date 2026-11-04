# SECURITY

## Reporting a vulnerability

Report privately to the maintainers through the repository's *Security → Report a
vulnerability* channel. Do not open a public issue for a suspected vulnerability. Include
affected version, a minimal reproduction and impact. Acknowledgement target: 5 working
days.

## Threat model

KÜYEN is a library inside an agent's process. It assumes:

* the agent process is trusted; KÜYEN provides no privilege boundary inside it;
* the canonical store directory is owned by the operator and not world-writable;
* source documents may be hostile (arbitrary Unicode, huge, adversarial structure);
* external engines (OpenViking, indexes) are **untrusted** for correctness: they are
  projections and never authoritative.

## Controls

| Control | Implementation |
| --- | --- |
| Path traversal | identifiers are validated before any path is built; `StoreError` otherwise. A version identifier must match `VER-<12 hex>`, and its resolved manifest must stay under `<store>/versions` (no `..`, no absolute path, no symlink that leaves the store) |
| Content integrity | every blob is named by the SHA-256 of its bytes and re-verified on read |
| Immutability | committed artifacts are `0444`; a rewrite attempt is detected |
| Tamper detection | see [Limits of tamper detection](#limits-of-tamper-detection): every artifact is bound to at least one content-addressed record, so an inconsistent change is detected |
| Source provenance | the original bytes of a source are hashed (`source_bytes_sha256`) and decoded without newline translation; evidence offsets are Unicode code points over the text that was stored, and the scope is declared per MAPU |
| Fail closed | corrupted or unsupported state raises or is reported; never guessed |
| No code execution from data | canonical objects are data; nothing is `eval`-ed or imported from the store |
| No secrets at rest | KÜYEN does not store credentials; provider credentials are outside the store |
| No network in the core | the core makes no outbound call; adapters are opt-in |
| Unvalidated writes | refused: `commit` requires a `VALIDATED` execution, and `VALIDATED` is only returned for a candidate that already passes the commit validation |

## Limits of tamper detection

KÜYEN has **no signature, no MAC and no external anchor**. Every record is bound to another
record by a hash, so a change that is not propagated to all of them is detected, but a writer
who can rewrite the whole store consistently produces a store that verifies. What that means
in practice:

| Change | Detected? | By what |
| --- | --- | --- |
| Corrupted or deleted blob | yes | the blob name is its SHA-256 and every read re-hashes it |
| One manifest field edited (`counts`, `object_hashes`, `canonical_graph_hash`, `parent_version_id`, `antu_id`, `kuyen_version`, `sidecar_content_hash`, references) | yes | the manifest must agree with its `identity_core`, its integrity record and its sidecar |
| A manifest moved to another version directory | yes | `version_id` is derived from `identity_core` and must equal the directory name |
| One event edited in the ledger | yes | `event_hash` and `prev_event_hash` no longer verify |
| The whole ledger chain rewritten | **no** | the chain is self-consistent; there is no anchor |
| A version replaced together with all its records | **no** | no root of trust distinguishes an authorized commit from a forged one |
| `CURRENT` moved to another *existing*, verified version (rollback) | **no** | the pointer still agrees with that version's manifest |
| Metadata outside the store (a copied `MAPU-*.txt`, a printed hash) | **no** | it is not part of the store |

### What an append validates, and what it does not

`append_event` reads the **tail** of the ledger to link the new record (`seq` and
`prev_event_hash` come from the last published event) and does not re-parse the whole chain:
re-parsing it made the cost of writing history grow with the history itself (quadratic,
measured in `KUYEN_RELEASE_CANDIDATE_05`, M6). The write path therefore cannot detect damage
in the *middle* of the chain before appending; readers can: `events()`, `verify_chain()`,
`verify()` and `ledger_state()` keep failing closed on `CORRUPT` and never repair anything
except a final incomplete record (M2). An appended record is always well-formed and links to
the previous one, so nothing invalid is written; a damaged history stays damaged, is
reported, and is never rewritten.

Closing those requires an external root of trust: a signing key whose public half lives
outside the store (per-version manifest signature, or an append-only external anchor for the
ledger head). That is a persisted-format change and a new key-management contract, so it is
not implemented here; until then, this page is the authoritative statement of what the store
proves. A store directory must therefore be protected by the operating system (ownership,
permissions, disk encryption), which is the assumption stated in the threat model.

## Source provenance

A source has three identities and KÜYEN keeps them apart (`kuyen.provenance`):

* `source_bytes_sha256` — SHA-256 of the original file bytes, exactly as read;
* `content` — those bytes decoded with the declared `encoding`, **without newline
  translation**, so `content.encode(encoding)` returns the original bytes;
* `content_sha256` — SHA-256 of that decoded text, which is what evidence offsets address
  (`offset_unit = "unicode_codepoint"`).

`newline_policy` is `PRESERVED` when the bytes were supplied and `UNKNOWN` when only text
was, and `source_hash_scope` says whether the record addresses `SOURCE_BYTES` or only the
`DECODED_TEXT`. An LF and a CRLF rendering of the same document are therefore different
sources with different hashes, both verifiable, and neither is silently normalised. Read
sources with `kuyen.provenance.read_source()`: `Path.read_text()` translates `\r\n` to `\n`
and would break exactly that correspondence.

## Secrets policy

* No credentials, tokens, `.env` files, key material or personal paths in the repository or
  in the built artifacts.
* The suite and CI run without credentials.
* Logs and error messages never print source text, only identifiers and hashes.

## Data at rest

MAPU content is stored verbatim. If a source is sensitive, the store inherits that
sensitivity: encrypt the volume, or keep the MAPU outside and store only its hash plus the
quoted evidence, which KÜYEN supports because evidence carries its own offsets and quote.

## Supported versions

Security fixes are applied to the current release candidate line. There is no long-term
support commitment before the first public release.
