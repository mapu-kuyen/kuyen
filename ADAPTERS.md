# ADAPTERS

A projection is a *view* of canonical memory in another engine (a graph store, a search
index, an agent runtime). Projections are optional, subordinate and regenerable.

## Contract

```python
memory.enqueue_projection(version_id, openviking_version="0.5.0", instance_tag="prod")
memory.pending_projections()
memory.project(client=client, openviking_version="0.5.0")
memory.projections()
memory.reconcile(client=client)
```

The outbox records what must be projected; the registry records what was projected, with
its classification, counts, correspondence manifest and integrity manifest.

## OpenViking adapter

`kuyen.projection.openviking` is an optional HTTP client for OpenViking 0.5.0. It is used
only when you call it; nothing in the core imports it. Verified endpoints:
`content/write`, `content/read`, `fs/*`, `search/grep`.

Verified limits (measured on OpenViking 0.5.0, and **not** capabilities of KÜYEN):

| Capability | Status |
| --- | --- |
| Native storage of projected content | works, byte-exact |
| Native projection of the full canonical model | incomplete — the sidecar is mandatory |
| Native compilation (`POST /api/v1/compile`) | not available without an LLM Skill; returns 503 |
| Semantic retrieval (`find`) | requires embeddings; returns 500 without them |
| Lexical retrieval (`search/grep`) | partial |

The product does not announce OpenViking native compilation or semantic retrieval. If
those become available they become a new, separately verified capability.

## Removing an adapter

Delete the adapter call sites: `verify()`, `graph()`, `versions()`, `history()`,
`backup()`, `restore()` and `recover_from_store()` never touch a projection, and the suite
proves memory works with no projection engine installed.
