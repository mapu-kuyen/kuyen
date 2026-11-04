"""Reproducible difference between two canonical versions (§3).

A version is compared by canonical identity: what exists now and did not exist before
(`added`), what exists in both but changed (`modified`), and what disappeared from the
current view because it was retracted or superseded (`removed`, always reported with the
object it left behind, because KÜYEN keeps it).

The output is deterministic: sorted identifiers, no timestamps, no ordering by insertion.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

COLLECTIONS = (("entities", "entity_id"), ("relations", "relation_id"),
               ("assertions", "assertion_id"), ("evidence", "evidence_id"))


def _index(document: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    canonical = document.get("canonical") or document
    return {group: {str(item.get(key)): item for item in (canonical.get(group) or [])
                    if item.get(key)}
            for group, key in COLLECTIONS}


def _is_current(item: Mapping[str, Any]) -> bool:
    if item.get("retracted"):
        return False
    return str(item.get("status") or "") not in ("SUPERSEDED", "RETRACTED")


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    fields = sorted(set(before) | set(after))
    return [field for field in fields
            if field not in ("origin", "revisions", "supersession", "retraction")
            and before.get(field) != after.get(field)]


def diff_documents(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Difference between two canonical documents, by canonical identity."""
    left = _index(before)
    right = _index(after)
    result: dict[str, Any] = {"collections": {}, "counts": {}}
    for group, _key in COLLECTIONS:
        added = sorted(set(right[group]) - set(left[group]))
        removed = sorted(set(left[group]) - set(right[group]))
        modified = sorted(
            identifier for identifier in set(left[group]) & set(right[group])
            if _changed_fields(left[group][identifier], right[group][identifier])
        )
        hidden = sorted(identifier for identifier in right[group]
                        if identifier in left[group] and _is_current(left[group][identifier])
                        and not _is_current(right[group][identifier]))
        restored = sorted(identifier for identifier in right[group]
                          if identifier in left[group] and not _is_current(left[group][identifier])
                          and _is_current(right[group][identifier]))
        result["collections"][group] = {
            "added": added,
            "modified": {identifier: _changed_fields(left[group][identifier], right[group][identifier])
                         for identifier in modified},
            "removed_from_current_view": hidden,
            "restored": restored,
            "deleted": removed,
            "unchanged": len(set(left[group]) & set(right[group])
                             - set(modified) - set(hidden) - set(restored)),
        }
        result["counts"][group] = {"before": len(left[group]), "after": len(right[group]),
                                   "added": len(added), "modified": len(modified),
                                   "retracted": len(hidden), "deleted": len(removed)}
    result["versions"] = {
        "before": {"kuyen_id": (before.get("kuyen") or {}).get("kuyen_id"),
                   "version": (before.get("kuyen") or {}).get("version"),
                   "canonical_graph_hash": (before.get("kuyen") or {}).get("canonical_graph_hash")},
        "after": {"kuyen_id": (after.get("kuyen") or {}).get("kuyen_id"),
                  "version": (after.get("kuyen") or {}).get("version"),
                  "canonical_graph_hash": (after.get("kuyen") or {}).get("canonical_graph_hash")},
    }
    result["empty"] = all(
        not value["added"] and not value["modified"] and not value["removed_from_current_view"]
        and not value["restored"] and not value["deleted"]
        for value in result["collections"].values())
    return result


def summarize(diff: Mapping[str, Any]) -> dict[str, Any]:
    """A compact, human-readable summary of a diff (used by the API result)."""
    summary = {}
    for group, value in (diff.get("collections") or {}).items():
        if not isinstance(value, Mapping):
            continue
        if value.get("added") or value.get("modified") or value.get("removed_from_current_view"):
            summary[group] = {"added": list(value.get("added") or []),
                              "modified": sorted((value.get("modified") or {}).keys()),
                              "retracted": list(value.get("removed_from_current_view") or [])}
    return summary


def current_objects(document: Mapping[str, Any], group: str) -> list[dict[str, Any]]:
    """Objects of a collection that are current (not retracted, not superseded)."""
    canonical = document.get("canonical") or document
    return [copy.deepcopy(item) for item in (canonical.get(group) or []) if _is_current(item)]
