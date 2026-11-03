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
| HEAD | `9a5e512` (con `b6ad5fc` en la historia) | `9a5e512` + 4 commits locales |
| Remoto / upstream | `origin` `https://github.com/mapu-kuyen/kuyen.git` · **sin upstream** | igual |
| Modificados / sin rastrear | 30 / 38 (verificado, coincide con el reporte previo) | ver §10 |
| Suite | 377 tests · 375 passed · 2 skipped · 0 failed | **438 tests · 435 passed · 3 skipped · 0 failed** |
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
| Suite completa (después) | **438 tests · 435 passed · 0 failed · 3 skipped** |
| `tests/unit/test_021_evidence_authority.py` (nuevo) | 20 tests: identidad MAPU, autoridad de la cita, desambiguación por contexto, SOURCE_UNIT, polaridad UNKNOWN, modalidad/atribución, v1+v2, lector de compatibilidad |
| `tests/editing/test_022_graph_edit.py` (nuevo) | 18 tests: los diez casos de §8.2 + procedencia, aislamiento de OpenViking, dry run, no-JSON, base obsoleta |
| `tests/editing/test_023_versioning.py` (nuevo) | 7 tests: reconstrucción de v1/v2/v3, mapeo ANTÜ→versión, diffs, concurrencia, interrupción + recuperación |
| `tests/integration/test_document_path_artifacts.py` (nuevo) | 9 tests sobre los artefactos reales del experimento 09 |
| `tests/integration/test_two_paths.py` (nuevo) | 5 tests de clasificación, aislamiento y ANTÜ de dos etapas |
| `tests/integration/test_real_editor.py` (nuevo, opt-in) | **skipped** (`KUYEN_RUN_REAL_MODEL` no configurado) |
| `scripts/verify_distribution.py` | **PASS** wheel y sdist × Python 3.11 y 3.13 |
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

**No ejecutadas.** Comprobaciones realizadas en este entorno:

| comprobación | resultado |
| --- | --- |
| Credenciales de proveedor en el entorno | **ninguna** (`OPENAI_*`, `ANTHROPIC_*`, `GEMINI_*`, `*_API_KEY` vacío) |
| OpenViking escuchando en `127.0.0.1:1933` | **no** (`curl` → `Connection refused`) |
| Paquete `openviking` instalado | **no** |
| Docker disponible | **no** |
| Inferencias ejecutadas | **0** |
| Créditos consumidos | **0** |

Lo que sí está hecho y es verificable sin red:

* `OpenAICompatibleGraphEditor` implementado y probado en su contrato (configuración,
  ausencia de credencial → `EDITOR_CREDENTIAL_UNAVAILABLE`, sin fallback);
* `tests/integration/test_real_editor.py` listo para ejecutarse con
  `KUYEN_RUN_REAL_MODEL=1` y escribe `evidence/real_model_inference.json` con proveedor,
  modelo, parámetros, propuesta, resultado y consumo cuando el proveedor lo informa;
* el camino documental real ya fue ejecutado en el experimento 08/09 con OpenViking 0.5.2.1
  y su Skill real; esta sesión **reutiliza esos artefactos** en lugar de simularlos.


## 8. Limitaciones (medidas, no supuestas)

1. **Integraciones reales no ejecutadas** en este entorno (sin servidor OpenViking y sin
   credenciales de proveedor). Ambas rutas están implementadas y con prueba opt-in.
2. **El perfil `generic-v1` no cubre los predicados del acta** (`contracted`, `supervises`,
   `complaint`, `has_installed_lights`, …). Sin extenderlo, el documento real se rechaza en
   la frontera ontológica — comportamiento correcto, pero bloquea la admisión. La prueba
   usa una ontología extendida **en el test**; la ontología publicada no se tocó.
3. **El modelo del experimento 08 reescribió dos citas** (una de ellas la previsión): KÜYEN
   las rechaza como `INVALID_QUOTE`. Sin corregirlas no hay versión. Es un hallazgo sobre el
   productor, no un defecto de KÜYEN.
4. **`value_type: integer` con el valor como cadena** en los artefactos reales: KÜYEN
   conserva el literal declarado y no lo convierte en silencio (de ahí `"12"`).
5. **La proyección nativa no representa retractaciones ni supersesiones**: el almacén
   canónico es la autoridad y conserva todo, pero el árbol proyectado sigue mostrando el
   estado del productor. La proyección es subordinada y regenerable.
6. **El contexto por palabras clave puede no incluir el objetivo** de una instrucción con
   vocabulario inesperado; en ese caso la operación se rechaza con `TARGET_NOT_IN_CONTEXT`
   (explícito) en vez de aplicarse sobre un objeto no autorizado. Para grafos ≤200 objetos
   se envía el índice completo.
7. **Un ANTÜ directo no puede citar evidencia documental nueva**: no hay documento. Sí
   conserva la evidencia de la afirmación anterior mediante `supersedes`.
8. **`apply_antu` mantiene el lock sólo durante la validación y el commit**; dos
   interpretaciones concurrentes del mismo texto producen un `REPLAYED` y un `STALE_BASE`
   deterministas, no una fusión.
9. **Sin fusión ni rebase**: un commit obsoleto se rechaza siempre; el usuario debe reevaluar.

## 9. Hashes de artefactos

Ver `MANIFEST.json` (sha256 de cada archivo de `evidence/` y `logs/`).

## 10. Commits locales

| commit | contenido |
| --- | --- |
| `c6c398c` | `fix(evidence)`: identidad MAPU, autoridad de la cita, polaridad sin default, `kuyen-provider-result-v2`, `read_candidate` sin duplicación, `test_021` |
| `ea5c87d` | `feat(semantics)`: procedencia explícita (`origin`), invariantes en `validation/canonical.py`, origen documental en el normalizador |
| `92ca99f` | `feat(editing)`: editor de grafo por ANTÜ, validador, aplicador, diff, `apply_antu`, `product`, pruebas de §8.2/§8.3 |
| `5f586fd` | `docs(experiment)`: contratos ES/EN, documentación actualizada, informe y evidencia |
| `f542db1` | estado de git final, hashes del manifiesto e imports de las pruebas de edición |
| `1e7319d` | corrección del ejemplo de uso y actualización del manifiesto |

La lista autoritativa es `git log --oneline 9a5e512..HEAD`; `git_state_final.txt` se capturó
inmediatamente antes del commit de cierre.

`b6ad5fc` y `9a5e512` permanecen intactos en la historia.

**Trabajo previo que viaja en los commits nuevos (declarado, no oculto).** Los archivos
`src/kuyen/api/memory.py`, `src/kuyen/lifecycle/antu.py`, `src/kuyen/lifecycle/ledger.py` y
`src/kuyen/__init__.py` ya estaban modificados (sin commit) por el usuario antes de esta
sesión, y las modificaciones nuevas **dependen** de ese estado (tipos de evento del ledger,
recuperación, endurecimiento del paquete). No son separables hunk a hunk sin operaciones git
destructivas, así que se incluyeron y aquí se deja constancia. En
`src/kuyen/adapters/openviking.py` sí se separó: el commit `c6c398c` contiene **sólo** el
cambio de `read_candidate` y la modificación previa de `compile()` sigue sin commitear.
Los 30 archivos modificados y 38 sin rastrear del estado inicial siguen presentes.

## 11. Estado del push final

**No se hizo push.** Criterio del encargo: publicar sólo cuando ambos flujos estén
demostrados. El Camino B está demostrado de forma determinista y completa; el Camino A está
demostrado sobre los artefactos reales del Skill, pero **la compilación real con OpenViking
0.5.x no pudo ejecutarse en este entorno** y la prueba de inferencia real con LLM está
`skipped`. Publicar ahora declararía una capacidad que no se verificó aquí.

Para completar el push cuando el entorno esté disponible:

```bash
# 1. con OpenViking 0.5.x y su Skill real
KUYEN_RUN_OPENVIKING=1 python -m pytest tests/integration/test_openviking_real.py -q
# 2. con un proveedor real
KUYEN_RUN_REAL_MODEL=1 KUYEN_EDITOR_MODEL=... KUYEN_EDITOR_API_KEY_ENV=... \
  python -m pytest tests/integration/test_real_editor.py -q
# 3. rama limpia y publicada
git log --oneline 9a5e512..HEAD
git push -u origin work/kuyen-free-text-graph   # nunca --force
```

