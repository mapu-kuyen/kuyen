# KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17

**Resultado: el producto ya está en Git y publicado.** Once commits convierten el historial en
algo que se clona, se instala, se ejecuta y pasa su propia CI:

```
git clone --branch work/kuyen-free-text-graph → 0.3.0 · 40 nombres públicos · working tree limpio
pytest desde el clon (3.13)                   → 527 passed, 3 skipped, 0 failed
pytest del mismo árbol (3.10)                 → 526 passed, 4 skipped, 0 failed
wheel 0.3.0 (111 archivos) + sdist (162)      → twine PASSED · 3.11 y 3.13 · pip check ok
quickstart desde la wheel instalada           → 2 versiones, evidencia, backup, restore, verify
verify_distribution.py                        → all_passed=True results=4
CI de la rama en GitHub                       → success (6/6 jobs: 3.10, 3.11, 3.12, 3.13, artefactos, higiene)
```

La auditoría 16 decía `NOT_READY` y tenía razón: el `git clone` no importaba. Ahora importa, y la
autoridad del producto es Git: **0 archivos rastreados quedan modificados** en el workspace.

---

## 1. Estado inicial

| dato | valor |
| --- | --- |
| raíz | `/private/tmp/kuyen_hardening_01/kuyen` |
| rama | `work/kuyen-free-text-graph` |
| HEAD inicial | `71e37c46a6c248cb2427ee3b6f5b1211b1e950d1` (`71e37c4`, el commit de la auditoría 16) |
| remoto | `origin` → `https://github.com/mapu-kuyen/kuyen.git` |
| upstream de la rama | ninguno |
| `origin/main` | `5fd8777` («Release KÜYEN 0.2.0»), sin cambios |
| ramas remotas | sólo `main` |
| staged | nada |
| modificados | 27 · no rastreados: 42 · **total 69** |
| `VERSION` | `0.2.1rc1` en el árbol, `0.2.0` en HEAD |
| artefactos 13/14/15 | 712 archivos, hash verificado: **intactos** |

La verificación previa se hizo contra el manifiesto de la auditoría 16
(`experiments/KUYEN_PRODUCTION_READINESS_16/evidence/working_tree_sha256.json`): los **894**
archivos pendientes y los **712** artefactos de los experimentos 13, 14 y 15 conservaban su
SHA-256. El inventario de la auditoría 16 seguía siendo exacto (4 módulos ausentes, 17 módulos
desactualizados, `VERSION` desalineado).

`evidence/pre_intervention_sha256.json` conserva el hash de los 56 archivos del producto tal como
estaban antes de intervenir; `evidence/state_initial` de la auditoría 16 sigue siendo la
referencia de la parte de experimentos.

## 2. Inventario de pendientes y clasificación

| grupo | elementos | decisión |
| --- | --- | --- |
| módulos ausentes (`provenance`, `semantics/schema`, `semantics/scope`, `vlm`) | 4 | **incorporados** (commit 1) |
| módulos rastreados desactualizados | 17 | **16 incorporados** (commits 2–3); `engine.py` también, con nota |
| suites nuevas de prueba | 22 módulos + `projection_helpers.py` + `test_source_unit_disambiguation.py` | **incorporadas** (commit 4) |
| pruebas modificadas | 4 | **incorporadas** (commit 4) |
| documentación de producto y auditorías | 3 guías + `docs/reports/` (5 informes) + 3 documentos raíz | **incorporada** (commit 5) |
| quickstart ejecutable y su prueba | `examples/quickstart.py`, `tests/examples/` | **incorporados** (commit 5) |
| distribución | `MANIFEST.in`, `scripts/verify_distribution.py`, `pyproject.toml` | **incorporados** (commit 6) |
| evidencia que leen las suites publicadas | 7 archivos de los experimentos 08 y 09 | **incorporados** (commit 7) |
| versión y changelog | `VERSION`, `CHANGELOG.md`, marcadores `0.2.1` de 5 documentos | **incorporados** (commit 8) |
| informes y artefactos de los experimentos 02, 03, 05, 07, 08, 09, 10, 12, 13 | 10 directorios | **fuera de la rama** |
| este experimento (17) | 1 directorio | commit propio, sólo el informe |

## 3. Matriz de dependencia (evidencia empírica, no supuesta)

Para cada uno de los 17 módulos desactualizados se construyó una copia del árbol funcional, se
revirtió **ese único archivo** a su versión de HEAD y se midió el import y la suite completa
(`evidence/necessity_matrix.json`, `evidence/necessity_matrix.log`):

| módulo | revertido a HEAD | necesario |
| --- | --- | --- |
| `adapters/openviking.py` | falla `test_013_ingestion` | sí |
| `backup/archive.py` | falla la suite (restore) | sí |
| `canonical.py` | **no importa** (`read_last_line`) | sí |
| `editing/context.py` | falla la suite (aplicabilidad) | sí |
| `engine.py` | importa y pasa la suite | **no por tests** (ver commit 3) |
| `errors.py` | **no importa** (`AmbiguousSourceUnit`) | sí |
| `ingest.py` | falla la suite (SOURCE_UNIT) | sí |
| `lifecycle/antu.py` | falla la suite | sí |
| `lifecycle/unit.py` | **no importa** (`reconcile_unit_history`) | sí |
| `product.py` | falla la suite | sí |
| `projection/native.py` | falla la suite | sí |
| `projection/openviking.py` | falla la suite | sí |
| `projection/outbox.py` | **no importa** (`claim`) | sí |
| `semantics`/`sidecar/__init__.py` | falla la suite | sí |
| `storage/commit.py` | **no importa** (`prepare_commit_artifacts`) | sí |
| `storage/registry.py` | falla la suite | sí |
| `storage/store.py` | falla la suite | sí |

**16 de 17** son necesarios por import o por suite. `engine.py` no lo es: su único cambio
pendiente añade el `title` del MAPU a la instrucción de compilación que se envía a OpenViking, y
ninguna prueba determinista inspecciona esa cadena. Se incorporó igualmente porque forma parte del
flujo documental validado en los experimentos 01–05: excluirlo publicaría un compilador distinto
del que produjo los diez KÜYEN reales. Es la única incorporación que no está cubierta por un test,
y se dice aquí en lugar de dejarla implícita.

## 4. Los commits (estructura finalmente adoptada: 11)

La separación prevista eran siete commits. La realidad impuso cuatro más, y ninguno se hizo para
"llegar al número":

* el **7** porque la reconstrucción limpia demostró que las pruebas publicadas leen artefactos de
  OpenViking que no estaban en Git (11 fallos en el clon del commit 6);
* los **9, 10 y 11** porque la primera ejecución real de CI encontró un defecto de portabilidad en
  Python 3.10 y un paso de CI que nunca había podido pasar.

| # | commit | asunto | archivos | +/− |
| --- | --- | --- | --- | --- |
| 1 | `71d882c` | fix(package): add the four modules the published history imports | 4 | +927 |
| 2 | `25da16b` | fix(domain): publish the corrections the engine and storage already use | 12 | +773 −114 |
| 3 | `9de0be5` | fix(product): align the document flow and the Antü context with the tested code | 5 | +123 −20 |
| 4 | `394bae3` | test: publish the suites that prove what the history now contains | 27 | +4214 −2 |
| 5 | `31d5da6` | docs: publish the VLM, quickstart and source-unit guides and the quickstart itself | 13 | +3747 −78 |
| 6 | `e854e1c` | build: ship the manifest and the distribution verifier, and fix the build floor | 3 | +250 −2 |
| 7 | `2d3fd09` | test: publish the real provider artefacts the document-path suite reads | 8 | +100 |
| 8 | `485c423` | release: align the version to 0.3.0 | 7 | +22 −13 |
| 9 | `df65a03` | fix(config): keep the package importable on Python 3.10 | 2 | +23 −3 |
| 10 | `5c88002` | ci(hygiene): give the version check the import it needs | 1 | +7 |
| 11 | `c98a289` | ci(hygiene): install the runtime dependencies the import needs | 1 | +2 −2 |

Cada commit se preparó con `git add` de rutas explícitas (nunca `git add -A`), se revisó con
`git diff --cached`, y `git diff --cached --check` quedó en **0** en los once. El duodécimo commit
de la rama es este informe; la rama queda 40 commits por delante de `origin/main`.


### 4.1 Commit 1 — módulos fundamentales

`semantics/schema.py` (contrato versionado de tipos y campos, incluidas las declaraciones de
esquema por Antü), `semantics/scope.py` (permisos efectivos que filtran el contexto y autorizan
cada operación), `provenance.py` (lectura de la fuente y registro `text_only`), `vlm.py`
(configuración del proveedor VLM/embeddings de OpenViking). Único retoque: se eliminó la línea en
blanco final de tres archivos para que `git diff --check` fuera limpio; sin cambio de
comportamiento.

Tras este commit el paquete **todavía no importa**: falta `errors.AmbiguousSourceUnit`, que llega
en el commit 2. Se dice explícitamente porque quien haga checkout de ese commit verá un error de
import; la cadena se cierra en el commit 2, y así se comprobó (`import kuyen` → ok tras su
staging).

### 4.2 Commit 2 — correcciones de dominio

`errors.py` (`AmbiguousSourceUnit`, `OpenAIConfigurationError`), `canonical.py` (`temporary_name`,
`read_last_line`, `iter_lines_reverse`: leer el final del ledger en vez de recorrerlo),
`lifecycle/unit.py` (`reconcile_unit_history`, `published_versions`, `uncovered_versions`),
`lifecycle/antu.py`, `storage/commit.py` (`prepare_commit_artifacts`, `classify_staging`,
`_require_expected_base`), `storage/store.py`, `storage/registry.py`, `projection/outbox.py`
(`claim`, `release_interrupted`), `projection/native.py`, `projection/openviking.py`,
`backup/archive.py` (`_reject_unsafe_target`, `_reject_unsafe_restore_target`,
`_remove_children`), `sidecar/__init__.py`.

### 4.3 Commit 3 — producto y edición ANTÜ

`editing/context.py` (el contexto lleva el esquema visible y las capacidades efectivas, filtrados
por el ámbito antes de existir), `product.py`, `ingest.py`, `adapters/openviking.py`, `engine.py`.

Las capacidades de edición que la tarea pide confirmar (contratos, operaciones, vocabulario de
outcome, actualizaciones parciales, entidad, atributo, relación, esquema, aplicación y
versionamiento) ya estaban en la historia desde los commits `d565f00`, `a6bc996` y `951b1ba` del
experimento 15; lo que faltaba era que el contexto que las alimenta fuera el probado, y eso se
cierra aquí.

### 4.4 Commit 4 — pruebas

22 módulos nuevos (ledger M1/M2/M6, límites de transacción, clasificación de staging,
reconciliación, procedencia de fuente, proyección, detección de manipulación, contención de
identificadores, backup/restore, aplicabilidad distribuida, contrato de Antü, VLM, canónico,
SOURCE_UNIT) más `tests/projection_helpers.py`, `tests/test_source_unit_disambiguation.py` y las 4
modificaciones necesarias. **32 → 55 módulos de prueba**. Ninguna expectativa se relajó: la suite
da el mismo resultado que el workspace.

### 4.5 Commit 5 — documentación y quickstart

`docs/KUYEN_OPENVIKING_VLM_CONFIGURATION_05.md` (única guía de `VlmProviderConfig`, la
indirección de credenciales y la corrección del endpoint de embeddings),
`docs/KUYEN_RELEASE_QUICKSTART_REPAIR_02.md`, `docs/KUYEN_SOURCE_UNIT_DISAMBIGUATION_03.md`,
`docs/reports/` (5 informes de endurecimiento que justifican el commit 2),
`BACKUP_AND_RECOVERY.md`, `SECURITY.md`, `SIDECAR.md` (documentan las reglas de destino de
restauración, la procedencia de fuente y los hashes de bytes/texto que el código aplica) y el
quickstart ejecutable con su prueba.


### 4.6 Commit 6 — distribución

`scripts/verify_distribution.py` (construye, instala en entornos desechables y ejecuta el
quickstart desde fuera del repositorio), `MANIFEST.in`, y las dos correcciones de `pyproject.toml`
que el propio build necesita: `setuptools>=77.0.1` (primera versión que acepta la expresión PEP 639
de `license` y `license-files` que el archivo ya declaraba) y `[dev]` con `httpx` y `pytest-cov`,
sin los cuales `pip install -e ".[dev]"` deja un entorno donde pytest no colecciona y el comando
de cobertura documentado no tiene plugin.

### 4.7 Commit 7 — la evidencia real que leen las suites

El clon del commit 6 fallaba **11 pruebas**: `tests/integration/test_document_path_artifacts.py`
(y `test_two_paths.py` a través de él) leen los artefactos que el Skill `knowledge-graph` escribió
en el experimento 09 y el documento fuente del experimento 08. Se publicaron **7 archivos** —
cuatro documentos de concepto, `assertions.jsonl`, `relations.jsonl` y la fuente de 1 692 bytes— y
nada más de esos experimentos. Una prueba que no puede ejecutarse desde un clon no es una prueba
del producto, y cambiarla para que se saltara habría escondido el hueco.

`.gitattributes` declara `experiments/**/evidence/** -whitespace`: los espacios finales de un
artefacto de proveedor son parte de lo que verifican las citas y los offsets, así que no se
normalizan (misma regla que ya existía para `*.patch`).

### 4.8 Commit 8 — versión

`VERSION` → `0.3.0`; `CHANGELOG.md` con una sección `0.3.0` que absorbe las cuatro secciones que
seguían marcadas *Unreleased* (`0.2.1rc1` queda como el candidato no publicado que fue); los
marcadores de capacidad que decían `0.2.1` pasan a `0.3.0` en `ARCHITECTURE.md`, `DATA_MODEL.md`,
`PUBLIC_API.md` y los dos `PRODUCT_MAPU_KUYEN_ANTU`.

### 4.9 Commit 9 — Python 3.10

La primera ejecución de CI sobre la rama recién publicada dio **cinco jobs bien y dos mal**. Uno de
los dos era un defecto real del producto: `config.py` importaba `tomllib` en la cabecera del
módulo, `tomllib` es de 3.11, y `pyproject.toml` declara `requires-python = ">=3.10"` con 3.10 en
los classifiers y en la matriz de CI. En 3.10 el paquete entero era **no importable** y la suite
moria antes de coleccionar.

Ahora la lectura TOML es opcional: el import va protegido y pedir una configuración TOML en un
intérprete sin `tomllib` lanza una explicación (`TOML_UNAVAILABLE`) en vez de romper el import;
`KuyenConfig.from_mapping()`, que es la vía programática documentada, sigue funcionando en 3.10.
La prueba que leía `pyproject.toml` con `tomllib` se salta en esos intérpretes (de ahí el cuarto
skip en 3.10). Verificado con CPython 3.10.16 y 3.13.1: **526 passed / 4 skipped** y **527 passed /
3 skipped**.

### 4.10 y 4.11 Commits 10 y 11 — el paso de CI que nunca pudo pasar

El otro job rojo era `secrets and metadata`, en el paso `version agrees`:

```
python -c "import kuyen; assert kuyen.__version__ == open('VERSION').read().strip()"
```

El proyecto usa *src layout* y ese job no instalaba el paquete, así que `import kuyen` no podía
funcionar **nunca**: es una de las dos causas del rojo histórico de `main`@`5fd8777`. El commit 10
añade el `pip install -e .` que faltaba y el 11 corrige el primer intento (`--no-deps` dejaba el
import sin `PyYAML`, reproducido en un venv limpio). **La aserción no se tocó**: sigue siendo la
misma línea, y sigue fallando si `VERSION` y `kuyen.__version__` no coinciden. No se saltó ningún
paso, no se marcó nada como no bloqueante y no se cambió la matriz.

Con los dos commits, el workflow completo queda en **success** (§11).

## 5. Archivos preservados fuera de los commits

Siguen sin rastrear, intactos:

```
experiments/KUYEN_DISTRIBUTED_ANTU_APPLICABILITY_12/   experiments/KUYEN_OPENVIKING_LUNA_SMOKE_07/
experiments/KUYEN_EXPLICIT_POLARITY_FIXTURES_10/      experiments/KUYEN_OPENVIKING_VLM_CONFIGURATION_05/
experiments/KUYEN_FREE_TEXT_TO_CANONICAL_GRAPH_08/    experiments/KUYEN_RELEASE_QUICKSTART_REPAIR_02/
experiments/KUYEN_NATIVE_GRAPH_CANDIDATE_09/          experiments/KUYEN_SOURCE_UNIT_DISAMBIGUATION_03/
experiments/KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13/
experiments/KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17/   (este informe)
```

De los directorios 08 y 09 sólo entró en Git, en el commit 7, la evidencia concreta que citan las
pruebas. Los informes, análisis, logs y manifiestos de esos experimentos —incluidos los 12 MB del
experimento 13— permanecen fuera de la rama publicada. Los experimentos 01, 11, 14 y 15 ya estaban
confirmados por sus propios commits y no se tocaron.

## 6. Reconstrucción limpia

No se usó un worktree (comparte el `.git` del original): se hizo un **clon real**, que es
exactamente lo que recibe un tercero.

```
$ git clone --branch work/kuyen-free-text-graph <repo> /tmp/kuyen17_clone
$ cd /tmp/kuyen17_clone && git status --porcelain | wc -l   →  0
$ env -u PYTHONPATH python3 -c 'import sys; sys.path.insert(0,"src"); import kuyen'
  → 0.3.0 · 40 nombres públicos
$ env -u PYTHONPATH python3 -m pytest tests/
  → 527 passed, 3 skipped in 26.06s          (exit 0)
```

Antes del commit 7 el mismo clon daba `11 failed, 516 passed, 3 skipped`; el detalle del fallo y
su causa están en §4.7. La reconstrucción se repitió **desde cero** después de cada corrección:
clon nuevo, no copia. Con el HEAD final (`c98a289`) se repitió una última vez, y también sobre
Python 3.10:

```
/tmp/kuyen17_verify  (clon de c98a289)
  py3.13.1 → 527 passed, 3 skipped        py3.10.16 → 526 passed, 4 skipped
  wheel + sdist → twine PASSED · verify_distribution → all_passed=True results=4
```

El cuarto skip de 3.10 es la prueba que lee `pyproject.toml` con `tomllib` (§4.9).

Pruebas por capacidad, todas ejecutadas en el clon:

| capacidad | evidencia (`editing/test_026`, `test_025`, …) |
| --- | --- |
| commit canónico, ledger, recovery, integridad | `storage/`, `lifecycle/test_m1_*`, `test_m2_*`, `test_m6_*`, `security/` |
| procedencia y evidencia | `unit/test_020`, `test_021`, `lifecycle/test_source_provenance` |
| MAPU y SOURCE_UNIT | `unit/test_013_*`, `test_source_unit_disambiguation` |
| adaptador OpenViking y VLM | `unit/test_adapter`, `unit/test_vlm_configuration`, `integration/test_openviking_real` (opt-in) |
| flujo documental con artefactos reales | `integration/test_document_path_artifacts` (7 pruebas) |
| edición ANTÜ: parciales, entidad, atributo, relación, esquema | `editing/test_025`, `test_026` (35 pruebas) |
| idempotencia, reconstrucción de versiones, outcome | `editing/test_023`, `test_026` |
| los dos flujos juntos | `integration/test_two_paths` |

Las 3 pruebas `SKIPPED` son las opt-in: `test_openviking_real` (necesita OpenViking vivo) y
`test_real_editor` (necesita `KUYEN_RUN_REAL_MODEL=1` y un proveedor configurado). No se gastó
ningún crédito de inferencia en esta tarea: los resultados con LLM real de los experimentos 13, 14
y 15 siguen siendo la evidencia de esa parte, y las pruebas que los reproducen son deterministas
(editor grabado o guionizado).


## 7. Distribución

Todo desde el clon.

| paso | resultado |
| --- | --- |
| `python -m build` | `kuyen-0.3.0-py3-none-any.whl` (111 archivos) y `kuyen-0.3.0.tar.gz` (162 archivos) |
| `twine check` | **PASSED** wheel y sdist |
| wheel: módulos restaurados | `semantics/schema.py`, `semantics/scope.py`, `provenance.py`, `vlm.py`: presentes |
| wheel: activos | `skills/knowledge-graph/SKILL.md` y `schemas/kuyen.schema.json`: presentes |
| wheel: contenido prohibido | ninguno (`.env`, `experiments/`, `tests/`, `runs/`, `scripts/`, `.coverage`) |
| sdist | sin `experiments/` ni `tests/`; 91 módulos de `src/kuyen` |
| instalación en 3.13 (wheel) | ok · `pip check` limpio · `import kuyen` → `0.3.0` · 40 nombres |
| instalación en 3.11 (sdist, compilado) | ok · `pip check` limpio · `import kuyen` → `0.3.0` · 40 nombres |
| `scripts/verify_distribution.py` | `[PASS] wheel 3.11`, `[PASS] wheel 3.13`, `[PASS] sdist 3.11`, `[PASS] sdist 3.13` → `all_passed=True` |
| metadatos y `VERSION` | coinciden en los dos artefactos y con `kuyen.__version__` |

Que una distribución se construya y no se pueda importar —el defecto del commit 6 de la
auditoría 16— ya no ocurre: la wheel incluye los cuatro módulos restaurados y el clon los importa
antes de construir.

## 8. Quickstart

Desde la wheel instalada en un venv 3.13, en un directorio fuera del repositorio y sin
`PYTHONPATH`:

```
memory created at /tmp/kuyen-demo/memory
committed MAPU-DEMO-01 as VER-e95aa365324f (kuyen 1.0.0)
Antü ANTU-DEMO-0002: VALIDATED (nothing written yet)
committed VER-152e1ad799b7 (kuyen 1.1.0), parent VER-e95aa365324f
graph: 3 entities, 1 relations, 1 assertions, 2 evidence records
claim asrt_b33e90e83cb4df3acb1c: 1200 cajas (2024)
provenance: 'exporto 1.200 cajas a Brasil' at 28:56 of MAPU-DEMO-02 …
verify: ok=True problems=[]
backup BKP-9bb799deec44b7fb: 2 versions, SEALED
restored: 2 versions, verify=True, reconstructed=2 accepted=True
```

No necesita red, ni modelo, ni OpenViking: es el camino que un desarrollador puede ejecutar con
una API key sin configurar nada más.

## 9. API pública

`kuyen.__all__` = **40 nombres**, sin cambios respecto del workspace (la lista está en
`evidence/api_surface.json` de la auditoría 16 y se releyó en el clon). Los que la tarea pide para
configurar y operar: `KuyenMemory`, `KuyenEngine`, `Mapu`, `build_document`,
`incorporate_document`, `apply_graph_edit`, `classify_antu`, `Antu`, `AntuEditResult`,
`EditorConfig`, `OpenAICompatibleGraphEditor`, `RecordedGraphEditor`, `VlmProviderConfig`,
`OpenVikingVlmRuntime`, `load_config`, `KuyenConfig`, `MemoryVersion`, `CommitResult`.

Lo que quedó documentado y lo que sigue siendo una limitación de documentación:

| necesidad | estado |
| --- | --- |
| configurar el proveedor LLM | `EditorConfig.from_env()` + `KUYEN_EDITOR_*` (`PUBLIC_API.md`) |
| configurar el VLM de OpenViking | `docs/KUYEN_OPENVIKING_VLM_CONFIGURATION_05.md` (commit 5) |
| configurar embeddings | en el mismo documento (endpoint separado cuando el proveedor no los expone) |
| incorporar un MAPU, leer el grafo, versiones, Antü, recuperar versión, verificar | `PUBLIC_API.md` + `QUICKSTART.md` |
| operaciones ejecutadas y su resultado | `docs/GRAPH_EDIT_ANTU*.md` (ES/EN) explican el contrato; `PUBLIC_API.md` sigue **sin** listar `outcome`/`outcomes` (§17) |

## 10. Seguridad

| comprobación | resultado |
| --- | --- |
| secretos en los 8 commits nuevos | ninguno (`git log -p 71e37c4..HEAD` sobre `sk-…`, `*_API_KEY=`, claves privadas) |
| secretos en archivos rastreados | ninguno |
| `.env` rastreado | no (ignorado por `.gitignore`) |
| wheel / sdist | sin `.env` ni credenciales |
| permisos | sin archivos escribibles por otros |
| mecanismo de credenciales | el sujeto es el **nombre** de la variable (`api_key_env`), resuelto en la llamada y nunca registrado; el metering no entra en el hash canónico |

No se imprimió ni copió ninguna clave. El `.env` del workspace no se tocó ni se copió al clon.

## 11. CI

**Resultado real sobre la rama publicada: `success`.**

```
run 41750565691 · work/kuyen-free-text-graph · c98a289 · completed success
  suite (py3.10)  success      suite (py3.13)  success
  suite (py3.11)  success      wheel and sdist          success
  suite (py3.12)  success      secrets and metadata     success
```

El camino hasta ahí, con las tres ejecuciones reales:

| run | commit | resultado | qué falló |
| --- | --- | --- | --- |
| 1 | `9a5e22d` | failure | `suite (py3.10)` (`tomllib`) y `version agrees` (import sin instalar) |
| 2 | `5c88002` | failure | sólo `version agrees` (el `--no-deps` dejaba el import sin `PyYAML`) |
| 3 | `c98a289` | **success** | nada |

Los dos fallos eran defectos reales: uno del producto (§4.9) y otro del propio workflow (§4.10-11).
Ninguno se silenció: no se añadieron `continue-on-error`, no se marcaron pasos como no bloqueantes,
no se recortó la matriz y las aserciones siguen intactas.

El workflow: `on: push` y `pull_request`, matriz 3.10, 3.11, 3.12 y 3.13 con
`pip install -e ".[dev]"` y `pytest -m "not openviking"` más un import fuera del árbol, job de
artefactos que construye, inspecciona el contenido e instala wheel y sdist en limpio, y job
`hygiene` con `forbidden files`, `version agrees` y `license agrees`.

Los dos runs históricos en rojo de `main`@`5fd8777` («Release KÜYEN 0.2.0») siguen ahí como
evidencia de que la release 0.2.0 nunca pasó su propia CI; no son fallos de esta rama.

## 12. Versión final

`0.3.0` (minor), no `0.2.0` (ya etiquetada) ni `0.2.1rc1` (no reconstruible, y nunca publicada).

* `VERSION` es la única fuente: `pyproject.toml` la lee en el build y `_version.py` la resuelve
  del checkout o de los metadatos instalados.
* El cambio desde `0.2.0` es **aditivo**: vocabulario `outcome`/`outcomes`, operaciones de
  entidad, atributo y relación, parches parciales, esquema versionado por Antü, runtime VLM y los
  módulos `provenance`/`semantics.*`. No hay nombres públicos eliminados ni formatos persistidos
  alterados (`STORE_FORMAT_VERSION`, `SIDECAR_SCHEMA_VERSION` estables), así que no hay migración.
* El `CHANGELOG` deja de prometer `0.2.1`: sus cuatro secciones *Unreleased* son ahora `0.3.0`.

La etiqueta `v0.3.0` y la publicación en PyPI **no** se hicieron en esta fase.


## 13. Estado del push

**Publicado.** `work/kuyen-free-text-graph` existe en el remoto.

| comprobación previa | resultado |
| --- | --- |
| rama local | `work/kuyen-free-text-graph`, 40 commits por delante de `origin/main` |
| `main` remoto | `5fd8777` — sin cambios desde la auditoría 16 |
| rama remota homónima | no existía (`git ls-remote --heads origin` sólo devolvía `main`) |
| divergencia posible | ninguna: el push creó la referencia, no sobrescribió nada |
| force push | no se usó |
| merge a main / etiquetas / PyPI / release de GitHub | no se hicieron |
| contenido | sólo los commits revisados; los 10 directorios de experimentos siguen fuera |

```
$ git push -u origin work/kuyen-free-text-graph
 * [new branch]      work/kuyen-free-text-graph -> work/kuyen-free-text-graph
branch 'work/kuyen-free-text-graph' set up to track 'origin/work/kuyen-free-text-graph'
```

Dos detalles de transporte, dichos para que no sorprendan a quien repita la operación:

1. El `origin` configurado es HTTPS y en este entorno no había credencial válida
   (`gh` tenía un token inválido en el llavero y el helper pedía contraseña). El push se hizo por
   SSH con una reescritura **de una sola invocación**
   (`git -c url."ssh://git@github.com/".insteadOf="https://github.com/" push …`), que autenticó
   como `mapu-kuyen`. La URL de `origin` no se modificó.
2. Los commits 9, 10 y 11 se publicaron con dos pushes de avance rápido (`9a5e22d..5c88002` y
   `5c88002..c98a289`) tras cada corrección de CI. La rama remota y la local terminan en el mismo
   `c98a289`.

Estado final del remoto:

```
5fd8777  refs/heads/main
c98a289  refs/heads/work/kuyen-free-text-graph
```

## 14. Hashes y artefactos

| artefacto | contenido |
| --- | --- |
| `evidence/pre_intervention_sha256.json` | SHA-256 de los 56 archivos del producto tal como estaban antes de intervenir |
| `evidence/necessity_matrix.json` y `.log` | las 17 reversiones medidas (import + suite) y su veredicto |
| `evidence/final_state.json` | HEAD, commits, conteos rastreados antes/después, estado del workspace y del clon |
| `evidence/clone_suite.log` | `527 passed, 3 skipped` en el clon |
| `evidence/clone_build.log`, `clone_twine.log` | build y `twine check` del clon |
| `evidence/clone_verify_distribution.log` | 4/4 PASS de `verify_distribution.py` |
| `evidence/ci_branch_run.json`, `ci_branch_jobs.json` | el run verde de la rama y sus seis jobs |
| `MANIFEST.json` | SHA-256 de todos los archivos de este experimento |


Integridad de los experimentos 13, 14 y 15: 712 archivos con el mismo hash que en la auditoría 16
(`experiments/KUYEN_PRODUCTION_READINESS_16/evidence/working_tree_sha256.json`, clave
`preserved_experiments`); no se modificó ninguno.

## 15. Limitaciones restantes

1. **`PUBLIC_API.md` no documenta `outcome`/`outcomes`** ni las operaciones de entidad, atributo y
   relación; el contrato completo está en `docs/GRAPH_EDIT_ANTU*.md`. Es documentación, no código:
   el comportamiento está probado.
2. **Paridad bilingüe incompleta**: sólo `docs/GRAPH_EDIT_ANTU` y `docs/PRODUCT_MAPU_KUYEN_ANTU`
   tienen par ES/EN; el README, el quickstart y la API pública están sólo en inglés.
3. **El quickstart no es re-ejecutable sobre el mismo directorio**: la segunda vez imprime
   `rejected: {'replayed_from_seq': …}` y termina en `REPLAYED`. Es la idempotencia de la Antü
   funcionando, pero el mensaje no lo explica en el propio ejemplo.
4. **El sdist no incluye `docs/`** (`MANIFEST.in` la poda), así que los enlaces del README a esos
   documentos no resuelven desde un sdist; sí desde el repositorio o la wheel.
5. **`engine.py` se incorporó sin prueba que lo cubra** (§3): su efecto sólo se ve en la
   instrucción que recibe OpenViking.
6. **Una prueba de integración depende de artefactos de experimentos** (commit 7). Ahora viajan en
   Git los siete archivos necesarios, pero el acoplamiento sigue ahí: si un día se reorganizan los
   experimentos, esas pruebas se rompen.
7. **OpenViking y el VLM no se ejercitaron en esta tarea** (no se consume nada externo): las
   pruebas `opt-in` siguen siendo la vía, documentada en §6.

## 16. Criterio de éxito

| criterio | estado |
| --- | --- |
| Todo el código necesario está en Git | sí: 91 módulos de `src/kuyen` (87 antes), 4 de ellos restaurados |
| Un desarrollador independiente puede clonar e instalar | sí: clon real, sin `PYTHONPATH`, `pip install` de wheel y sdist |
| El paquete importa | sí: `0.3.0`, 40 nombres públicos |
| La suite pasa desde un checkout limpio | sí: **527 passed, 3 skipped, 0 failed** |
| El Quickstart funciona | sí, desde la wheel instalada |
| Los dos flujos están implementados y documentados | sí: `ARCHITECTURE.md:77` y `docs/PRODUCT_MAPU_KUYEN_ANTU*.md`; el flujo documental se prueba con artefactos reales |
| La versión del paquete coincide con la del repositorio | sí: `VERSION` = metadatos = `kuyen.__version__` = `0.3.0` |
| No se incorporan cambios previos ajenos | sí: 10 directorios de experimentos quedan fuera; de 08 y 09 sólo la evidencia que citan las pruebas |
| Los experimentos 13, 14 y 15 permanecen íntegros | sí: 712 archivos con el mismo hash |
| El push publica únicamente la rama revisada | sí: `work/kuyen-free-text-graph` @ `c98a289`; `main` intacto |
| La CI de la rama pasa | sí: run `41750565691` en **success**, seis jobs en verde |

**La autoridad del producto es Git.** Se comprobó clonando: el árbol de trabajo no aporta nada que
el clon no tenga (0 archivos rastreados modificados).

## 17. Reproducibilidad

```bash
# 1. matriz de necesidad (no modifica nada; copia en /tmp)
python3 experiments/KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17/scripts/collect.py

# 2. reconstrucción limpia desde el clon
git clone --branch work/kuyen-free-text-graph <repo> /tmp/kuyen17_clone
cd /tmp/kuyen17_clone && env -u PYTHONPATH python3 -m pytest tests/     # 527 passed, 3 skipped

# 3. distribución
python3 -m build && python3 -m twine check dist/*
python3 scripts/verify_distribution.py --no-build \
    --wheel dist/kuyen-0.3.0-py3-none-any.whl --sdist dist/kuyen-0.3.0.tar.gz

# 4. quickstart desde la wheel
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install dist/*.whl
cd /tmp && /tmp/venv/bin/python <repo>/examples/quickstart.py
```
