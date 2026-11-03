"""Real Antü operations on the ten existing KÜYEN (no OpenViking, no rebuild, no fallback).

Why this exists (KUYEN_ANTU_OPERATIONAL_COVERAGE_15, §3-§6): experiment 14 demonstrated
partial updates and multi-retraction with the real model, but never a relation *addition*, an
`UPDATE_ENTITY` or an `UPDATE_ATTRIBUTE`, and it recorded every empty proposal as `NO_CHANGES`.
This script exercises exactly those operations against the graphs that already exist, with the
same provider, the same model and the same generation parameters as experiments 13 and 14.

The two dry runs come first and share one base version, so the short and the long form of the
same request are compared on identical knowledge; a dry run validates but never writes.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kuyen import KuyenMemory  # noqa: E402
from kuyen.editing.editors import EditorConfig, OpenAICompatibleGraphEditor  # noqa: E402

WORK = pathlib.Path("/tmp/kuyen13_work/instances")
EVIDENCE = EXPERIMENT / "evidence"
MODEL = os.environ.get("KUYEN_INFERENCE_MODEL", "deepseek-flash")
API_BASE = os.environ.get("KUYEN_INFERENCE_API_BASE", "https://api.deepseek.com/v1")
API_KEY_ENV = os.environ.get("KUYEN_INFERENCE_API_KEY_ENV", "DEEPSEEK_API_KEY")
PRICE_INPUT, PRICE_OUTPUT = 0.30, 1.20  # deepseek-flash, peak, cache-miss (exp 13)

SHORT = ("El Instituto para la Diversificación y Ahorro de la Energía pertenece al Ministerio "
         "para la Transición Ecológica y el Reto Demográfico: incorpora esa relación entre las "
         "dos entidades.")
LONG = (
    "Estoy revisando la ficha de la central hidráulica reversible de Los Guájares en este KÜYEN "
    "y hay varias cosas que deben quedar registradas en una sola petición. Primero, el "
    "Instituto para la Diversificación y Ahorro de la Energía es un organismo adscrito al "
    "Ministerio para la Transición Ecológica y el Reto Demográfico, de modo que entre esas dos "
    "entidades que ya existen debe figurar la relación de pertenencia correspondiente. Segundo, "
    "la denominación de la central aparece sin tilde y su nombre correcto es «Central Hidráulica "
    "Reversible Los Guájares», así que actualiza la denominación de la entidad existente "
    "conservando la forma anterior como alias. Tercero, añade el alias «Los Guájares» a la misma "
    "central. Son tres cambios independientes sobre entidades que ya están en el KÜYEN: no "
    "inventes entidades nuevas, no omitas ninguno y no los resumas en uno solo."
)

PLAN = [
    {"kuyen": "KUYEN-004", "id": "K004-DRY-SHORT", "case": "long_vs_short_short",
     "instruction": SHORT, "dry_run": True},
    {"kuyen": "KUYEN-004", "id": "K004-DRY-LONG", "case": "long_vs_short_long",
     "instruction": LONG, "dry_run": True},
    {"kuyen": "KUYEN-004", "id": "K004-REL", "case": "relation_addition",
     "instruction": "El Instituto para la Diversificación y Ahorro de la Energía es un "
                    "organismo adscrito al Ministerio para la Transición Ecológica y el Reto "
                    "Demográfico: incorpora esa relación de pertenencia entre ambas entidades."},
    {"kuyen": "KUYEN-004", "id": "K004-ENT", "case": "entity_rename",
     "instruction": "La denominación de la central figura sin tilde en este KÜYEN: su nombre "
                    "correcto es «Central Hidráulica Reversible Los Guájares». Actualiza la "
                    "denominación de la entidad que ya existe y conserva la forma anterior como "
                    "alias."},
    {"kuyen": "KUYEN-004", "id": "K004-ATTR-DECL", "case": "attribute_declared_and_set",
     "instruction": "Declara en las entidades de tipo product el atributo estado_operativo, de "
                    "tipo texto, y ponlo en «operativa» para la Central Hidráulica Reversible "
                    "Los Guájares."},
    {"kuyen": "KUYEN-004", "id": "K004-ATTR", "case": "attribute_correction",
     "instruction": "El estado operativo de la Central Hidráulica Reversible Los Guájares no es "
                    "«operativa» sino «en mantenimiento»: corrige ese atributo de la ficha."},
    {"kuyen": "KUYEN-004", "id": "K004-SAT", "case": "already_satisfied",
     "instruction": "Confirma que el Instituto para la Diversificación y Ahorro de la Energía "
                    "financia la Central Hidráulica Reversible Los Guájares."},
    {"kuyen": "KUYEN-004", "id": "K004-CLAR", "case": "ambiguous_target",
     "instruction": "Corrige la denominación de la estación de este KÜYEN."},
    # After the verifiable-decline correction: the same request, a new Antü identity, so the
    # idempotency guard does not replay the refusal and the model has to answer again.
    {"kuyen": "KUYEN-004", "id": "K004-SAT2", "case": "already_satisfied_after_fix",
     "instruction": "Confirma que el Instituto para la Diversificación y Ahorro de la Energía "
                    "financia la Central Hidráulica Reversible Los Guájares."},
    {"kuyen": "KUYEN-004", "id": "K004-LONG2", "case": "long_instruction_after_fix",
     "instruction": LONG, "dry_run": True},
    {"kuyen": "KUYEN-004", "id": "K004-LONG3", "case": "long_instruction_after_claim_fix",
     "instruction": LONG, "dry_run": True},
    # A long, multi-operation request on another memory: schema declaration, typed attribute
    # and a relation addition, each on a different object of a KÜYEN untouched by this
    # experiment until now.
    {"kuyen": "KUYEN-005", "id": "K005-LONG", "case": "long_multi_operation",
     "instruction":
         "Necesito dejar la ficha de Óscar Monroig completa en este KÜYEN. En primer lugar, las "
         "personas de esta memoria deben poder llevar un atributo «rol» de tipo texto, que "
         "todavía no está declarado en el esquema: decláralo. En segundo lugar, el rol de Óscar "
         "Monroig es «investigador del CSIC», así que registra ese valor en su ficha. Por "
         "último, aunque ya consta para qué instituciones trabaja, falta la relación que lo "
         "vincula con el proyecto: Óscar Monroig participa en AQUALICIOUS, e incorpora esa "
         "relación entre las dos entidades que ya existen. Son tres cambios distintos sobre "
         "objetos distintos; no omitas ninguno."},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecordingEditor:
    """The real editor, wrapped so the raw response is kept as evidence (§6).

    KÜYEN parses the proposal and never needs the raw text, but an experiment that studies why
    a model produced no operation has to be able to read what it actually answered.
    """

    name = "recording"

    def __init__(self, inner: OpenAICompatibleGraphEditor) -> None:
        self.inner = inner
        self.last_raw: str | None = None

    @property
    def last_usage(self):
        return getattr(self.inner, "last_usage", None)

    def metadata(self) -> dict:
        return {**self.inner.metadata(), "raw_capture": True}

    def interpret(self, request) -> str:
        raw = self.inner.interpret(request)
        self.last_raw = raw
        return raw


def editor() -> RecordingEditor:
    return RecordingEditor(OpenAICompatibleGraphEditor(EditorConfig(
        model=MODEL, endpoint=API_BASE, api_key_env=API_KEY_ENV, temperature=0.0,
        max_tokens=8192, timeout_s=240.0, json_mode=True)))


def snapshot(memory: KuyenMemory) -> dict:
    """The observable state of one memory: versions, current pointer and object counts."""
    graph = memory.graph()
    return {"current": (memory.current() or {}).version_id,
            "versions": [item.version_id for item in memory.versions()],
            "verify": memory.verify()["ok"],
            "entities": {str(item.get("entity_id")): item.get("name")
                         for item in graph.get("entities") or []},
            "relations": {str(item.get("relation_id")): {
                "from": item.get("from_entity"), "to": item.get("to_entity"),
                "predicate": item.get("predicate"), "status": item.get("status")}
                for item in graph.get("relations") or []},
            "attributes": {str(item.get("entity_id")): dict(item.get("metadata") or {})
                           for item in graph.get("entities") or []}}


def preservation(before: dict, after: dict) -> dict:
    """What the Antü changed in the objects that existed before it ran.

    A property the Antü did not name must survive; an entity keeps its identity, its relations
    and its attributes. This is measured on the graphs, not on the proposal.
    """
    changed: list[str] = []
    lost: list[str] = []
    for entity_id, name in before["entities"].items():
        if entity_id not in after["entities"]:
            lost.append(f"entity {entity_id} disappeared")
            continue
        if after["entities"][entity_id] != name:
            changed.append(f"entity {entity_id}: {name!r} -> "
                           f"{after['entities'][entity_id]!r}")
        old_attributes = before["attributes"].get(entity_id) or {}
        new_attributes = after["attributes"].get(entity_id) or {}
        for key, value in old_attributes.items():
            if key not in new_attributes:
                lost.append(f"attribute {entity_id}.{key} disappeared")
            elif new_attributes[key] != value:
                changed.append(f"attribute {entity_id}.{key}: {value!r} -> "
                               f"{new_attributes[key]!r}")
    for relation_id, old in before["relations"].items():
        new = after["relations"].get(relation_id)
        if new is None:
            lost.append(f"relation {relation_id} disappeared")
        elif {key: new[key] for key in ("from", "to", "predicate")} != {
                key: old[key] for key in ("from", "to", "predicate")}:
            changed.append(f"relation {relation_id} changed endpoint or predicate")
    return {
        "entities_before": len(before["entities"]), "entities_after": len(after["entities"]),
        "relations_before": len(before["relations"]), "relations_after": len(after["relations"]),
        "changed": changed, "lost": lost,
    }


def run(spec: dict, summary: dict) -> dict:
    memory = KuyenMemory.open(WORK / spec["kuyen"] / "memory")
    before_snapshot = snapshot(memory)
    model = editor()
    started = time.time()
    record: dict = {"kuyen": spec["kuyen"], "antu_id": spec["id"], "case": spec["case"],
                    "instruction": spec["instruction"],
                    "version_before": before_snapshot["current"],
                    "dry_run": bool(spec.get("dry_run")), "started_at": now(),
                    "model": {"model": MODEL, "endpoint": API_BASE,
                              "api_key_env": API_KEY_ENV, "temperature": 0.0,
                              "max_tokens": 8192}}
    result = memory.apply_antu(spec["instruction"], editor=model, antu_id=spec["id"],
                               dry_run=bool(spec.get("dry_run")))
    record["seconds"] = round(time.time() - started, 2)
    record.update({"status": result.status, "outcome": result.outcome,
                   "version_after": result.version_id, "committed": result.committed,
                   "operations": result.operations, "applied": result.applied,
                   "declined": result.declined, "rejected": result.rejected,
                   "outcomes": result.outcomes, "applicability": result.applicability,
                   "schema_changes": result.schema_changes, "reasons": result.reasons,
                   "proposal": (result.run.proposal.to_dict()
                                if result.run and result.run.proposal else None),
                   "raw_response": (model.last_raw or "")[:20000],
                   "prompt_sha256": (result.run.request.prompt_sha256
                                     if result.run else None),
                   "context": dict(result.run.context.selection) if result.run else {},
                   "verify": memory.verify()["ok"]})
    after_snapshot = snapshot(memory)
    record["preservation"] = preservation(before_snapshot, after_snapshot)
    record["version_after"] = after_snapshot["current"]
    record["versions"] = after_snapshot["versions"]
    record["finished_at"] = now()
    usage = getattr(model, "last_usage", None)
    if usage is not None:
        prompt = getattr(usage, "prompt_tokens", None) or 0
        completion = getattr(usage, "completion_tokens", None) or 0
        record["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion,
                           "cost_usd": round(prompt / 1e6 * PRICE_INPUT
                                             + completion / 1e6 * PRICE_OUTPUT, 6)}
    summary.setdefault("cash", {"cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
    if record.get("usage"):
        summary["cash"]["cost_usd"] = round(summary["cash"]["cost_usd"]
                                            + record["usage"]["cost_usd"], 6)
        summary["cash"]["prompt_tokens"] += record["usage"]["prompt_tokens"]
        summary["cash"]["completion_tokens"] += record["usage"]["completion_tokens"]
    return record


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    only = {item for item in sys.argv[1:] if not item.startswith("--")} or None
    summary_path = EVIDENCE / "real_runs.json"
    summary = (json.loads(summary_path.read_text(encoding="utf-8"))
               if summary_path.exists() else {"experiment": EXPERIMENT.name,
                                              "model": MODEL, "endpoint": API_BASE,
                                              "runs": {}})
    for spec in PLAN:
        if only and spec["id"] not in only:
            continue
        if spec["id"] in summary["runs"] and summary["runs"][spec["id"]].get("status"):
            print(f"[skip] {spec['id']} already recorded")
            continue
        print(f"[antu] {spec['kuyen']} {spec['id']} · {spec['instruction'][:70]}", flush=True)
        try:
            summary["runs"][spec["id"]] = run(spec, summary)
        except Exception as exc:  # noqa: BLE001 - a failure is evidence too
            summary["runs"][spec["id"]] = {
                "kuyen": spec["kuyen"], "antu_id": spec["id"], "case": spec["case"],
                "instruction": spec["instruction"], "status": "FAILED",
                "error": f"{type(exc).__name__}: {exc}"[:800]}
        item = summary["runs"][spec["id"]]
        print(f"        {item.get('status')} · outcome={item.get('outcome')} · "
              f"{item.get('seconds')}s · version={item.get('version_after')} · "
              f"applied={len(item.get('applied') or [])} · "
              f"lost={len((item.get('preservation') or {}).get('lost') or [])} · "
              f"error={item.get('error')}", flush=True)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

