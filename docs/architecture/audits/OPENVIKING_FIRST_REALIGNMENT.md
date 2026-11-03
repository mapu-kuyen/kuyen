# Auditoría: realineamiento arquitectónico OpenViking-first

**Fecha:** 2026-11-02 · **Tipo:** auditoría + refactorización selectiva + commit documentado
**Decisión:** [ADR 0001](../../adr/0001-openviking-first-realignment.md)
**Evidencia reproducible:** `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/`

---

## 1. HEAD y estado inicial del repositorio

| dato | valor |
|---|---|
| Repositorio | `/tmp/kuyen_hardening_01/kuyen` (`git rev-parse --show-toplevel` → `/private/tmp/kuyen_hardening_01/kuyen`) |
| Remoto | `https://github.com/mapu-kuyen/kuyen.git` (`origin`, fetch y push) |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — *Release KÜYEN 0.2.0*, `HEAD` detached; **un único commit en todo el repositorio** |
| `VERSION` | `0.2.1rc1` (intacto) |
| Estado | **31 archivos rastreados modificados + 30 sin rastrear**, nada en el índice |
| `diff HEAD --stat` | 31 files changed, 2198 insertions(+), 355 deletions(-) |
| Naturaleza de esos cambios | hardening 01–05, reparación del Quickstart 02, desambiguación de SOURCE_UNIT 03, experimentos 05 y 07, y ediciones incompletas de E2E_01 — **todos previos a esta tarea** |
| Operaciones destructivas | **ninguna** (`reset`, `clean`, `checkout`, `restore`, `stash`: no ejecutados) |
| Protección | SHA-256 de 183 archivos (`hashes_initial.txt`) y dos tarballs recuperables (476 entradas) en `/tmp/kuyen_realign_01/backup/` |
| Secretos | `.env` vive **fuera** del repositorio y está en `.gitignore`; no se copió ni se incluyó nada sensible |

Este repositorio es el paquete público KÜYEN. No es `leftraruOS`, ni `runtime/memory_kuyen`, ni una
copia en `site-packages`, ni un servidor OpenViking: se verificaron ruta, remoto y `kuyen.__file__`
antes de tocar nada.

## 2. Inventario de módulos y responsabilidades

83 módulos Python, 15.932 líneas de código fuente (medido sobre el respaldo, ver §12).

| grupo | módulos | responsabilidad | LOC |
|---|---|---|---|
| `api/` | `memory.py` | API pública: store, Antü, commit, graph, trace, verify, backup | 694 |
| `storage/` | store, versions, registry, commit | almacén canónico, manifiestos inmutables, protocolo de commit | 1.900 |
| `lifecycle/` | antu, ledger, unit | ejecución de Antü, ledger encadenado, revisiones de unidad | 1.100 |
| primitivas | `canonical`, `contracts`, `errors`, `credentials`, `security`, `versioning`, `provenance`, `ingest`, `models/`, `ontology`, `config` | identidad, procedencia, contratos, errores | 2.700 |
| `validation/` | canonical, validators | validación de objetos canónicos y del candidato | 566 |
| `sidecar/`, `backup/`, `recovery/` | — | sidecar canónico, backup verificado, reconstrucción | 1.100 |
| `engine.py`, `adapters/`, `ports/` | — | **motor OpenViking**: build_async, adaptador SDK, publicación | 1.475 |
| `materialization/` | contract, materializer, paths | artefactos del proveedor → `CandidateBundle` | 861 |
| `semantics/`, `normalization/`, `coverage/` | — | preservación de predicados, identidad, inventario de unidades | 942 |
| `serialization/` | serializer | parseo de árbol nativo/frontmatter | 178 |
| `publication/` | coordinator, planner, registry, verifier, models | publicación gobernada con ACL | 800 |
| `projection/` | native, mapping, projector, outbox, reconciliation, **openviking** | proyección, correspondencia, outbox, cliente HTTP y **ciclo de vida del servidor** | 1.750 |
| `vlm.py` | — | configuración del proveedor VLM (API pública) | 310 |
| `query/` | graph | helpers de lectura del grafo canónico | 367 |
| `importing/` | historical | importación de grafos de otros sistemas | 256 |
| `extraction/` | **retirado** | extracción OpenAI directa (drift) | **1.542** |
| `skills/`, `schemas/`, `config/` | datos de paquete | Skill `knowledge-graph`, contratos JSON, ontologías | — |

## 3. Mapa de dependencias

Generado con análisis **AST** (no sólo grep), incluyendo importaciones relativas y resolución de
módulos: `/tmp/kuyen_realign_01/graph.json` (copia en `graph.json` del experimento).

| módulo | importadores internos | consumidores externos |
|---|---|---|
| `api.memory` | `kuyen/__init__` | tests/api, tests/lifecycle, tests/recovery, conftest, examples/quickstart |
| `engine` | `kuyen/__init__` | tests/unit (engine, engine_flow, 011, 013, 014, 019), tests/contract, tests/integration |
| `adapters.openviking` | **ninguno** (carga diferida por `adapters/__init__.__getattr__`) | tests/unit/test_adapter, 013, 014, integration |
| `ports.openviking` | adapters, engine | test_engine_flow |
| `materialization.*` | engine | test_014, test_019 |
| `validation.canonical` | lifecycle.antu, storage.commit | — (cubierto por tests de lifecycle/storage) |
| `validation.validators` | validation, engine | test_016 |
| `semantics.*` | engine | test_017, 018, 019 |
| `serialization.serializer` | adapters.openviking, importing.historical, materialization.materializer, serialization | tests de contrato |
| `publication.*` | engine | test_publication |
| `query.graph` | `query/__init__` | test_017 |
| `importing.historical` | `importing/__init__` | test_013_historical_import |
| **`extraction.*`** | **ninguno** | **sólo tests 015, 016, 018** |

Comprobaciones adicionales exigidas: importación dinámica (`adapters/__init__` con `importlib` por
nombre, `contracts.schema_path`, `importlib.metadata` en `_version.py`), datos de paquete
(`pyproject [tool.setuptools.package-data]`), sin entry points ni consola, sin registro de plugins,
sin carga por ruta en runtime (la única carga por ruta es de *assets*: esquemas, ontologías, Skill).

Ningún módulo de `src/` importa `kuyen.extraction`.

## 4. Clasificación A–F

| categoría | componentes | decisión |
|---|---|---|
| **A. KEEP_CORE** | `canonical`, `contracts`, `errors`, `credentials`, `security`, `versioning`, `provenance`, `ingest`, `models/`, `ontology`, `config`, `storage/`, `lifecycle/`, `validation/canonical`, `sidecar/`, `backup/`, `recovery/`, `api/memory`, `schemas/`, `py.typed` | intactos |
| **B. KEEP_OPENVIKING_INTEGRATION** | `engine`, `adapters/`, `ports/`, `vlm`, `materialization/`, `validation/validators`, `semantics/`, `normalization/`, `coverage/`, `serialization/`, `publication/`, `projection/`, `skills/` | intactos (≈4.700 líneas) |
| **C. DELEGATE_TO_OPENVIKING** | capacidad *producción de candidatos de grafo* y *procesamiento semántico* | delegada; el código que la duplicaba pasa a D |
| **D. REMOVE_CONFIRMED_REDUNDANT** | `src/kuyen/extraction/` (7 archivos, 1.542 líneas), `tests/unit/test_015_extraction.py`, 1 caso de `test_016`, 1 caso de `test_018` | **retirado** |
| **E. ARCHIVE_EXPERIMENT** | todos los `experiments/KUYEN_*`, `docs/reports/*`, `docs/KUYEN_*`, y los tres archivos de test retirados | conservados / archivados |
| **F. UNCERTAIN_DO_NOT_DELETE** | `query/` (367), `importing/` (256), jerarquía de errores OpenAI en `errors.py`, cliente HTTP propio de `projection/openviking.py`, `engine`+`adapters` (integración no validada extremo a extremo) | intactos, documentados |

## 5. Archivos eliminados y motivo individual

| ruta | líneas | responsabilidad | evidencia de redundancia | sustituto |
|---|---|---|---|---|
| `src/kuyen/extraction/__init__.py` | 30 | re-export del subsistema | ningún importador en `src/`; no está en `kuyen.__all__`; 0 menciones en documentación pública | — |
| `src/kuyen/extraction/openai_provider.py` | 450 | cliente OpenAI (Responses API + Structured Outputs), presupuesto, parseo | idem; la producción de candidatos la ejecuta OpenViking con la Skill | `SdkOpenVikingAdapter.compile` + Skill `knowledge-graph` |
| `src/kuyen/extraction/schema.py` | 326 | esquema JSON de salida del modelo, generado del Antü | la Skill y `materialization/contract.py` cubren el contrato de salida | Skill + `kuyen-provider-result-v1` |
| `src/kuyen/extraction/conversion.py` | 189 | candidato OpenAI → `kuyen-provider-result-v1` | sólo lo usaba el proveedor retirado; OpenViking entrega ya ese contrato | `materialization.materializer` |
| `src/kuyen/extraction/budget.py` | 159 | contabilidad de coste de llamadas | dependía del proveedor retirado; OpenViking gestiona su propio uso | fuera de KÜYEN |
| `src/kuyen/extraction/fact_coverage.py` | 191 | evaluación de cobertura fáctica contra ground truth | arnés de experimento, no runtime; sin consumidor | archivado como evidencia |
| `src/kuyen/extraction/config.py` | 197 | `OpenAIConfig` público (sin commitear) | parte de la deriva que este ADR corrige | `VlmProviderConfig` |
| `tests/unit/test_015_extraction.py` | 372 | 9 pruebas del subsistema | prueban sólo código eliminado | archivado |
| `tests/unit/test_016_temporal.py` (1 caso) | 22 | esquema v2 del extractor | ídem; los otros 3 casos se conservan | archivado |
| `tests/unit/test_018_generalization.py` (1 caso) | 17 | fallback de valor no numérico en `conversion` | ídem; el otro caso se conserva | archivado |

**Total:** 7 archivos de código (1.542 líneas en el árbol de trabajo; 1.150 en `HEAD`) y 11 casos de
prueba (9 + 1 + 1).

## 6. Archivos conservados y razón

| componente | razón |
|---|---|
| `engine.py` + `adapters/` + `ports/` (1.475) | **es** el motor OpenViking; retirarlo eliminaría la arquitectura objetivo |
| `materialization/` (861) | convierte los artefactos de OpenViking en `CandidateBundle`; sin sustituto |
| `semantics/`, `normalization/`, `coverage/` (942) | reglas propias de preservación de predicados, identidad y unidades |
| `publication/` (800) | publicación gobernada con ACL; OpenViking no la sustituye |
| `projection/` (1.750) | proyección + **ciclo de vida del servidor aislado** que usa `vlm.py` |
| `validation/canonical.py` (104) | gobierno canónico: evidencia, duplicados, hashes |
| `validation/validators.py` (462) | gate de admisión del candidato en la ruta de `KuyenEngine` |
| `query/` (367), `importing/` (256) | F: función no cubierta por OpenViking y sin evidencia de que sobren |
| `errors.py` (196) | contrato público; contiene cambios previos sin commitear (§11) |

## 7. Código delegado a OpenViking

| capacidad | cómo se ejecuta ahora | prueba que lo demuestra |
|---|---|---|
| Extracción semántica | `KuyenEngine.build_async` → `SdkOpenVikingAdapter.compile` con Skill 1.3.0 | `tests/unit/test_014_materializer.py`, `test_engine_flow.py`, `test_013_ingestion.py` |
| L0/L1 | `SemanticProcessor` de OpenViking | experimentos 05 (`gpt-4o-mini`) y 07 (`gpt-6-luna`), L0/L1 persistidos con `generated_by: SemanticProcessor` |
| VLM y credencial | `ov.conf` → `vlm.*` con `${KUYEN_VLM_API_KEY}` | `tests/unit/test_vlm_configuration.py` (23 pruebas) + smoke real |
| Embeddings / índices | `embedding.*` de `ov.conf` | **no configurado** en este entorno (§11) |

## 8. Contratos públicos afectados o preservados

| contrato | estado |
|---|---|
| `kuyen.__all__` (28 símbolos) | **sin cambios** |
| `KuyenMemory` (todos sus métodos) | sin cambios |
| `build_document` | sin cambios |
| `KuyenEngine`, `KuyenConfig`, `ExecutionHandle`, `PublicationHandle` | sin cambios |
| `VlmProviderConfig`, `OpenVikingVlmRuntime`, `VlmConfigurationError` | sin cambios |
| Modelo canónico, sidecar, formatos persistidos, `unit_id` local a MAPU | sin cambios |
| `kuyen.errors` | sin cambios (incluye la jerarquía OpenAI como deuda, §11) |
| `from kuyen.extraction import …` | **deja de existir** (import interno no documentado, sin contrato) |

## 9. Pruebas ejecutadas y resultados

| comprobación | antes | después |
|---|---|---|
| Suite completa (`PYTHONPATH=src pytest -q`) | 388 tests · 386 passed · 0 failed · 0 errors · 2 skipped | **377 tests · 375 passed · 0 failed · 0 errors · 2 skipped** |
| `test_014_materializer`, `test_016_temporal`, `test_018_generalization`, `test_019` | verdes | verdes |
| `import kuyen` + `kuyen.__all__` | 28 símbolos | 28 símbolos |
| `importlib.util.find_spec("kuyen.extraction")` | presente | **`None`** |
| Wheel / sdist × Python 3.11 y 3.13 (quickstart fuera del repo) | 4/4 PASS | **4/4 PASS** |
| Contenido de la wheel con `extraction` | entradas presentes | **0** |

Los 11 casos retirados probaban exclusivamente el subsistema eliminado. Los 3 casos de
`test_016` y el caso restante de `test_018` que cubren código **conservado** se mantuvieron
(adaptados para no importar el módulo retirado): no se redujo cobertura de comportamiento del
código que permanece.

## 10. Limitaciones de la auditoría

1. **No se ejecutó la ruta OpenViking de extremo a extremo.** `KuyenEngine.build_async` requiere un
   OpenViking con `compile_api.base_url` configurado; hoy devuelve 503. Su sustituto se acredita con
   pruebas de contrato y con el adaptador, no con una compilación real de grafo.
2. **No se verificaron consumidores externos fuera de este repositorio.** No hay evidencia de
   ningún consumidor de `kuyen.extraction`; el paquete no la exportaba.
3. **La medición de LOC es del árbol de trabajo**, no del commit: 1.150 de las 1.542 líneas
   eliminadas estaban en `HEAD` y el resto eran ediciones locales sin commitear del experimento
   E2E_01 (preservadas como parche, §12).
4. **No se revisó el resto de repositorios** (`leftraruOS`, `runtime/memory_kuyen`): fuera de
   alcance por instrucción expresa.

## 11. Riesgos abiertos

| riesgo | impacto | mitigación |
|---|---|---|
| La jerarquía de errores OpenAI sigue en `errors.py` | código muerto (~20 líneas) en un módulo público | documentado; se retirará cuando se pueda aislar de los cambios locales de ese archivo |
| `compile` sin validar (503) | el grafo compilado no está demostrado | ADR lo declara explícitamente; siguiente experimento |
| Embeddings locales ausentes | cola de ingesta estancada, recuperación vectorial degradada | configurar `embedding.dense.provider` |
| `query/` e `importing/` sin ruta pública | mantenimiento de código no ejercitado | clasificados F; no se tocan |
| Commit aislado del resto | el commit **no** reproduce por sí solo un árbol verde, porque los cambios de hardening previos siguen sin commitear | declarado en el mensaje y en §12; el árbol de trabajo sí está verde |

## 12. Hashes y referencias para reproducir

| artefacto | ubicación |
|---|---|
| Estado Git inicial (HEAD, remoto, `status`, `diff --stat`) | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/git_state_initial.txt` |
| SHA-256 de 183 archivos antes de tocar nada | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/hashes_initial.txt` |
| Mapa de dependencias AST | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/graph.json` |
| Suite antes / después (JUnit XML + log) | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/logs/` |
| Distribución (wheel/sdist × 3.11/3.13) | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/30_distribution_verification.json` |
| Tests y parche archivados | `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/archived/` |
| Respaldo recuperable del árbol intervenido | `/tmp/kuyen_realign_01/backup/worktree_src_tests_docs.tgz` (`3d9ab695…`) |
| Recuperación del código retirado | `git show <commit>^:src/kuyen/extraction/openai_provider.py` |

## 13. Resultado final y decisión de promoción

- **Retirado:** `src/kuyen/extraction/` (7 archivos) y 11 casos de prueba que sólo probaban ese
  subsistema.
- **Conservado:** toda la autoridad canónica de KÜYEN y toda la integración con OpenViking.
- **Reducción:** `src/kuyen` 83 → 76 archivos, 15.932 → 14.390 líneas (−9,7 %); `tests/` 47 → 46
  archivos, 7.230 → 6.856 líneas.
- **Pruebas:** 377 · 375 passed · 0 failed · 2 skipped; distribución 4/4 PASS.
- **Promoción:** commit local con mensaje arquitectónico explícito. **Sin push, sin release, sin
  cambio de versión.**
