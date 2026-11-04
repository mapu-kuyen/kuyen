"""Generate REPORT.md and the hash manifest from the recorded evidence."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kuyen import KuyenMemory  # noqa: E402

EVIDENCE = EXPERIMENT / "evidence"
WORK = pathlib.Path("/tmp/kuyen13_work/instances")


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def main() -> int:
    runs = json.loads((EVIDENCE / "real_runs.json").read_text())["runs"]
    comparison = json.loads((EVIDENCE / "comparison.json").read_text())
    baseline = json.loads((EVIDENCE / "baseline_semantic_audit.json").read_text())
    hardened = json.loads((EVIDENCE / "experiment14_semantic_audit.json").read_text())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    versions = []
    for index in range(1, 11):
        kuyen = f"KUYEN-{index:03d}"
        memory = KuyenMemory.open(WORK / kuyen / "memory")
        versions.append([kuyen, len(memory.versions()), memory.current().version_id,
                         memory.verify()["ok"]])
    exp13_versions = 15
    total_versions = sum(int(row[1]) for row in versions)
    rows = [[run.get("kuyen"), run.get("antu_id"), run.get("case"), run.get("status"),
             len([item for item in run.get("applied") or []
                  if item.get("status") == "COMMITTED"]),
             len(run.get("declined") or []), len(run.get("rejected") or []),
             sum(len(check.get("violations") or [])
                 for check in run.get("semantic_checks") or []),
             run.get("version_after") or "—", run.get("seconds")]
            for run in runs.values()]
    body = f"""# KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14

**Veredicto.** El editor ANTÜ dejó de destruir propiedades que la instrucción no nombra. Sobre
las diez memorias reales del experimento 13, sin recompilar ningún documento:

* las tres afirmaciones reemplazadas por ANTÜ **conservaron modalidad, polaridad, unidad,
  contexto y ámbito** (en el experimento 13 las tres perdieron propiedades: 7 en total);
* se modificó la modalidad **sin tocar el valor** en KÜYEN-002 y KÜYEN-006, y la afirmación
  documental conservó su origen `DOCUMENT_EVIDENCE` y su evidencia;
* KÜYEN-005 retractó **dos relaciones geográficas en una sola versión atómica** sin tocar las
  relaciones válidas;
* KÜYEN-010 declaró `supplier.codigo_interno` como cambio de esquema versionado, y los intentos
  posteriores se declararon ya satisfechos sin crear versiones ficticias;
* ninguna operación se registra como confirmada antes del commit: las rechazadas quedan
  `DISCARDED` y las aceptadas, `VALIDATED`.

* rama: `{branch}` · HEAD al generar este informe: `{head}`
* evaluaciones reales: {comparison['14']['evaluations']} · confirmadas: {comparison['14']['committed']}
* coste: ${comparison['14']['cost_usd']:.4f} USD · tiempo de inferencia acumulado: {comparison['14']['seconds']} s
* versiones: {exp13_versions} al cerrar el experimento 13 → {total_versions} ahora

## 1. Estado del repositorio

| dato | valor |
| --- | --- |
| raíz | `/private/tmp/kuyen_hardening_01/kuyen` |
| rama | `{branch}` |
| HEAD inicial | `dfab165` (sin commits nuevos del experimento 14 al empezar) |
| HEAD al generar | `{head}` |
| trabajo previo | intacto: 79 entradas en `git status` antes de empezar, manifiesto en `evidence/experiment13_sha256.txt`, copia en `/tmp/kuyen14_backup_before.tar.gz` |
| OpenViking | **no ejecutado**; ninguna compilación documental repetida |

## 2. Hallazgos y causas técnicas

| # | defecto observado en 13 | causa encontrada | corrección |
| --- | --- | --- | --- |
| 1 | KÜYEN-008 perdió `FACT` al cambiar el valor | el aplicador construía la afirmación nueva desde la operación y ponía `UNKNOWN`/`None` en lo omitido | actualización parcial: `modality`, `polarity`, `scope` y la forma de `value` se heredan |
| 2 | KÜYEN-005 dejó relaciones geográficas equivalentes | el modelo propuso una sola retractación; el contrato no guiaba el barrido | prompt de relaciones + prueba de retractación múltiple atómica; la segunda instrucción retiró las dos |
| 3 | KÜYEN-002 no podía cambiar solo la modalidad | `_ASSERTION_UPDATE_FIELDS` no incluía `modality` y el aplicador exigía valor | `modality`/`attribution`/`polarity`/`scope` son campos de parche; la identidad no cambia |
| 4 | KÜYEN-010 no produjo `ADD_FIELD` | el modelo no proponía la operación; el motor sí la soporta | prompt de esquema explícito; primera llamada confirmada, las siguientes `ALREADY_SATISFIED` |
| 5 | `NO_CHANGES` genérico | el estado no distinguía «sin operaciones» de otras causas | se conserva `NO_CHANGES` con `reasons` explícitas y aplicabilidad por operación; el informe separa modelos que no propusieron |
| 6 | `ALREADY_SATISFIED` con `ADD_ASSERTION` malformada | la verificación de la afirmación no comparaba la forma propuesta | el motor rechaza la reclamación no comprobable (`APPLICABILITY_CLAIM_UNSUPPORTED`) sin escribir |
| 7 | `applied` parecía confirmado tras un rechazo | el resultado exponía la aplicación al candidato como si fuera el commit | ciclo de vida por operación y `DISCARDED` cuando no hubo commit |

## 3. Código y contratos modificados

| archivo | cambio |
| --- | --- |
| `src/kuyen/editing/validator.py` | parches de afirmación y relación; `modality`/`attribution`/`polarity`/`scope`; identidad vs propiedad; rechazo de propuestas incompletas sin excepción |
| `src/kuyen/editing/applier.py` | herencia de propiedades, fusión de `value`, `previous_evidence_ids`, `instruction_edits`, origen documental preservado |
| `src/kuyen/api/memory.py` | ciclo de vida `VALIDATED`/`COMMITTED`/`DISCARDED`; `applied` separado de `operations` |
| `src/kuyen/storage/versions.py` | orden de versiones por `created_at` (antes, por hash del directorio) |
| `src/kuyen/editing/prompt.py` | contrato de parche, barrido de relaciones y ejemplo de esquema |
| `DATA_MODEL.md`, `ANTU_LIFECYCLE.md`, `docs/PRODUCT_MAPU_KUYEN_ANTU*.md`, `CHANGELOG.md` | documentación ES/EN |

## 4. Pruebas deterministas

`tests/editing/test_025_semantic_fidelity.py` (20 pruebas): valor sin perder modalidad, modalidad
sin valor, atribución sin perder evidencia, polaridad explícita, `UNKNOWN` explícito, valor
parcial sin unidad, `expected` obligatorio, retractación múltiple atómica con relación válida
intacta, retractación sin objetivo, etiqueta de relación en sitio, campo nuevo, campo existente,
tipo inexistente, actualización de campo sin declaración, idempotencia, ciclo de vida, rechazo
tras aplicación (`DISCARDED`), origen documental conservado y `ADD_FIELD` malformado sin crash.

```
python3 -m pytest -q tests/            # suite completa en verde (3 opt-in skipped)
python3 -m pytest -q tests/editing/test_025_semantic_fidelity.py   # 20 passed
```

## 5. Operaciones reales

{table(["KÜYEN", "ANTÜ", "caso", "resultado", "aplicadas", "declinadas", "rechazadas", "pérdidas", "versión", "s"], rows)}

## 6. Fidelidad semántica medida en las versiones

Misma auditoría aplicada a las dos tandas: se compara la afirmación reemplazada con su
predecesora en la versión confirmada y se miran solo las propiedades que la operación no pidió.

| experimento | afirmaciones reemplazadas | con pérdida | propiedades perdidas |
| --- | --- | --- | --- |
| 13 | {baseline['assertions_replaced']} | {baseline['with_semantic_loss']} | {baseline['properties_lost']} |
| 14 | {hardened['assertions_replaced']} | {hardened['with_semantic_loss']} | {hardened['properties_lost']} |

Pérdidas del experimento 13: {', '.join(f"{item['kuyen']}/{item['antu']} " + ", ".join(prop['property'] for prop in item['lost']) for item in baseline['findings'] if item['lost'])}.

## 7. Versiones

{table(["KÜYEN", "versiones", "versión vigente", "verify()"], versions)}

Las versiones anteriores siguen siendo legibles y verificables; cada una reconstruye el estado
anterior del grafo (las pruebas y `memory.graph(version)` lo cubren).

## 8. Comparación 13 → 14

| métrica | 13 | 14 |
| --- | --- | --- |
| evaluaciones | {comparison['13']['evaluations']} | {comparison['14']['evaluations']} |
| confirmadas | {comparison['13']['committed']} | {comparison['14']['committed']} |
| sin cambios | {comparison['13']['no_changes']} | {comparison['14']['no_changes']} |
| rechazadas | {comparison['13']['rejected']} | {comparison['14']['rejected']} |
| aclaración | {comparison['13']['clarification']} | {comparison['14']['clarification']} |
| fallo de ejecución | {comparison['13']['failed']} | {comparison['14']['failed']} |
| coste USD | {comparison['13']['cost_usd']} | {comparison['14']['cost_usd']} |

No se declara una mejora porcentual: la diferencia relevante es cualitativa y está medida en la
§6 (0 propiedades perdidas frente a 7) y en los casos nuevos que antes eran imposibles
(modalidad aislada, origen documental preservado, dos retractaciones atómicas, campo de esquema
versionado).

## 9. Coste

Coste calculado con la tarifa de `deepseek-flash` del experimento 13 (entrada como *cache miss*,
hora punta) y la tarifa de lista de `text-embedding-3-small`. El detalle por ejecución está en
`benchmarks/runs.csv`; el metering no entra en ningún hash canónico.

## 9-bis. Criterios de aceptación verificados

`evidence/acceptance.json` comprueba doce criterios contra las memorias reales (no contra fixtures):
actualización parcial conserva modalidad y polaridad; modalidad sola no cambia el valor ni la
atribución; el origen documental sobrevive; dos retractaciones son atómicas y las relaciones
válidas siguen intactas; el campo de esquema está versionado; repetir el ANTÜ no crea versión;
ningún rechazo figura como confirmado; las diez memorias verifican.

## 10. Limitaciones

* El modelo `deepseek-flash` sigue devolviendo `NO_CHANGES` sin operaciones en instrucciones
  largas o con muchos objetos (KÜYEN-003 y KÜYEN-005 necesitaron una segunda formulación; KÜYEN-007
  no llegó a proponer la relación). El motor no lo interpreta como éxito: la evaluación queda
  registrada y no hay versión.
* La adición de relación en KÜYEN-007 no se demostró con LLM real: en el experimento 13
  también devolvió `NO_CHANGES`. Está cubierta por prueba determinista; el motor la soporta y la
  retractación múltiple sí se demostró con el modelo real en KÜYEN-005.
* `UPDATE_ENTITY` y `UPDATE_ATTRIBUTE` no se tocaron: el alcance eran afirmaciones, relaciones y
  esquema.
* No se repitió ninguna compilación de OpenViking ni se modificó ningún MAPU.

## 11. Reproducibilidad

```bash
python3 scripts/run_real.py            # primera tanda (11 instrucciones)
python3 scripts/run_real.py --retries  # reintentos dirigidos
python3 scripts/run_real.py --retries3 # formulación explícita de relaciones y esquema
python3 scripts/audit_baseline.py      # auditoría semántica 13 y 14
python3 scripts/analyze.py             # tablas comparativas
python3 scripts/report14.py            # este informe y el manifiesto
```

Cada archivo de `evidence/` tiene su sha256 en `MANIFEST.json`. Los artefactos del experimento 13
no se modificaron: su inventario previo está en `evidence/experiment13_sha256.txt`.
"""
    (EXPERIMENT / "REPORT.md").write_text(body, encoding="utf-8")
    files = sorted(path for path in EXPERIMENT.rglob("*")
                   if path.is_file() and "MANIFEST.json" not in path.name)
    manifest = {"experiment": EXPERIMENT.name,
                "files": [{"path": str(path.relative_to(EXPERIMENT)),
                           "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in files]}
    manifest["file_count"] = len(manifest["files"])
    (EXPERIMENT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("REPORT.md", len(body), "files", manifest["file_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
