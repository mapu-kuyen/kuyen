# VERSIONING

KÜYEN keeps seven version domains strictly separate. No domain borrows another's number,
so an artifact can always say *which* contract it satisfies.

| Domain | Meaning | Current |
| --- | --- | --- |
| `leftraru_id` | The unit that owns the memory | per memory |
| `unit_revision` | `R0000`, `R0001`, … one per Antü execution | per execution |
| `kuyen_id` | Identity of the knowledge base | stable |
| `kuyen_version` | Semantic version of the knowledge (`1.0.0` → `1.1.0`) | per commit |
| `mapu_revisions` | Versions of the source documents | per source |
| `sidecar_schema_version` | Shape of the canonical sidecar | `1.0.0` |
| `store_format_version` | On-disk canonical store format | `1.0.0` |

The package has its own distribution version (`kuyen.__version__`), resolved from a single
source: the `VERSION` file at build time, then the installed metadata. The package version
describes the *software*; `kuyen_version` describes the *knowledge*.

## Immutability rules

1. A committed version is immutable: its manifest, sidecar, mapping, native projection and
   objects are content-addressed and read-only (`0444`).
2. A new Antü always produces a **new** version with `parent_version_id` pointing at its
   base. Nothing is edited in place.
3. `CURRENT` is a pointer, not a source of truth: it can only move by compare-and-set from
   a known version to one of its children.
4. Re-committing identical content reuses every object (content addressing) but still
   creates a distinct version, because version identity is the commit, not the bytes.

## Package version policy

The public API is the contract. Before it changes incompatibly, the package stays in
`0.x`. Moving to `1.0.0` is a decision for the owner, taken together with the licence
decision and the first public release (see `RELEASE_READINESS_REPORT.md`).
