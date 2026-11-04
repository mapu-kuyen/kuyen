# KUYEN_PRODUCTION_READINESS_16

**Decisión: `NOT_READY`.** No se hizo push.

El código que se publicaría **no se puede importar** desde la historia de Git. Un checkout limpio
de `f763f79` falla en la primera línea de importación:

```
src/kuyen/editing/applier.py:23: from ..semantics.schema import GraphSchema, SchemaError
E   ModuleNotFoundError: No module named 'kuyen.semantics.schema'
```

Cuatro módulos de `src/kuyen` existen sólo en el árbol de trabajo y nunca se confirmaron
(`provenance.py`, `semantics/schema.py`, `semantics/scope.py`, `vlm.py`), y otros diecisiete
módulos rastreados tienen versiones antiguas en HEAD que no coinciden con el código que las usa
(`errors.py` en HEAD no conoce `AmbiguousSourceUnit`, que `api/memory.py` importa). El producto
funciona en el workspace (`527 passed, 3 skipped`) y **no** funciona en la distribución: la
wheel construida desde HEAD instala con `pip check` limpio y falla al importar.

El defecto ya estaba publicado: el único workflow de CI del repositorio se ejecutó dos veces,
ambas sobre `main` en `5fd8777` (la release 0.2.0), y ambas terminaron en **failure** por la
misma causa.

Este informe no incluye los 69 elementos de trabajo previo en ningún commit: siguen intactos y
con su hash registrado. La corrección propuesta está en §12 y requiere autorización explícita,
porque implica confirmar trabajo de experimentos anteriores.

Correspondencia con los dieciséis apartados pedidos: 1 → §1, 2 → §2, 3 → §3, 4 (instalaciones) y
6 (distribuciones) → §4, 5 (pruebas) → §5, 7 (API pública) → §7, 8 (documentación) → §8,
9 (CI) → §11, 10 (seguridad) → §9, 11 (dependencias) → §10, 12 (limitaciones) → §12,
13 (decisión) → §13, 14 (hashes) → §14, 15 (estado de push) → §15, 16 (versión) → §16. Se añaden
§6 (los dos flujos), §17 (diferencias entre el estado original y el limpio) y §18
(reproducibilidad).

---

## 1. Estado inicial

| dato | valor |
| --- | --- |
| raíz | `/private/tmp/kuyen_hardening_01/kuyen` |
| rama | `work/kuyen-free-text-graph` |
| HEAD | `f763f79c91903e6d48ab2a31187c1426ef514941` (`f763f79`) |
| remoto | `origin` → `https://github.com/mapu-kuyen/kuyen.git` |
| upstream de la rama | ninguno (`no upstream configured`) |
| `origin/main` | `5fd8777a8305097792380fceb9ff861de208147a` — «Release KÜYEN 0.2.0» |
| ramas remotas | sólo `refs/heads/main` (verificado con `git ls-remote`) |
| divergencia | 27 commits por delante de `origin/main`, 0 por detrás (28 al cerrar, con el commit de este informe) |
| tags | `v0.2.0` → `5fd8777` (misma release) |
| `VERSION` en el árbol de trabajo | `0.2.1rc1` (**modificado, sin confirmar**) |
| `VERSION` en HEAD | `0.2.0` |
| `VERSION` en `origin/main` | `0.2.0` |
| staged | nada |
| modificados | 27 |
| no rastreados | 42 |
| total | 69 entradas previas |

Al cerrar la auditoría hay **70** entradas: las 69 anteriores sin tocar más el directorio de este
experimento. La prueba de que las 69 siguen intactas está en
`evidence/working_tree_sha256.json` (894 archivos con su SHA-256) y en
`evidence/working_tree_sha256.json → preserved_experiments` (712 archivos de los experimentos 13,
14 y 15).

Ninguna de las operaciones prohibidas por la tarea se ejecutó: no hubo `reset`, `clean`,
`restore` global, `checkout` descartando cambios, `stash`, `add -A`, squash, rebase ni force push.

## 2. Auditoría de los commits

Los seis commits existen, en este orden, y contienen lo declarado:

| commit | asunto | archivos | naturaleza |
| --- | --- | --- | --- |
| `d565f00` | fix(editing): read nested proposals and never infer NO_CHANGES | 4 | `outcome.py` (nuevo), `operations.py`, `service.py`, `api/memory.py` |
| `a6bc996` | feat(editing): checked entity, attribute and relation operations | 3 | `validator.py`, `applier.py`, `prompt.py` |
| `951b1ba` | test(editing): operational coverage … | 1 | `tests/editing/test_026_operational_coverage.py` (825 líneas) |
| `e85d95b` | docs(experiment): operational coverage of Antu operations 15 | 14 | `REPORT.md`, 12 artefactos, `docs/GRAPH_EDIT_ANTU*.md`, `CHANGELOG.md` |
| `54ce6e7` | docs(experiment): manifest of the operational coverage 15 | 1 | `MANIFEST.json` |
| `f763f79` | docs(experiment): exact counts and final Git state | 2 | `REPORT.md`, `MANIFEST.json` |

Ninguno elimina archivos, ninguno toca dependencias y ninguno introduce credenciales. El
contenido coincide con lo que declara el mensaje: se verificó con `git show --stat` commit por
commit y con la lectura del diff de cada archivo de código.

### Lo que los commits **no** contienen

La lista de capacidades que la tarea pide confirmar se contrastó contra el árbol de HEAD, no
contra los informes:

| capacidad | en HEAD | comentario |
| --- | --- | --- |
| OpenViking-first y materialización por Skill | código rastreado (`adapters/openviking.py`, `materialization/`, `skills/knowledge-graph/SKILL.md`) | las versiones de `adapters/openviking.py`, `product.py`, `engine.py` e `ingest.py` de HEAD **no** son las que se probaron: están modificadas sin confirmar |
| VLM configuration | **no** | `src/kuyen/vlm.py` no está en la historia; el test `tests/unit/test_vlm_configuration.py` tampoco |
| MAPU y SOURCE_UNIT | código y tests rastreados | `tests/test_source_unit_disambiguation.py` **no** está en la historia |
| Evidence validation | rastreado (`support.py`, `origin.py`, `test_021_evidence_authority.py`) | — |
| Canonical commit / ledger / recovery | rastreado | los tests M1/M2 de ledger, tamper y containment **no** están en la historia |
| Versionamiento por ANTÜ | rastreado (`test_023_versioning.py`) | — |
| Actualizaciones parciales | rastreado (`test_025_semantic_fidelity.py`) | depende de `semantics/schema.py`, que no está |
| Entidades, atributos, relaciones, esquema | rastreado (commits `d565f00`, `a6bc996`) | idem: no importa sin `semantics/schema.py` |
| Outcome vocabulary | rastreado (`editing/outcome.py` en `d565f00`) | idem |
| Preservación de procedencia y semántica | rastreado | `provenance.py` **no** está |
| Pruebas operativas 13/14/15 | parcial | `test_026` (exp. 15) está; `test_024` (aplicabilidad distribuida, exp. 12) **no**; los tests del exp. 14 están |

Es decir: **el código de las capacidades está confirmado, pero el producto no arranca** porque
los módulos que esas capacidades importan no están, y una parte de los tests que las demuestran
tampoco.

## 3. Checkout limpio

Se creó con `git worktree add --detach /tmp/kuyen_production_clean_16 HEAD`: sólo lo que Git
conoce en `f763f79`, sin copiar nada del workspace, sin `PYTHONPATH` heredado y sin reutilizar
entornos virtuales existentes.

```
$ cd /tmp/kuyen_production_clean_16 && env -u PYTHONPATH python3 -m pytest -q tests/
E   ModuleNotFoundError: No module named 'kuyen.semantics.schema'
exit=4                      # error de colección: no se ejecuta ni una prueba
```

Lo que falta, exactamente:

| archivo | qué es | quién lo importa |
| --- | --- | --- |
| `src/kuyen/semantics/schema.py` | `GraphSchema`: contrato versionado de tipos de entidad, campos, tipos de valor, declaración por ANTÜ (`ADD/UPDATE/RETRACT_FIELD`) | `editing/applier.py`, `editing/context.py`, `editing/validator.py`, `product.py` |
| `src/kuyen/semantics/scope.py` | `AntuScope` y permisos (`DATA_READ`, `SCHEMA_WRITE`, …) que filtran el contexto y autorizan cada operación | `api/memory.py`, `editing/context.py`, `editing/service.py`, `editing/validator.py` |
| `src/kuyen/provenance.py` | lectura de la fuente y registro `text_only` de la procedencia documental | `api/memory.py`, `ingest.py` |
| `src/kuyen/vlm.py` | configuración del proveedor VLM/embeddings de OpenViking | `__init__.py`, `projection/openviking.py` |

Y lo que está, pero **no en la versión que el código espera** (17 módulos rastreados con
modificaciones sin confirmar):

```
src/kuyen/canonical.py            src/kuyen/lifecycle/antu.py        src/kuyen/projection/outbox.py
src/kuyen/errors.py               src/kuyen/lifecycle/unit.py        src/kuyen/sidecar/__init__.py
src/kuyen/engine.py               src/kuyen/product.py               src/kuyen/storage/commit.py
src/kuyen/ingest.py               src/kuyen/projection/native.py     src/kuyen/storage/registry.py
src/kuyen/adapters/openviking.py  src/kuyen/projection/openviking.py src/kuyen/storage/store.py
src/kuyen/backup/archive.py       src/kuyen/editing/context.py
```

Prueba de que no basta con añadir los cuatro módulos nuevos: en una copia de diagnóstico se
añadieron sólo esos cuatro y el import siguió fallando, ahora en `errors.py`
(`cannot import name 'AmbiguousSourceUnit'`). La comprobación completa está en
`evidence/module_gap.json`.

### Diagnóstico por contraste

Se preparó una copia **de diagnóstico** del árbol completo (`/tmp/kuyen16_diag_b`: HEAD más las
69 entradas) para medir el tamaño real de la brecha. Es diagnóstico, no publicación: no se
confirmó nada de ella ni se copió al checkout limpio.

| árbol | suite | import |
| --- | --- | --- |
| checkout limpio (`f763f79`) | no colecciona (`exit=4`) | `ModuleNotFoundError: kuyen.semantics.schema` |
| copia de diagnóstico (HEAD + 69 entradas) | **527 passed, 3 skipped, 0 failed** | ok, `0.2.1rc1` |

Conclusión: el producto **sí** funciona; la historia publicada **no** lo contiene.

## 4. Instalación y distribución

Todo desde el checkout limpio.

| comprobación | resultado |
| --- | --- |
| `python -m build` (wheel + sdist) | ok — pero produce **`kuyen-0.2.0`**: el `VERSION` de HEAD es `0.2.0` |
| contenido de la wheel | 107 archivos; sin `.env`, sin `tests/`, sin `experiments/`, sin `runs/`, sin `scripts/` |
| módulos en la wheel | falta `kuyen/semantics/schema.py` y `kuyen/semantics/scope.py` (y `provenance.py`, `vlm.py`) |
| `twine check` | **PASSED** en wheel y sdist (los metadatos son válidos aunque el paquete no importe) |
| instalación de la wheel en venv 3.13 limpio | `pip install` ok, `pip check` = «No broken requirements found» |
| `import kuyen` tras instalar | **falla**: `ModuleNotFoundError: No module named 'kuyen.semantics.schema'` |
| `kuyen.__all__` | no evaluable desde la wheel publicada |
| Quickstart sin `PYTHONPATH` | no evaluable: el import falla antes |

Del árbol de diagnóstico (mismo contenido que el workspace) sí se pudo verificar la cadena
completa, y se registra como evidencia de que el problema es la falta de commits y no la
configuración del paquete:

| comprobación | resultado |
| --- | --- |
| wheel / sdist | `kuyen-0.2.1rc1` (111 archivos en la wheel) |
| `twine check` | PASSED (wheel y sdist) |
| instalación en venv 3.13 (wheel) | ok · `pip check` ok · `import kuyen` ok · `__version__ = 0.2.1rc1` |
| instalación en venv 3.11 (sdist, compilado) | ok · `pip check` ok · `import kuyen` ok |
| `kuyen.__all__` | **40 nombres** (ver `evidence/api_surface.json`) |
| Quickstart desde `/tmp`, sin `PYTHONPATH` | ok: 2 versiones, evidencia localizada, backup, restore, `verify=True` |

Observación de UX: al ejecutar el quickstart **por segunda vez** sobre el mismo directorio
imprime una línea `rejected: {'replayed_from_seq': 6, …}` antes de continuar y termina en
`REPLAYED`. Es el comportamiento idempotente de la Antü, pero el mensaje confunde y no está
documentado en el quickstart.

`VERSION` no se modificó en esta fase.


## 5. Pruebas de regresión y funcionamiento

| árbol | referencia del experimento 15 | real |
| --- | --- | --- |
| checkout limpio | 527 PASS · 3 SKIPPED · 0 FAIL | **no ejecutable** (error de colección) |
| copia de diagnóstico (HEAD + 69) | 527 PASS · 3 SKIPPED · 0 FAIL | **527 passed, 3 skipped** — coincide |

Archivos de prueba: **32** en HEAD, **55** en el árbol de trabajo. Los 23 módulos de prueba que
faltan en la historia son, entre otros:

```
tests/editing/test_024_distributed_applicability.py   tests/lifecycle/test_antu_contract.py
tests/unit/test_vlm_configuration.py                  tests/lifecycle/test_m1_ledger_concurrency.py
tests/security/test_tamper_detection.py               tests/lifecycle/test_m1_ledger_multiprocess.py
tests/security/test_version_id_containment.py         tests/lifecycle/test_m2_ledger_recovery.py
tests/storage/test_a2_stale_base_commit.py            tests/lifecycle/test_m6_append_scaling.py
tests/storage/test_atomic_write_boundary.py           tests/lifecycle/test_operation_boundary.py
tests/api/test_a1_canonical_validation.py             tests/projection/test_*.py
tests/test_source_unit_disambiguation.py               tests/examples/test_quickstart_example.py
```

Cobertura por capacidad, separando lo que está en la historia de lo que sólo está en el
workspace:

| capacidad | test en HEAD | test sólo en el workspace |
| --- | --- | --- |
| canonical commit / storage | `storage/test_canonical_storage.py` | `test_atomic_write_boundary`, `test_a2_*`, `test_a3_*`, `test_b2_*` |
| ledger / recovery | — | `lifecycle/test_m1_*`, `test_m2_*`, `test_m6_*` |
| integrity / tamper | `security/test_fail_closed.py` | `security/test_tamper_detection.py`, `test_version_id_containment.py` |
| provenance | `unit/test_020_version_provenance.py` | `lifecycle/test_source_provenance.py` |
| MAPU / SOURCE_UNIT | `unit/test_013_*.py`, `contract/test_schemas.py` | `test_source_unit_disambiguation.py` |
| evidence | `unit/test_021_evidence_authority.py` | — |
| OpenViking adapter | `unit/test_adapter.py`, `integration/test_openviking_real.py` (opt-in) | — |
| VLM configuration | — | `unit/test_vlm_configuration.py` |
| grafo nativo / materialización | `unit/test_014_materializer.py`, `integration/test_document_path_artifacts.py` | `tests/projection/*` |
| aceptación (gate) | `api/test_public_api.py`, `contract/test_schemas.py` | `api/test_a1_canonical_validation.py` |
| ANTÜ editing | `editing/test_022`, `test_023` | `editing/test_024` |
| actualizaciones parciales | `editing/test_025_semantic_fidelity.py` | — |
| `UPDATE_ENTITY` / `UPDATE_ATTRIBUTE` / `ADD_RELATION` | `editing/test_026_operational_coverage.py` | — |
| `RETRACT_RELATION` múltiple / `ADD_FIELD` | `editing/test_025`, `test_026` | — |
| idempotencia / reconstrucción de versiones | `editing/test_023`, `test_026` | `lifecycle/test_antu_contract.py` |
| clasificación de outcome | `editing/test_026` | — |

Los tests `opt-in` que necesitan proveedores externos son
`tests/integration/test_openviking_real.py` (marcador `openviking`) y
`tests/integration/test_real_editor.py`. No se ejecutaron en esta auditoría porque implican un
servicio levantado o coste de inferencia; se ejecutan con:

```bash
python -m pytest tests/integration/test_openviking_real.py -m openviking   # exige OpenViking vivo
KUYEN_EDITOR_MODEL=… KUYEN_EDITOR_API_KEY_ENV=… python -m pytest tests/integration/test_real_editor.py
```

Las tres pruebas `SKIPPED` de la suite son exactamente esas condiciones opcionales.

Diferencia entre tipos de evidencia: las pruebas de fixture validan contratos deterministas
(p. ej. `test_025`, `test_026`); las pruebas operativas de los experimentos 13–15 usaron memorias
reales. En esta auditoría **no** se ejecutaron pruebas operativas nuevas: el objetivo era
comprobar reproducibilidad, y la reproducibilidad falla antes de empezar.


## 6. Los dos flujos principales

Ambos están documentados en la historia (`ARCHITECTURE.md:77` dibuja el camino documental y
`docs/PRODUCT_MAPU_KUYEN_ANTU.md` explica MAPU/KÜYEN/ANTÜ y la aplicabilidad por operación) y
ambos están implementados, pero **ninguno es ejecutable desde HEAD** porque el paquete no importa.

### A. Documento MAPU (OpenViking-first)

```
DOCUMENT → MAPU → OPENVIKING → KNOWLEDGE GRAPH SKILL → CANDIDATE → KÜYEN VALIDATION → CANONICAL COMMIT
```

* `src/kuyen/ingest.py`, `materialization/`, `adapters/openviking.py`,
  `projection/openviking.py`, `skills/knowledge-graph/SKILL.md` (incluida en la wheel).
* `ADAPTERS.md` describe los límites medidos de OpenViking 0.5.0 y **no** anuncia como propias
  capacidades que no tiene (compilación nativa, recuperación semántica sin embeddings).
* El commit canónico y el versionamiento son los mismos que usa el camino B: no hay una segunda
  vía de escritura.

### B. Modificación mediante ANTÜ

```
ANTÜ → LLM → STRUCTURED OPERATIONS → VALIDATION → GRAPH EXECUTION → VERIFICATION → NEW VERSION
```

* `apply_antu` está documentado en `PUBLIC_API.md` como «OpenViking is never used» y la prueba
  `tests/editing/test_022_graph_edit.py::test_the_edit_never_touches_openviking` (presente en
  HEAD, línea 433) comprueba que el adaptador no se invoca durante una edición.
* Ninguna modificación persiste sin versión: `commit_version` es la única escritura y una
  operación sólo pasa a `COMMITTED` después del commit (`editing/outcome.py`, exp. 15).

Ambos flujos comparten `lifecycle/` (ledger, revisiones, sidecar) y el registro de versiones. La
verificación de que funcionan con el contenido actual está en la copia de diagnóstico (§3), no en
la historia.

## 7. API pública y experiencia de desarrollador

`kuyen.__all__` expone **40 nombres** (`evidence/api_surface.json`): `KuyenMemory`, `KuyenEngine`,
`Antu`, `AntuEditResult`, `AntuExecution`, `CommitResult`, `MemoryVersion`, `Mapu`,
`DocumentIncorporation`, `build_document`, `incorporate_document`, `apply_graph_edit`,
`classify_antu`, `load_config`, `KuyenConfig`, `EditorConfig`, `OpenAICompatibleGraphEditor`,
`RecordedGraphEditor`, `GraphEditorPort`, `VlmProviderConfig`, `OpenVikingVlmRuntime`,
`VlmConfigurationError`, `ValidationReport`, `Candidate*`, `Coverage*`, `Publication*`,
`Execution*`, `VersionDomains`, `SIDECAR_SCHEMA_VERSION`, `STORE_FORMAT_VERSION`,
`ANTU_KIND_*`, `ActorContext`.

| necesidad del desarrollador | documentado |
| --- | --- |
| crear/abrir una memoria, leer grafo y versiones | sí (`PUBLIC_API.md` §KuyenMemory) |
| incorporar un MAPU y obtener el grafo | sí (`build_document`, `incorporate_document`) |
| enviar una Antü y leer el resultado | sí (`apply_antu`, `AntuEditResult`) |
| consultar operaciones ejecutadas | parcial: el listado de campos de `AntuEditResult` **no** incluye `outcome` ni `outcomes` (exp. 15) |
| recuperar una versión anterior | sí (`graph(version_id)`) |
| verificar integridad y procedencia | sí (`verify`, `provenance`) |
| configurar el proveedor LLM | sí (`EditorConfig`, `KUYEN_EDITOR_*`) |
| configurar el VLM de OpenViking | **no**: `VlmProviderConfig` no aparece en ninguna guía publicada; el documento que lo explica (`docs/KUYEN_OPENVIKING_VLM_CONFIGURATION_05.md`) no está en la historia |
| configurar embeddings | **no** (sólo una nota en `ADAPTERS.md` sobre que `find` los requiere) |
| qué operaciones acepta el contrato | parcial: `docs/GRAPH_EDIT_ANTU*.md` las enumera y explica; `PUBLIC_API.md` no |

El quickstart publicado (el de HEAD) es una versión anterior y más corta que la del workspace: la
que se validó en el experimento 15 (dos MAPU, evidencia localizada, backup y restore) no está
confirmada.

## 8. Documentación de open source

| documento | idioma | estado |
| --- | --- | --- |
| `README.md` | inglés | correcto; explica qué es y qué no es KÜYEN |
| `QUICKSTART.md` | inglés | correcto para el camino determinista; no cubre OpenViking ni el VLM |
| `PUBLIC_API.md` | inglés | desactualizado en `outcome`/`outcomes`, operaciones de edición y configuración VLM |
| `DATA_MODEL.md`, `ARCHITECTURE.md`, `ADAPTERS.md`, `VERSIONING.md`, `SIDECAR.md`, `CANONICAL_STORAGE.md`, `BACKUP_AND_RECOVERY.md`, `PLATFORM_COMPATIBILITY.md`, `SECURITY.md`, `CONTRIBUTING.md`, `ANTU_LIFECYCLE.md`, `LICENSE` | inglés | presentes |
| `docs/PRODUCT_MAPU_KUYEN_ANTU.md` + `.en.md` | **es + en** | par bilingüe completo |
| `docs/GRAPH_EDIT_ANTU.md` + `.en.md` | **es + en** | par bilingüe completo |
| `docs/KUYEN_OPENVIKING_VLM_CONFIGURATION_05.md`, `…_RELEASE_QUICKSTART_REPAIR_02.md`, `…_SOURCE_UNIT_DISAMBIGUATION_03.md` | español | **no están en la historia** |

Paridad bilingüe: **no cumplida**. Sólo hay dos pares ES/EN (los `docs/*.en.md`); README,
quickstart, API pública y modelo de datos están sólo en inglés. Los mensajes que la tarea exige
transmitir sí están: OpenViking como dependencia interna esencial (`ARCHITECTURE.md`,
`ADAPTERS.md`), KÜYEN no es un extractor genérico (`README.md`), la Antü evoluciona el
conocimiento y cada modificación confirmada genera versión (`docs/PRODUCT_MAPU_KUYEN_ANTU.md`), el
LLM propone y KÜYEN controla (`docs/GRAPH_EDIT_ANTU.md`).

No se encontraron declaraciones de Skills dinámicos ni de autonomía de LeftraruOS como funciones
de KÜYEN. Las limitaciones de los experimentos 13–15 están en `docs/GRAPH_EDIT_ANTU*.md` y en el
`CHANGELOG.md` confirmado.


## 9. Seguridad y cadena de suministro

| comprobación | resultado |
| --- | --- |
| archivos `.env` en el árbol de HEAD | ninguno (`git ls-files \| grep .env` vacío) |
| archivos `.env*`, `*.pem`, `*.key` en el checkout limpio | ninguno |
| patrones de secreto (`sk-…`, `*_API_KEY=…`, claves privadas) en HEAD | ninguno |
| secretos en los 27 commits de la rama | ninguno (`git log -p 5fd8777..HEAD`) |
| secretos en una muestra de 40 commits de la historia | ninguno |
| permisos de archivo | ningún archivo escribible por otros |
| wheel / sdist | sin `.env`, `tests/`, `experiments/`, `runs/`, `scripts/`, `.coverage` |
| `.gitignore` | cubre `.env`, `dist/`, `__pycache__`, `.coverage` |
| mecanismo de credenciales | el sujeto es el **nombre** de la variable de entorno (`EditorConfig.api_key_env`, `VlmProviderConfig.api_key_env`), nunca el valor; se resuelve en la llamada y no se registra |
| metering en la identidad del grafo | excluido: `usage` vive en el ledger y en el run, no en la procedencia (`test_the_version_identity_does_not_depend_on_token_metering`) |

No hay herramienta de auditoría de vulnerabilidades instalada (`pip-audit`, `safety`) y no se
añadió ninguna dependencia para esta fase: el inventario se hizo a mano y con `pip check`. El
workspace contiene un `.env` con credenciales reales; está ignorado por Git y nunca se copió al
checkout limpio ni a las copias de diagnóstico.

## 10. Dependencias

| ámbito | dependencias |
| --- | --- |
| producción | `jsonschema>=4.0`, `PyYAML>=6.0` |
| extra `openviking` | `httpx>=0.25` |
| extra `dev` en HEAD | `pytest>=7.0`, `build>=1.0`, `twine>=5.0` |
| extra `dev` en el árbol de trabajo | añade `pytest-cov>=4.0` y `httpx>=0.25` |

La diferencia importa: la documentación de cobertura usa `pytest-cov`, que no está declarado en
la historia; quien instale `.[dev]` desde HEAD no lo tendrá. `pip check` = «No broken requirements
found» en las cuatro instalaciones verificadas. No se añadió ninguna dependencia en esta fase.

## 11. CI y estado remoto

`.github/workflows/ci.yml` define tres jobs: `suite` (matriz 3.10–3.13, `pip install -e ".[dev]"`,
`pytest -m "not openviking"`, import fuera del árbol), `artifacts` (build, inspección del contenido
y dos instalaciones limpias) y `hygiene` (archivos prohibidos, «version agrees», licencia).

Estado real (`evidence/ci_runs.json`, `evidence/ci_jobs.json`):

| run | rama | commit | resultado |
| --- | --- | --- | --- |
| `ci` | `main` | `5fd8777` («Release KÜYEN 0.2.0») | **failure** |
| `ci` | `v0.2.0` | `5fd8777` | **failure** |

| job | resultado | paso que falla |
| --- | --- | --- |
| `suite (py3.10)` | failure | `product suite` |
| `suite (py3.11)` | failure | `product suite` |
| `suite (py3.12)` | failure | `product suite` |
| `suite (py3.13)` | failure | `product suite` |
| `wheel and sdist` | success | — |
| `secrets and metadata` | failure | `version agrees` (`import kuyen`) |

Son los dos únicos runs del repositorio: **no existe ningún run de
`work/kuyen-free-text-graph`** porque la rama nunca se publicó. Los seis fallos tienen la misma
causa que el checkout limpio: el paquete no importa. El job de artefactos pasa porque construir no
importa el paquete; `version agrees` falla al importar `kuyen`, no por un desajuste de versión. No
se modificó ningún workflow.


## 12. Limitaciones y corrección propuesta

Bloqueantes (impiden publicar):

1. **Cuatro módulos fuera de la historia** (`provenance.py`, `semantics/schema.py`,
   `semantics/scope.py`, `vlm.py`). Sin ellos no hay import, ni suite, ni Quickstart, ni documento
   materializado.
2. **Diecisiete módulos rastreados desactualizados** respecto del código que los usa; el primero
   que falla es `errors.py` (`AmbiguousSourceUnit`), y detrás vienen `canonical.py`, `lifecycle/`,
   `storage/`, `projection/`, `product.py`, `engine.py`, `ingest.py`, `adapters/openviking.py`.
3. **`VERSION` en HEAD es `0.2.0`**, la misma versión ya publicada y etiquetada (`v0.2.0`), con
   código nuevo encima: publicar así produce una colisión de versión y un artefacto que se llama
   igual que la release anterior sin serlo.

No bloqueantes, pero deben corregirse antes de anunciar el producto:

4. `PUBLIC_API.md` no documenta `outcome`/`outcomes` ni las operaciones de entidad, atributo y
   relación, y no hay guía publicada de configuración del VLM ni de embeddings.
5. Paridad bilingüe incompleta (sólo dos pares ES/EN).
6. El quickstart imprime `rejected: …` al ejecutarse dos veces sobre el mismo directorio.
7. `pytest-cov` está documentado pero no declarado en `extras[dev]` de la historia.

### Separación propuesta (no ejecutada: requiere autorización)

Los 69 elementos pendientes no se confirman sin permiso expreso. La forma correcta de
incorporarlos es por responsabilidad, no en bloque:

| commit propuesto | contenido | por qué |
| --- | --- | --- |
| `fix(package): add the modules the published history imports` | los 4 módulos nuevos | mínimo para que el paquete importe; sin lógica nueva |
| `fix(domain): publish the corrections the engine and storage already use` | `canonical.py`, `errors.py`, `lifecycle/*`, `storage/*`, `sidecar/__init__.py`, `projection/*`, `backup/archive.py` | robustez (límites de transacción, orden de versiones, contención de ids) que los tests ya ejercitan |
| `fix(product): align document flow and editing with the tested code` | `product.py`, `engine.py`, `ingest.py`, `adapters/openviking.py`, `editing/context.py`, `examples/quickstart.py` | cierra el flujo A y el contexto de edición |
| `test: publish the suites that prove the corrections` | 23 módulos de prueba + 4 modificados | sin ellos la historia no demuestra lo que declara |
| `docs: publish the VLM, quickstart and source-unit guides` | 3 documentos + `docs/reports/` | cierra la falta de guía de VLM |
| `build: ship MANIFEST.in and the distribution verifier` | `MANIFEST.in`, `scripts/verify_distribution.py` | la verificación de distribución debe ser reproducible por terceros |
| `release: bump VERSION and CHANGELOG to the stable version` | `VERSION`, `CHANGELOG.md` | ver §16 |

Después de esos commits hay que repetir esta auditoría (checkout limpio → suite 527/3 → wheel
instalable → quickstart) **antes** del push.

## 13. Decisión de producción

**`NOT_READY`.**

Se cumplen: historia de commits revisada, distribución bien formada (`twine check` PASSED),
metadatos y licencia correctos, dependencias declaradas y consistentes, ausencia de secretos y
permisos sanos, documentación de arquitectura y producto de calidad.

No se cumplen, y son bloqueantes:

* **checkout limpio**: el paquete no importa;
* **suite**: no se ejecuta desde la historia;
* **quickstart**: no se ejecuta desde la distribución publicada;
* **dependencia de archivos locales no publicados**: 4 módulos nuevos y 17 modificados;
* **CI**: rojo en `main` y en `v0.2.0`, por la misma causa.

No se rebajó ningún criterio. Un producto que sólo funciona en el workspace del autor no es un
producto publicable, y publicar la rama ahora propagaría el fallo a cualquiera que clone el
repositorio.


## 14. Hashes y artefactos

| artefacto | contenido |
| --- | --- |
| `evidence/state_initial.json` | rama, HEAD completo, remoto, upstream, `origin/main`, tags, versiones, 69 entradas, 27 commits |
| `evidence/working_tree_sha256.json` | SHA-256 de los 894 archivos del trabajo pendiente + 712 de los experimentos 13/14/15 |
| `evidence/module_gap.json` | módulos presentes, módulos en HEAD, los 4 ausentes, quién los importa y el primer error de import |
| `evidence/distribution.json` | wheel/sdist del checkout limpio (107 archivos) y del diagnóstico (111), módulos Python incluidos, entradas sospechosas |
| `evidence/api_surface.json` | versión y los 40 nombres de `kuyen.__all__` |
| `evidence/docs_audit.json` | documentos en la historia y en el workspace, menciones en `PUBLIC_API.md`, pares bilingües |
| `evidence/ci_runs.json`, `evidence/ci_jobs.json` | los dos runs y sus jobs con el paso que falla |
| `evidence/logs/*.log` | suite del checkout limpio, suite del workspace, `twine check` |

`MANIFEST.json` reúne el SHA-256 de todos los archivos de este experimento.

## 15. Estado de push

**No se hizo push.** La rama `work/kuyen-free-text-graph` sigue siendo local: `git ls-remote`
muestra sólo `refs/heads/main`. No hay divergencia posible porque no existe rama remota homónima,
y no se creó ninguna etiqueta, no se publicó nada en PyPI y `VERSION` no se modificó.

## 16. Recomendación de versión estable

**`0.3.0`** (minor), no `0.2.1rc1`.

* `HEAD` dice `0.2.0`, que es exactamente la versión ya publicada y etiquetada: un artefacto
  construido hoy desde la rama se llamaría igual que la release anterior y contendría código
  distinto.
* `0.2.1rc1` (árbol de trabajo) es una *pre-release* coherente con el `CHANGELOG` («Direct Antü
  editing (0.2.1)»), pero hoy no es reconstruible desde ningún commit, porque su código no está
  confirmado.
* El cambio acumulado desde `0.2.0` es **aditivo** y amplía la superficie pública: vocabulario
  `outcome`/`outcomes` en `AntuEditResult`, operaciones `UPDATE_ENTITY`, `UPDATE_ATTRIBUTE`,
  `ADD_RELATION`, `UPDATE_RELATION`, parches parciales, esquema versionado por Antü, runtime VLM
  (`VlmProviderConfig`, `OpenVikingVlmRuntime`) y los módulos `provenance`, `semantics.schema`,
  `semantics.scope`. No se observaron eliminaciones ni cambios incompatibles en las firmas
  documentadas.

| aspecto | recomendación |
| --- | --- |
| versión | `0.3.0` |
| compatibilidad | compatible hacia atrás para el uso documentado en 0.2.0; los formatos persistidos no cambian (`STORE_FORMAT_VERSION`, `SIDECAR_SCHEMA_VERSION` estables) |
| migraciones | ninguna; las memorias 1.0.0 existentes siguen verificando |
| riesgos | el `CHANGELOG` debe mover la entrada de edición de Antü de «0.2.1» a «0.3.0» para no prometer una versión que nunca existió |
| publicación PyPI | operación separada: sólo desde un tag `v0.3.0` sobre un commit que pase esta auditoría, nunca desde el árbol de trabajo |

`VERSION` no se modificó en esta fase: el cambio de versión pertenece al commit de release
propuesto en §12.

## 17. Diferencias entre el estado original y la distribución limpia

| dimensión | estado original (workspace) | checkout limpio (`f763f79`) |
| --- | --- | --- |
| import del paquete | ok, `0.2.1rc1` | **falla** (`kuyen.semantics.schema`) |
| suite | 527 passed · 3 skipped | no colecciona |
| módulos de `src/kuyen` | 106 | 102 (faltan 4) |
| módulos con correcciones | 17 | versiones antiguas |
| archivos de prueba | 55 | 32 (faltan 23) |
| documentos de `docs/` | 7 + `docs/reports/` | 4 (faltan 3 + reports) |
| `scripts/verify_distribution.py` | presente | **ausente** |
| `MANIFEST.in` | presente | **ausente** |
| experimentos | 13 directorios | 4 (faltan 9, incluido el 13) |
| quickstart validado | sí (2 MAPU, backup, restore) | versión anterior, no ejecutable |
| `VERSION` | `0.2.1rc1` | `0.2.0` |
| wheel construida | `0.2.1rc1` (111 archivos) | `0.2.0` (107 archivos) |
| instalación limpia | import ok, `pip check` ok | `pip check` ok, **import falla** |
| extras `dev` | incluye `pytest-cov`, `httpx` | no los incluye |

## 18. Reproducibilidad de esta auditoría

```bash
# 1. estado y manifiesto de hashes (no modifica nada)
python3 experiments/KUYEN_PRODUCTION_READINESS_16/scripts/collect.py

# 2. checkout limpio: sólo lo que Git conoce
git worktree add --detach /tmp/kuyen_production_clean_16 HEAD
cd /tmp/kuyen_production_clean_16 && env -u PYTHONPATH python3 -m pytest -q tests/   # exit 4

# 3. distribución desde HEAD
cd /tmp/kuyen_production_clean_16 && python3 -m build && python3 -m twine check dist/*
python3 -m venv /tmp/venv16_clean313 && /tmp/venv16_clean313/bin/pip install dist/*.whl
/tmp/venv16_clean313/bin/python -c 'import kuyen'                                   # ModuleNotFoundError

# 4. contraste (diagnóstico, no publicación)
rsync -a --exclude .git --exclude dist --exclude .env ./ /tmp/kuyen16_diag_b/
cd /tmp/kuyen16_diag_b && env -u PYTHONPATH python3 -m pytest tests/                 # 527 passed, 3 skipped

# 5. CI
curl -s 'https://api.github.com/repos/mapu-kuyen/kuyen/actions/runs?per_page=5'
```

El checkout limpio se deja en `/tmp/kuyen_production_clean_16` y la copia de diagnóstico en
`/tmp/kuyen16_diag_b` para que el resultado sea inspeccionable. Se eliminan con
`git worktree remove /tmp/kuyen_production_clean_16 --force` y `rm -rf /tmp/kuyen16_diag_b`.

