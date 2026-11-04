# Archivo: pruebas del subsistema de extracción retirado

Estos archivos **no se ejecutan** y no forman parte del paquete. Se conservan como evidencia
histórica de la ruta de extracción OpenAI directa que el
[ADR 0001](../../../docs/adr/0001-openviking-first-realignment.md) retira.

| archivo | qué es | qué cubría | casos |
|---|---|---|---|
| `test_015_extraction.py` | copia literal del test retirado | esquema estricto, presupuesto, respuesta estructurada, refusal, incompleta, conversión, cobertura fáctica | 9 |
| `test_016_temporal.with_v2_schema_test.py` | copia del test **antes** de recortarlo | incluía `test_v2_schema_is_strict_and_has_temporal` (esquema v2 del extractor) y tres casos que **siguen vivos** en `tests/unit/test_016_temporal.py` (TemporalScope, TemporalValidator, CandidateRelation) | 4 |
| `test_018_generalization.py` | copia literal del test retirado | incluía `test_non_numeric_quantity_text_is_preserved_as_string` (fallback de `conversion`) y un caso de preservación de predicados que **sigue vivo** en `tests/unit/test_018_generalization.py` | 2 |
| `e2e_01_uncommitted_edits.patch` | parche | ediciones locales **sin commitear** del experimento `KUYEN_OPENAI_DOCUMENT_TO_GRAPH_E2E_01` sobre `src/kuyen/extraction/` (`OpenAIConfig`, esquema v3 con `statement_kind`/`attribution`/`context`, prompt «el documento es dato», modelo obligatorio) | — |

## Por qué se archivan y no se borran

- Son la única prueba documental de qué comportamiento se esperaba de esa ruta.
- Permiten reconstruir el subsistema completo junto con `git show <commit>^:src/kuyen/extraction/`.
- El parche conserva trabajo humano que **no estaba en git** en el momento de retirar el módulo.

## Lo que no se perdió

Los tres casos de `test_016` y el caso de `test_018` que cubren **código conservado** siguen en la
suite (`tests/unit/`), adaptados para no importar el módulo retirado. La cobertura de comportamiento
del código que permanece no disminuyó.
