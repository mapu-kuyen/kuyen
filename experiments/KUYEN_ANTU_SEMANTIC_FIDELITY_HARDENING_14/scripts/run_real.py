"""Real Antü operations on the ten existing KÜYEN (no OpenViking, no rebuild).

Each call uses the current version of its memory, the same inference configuration as
experiment 13 and a literal instruction written after inspecting that memory. For every
applied operation the script checks, from the before/after graphs, that the properties the
Antü did not name survived.
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

PLAN = [
    {"kuyen": "KUYEN-002", "id": "K002-MOD", "case": "modality_only",
     "instruction": "La superficie quemada por el incendio es una estimación provisional, no un "
                    "hecho confirmado: cambia la modalidad de esa afirmación a ESTIMATE."},
    {"kuyen": "KUYEN-003", "id": "K003-VAL", "case": "value_correction",
     "instruction": "Corrige el porcentaje de capacidad de Cantábrico Occidental: debe ser "
                    "54,7 %, no 54,6 %."},
    {"kuyen": "KUYEN-005", "id": "K005-REL", "case": "multi_relation_retraction",
     "instruction": "Las relaciones que ubican AQUALICIOUS en España y en Noruega son incorrectas: "
                    "el proyecto no está ubicado allí, solo tiene instalaciones piloto en esos "
                    "países. Retíralas sin tocar las demás relaciones."},
    {"kuyen": "KUYEN-008", "id": "K008-MOD", "case": "modality_only",
     "instruction": "La temperatura media de septiembre de 2026 es un dato medido: marca esa "
                    "afirmación como FACT."},
    {"kuyen": "KUYEN-008", "id": "K008-VAL", "case": "value_correction",
     "instruction": "Corrige la temperatura media de septiembre de 2026 a 22,7 °C."},
    {"kuyen": "KUYEN-010", "id": "K010-SCH", "case": "schema_add_field",
     "instruction": "Añade el campo codigo_interno, de tipo texto, al tipo de entidad supplier "
                    "de este KÜYEN."},
    {"kuyen": "KUYEN-001", "id": "K001-VAL", "case": "value_correction",
     "instruction": "Corrige la tasa de paro del tercer trimestre de 2026: debe ser 10,20 %, no "
                    "10,18 %."},
    {"kuyen": "KUYEN-004", "id": "K004-VAL", "case": "value_correction",
     "instruction": "Corrige la potencia de bombeo de la central: son 364 MW, no 363,99 MW."},
    {"kuyen": "KUYEN-006", "id": "K006-MOD", "case": "modality_only",
     "instruction": "La contribución de Thwaites al aumento del nivel del mar es una proyección, "
                    "no un hecho: cambia la modalidad de esa afirmación a FORECAST."},
    {"kuyen": "KUYEN-007", "id": "K007-REL", "case": "relation_addition",
     "instruction": "Añade que Joel W. Sills trabaja en el Langley Research Center de la NASA."},
    {"kuyen": "KUYEN-009", "id": "K009-SAT", "case": "already_satisfied",
     "instruction": "Confirma que la reducción ajustada por volumen de los puntos de requisa "
                    "evitables es del 39,1 %."},
]


RETRIES = [
    {"kuyen": "KUYEN-002", "id": "K002-MOD2", "case": "modality_only",
     "instruction": "La afirmación que dice que la superficie quemada es 750 hectáreas es una "
                    "estimación provisional: cambia su modalidad a ESTIMATE sin cambiar el valor."},
    {"kuyen": "KUYEN-003", "id": "K003-VAL2", "case": "value_correction",
     "instruction": "La afirmación que dice que Cantábrico Occidental tiene un 54,6 % de "
                    "capacidad debe pasar a 54,7 %."},
    {"kuyen": "KUYEN-005", "id": "K005-REL2", "case": "multi_relation_retraction",
     "instruction": "Retira las relaciones «AQUALICIOUS se ubica en España» y «AQUALICIOUS se "
                    "ubica en Noruega». Son incorrectas."},
    {"kuyen": "KUYEN-008", "id": "K008-VAL2", "case": "value_correction",
     "instruction": "Corrige la afirmación que dice que la temperatura media de septiembre de "
                    "2026 es 22,6 °C: el valor correcto es 22,7 °C."},
    {"kuyen": "KUYEN-010", "id": "K010-SCH2", "case": "schema_add_field",
     "instruction": "Añade el campo codigo_interno, de tipo texto, al tipo de entidad supplier "
                    "de este KÜYEN."},
    {"kuyen": "KUYEN-006", "id": "K006-MOD2", "case": "modality_only",
     "instruction": "La contribución de Thwaites al aumento del nivel del mar es una proyección, "
                    "no un hecho: cambia la modalidad de esa afirmación a FORECAST."},
    {"kuyen": "KUYEN-007", "id": "K007-REL2", "case": "relation_addition",
     "instruction": "Añade que Joel W. Sills trabaja en el Langley Research Center de la NASA."},
    {"kuyen": "KUYEN-004", "id": "K004-VAL2", "case": "value_correction",
     "instruction": "La afirmación que dice que la potencia de bombeo es 363,99 MW debe pasar a "
                    "364 MW."},
]


RETRIES3 = [
    {"kuyen": "KUYEN-003", "id": "K003-VAL3", "case": "value_correction",
     "instruction": "Cambia 54,6 por 54,7 en la afirmación de capacidad de Cantábrico Occidental."},
    {"kuyen": "KUYEN-005", "id": "K005-REL3", "case": "multi_relation_retraction",
     "instruction": "Hay dos relaciones incorrectas: AQUALICIOUS → España y AQUALICIOUS → Noruega. "
                    "Retira las dos; son operaciones distintas."},
    {"kuyen": "KUYEN-010", "id": "K010-SCH3", "case": "schema_add_field",
     "instruction": "Declara el campo codigo_interno de tipo texto en el tipo de entidad supplier. "
                    "Es un cambio de esquema, no de datos."},
    {"kuyen": "KUYEN-007", "id": "K007-REL3", "case": "relation_addition",
     "instruction": "Crea la entidad Langley Research Center como organización y añade que J. "
                    "Sills trabaja en ella."},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def editor() -> OpenAICompatibleGraphEditor:
    return OpenAICompatibleGraphEditor(EditorConfig(
        model=MODEL, endpoint=API_BASE, api_key_env=API_KEY_ENV, temperature=0.0,
        max_tokens=8192, timeout_s=240.0, json_mode=True))


def index(graph: dict, kind: str) -> dict[str, dict]:
    key = {"assertion": "assertion_id", "relation": "relation_id",
           "entity": "entity_id"}.get(kind)
    if key is None:
        # schema changes are recorded by the applier as `field`: they have no object in the
        # graph to compare, the schema itself is the record.
        return {}
    return {str(item.get(key)): item for item in graph.get(kind + "s") or []}


def semantic_checks(before: dict, after: dict, result) -> list[dict]:
    """For every applied operation: were the properties the Antü did not name preserved?"""
    accepted = {str(item.get("operation_id")): item for item in result.operations}
    checks: list[dict] = []
    for applied in result.applied:
        operation = accepted.get(str(applied.get("operation_id"))) or {}
        requested = {key for key in (operation.get("value") or {}) if not key.startswith("_")}
        kind = applied.get("object_kind")
        object_id = str(applied.get("object_id"))
        previous = applied.get("previous") or {}
        before_objects = index(before, kind)
        after_objects = index(after, kind)
        after_object = after_objects.get(object_id) or {}
        preserved: dict[str, object] = {}
        violations: list[str] = []
        for prop in ("modality", "polarity", "scope", "attribution"):
            if prop in requested:
                continue
            expected = previous.get(prop, (before_objects.get(object_id) or {}).get(prop))
            actual = after_object.get(prop)
            if expected != actual:
                violations.append(f"{prop}: {expected!r} -> {actual!r}")
            else:
                preserved[prop] = actual
        if kind == "assertion":
            old_value = previous.get("value")
            new_value = after_object.get("value") or {}
            for field in ("unit", "context", "value_type"):
                if "value" in requested and field not in (operation.get("value") or {}).get("value", {}):
                    expected = (old_value or {}).get(field)
                    if expected != new_value.get(field):
                        violations.append(f"value.{field}: {expected!r} -> {new_value.get(field)!r}")
                    else:
                        preserved[f"value.{field}"] = new_value.get(field)
            # evidence: the superseded statement keeps its own; the new one records the history
            old_evidence = list(previous.get("evidence_ids") or [])
            new_evidence = list(after_object.get("evidence_ids") or [])
            if old_evidence and not new_evidence and not after_object.get("previous_evidence_ids"):
                violations.append("evidence: the prior evidence disappeared without a trace")
        checks.append({"operation_id": applied.get("operation_id"), "effect": applied.get("effect"),
                       "object_kind": kind, "object_id": object_id,
                       "requested": sorted(requested), "preserved": preserved,
                       "violations": violations})
    return checks


def run(spec: dict) -> dict:
    memory = KuyenMemory.open(WORK / spec["kuyen"] / "memory")
    before = memory.graph()
    base = (memory.current() or {}).version_id if memory.current() else None
    model = editor()
    started = time.time()
    record: dict = {"kuyen": spec["kuyen"], "antu_id": spec["id"], "case": spec["case"],
                    "instruction": spec["instruction"], "version_before": base,
                    "started_at": now(),
                    "model": {"model": MODEL, "endpoint": API_BASE,
                              "api_key_env": API_KEY_ENV}}
    result = memory.apply_antu(spec["instruction"], editor=model, antu_id=spec["id"])
    record["seconds"] = round(time.time() - started, 2)
    record["status"] = result.status
    record["version_after"] = result.version_id
    record["committed"] = result.committed
    record["operations"] = result.operations
    record["applied"] = result.applied
    record["declined"] = result.declined
    record["rejected"] = result.rejected
    record["applicability"] = result.applicability
    record["schema_changes"] = result.schema_changes
    record["reasons"] = result.reasons
    record["proposal"] = result.run.proposal.to_dict() if result.run and result.run.proposal else None
    record["context"] = {"selection": dict(result.run.context.selection),
                         "prompt_sha256": result.run.request.prompt_sha256,
                         "context_sha256": result.run.request.context_sha256}
    after = memory.graph()
    try:
        record["semantic_checks"] = semantic_checks(before, after, result)
    except Exception as exc:  # noqa: BLE001 - the analysis must never erase a committed outcome
        record["semantic_checks"] = []
        record["analysis_error"] = f"{type(exc).__name__}: {exc}"
    record["graph_before"] = {"version": before.get("version"),
                              "assertions": index(before, "assertion"),
                              "relations": index(before, "relation")}
    record["graph_after"] = {"version": after.get("version"),
                             "assertions": index(after, "assertion"),
                             "relations": index(after, "relation")}
    usage = getattr(model, "last_usage", None)
    if usage is not None:
        prompt = getattr(usage, "prompt_tokens", None) or 0
        completion = getattr(usage, "completion_tokens", None) or 0
        record["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion,
                           "cost_usd": round(prompt / 1e6 * PRICE_INPUT
                                             + completion / 1e6 * PRICE_OUTPUT, 6)}
    record["verify"] = memory.verify()
    record["versions"] = [item.version_id for item in memory.versions()]
    record["finished_at"] = now()
    return record


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    only = {item for item in sys.argv[1:] if not item.startswith("--")} or None
    summary_path = EVIDENCE / "real_runs.json"
    summary = (json.loads(summary_path.read_text(encoding="utf-8"))
               if summary_path.exists() else {"experiment": EXPERIMENT.name, "runs": {}})
    selected = PLAN
    if "--retries" in sys.argv:
        selected = PLAN + RETRIES
    if "--retries3" in sys.argv:
        selected = RETRIES3
    for spec in selected:
        if only and spec["id"] not in only:
            continue
        if spec["id"] in summary["runs"] and summary["runs"][spec["id"]].get("status"):
            print(f"[skip] {spec['id']} already recorded")
            continue
        print(f"[antu] {spec['kuyen']} {spec['id']} · {spec['instruction'][:80]}", flush=True)
        try:
            summary["runs"][spec["id"]] = run(spec)
        except Exception as exc:  # noqa: BLE001 - a failure is evidence too
            summary["runs"][spec["id"]] = {"kuyen": spec["kuyen"], "antu_id": spec["id"],
                                            "case": spec["case"],
                                            "instruction": spec["instruction"],
                                            "status": "FAILED",
                                            "error": f"{type(exc).__name__}: {exc}"[:800]}
        item = summary["runs"][spec["id"]]
        violations = sum(len(check["violations"]) for check in item.get("semantic_checks") or [])
        print(f"        {item.get('status')} · {item.get('seconds')}s · version={item.get('version_after')} · "
              f"applied={len(item.get('applied') or [])} · violations={violations} · "
              f"error={item.get('error')}", flush=True)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
