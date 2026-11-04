# SIDECAR

The canonical sidecar is the self-describing record of one version. It exists because an
external engine's representation is a *projection*: it can lose relations, merge
predicates or disappear entirely. The sidecar is what makes the memory reconstructable.

## Structure

```
KUYEN_CANONICAL_SIDECAR
├── schema_name / schema_version        "1.0.0"
├── kuyen_id / kuyen_version
├── mapu_id / mapu_ids
├── canonical_graph_hash                hash of the canonical graph
├── source_hashes                       graph, canonical serialization, per MAPU, per unit
├── exporter_version / projector_version / reconstructor_version
├── openviking_version                  the engine version it was projected to (or "")
├── kuyen_contract                      contract snapshot hash, schema versions
├── object_counts
├── projection_manifest_hash / mapping_manifest_hash
├── kuyen                               the canonical record
├── canonical                           entities, relations, assertions, evidence, source_units, coverage
├── mapus                               the source texts with their byte and text hashes
├── projection                          classification, artifacts, counts, collisions, transformations
├── mapping                             object-level correspondences
└── integrity                           sidecar content hash
```

## Guarantees

1. **Self-verifying** — the sidecar carries its own content hash; a modified sidecar is
detected, not trusted.
2. **Reconstructable** — `recovery` rebuilds the canonical graph from the sidecar and the
   contract alone, and the rebuilt hash must equal `canonical_graph_hash`.
3. **Honest about loss** — a projection may be incomplete; the sidecar records which
   objects could not be projected and why (`LOSSY_PROJECTION`).
4. **Versioned** — the schema version is independent of the store format and of the
   knowledge version.

## Correspondence mapping

Every canonical object that reaches a projection is recorded with its native location in
the mapping manifest, so "which line is this relation?" is answerable, and a collision
(several canonical relations that a native model can only express once) is recorded rather
than hidden.
