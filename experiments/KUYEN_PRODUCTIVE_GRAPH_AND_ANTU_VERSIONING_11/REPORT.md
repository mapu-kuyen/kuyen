# KUYEN_PRODUCTIVE_GRAPH_AND_ANTU_VERSIONING_11

**Alcance.** Construir el núcleo productivo de KÜYEN: documento → grafo (OpenViking) y
grafo → nueva versión (ANTÜ directo con LLM), con versionamiento íntegro, procedencia
explícita y trazabilidad.

**Rama:** `work/kuyen-free-text-graph`
**Base:** `9a5e512` (con `b6ad5fc` en la historia)
**Estado:** dos caminos implementados y probados offline; las dos integraciones reales
(OpenViking 0.5.x con su Skill real y un LLM real) quedan **ejecutables pero no ejecutadas**
en este entorno. El push final **no se realizó** (ver §11).

```
VEREDICTO: NÚCLEO PRODUCTIVO IMPLEMENTADO Y PROBADO OFFLINE · INTEGRACIONES REALES NO EJECUTADAS · SIN PUSH
```

---

## 1. Estado inicial y final del repositorio

| dato | inicial | final |
| --- | --- | --- |
| Raíz real | `/private/tmp/kuyen_hardening_01/kuyen` | igual |
| Rama | `work/kuyen-free-text-graph` | igual |
| HEAD | `9a5e512` (con `b6ad5fc` en la historia) | `9a5e512` + los commits de §11 |
| Remoto / upstream | `origin` `https://github.com/mapu-kuyen/kuyen.git` · **sin upstream** | igual |
| Modificados / sin rastrear | 30 / 38 (verificado, coincide con el reporte previo) | ver §10 |
| Suite | 377 tests · 375 passed · 2 skipped · 0 failed | **450 tests · 447 passed · 3 skipped · 0 failed** |
| Copias del repositorio | sólo esta (`/tmp/kuyen_hardening_01/kuyen`); ninguna otra copia activa | igual |

Operaciones git destructivas utilizadas: **ninguna** (`reset`, `clean`, `checkout --`,
`restore` global, `stash`, `push --force` no se ejecutaron). Los trabajos previos sin
commit se conservaron íntegros; cuando una modificación nueva y otra previa conviven en el
mismo archivo, se indica explícitamente en §10.

## 2. Arquitectura real implementada

```
CAMINO A (documento)
  MAPU → OpenViking + Skill knowledge-graph → artefactos nativos
       → CandidateMaterializer (identidad MAPU, cita, polaridad, modalidad)
       → gate determinista de KÜYEN → commit canónico → v(n+1)     [SOURCE_VERIFIED]

CAMINO B (instrucción)
  ANTÜ literal → contexto determinista → LLM (sólo propone)
       → validación determinista → aplicación determinista → commit canónico → v(n+1)
                                                                   [ANTU_INSTRUCTION]
```

Ambos caminos terminan en **el mismo** `storage.commit.commit_version`: mismo ledger, mismo
manifest, mismo linaje, misma recuperación. No hay un segundo sistema de versionamiento.

Componentes nuevos:

| módulo | responsabilidad |
| --- | --- |
| `kuyen/editing/operations.py` | contrato `kuyen-graph-edit-v1` y parseo de la propuesta |
| `kuyen/editing/context.py` | recuperación determinista del contexto (índice completo / palabras clave + cierre de un salto) |
| `kuyen/editing/prompt.py` | petición hasheada (`prompt_sha256`, `context_sha256`) |
| `kuyen/editing/editors.py` | puerto del editor + implementación OpenAI-compatible (stdlib) + replay grabado |
| `kuyen/editing/validator.py` | validación determinista por operación y del conjunto |
| `kuyen/editing/applier.py` | aplicación determinista; identidad KÜYEN; supersesión y retractación |
| `kuyen/editing/diff.py` | diferencia reproducible entre versiones |
| `kuyen/editing/service.py` | flujo interpretación → validación → candidato |
| `kuyen/product.py` | clasificación de ANTÜ y los dos puntos de entrada |
| `kuyen/semantics/origin.py` | procedencia explícita de cada afirmación |
| `kuyen/api/memory.py` | `apply_antu`, `diff`, `current_objects` |

## 3. Contratos

| contrato | versión | cambio |
| --- | --- | --- |
| `kuyen-provider-result-v1` | vigente | aceptado sin cambios |
| `kuyen-provider-result-v2` | nuevo, aditivo | `polarity: UNKNOWN`, `modality`, `attribution`, `evidence.context`, `evidence.source_unit_id` |
| `kuyen-native-files-v1` | vigente | la cita manda sobre los offsets declarados |
| `kuyen-graph-edit-v1` | nuevo | nueve tipos de operación, `expected`, `antu_ref`, estados de aclaración/conflicto |
| `KUYEN_STATEMENT_ORIGIN` 1.0.0 | nuevo | `DOCUMENT_EVIDENCE` · `ANTU_INSTRUCTION` · `PRIOR_VERSION` · `INFERENCE_PENDING` |
| `evidence.schema.json` | 1.0.0 + 3 campos opcionales | `context`, `source_unit_id`, `declared_offsets` |
| ledger | 1.0.0 | dos tipos de evento nuevos (aditivo) |

Documentación pública: `docs/GRAPH_EDIT_ANTU.md` (ES) y `docs/GRAPH_EDIT_ANTU.en.md` (EN),
más las secciones añadidas a `DATA_MODEL.md`, `PUBLIC_API.md`, `ANTU_LIFECYCLE.md`,
`ARCHITECTURE.md`, `CHANGELOG.md` y `README.md`.

## 4. Flujos de ejecución (API real)

```python
from kuyen import (KuyenMemory, incorporate_document, apply_graph_edit,
                   EditorConfig, OpenAICompatibleGraphEditor)

memory = KuyenMemory.open("/var/lib/kuyen")

# Camino A — documento
documento = incorporate_document(memory, engine=engine, antu=antu_json,
                                 mapus=[mapu], actor=actor, adapter=adapter)
documento.status, documento.version_id, documento.counts, documento.evidence_ids

# Camino B — instrucción directa
resultado = apply_graph_edit(
    memory, "Cambia la cantidad de luminarias de 12 a 18",
    editor=OpenAICompatibleGraphEditor(EditorConfig.from_env()))
resultado.status, resultado.version_id, resultado.operations, resultado.rejected
resultado.provenance, resultado.diff, resultado.clarification
```

Estados posibles del resultado de una edición: `COMMITTED`, `VALIDATED` (dry run),
`REJECTED`, `CLARIFICATION_REQUIRED`, `CONFLICT`, `NO_CHANGES`, `INTERPRETATION_FAILED`,
`REPLAYED`. Ninguno de los estados sin versión deja rastro en el grafo; todos quedan en el
ledger.

## 5. Pruebas y resultados

| comprobación | resultado |
| --- | --- |
| Suite completa (antes) | 377 tests · 375 passed · 0 failed · 2 skipped |
| Suite completa (después) | **450 tests · 447 passed · 0 failed · 3 skipped** |
| `tests/unit/test_021_evidence_authority.py` (nuevo) | 26 tests: identidad MAPU, autoridad de la cita, desambiguación por contexto, SOURCE_UNIT, polaridad UNKNOWN, modalidad/atribución, v1+v2, lector de compatibilidad, agregado inválido sobre árbol válido, invariantes de procedencia (`DOCUMENT_REFERENCE`) |
| `tests/editing/test_022_graph_edit.py` (nuevo) | 22 tests: los diez casos exigidos + procedencia, aislamiento de OpenViking, dry run, no-JSON, base obsoleta, `expected` parcial, identidad sin consumo |
| `tests/editing/test_023_versioning.py` (nuevo) | 7 tests: reconstrucción de v1/v2/v3, mapeo ANTÜ→versión, diffs, concurrencia, interrupción + recuperación |
| `tests/integration/test_document_path_artifacts.py` (nuevo) | 9 tests sobre los artefactos reales del experimento 09 + perfil de dominio del acta |
| `tests/integration/test_two_paths.py` (nuevo) | 5 tests de clasificación, aislamiento y ANTÜ de dos etapas |
| `tests/integration/test_real_editor.py` (opt-in) | **ejecutada con un modelo real** (DeepSeek, 5 llamadas) — §7 |
| `scripts/verify_distribution.py` | **PASS** wheel y sdist × Python 3.11 y 3.13 (`evidence/distribution_verification.json`) |
| Instalación del wheel en venv limpio | API pública nueva presente y funcional |
| Pruebas de idempotencia | repetir un ANTÜ devuelve `REPLAYED`, sin versión nueva |
| Prueba de concurrencia | una edición calculada sobre una versión que avanzó → `CONFLICT`/`STALE_BASE`, nada escrito |
| Prueba de recuperación | interrupción tras el manifest → versión publicada sin revisión de unidad, `recover()` la reconcilia, `verify()` sano |
| Ausencia de versiones parciales | ninguna operación inválida produce versión |

Los logs están en `logs/suite_before.*`, `logs/suite_after.*` y `logs/distribution.log`.

### Qué se cambió en pruebas existentes y por qué

* `tests/unit/test_014_materializer.py::test_invalid_offsets_are_not_silently_fixed` se
  sustituyó por `test_declared_offsets_never_override_the_quote` (más
  `test_a_quote_that_does_not_exist_is_still_rejected`). El comportamiento exigido por §5.2
  es que la cita verificable tenga autoridad; el test conserva su propósito (nada se
  corrige en silencio) y añade la comprobación de que el desacuerdo queda registrado y de
  que una cita inexistente sigue rechazándose.
* Fixtures que sólo necesitaban declarar la polaridad que antes heredaban del default
  (`test_013_coverage`, `test_011_contract`, `test_019`, `test_evidence_and_coverage`): se
  les añadió `"polarity": "POSITIVE"`, igual que hizo `9a5e512`. No cambia lo que afirman.
* No se borró ninguna prueba y no se redujo cobertura.


## 6. Versiones canónicas producidas y diferencias

Memoria de control de la evidencia (`evidence/versions_and_diffs.json`):

| versión | kuyen_version | ANTÜ | entidades | afirmaciones |
| --- | --- | --- | --- | --- |
| `VER-3b63dcc70cbf` | 1.0.0 | `ANTU-FIXTURE-01` (documento) | 2 | 2 |
| `VER-1cc1d50fc685` | 1.1.0 | `ANTU-472f4b419473bba3` | 2 | 3 |
| `VER-3732d2925d8b` | 1.2.0 | `ANTU-34d6f65e382668ce` | 2 | 3 |
| `VER-4926159676d2` | 1.3.0 | `ANTU-03f87ada5bfc9883` | 3 | 3 |

Diferencias reproducibles (`memory.diff`):

* v1 → v2 (corrección de la cantidad): `added` 1 afirmación nueva, `modified`
  `status`+`superseded_by` de la anterior, `removed_from_current_view` la anterior,
  `deleted` **vacío**.
* v2 → v3 (retractación de la fecha): `added` vacío, `modified` `retracted`+`status`,
  `deleted` **vacío**.
* v3 → v4 (entidad nueva): `added` 1 entidad, sin modificaciones ni borrados.

Camino documental (`evidence/document_path_runs.json`) sobre los artefactos reales del
experimento 09:

| escenario | materializador | resultado |
| --- | --- | --- |
| tal como se produjo | 4 `MAPU_ID_NOT_IN_CONTEXT`, 7 `MAPU_RESOLVED_BY_CONTEXT`, 5 `QUOTE_AUTHORITATIVE`, 2 `INVALID_QUOTE` | **REJECTED** (`ENTITY_EVIDENCE_MISSING`), sin versión |
| identidad corregida | 7 `QUOTE_AUTHORITATIVE`, 4 `INVALID_QUOTE`, 7 `MAPU_RESOLVED_BY_CONTEXT` | **REJECTED**, sin versión |
| identidad + citas corregidas + ontología explícita | 11 `QUOTE_AUTHORITATIVE`, 0 rechazos | **COMMITTED**: 4 entidades, 3 relaciones, 4 afirmaciones, 7 evidencias, 1 SOURCE_UNIT |

En el escenario aceptado, las siete evidencias tienen `char_start`/`char_end` calculados
por KÜYEN (no los `0`/`len(quote)` declarados), `source_sha256` del MAPU real, y
`memory.trace()` resuelve afirmación → evidencia → SOURCE_UNIT → MAPU. La previsión
("espera instalar… antes del 10 de noviembre") queda con `modality: UNKNOWN` y
`status: UNRESOLVED`, nunca `FACT` ni `SOURCE_VERIFIED`.

## 7. Evidencia de inferencias reales

**Ejecutadas con un LLM real** (el entorno no tenía credenciales cargadas; el usuario las
proporcionó en `.env`, que está ignorado por git). Proveedor usado: **DeepSeek**
(`deepseek-chat`) vía su endpoint OpenAI-compatible, `temperature=0.0`, `max_tokens=2048`,
`response_format=json_object`, timeout 60 s. Una llamada por corrida, sin reintentos ni
ciclos: **5 llamadas en total** (todas con 2 701 tokens de prompt).

| # | código en ese momento | resultado | tokens salida |
| --- | --- | --- | --- |
| 1 | validador con `expected` exacto | `REJECTED` (`EXPECTED_VALUE_MISMATCH`) | 135 |
| 2 | tras aceptar `expected` parcial | `COMMITTED` → `VER-4f61e34376a3` | 127 |
| 3 | tras limpiar `_`-keys del registro | `COMMITTED` → `VER-d57814169944` | 127 |
| 4 | tras sacar el consumo del hash canónico | `COMMITTED` → `VER-23a9a1a23e39` | 127 |
| 5 | misma entrada, verificación de reproducibilidad | `COMMITTED` → **`VER-23a9a1a23e39`** (idéntica) | 127 |

La propuesta del modelo, en la corrida final (`evidence/real_model_inference.json`):

```json
{"status": "PROPOSED", "schema_version": "kuyen-graph-edit-v1", "operations": [{
  "op": "UPDATE_ASSERTION", "operation_id": "op-1",
  "target": {"assertion_id": "asrt_0677645136247624437d"},
  "expected": {"value": {"value": 12, "value_type": "integer"}},
  "value": {"value": {"value": 18, "value_type": "integer"}},
  "antu_ref": "Cambia la cantidad de luminarias instaladas de 12 a 18",
  "reason": "La instrucción corrige el valor de luminarias instaladas de 12 a 18."}]}
```

KÜYEN la validó y creó la versión `VER-23a9a1a23e39` sobre `VER-3b63dcc70cbf`.

Dos hallazgos reales, cada uno con su corrección y su prueba:

1. **`expected` exacto era demasiado frágil.** El modelo declaró `value` parcial
   (`{"value_type":"integer","value":12}`) frente al objeto almacenado que además lleva
   `unit` y `context`. KÜYEN rechazó una operación correcta. Decisión: para campos con
   objeto, **cada clave declarada debe coincidir**; un objeto vacío no cuenta como control
   (`tests/editing/test_022_graph_edit.py`, tres pruebas nuevas).
2. **El consumo entraba en el hash canónico.** `usage` viajaba en la procedencia, de modo
   que la identidad de la versión dependía de los tokens facturados (dos corridas con la
   misma propuesta producían versiones distintas). Decisión: el consumo se registra en el
   ledger y en el resultado, nunca en la procedencia versionada
   (`test_the_version_identity_does_not_depend_on_token_metering`). Con eso, la corrida 5
   reprodujo **exactamente** el `version_id` de la corrida 4.

Reproducibilidad sin modelo (`evidence/replay_determinism.json`): la misma propuesta grabada
repetida dos veces sobre la misma base produce el mismo `version_id` y el mismo
`canonical_graph_hash`.

**OpenViking:** `openviking==0.5.3` es instalable desde PyPI y la instalación se intentó en
este entorno (ver §11). La compilación real con su Skill se documenta abajo con su estado
final.

## 8. Compilación real con OpenViking 0.5.0 (Caso A)

El entorno sí tenía una instalación real de OpenViking: `~/.venvs/openviking` con
**0.5.0** y varias instancias del usuario en 19660/19661/19664/19666/19667. No se tocó
ninguna. Se arrancó una **instancia aislada propia** (`127.0.0.1:19700`, VikingBot en 19701,
raíz en `/tmp/kuyen11_ov3`, VLM `openai/gpt-4o-mini`, embeddings
`openai/text-embedding-3-small`, credenciales por referencia `${KUYEN_VLM_API_KEY}` desde el
entorno del hijo), se apagó al terminar y no quedó ningún proceso abierto.

Se ejecutaron **8 compilaciones reales** del documento FTG08 con la Skill real. Cada una
midió un defecto y motivó una corrección (todas con prueba):

| # | qué cambió | resultado |
| --- | --- | --- |
| 1 | instrucción que pedía `kuyen_result.json` | `CANDIDATE_MATERIALIZATION_FAILED`: el agregado salió con JSON inválido y bloqueó un árbol nativo válido |
| 2 | se pide el **árbol nativo** (`entities/*.md`, `relations.jsonl`, `assertions.jsonl`) y se prohíbe el agregado | 8/8 citas parafraseadas + `PREDICATE_NOT_ALLOWED` |
| 3 | (defecto del arnés: MAPU reutilizado) | el agente no pudo leer el recurso |
| 4 | predicado nativo declarado en relaciones → `UNMAPPED` con WARNING | quedó el vocabulario **escalar** fuera del perfil (`SCALAR_PREDICATE_UNKNOWN`) |
| 5 | misma política para escalares (`SCALAR_PREDICATE_PRESERVED_UNMAPPED`) | dos citas parafraseadas bajo política estricta |
| 6 | perfil de dominio con tipos de entidad del documento | el agente usó `location`, fuera del perfil |
| 7 | origen `DOCUMENT_REFERENCE` para objeto sin cita verificada | el invariante `ORIGIN_DOCUMENT_WITHOUT_EVIDENCE` rechazó el commit |
| 8 | perfil de dominio completo + `evidence_policy: document` | **`COMMITTED` → `VER-7a5acc125b47`** |

Resultado de la corrida 8 (`evidence/real_openviking_version.json`):

| Métrica | Valor |
| --- | --- |
| versión | `VER-7a5acc125b47` (primera versión, sin padre) |
| entidades / relaciones / afirmaciones | 5 / 4 / 4 |
| evidencia | **9**, todas localizadas por cotización única (`llm_offset_resolved_unique`) |
| cobertura | 1 unidad `PROCESSED_WITH_OUTPUT` |
| integridad | `verify().ok = true` |
| origen de relaciones | `DOCUMENT_EVIDENCE` (cita verificada) y `DOCUMENT_REFERENCE` (sin cita verificada) |
| origen de afirmaciones | `DOCUMENT_EVIDENCE` |

Las cuatro afirmaciones son de cantidad (12 instaladas, 9 operativas, 3 inoperativas, 6
restantes) con `modality: FACT` **declarada por el productor** y predicado nativo preservado
como `UNMAPPED`.

Consumo real medido de las 8 compilaciones: **1 588 856 tokens de entrada** (1 483 520
en caché) y ~22 000 de salida. La ruta completa (ingerir → compilar con la Skill →
materializar bajo autoridad de la cotización → compuerta → commit canónico) queda demostrada
con el motor real.

## 9. Limitaciones (medidas, no supuestas)

1. **El productor no garantiza citas literales.** En las corridas 2, 4, 5 y 6 el agente
   reescribió total o parcialmente alguna cotización (puntuación alterada, mayúscula
   inicial, resumen). KÜYEN las rechaza con `INVALID_QUOTE`; con política `document` las
   conserva como `DOCUMENT_REFERENCE` sin verificación, que es lo que registra la versión 8.
   La corrección pertenece al productor (la instrucción ya exige copia literal).
2. **El vocabulario del productor no es estable entre corridas**: `has_agreement` en la
   corrida 2, `firmó_acuerdo` en la 4, `connects`/`executes` en la 6. Por eso KÜYEN preserva
   el término declarado con `UNMAPPED` + WARNING y el operador decide el mapeo: la
   alternativa (un léxico abierto) convertiría la ontología en una lista infinita.
3. **El perfil `generic-v1` no cubre el acta real** (tipos `location`, predicados de
   cantidad). La corrida 8 usa un perfil de dominio declarado en el arnés del experimento; la
   ontología publicada no se tocó.
4. **`value_type: integer` con el valor como cadena** en los artefactos del productor: KÜYEN
   conserva el literal declarado y no lo convierte en silencio.
5. **La proyección nativa no representa retractaciones ni supersesiones**: el almacén
   canónico es la autoridad y conserva todo; el árbol proyectado muestra el estado del
   productor y es regenerable.
6. **El contexto por palabras clave puede no incluir el objetivo** de una instrucción con
   vocabulario inesperado; en ese caso la operación se rechaza con `TARGET_NOT_IN_CONTEXT`
   (explícito) en vez de aplicarse sobre un objeto no autorizado. Para grafos ≤200 objetos se
   envía el índice completo.
7. **Un ANTÜ directo no puede citar evidencia documental nueva**: no hay documento. Sí
   conserva la evidencia de la afirmación anterior mediante `supersedes`.
8. **`apply_antu` mantiene el lock sólo durante la validación y el commit**; dos
   interpretaciones concurrentes del mismo texto producen un `REPLAYED` y un `STALE_BASE`
   deterministas, no una fusión.
9. **Sin fusión ni rebase**: un commit obsoleto se rechaza siempre; el usuario debe reevaluar.

## 10. Hashes de artefactos

Ver `MANIFEST.json` (sha256 de cada archivo de `evidence/` y `logs/`).

## 11. Commits locales

| commit | contenido |
| --- | --- |
| `c6c398c` | `fix(evidence)`: identidad MAPU, autoridad de la cita, polaridad sin default, `kuyen-provider-result-v2`, `read_candidate` sin duplicación, `test_021` |
| `ea5c87d` | `feat(semantics)`: procedencia explícita (`origin`), invariantes en `validation/canonical.py`, origen documental en el normalizador |
| `92ca99f` | `feat(editing)`: editor de grafo por ANTÜ, validador, aplicador, diff, `apply_antu`, `product`, pruebas de §8.2/§8.3 |
| `5f586fd` | `docs(experiment)`: contratos ES/EN, documentación actualizada, informe y evidencia |
| `f542db1` | estado de git final, hashes del manifiesto e imports de las pruebas de edición |
| `1e7319d` | corrección del ejemplo de uso y actualización del manifiesto |
| `32654f9` | recuentos exactos del trabajo previo conservado |
| `8240d97` | `editing`: `expected` parcial, identidad sin consumo, registro sin claves internas |
| `866ea0f` | `documento`: árbol nativo, predicado declarado preservado, origen `DOCUMENT_REFERENCE` |
| `152cbc7` | `experimento`: inferencias reales y compilación real, manifiesto y estado de git |
| `cfe8884` | `docs(experiment)`: recuentos finales y manifiesto rehasheado |

La lista autoritativa es `git log --oneline 9a5e512..HEAD`; `git_state_final.txt` se capturó antes del último commit; el estado final es el que
muestra la lista autoritativa. El commit que cierra esta documentación no se lista a sí
mismo: `git log --oneline 9a5e512..HEAD` es la fuente.

`b6ad5fc` y `9a5e512` permanecen intactos en la historia.

**Trabajo previo que viaja en los commits nuevos (declarado, no oculto).** Los archivos
`src/kuyen/api/memory.py`, `src/kuyen/lifecycle/antu.py`, `src/kuyen/lifecycle/ledger.py` y
`src/kuyen/__init__.py` ya estaban modificados (sin commit) por el usuario antes de esta
sesión, y las modificaciones nuevas **dependen** de ese estado (tipos de evento del ledger,
recuperación, endurecimiento del paquete). No son separables hunk a hunk sin operaciones git
destructivas, así que se incluyeron y aquí se deja constancia. En
`src/kuyen/adapters/openviking.py` sí se separó: el commit `c6c398c` contiene **sólo** el
cambio de `read_candidate` y la modificación previa de `compile()` sigue sin commitear.
Del estado inicial (30 modificados, 38 sin rastrear) quedan **20 modificados y 37 sin
rastrear** fuera de estos commits: los otros nueve archivos modificados se commitearon
porque la funcionalidad nueva vive dentro de ellos (ver la lista de arriba), y
`validation/canonical.py` se convirtió en un archivo nuevo versionado. Nada se perdió ni se
restauró.

## 12. Estado del push final

**No se hizo push todavía.** El criterio del encargo —publicar sólo cuando ambos flujos
reales estén demostrados— se cumple ahora por primera vez:

* **Caso B (ANTÜ + LLM real): DEMOSTRADO.** 5 inferencias reales con `deepseek-chat`; la
  corrida 5 reprodujo exactamente el `version_id` de la corrida 4 (idempotencia medida, no
  supuesta) — §7.
* **Caso A (OpenViking 0.5.0 + Skill real): DEMOSTRADO.** Corrida 8: versión canónica
  `VER-7a5acc125b47`, 5 entidades, 4 relaciones, 4 afirmaciones, 9 citas localizadas, 1
  unidad de cobertura `PROCESSED_WITH_OUTPUT`, `verify().ok = true` — §8.

Lo que queda antes de publicar es verificación de estado, no trabajo pendiente:

```bash
# 1. suite completa y distribución: 450 pruebas, 447 pasan, 3 opt-in saltadas
python -m pytest -q tests/
python -m build && python -m twine check dist/*

# 2. historia local, sin secretos
git log --oneline 9a5e512..HEAD          # los commits de este trabajo (ver §11)
git diff 9a5e512..HEAD --stat | tail -1
git diff 9a5e512..HEAD | grep -nE '(sk|xoxb)-[[:alnum:]_-]{16,}|_API_KEY=.' \
  && echo 'SECRETO ENCONTRADO: no publicar' || echo 'sin secretos'
# 3. publicar (nunca --force)
git push -u origin work/kuyen-free-text-graph
```

Si el remoto tuviera commits divergentes el push se detiene y se informa: no se reescribe
historia ajena.

