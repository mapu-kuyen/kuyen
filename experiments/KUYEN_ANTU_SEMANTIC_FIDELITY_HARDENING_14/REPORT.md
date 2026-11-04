# KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14

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

* rama: `work/kuyen-free-text-graph` · HEAD al generar este informe: `dfab165eec044b344dd8a5e3e2b94693153fc968`
* evaluaciones reales: 23 · confirmadas: 8
* coste: $0.1904 USD · tiempo de inferencia acumulado: 129.3 s
* versiones: 15 al cerrar el experimento 13 → 23 ahora

## 1. Estado del repositorio

| dato | valor |
| --- | --- |
| raíz | `/private/tmp/kuyen_hardening_01/kuyen` |
| rama | `work/kuyen-free-text-graph` |
| HEAD inicial | `dfab165` (sin commits nuevos del experimento 14 al empezar) |
| HEAD al generar | `dfab165eec044b344dd8a5e3e2b94693153fc968` |
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

| KÜYEN | ANTÜ | caso | resultado | aplicadas | declinadas | rechazadas | pérdidas | versión | s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KUYEN-002 | K002-MOD | modality_only | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.28 |
| KUYEN-003 | K003-VAL | value_correction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 5.03 |
| KUYEN-005 | K005-REL | multi_relation_retraction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.77 |
| KUYEN-008 | K008-MOD | modality_only | COMMITTED | 1 | 0 | 0 | 0 | VER-db7e9865990d | 3.7 |
| KUYEN-008 | K008-VAL | value_correction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.63 |
| KUYEN-010 | K010-SCH | schema_add_field | COMMITTED | 1 | 0 | 0 | 0 | VER-aa3c7866061c | None |
| KUYEN-001 | K001-VAL | value_correction | COMMITTED | 1 | 0 | 0 | 0 | VER-6d440968cbb3 | 6.73 |
| KUYEN-004 | K004-VAL | value_correction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 15.08 |
| KUYEN-006 | K006-MOD | modality_only | REJECTED | 0 | 1 | 0 | 0 | — | 11.4 |
| KUYEN-007 | K007-REL | relation_addition | FAILED | 0 | 0 | 0 | 0 | — | None |
| KUYEN-009 | K009-SAT | already_satisfied | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.56 |
| KUYEN-002 | K002-MOD2 | modality_only | COMMITTED | 1 | 0 | 0 | 0 | VER-36bafc9dcf2f | 4.07 |
| KUYEN-003 | K003-VAL2 | value_correction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.45 |
| KUYEN-005 | K005-REL2 | multi_relation_retraction | NO_CHANGES | 0 | 0 | 0 | 0 | — | 4.76 |
| KUYEN-008 | K008-VAL2 | value_correction | COMMITTED | 1 | 0 | 0 | 0 | VER-529b4688b446 | 3.54 |
| KUYEN-010 | K010-SCH2 | schema_add_field | NO_CHANGES | 0 | 0 | 0 | 0 | — | 2.72 |
| KUYEN-006 | K006-MOD2 | modality_only | COMMITTED | 1 | 1 | 0 | 0 | VER-71b8665042d5 | 7.4 |
| KUYEN-007 | K007-REL2 | relation_addition | CLARIFICATION_REQUIRED | 0 | 0 | 0 | 0 | — | 21.46 |
| KUYEN-004 | K004-VAL2 | value_correction | REJECTED | 0 | 0 | 1 | 0 | — | 3.87 |
| KUYEN-003 | K003-VAL3 | value_correction | COMMITTED | 1 | 0 | 0 | 0 | VER-b54579461c44 | 4.01 |
| KUYEN-005 | K005-REL3 | multi_relation_retraction | COMMITTED | 2 | 0 | 0 | 0 | VER-924d732d0d70 | 4.32 |
| KUYEN-010 | K010-SCH3 | schema_add_field | NO_CHANGES | 0 | 0 | 0 | 0 | — | 2.59 |
| KUYEN-007 | K007-REL3 | relation_addition | NO_CHANGES | 0 | 0 | 0 | 0 | — | 5.93 |

## 6. Fidelidad semántica medida en las versiones

Misma auditoría aplicada a las dos tandas: se compara la afirmación reemplazada con su
predecesora en la versión confirmada y se miran solo las propiedades que la operación no pidió.

| experimento | afirmaciones reemplazadas | con pérdida | propiedades perdidas |
| --- | --- | --- | --- |
| 13 | 3 | 3 | 7 |
| 14 | 3 | 0 | 0 |

Pérdidas del experimento 13: KUYEN-003/ANTU-K003-03 scope, KUYEN-008/ANTU-K008-02 attribution, scope, KUYEN-008/ANTU-K008-04 modality, attribution, scope, value.context.

## 7. Versiones

| KÜYEN | versiones | versión vigente | verify() |
| --- | --- | --- | --- |
| KUYEN-001 | 2 | VER-6d440968cbb3 | True |
| KUYEN-002 | 2 | VER-36bafc9dcf2f | True |
| KUYEN-003 | 3 | VER-b54579461c44 | True |
| KUYEN-004 | 1 | VER-8732e4ef6f56 | True |
| KUYEN-005 | 4 | VER-924d732d0d70 | True |
| KUYEN-006 | 2 | VER-71b8665042d5 | True |
| KUYEN-007 | 1 | VER-34b7b1f4eecb | True |
| KUYEN-008 | 5 | VER-529b4688b446 | True |
| KUYEN-009 | 1 | VER-884d87f21f7a | True |
| KUYEN-010 | 2 | VER-aa3c7866061c | True |

Las versiones anteriores siguen siendo legibles y verificables; cada una reconstruye el estado
anterior del grafo (las pruebas y `memory.graph(version)` lo cubren).

## 8. Comparación 13 → 14

| métrica | 13 | 14 |
| --- | --- | --- |
| evaluaciones | 25 | 23 |
| confirmadas | 5 | 8 |
| sin cambios | 16 | 11 |
| rechazadas | 3 | 2 |
| aclaración | 1 | 1 |
| fallo de ejecución | 0 | 1 |
| coste USD | 0.229773 | 0.190396 |

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
