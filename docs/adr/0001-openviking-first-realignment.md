# ADR 0001 — Realineamiento arquitectónico: KÜYEN como autoridad canónica sobre OpenViking

- **Estado:** Aceptado
- **Fecha:** 2026-11-02
- **Base:** `HEAD 5fd8777` (*Release KÜYEN 0.2.0*), `VERSION 0.2.1rc1`
- **Informe de auditoría:** [docs/architecture/audits/OPENVIKING_FIRST_REALIGNMENT.md](../architecture/audits/OPENVIKING_FIRST_REALIGNMENT.md)
- **Evidencia reproducible:** `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/`

---

## Contexto

KÜYEN evolucionó en dos etapas que dejaron rastros superpuestos en el mismo paquete.

Antes de disponer de una integración efectiva con OpenViking se desarrollaron **rutas propias** de
extracción, procesamiento y materialización. La más completa fue `src/kuyen/extraction/`
(`OpenAIExtractionProvider` + `BudgetLedger` + `extraction_to_provider_result` + esquema de
Structured Outputs + evaluación de cobertura fáctica): 1.347 líneas que llamaban directamente a la
API de OpenAI desde dentro de KÜYEN.

La incorporación de OpenViking como motor interno cambió la distribución de responsabilidades,
pero el código anterior **no se retiró**. El resultado fue un paquete con dos arquitecturas
paralelas:

- una ruta OpenViking (`KuyenEngine` → `SdkOpenVikingAdapter.compile` con Skill → `read_candidate`
  → `AcceptanceGate`), pública, funcional y **sin documentar**;
- una ruta OpenAI directa, **completa, probada y sin un solo consumidor** en `src/`, no exportada
  y sin mención alguna en la documentación pública.

La auditoría `KUYEN_OPENVIKING_INTERNAL_MATERIALIZATION_TRACE_04` confirmó que ningún módulo de
`src/kuyen` importaba `kuyen.extraction`, que la palabra «OpenAI» no aparecía en ningún documento
público, y que el contrato del README («it is not an LLM and it does not produce knowledge by
itself») contradecía la existencia de ese motor dentro del paquete.

## Decisión

**OpenViking es el motor interno de materialización y contexto.** Le corresponden la ingesta, el
parsing, el procesamiento semántico L0/L1, el VLM, los embeddings y los índices, la recuperación de
contexto, la ejecución de Skills y la generación de candidatos de grafo, en la medida en que sus
capacidades reales lo permitan.

**KÜYEN conserva la autoridad sobre el conocimiento canónico**: identidad y procedencia de MAPU,
identidad de `SOURCE_UNIT` (local a su MAPU), validación de evidencia (cita, offsets, hashes,
correspondencia con el documento), contratos de afirmaciones y relaciones, reglas de admisión,
commit canónico, versionado, ledger, recuperación, linaje y consulta del conocimiento confirmado.

**Se retira `src/kuyen/extraction/`** — y sólo eso — porque su redundancia quedó demostrada: no
tiene consumidores en el paquete, su responsabilidad (producción de candidatos) es exactamente la
que OpenViking ejecuta con la Skill `knowledge-graph` sobre el mismo contrato de resultado de
proveedor (`kuyen-provider-result-v1`, validado por `materialization/contract.py`), y su existencia
mantiene abierta una segunda ruta de inferencia que el contrato público del producto niega.

## Motivo

1. **Una sola arquitectura.** Dos rutas de producción de conocimiento con la misma salida es una
   fuente permanente de decisiones ambiguas: cada nueva capacidad admite dos implementaciones.
2. **Coherencia con el contrato público.** El README declara que KÜYEN no produce conocimiento por
   sí mismo; el paquete contenía un motor de extracción LLM completo.
3. **Superficie de mantenimiento.** 1.347 líneas, siete archivos y tres módulos de prueba dedicados
   a un subsistema sin ruta de ejecución.
4. **Riesgo de deriva silenciosa.** El experimento inmediatamente anterior a la auditoría
   (`KUYEN_OPENAI_DOCUMENT_TO_GRAPH_E2E_01`) estaba empezando a **institucionalizar** esa ruta (un
   `OpenAIConfig` público y un `ingest_document` con proveedor de modelo). Sin esta decisión, la

## Consecuencias

### Capacidades delegadas a OpenViking

| Capacidad | Antes en KÜYEN | Ahora |
|---|---|---|
| Extracción semántica de entidades/relaciones/afirmaciones | `extraction/openai_provider.py` | OpenViking (Skill + VLM configurado por KÜYEN) |
| Generación de L0/L1 | no existía en KÜYEN | OpenViking `SemanticProcessor` (demostrado en los experimentos 05 y 07) |
| Embeddings e índices vectoriales | no existían en KÜYEN | OpenViking (`embedding.*` de `ov.conf`) |
| Contabilidad de coste de llamadas al modelo | `extraction/budget.py` | fuera de KÜYEN: lo gestiona OpenViking |
| Esquema JSON de salida estructurada del modelo | `extraction/schema.py` | Skill `knowledge-graph` + contrato `kuyen-provider-result-v1` |

### Capacidades que permanecen en KÜYEN (sin cambios)

Procedencia canónica (`provenance.py`, `ingest.py`), almacenamiento y commit (`storage/`), ciclo de
vida y ledger (`lifecycle/`), validación canónica (`validation/canonical.py`), sidecar, backup y
recuperación (`sidecar/`, `backup/`, `recovery/`), versionado y registro (`storage/versions.py`,
`storage/registry.py`), API pública (`api/memory.py`) y la integración con OpenViking (`engine.py`,
`adapters/`, `vlm.py`, `materialization/`, `validation/validators.py`, `semantics/`,
`normalization/`, `coverage/`, `serialization/`, `publication/`, `projection/`, `ports/`,
`skills/`).

### Código eliminado

`src/kuyen/extraction/` (7 archivos, 1.542 líneas en el árbol de trabajo; 1.150 de ellas ya estaban
en `HEAD`) y los tests que sólo probaban ese subsistema (`tests/unit/test_015_extraction.py`
completo y dos casos individuales de `test_016_temporal.py` y `test_018_generalization.py`). Los
tres archivos quedan archivados como evidencia en
`experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/archived/`, junto con un parche con las
ediciones locales que ese subsistema tenía sin commitear.

### Contratos preservados

`kuyen.__all__` (28 símbolos) no cambia: `extraction` nunca fue parte de la superficie pública.
`build_document`, `KuyenMemory`, `KuyenEngine`, `VlmProviderConfig`, `OpenVikingVlmRuntime`, el
modelo canónico y los formatos persistidos siguen intactos.

### Limitaciones abiertas

1. **La ruta OpenViking sigue sin documentación pública.** `KuyenEngine` + `SdkOpenVikingAdapter`
   son el motor, pero `ADAPTERS.md` no los describe y `PUBLIC_API.md` no los menciona. Retirar la
   ruta alternativa no arregla por sí solo esa carencia.
2. **`compile` no está validado de extremo a extremo.** `compile_api.base_url` sigue vacío y
   devuelve 503; el VLM y L0/L1 sí están demostrados (experimentos 05 y 07), el grafo compilado no.
3. **Los embeddings locales no están configurados** (`llama-cpp-python` ausente): la cola de
   ingesta no avanza y la recuperación vectorial queda degradada.
4. **`fact_coverage.py` era el banco de evaluación de cobertura fáctica.** Se archiva como
   evidencia; hoy no hay un arnés equivalente.

### Deuda técnica no resuelta en esta decisión

- Las cuatro clases de error de la jerarquía OpenAI (`OpenAIProviderError`,
  `OpenAIBudgetExceededError`, `OpenAIExtractionError`, `OpenAIConfigurationError`) siguen en
  `src/kuyen/errors.py`. No se retiraron porque ese archivo tiene **cambios locales previos sin
  commitear** y mezclarlos en este commit habría violado la separación exigida.
- `projection/openviking.py` mantiene un cliente HTTP propio que duplica operaciones que el SDK de
  OpenViking ya ofrece (`content/write`, `content/read`, `fs/*`, `search/grep`). Delegarlo exige
  reescribir una ruta que hoy funciona y no se hizo aquí.

### Consumidores externos

Ningún consumidor podía usar `kuyen.extraction` a través de la API pública (no se exportaba). Un
consumidor que la importara directamente deja de poder hacerlo; era un import de módulo interno,
sin contrato ni documentación. La migración es usar el motor OpenViking (`KuyenEngine`) o la
configuración pública del VLM (`VlmProviderConfig` + `OpenVikingVlmRuntime`).

## Decisiones no tomadas

- **No se retiró `importing/`** (253 líneas, sólo usado por un test) ni **`query/`** (364 líneas,
  idem): su función no está cubierta por OpenViking y no hay evidencia de que sobren. Quedan como
  `UNCERTAIN_DO_NOT_DELETE`.
- **No se tocó `engine.py`, `adapters/`, `materialization/`, `semantics/`, `normalization/`,
  `coverage/`, `publication/`, `projection/`** (≈4.700 líneas): son la integración con OpenViking,
  no duplicación.
- **No se validó ni se anuncia Compile Runtime ni la Skill de Knowledge Graph de extremo a
  extremo.** Siguen sin estar demostradas; este ADR no las presenta como implementadas.
- **No se reescribió** ningún módulo para uniformar estilo, ni se introdujeron abstracciones,
  dependencias ni frameworks nuevos.

## Referencias

- Informe de auditoría: `docs/architecture/audits/OPENVIKING_FIRST_REALIGNMENT.md`
- Evidencia y archivo: `experiments/KUYEN_OPENVIKING_FIRST_REALIGNMENT_01/`
- Configuración VLM demostrada: `docs/KUYEN_OPENVIKING_VLM_CONFIGURATION_05.md`
- Smoke con `gpt-4o-mini`: `experiments/KUYEN_OPENVIKING_VLM_CONFIGURATION_05/`
- Smoke con `gpt-6-luna`: `experiments/KUYEN_OPENVIKING_LUNA_SMOKE_07/`

   ruta habría pasado a ser API pública.
