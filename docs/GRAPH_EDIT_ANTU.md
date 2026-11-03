# EDICIÓN DEL GRAFO POR ANTÜ (ES)

Este documento describe la segunda forma de evolucionar un KÜYEN: la instrucción directa.
Está escrito para quien va a usarla y para quien va a auditarla.

English version: [`GRAPH_EDIT_ANTU.en.md`](GRAPH_EDIT_ANTU.en.md).

---

## 1. Las dos formas de evolucionar un KÜYEN

| | Camino A — documento | Camino B — instrucción |
| --- | --- | --- |
| Entrada | un documento libre (MAPU) | una instrucción ANTÜ literal |
| Motor | **OpenViking** + Skill `knowledge-graph` | un **LLM** que sólo propone |
| Qué produce | entidades, relaciones, afirmaciones y evidencia textual | operaciones estructuradas sobre el grafo existente |
| Quién decide | KÜYEN (gate determinista) | KÜYEN (validador determinista) |
| Procedencia | `DOCUMENT_EVIDENCE` | `ANTU_INSTRUCTION` |
| Puede declarar `SOURCE_VERIFIED` | **sí** | **nunca** |
| Punto de entrada | `kuyen.incorporate_document` | `kuyen.apply_graph_edit` / `KuyenMemory.apply_antu` |

`kuyen.product.classify_antu` clasifica la instrucción y **falla** si el tipo no se conoce.
Un ANTÜ de edición nunca arranca OpenViking; un ANTÜ documental nunca usa el editor.

Un ANTÜ puede necesitar dos etapas (incorporar un documento y después corregir el grafo).
Son dos operaciones, dos versiones y dos linajes: no se mezclan.

## 2. Flujo de una edición

```
instrucción + versión vigente
   → contexto determinista        (editing.context)
   → petición hasheada al modelo  (editing.prompt, editing.editors)
   → propuesta parseada           (editing.operations)
   → validación determinista      (editing.validator)
   → aplicación determinista      (editing.applier)
   → commit canónico              (storage.commit, el mismo de siempre)
```

La interpretación ocurre **fuera** del lock de escritura; la validación y el commit
ocurren **dentro** y vuelven a comprobar la versión de origen. Si otro ANTÜ avanzó el
grafo entretanto, el commit se rechaza con `STALE_BASE` y no se escribe nada.

## 3. Contrato de la propuesta (`kuyen-graph-edit-v1`)

```json
{
  "schema_version": "kuyen-graph-edit-v1",
  "status": "PROPOSED | CLARIFICATION_REQUIRED | CONFLICT | NO_CHANGES",
  "antu_id": "opcional, KÜYEN lo deriva de la instrucción",
  "base_version_id": "opcional, debe coincidir con la versión del contexto",
  "interpretation": "qué entendió el modelo",
  "clarification": {"question": "..."},
  "conflict": {"reason": "..."},
  "operations": [
    {
      "operation_id": "op-1",
      "op": "UPDATE_ASSERTION",
      "target": {"assertion_id": "asrt_..."},
      "expected": {"value": {"value_type": "integer", "value": 12}},
      "value": {"value": {"value_type": "integer", "value": 18}},
      "reason": "por qué cambia el conocimiento",
      "antu_ref": "fragmento literal de la instrucción"
    }
  ]
}
```

Operaciones admitidas: `ADD_ENTITY`, `UPDATE_ENTITY`, `ADD_ASSERTION`,
`UPDATE_ASSERTION`, `RETRACT_ASSERTION`, `ADD_RELATION`, `UPDATE_RELATION`,
`RETRACT_RELATION`, `UPDATE_ATTRIBUTE`.

Reglas que KÜYEN exige y verifica:

* toda operación que **modifica o retira** declara `expected` (el valor que espera
  encontrar). Para campos escalares la comparación es exacta; para un campo con objeto
  (`value`, `temporal`) basta con declarar las claves en las que te apoyas: cada clave
  declarada debe coincidir con el valor actual, y un objeto vacío no cuenta como control;
* toda operación cita la instrucción en `antu_ref`; un fragmento literal o una paráfrasis
  fiel (≥80 % de sus palabras presentes) se acepta, una justificación inventada no;
* para agregar hay que proponer un identificador **local** (`value.ref`); la identidad
  canónica la genera KÜYEN y es determinista, así que repetir la instrucción no duplica;
* `polarity` es obligatoria en relaciones y afirmaciones (`POSITIVE` o `NEGATIVE`);
* `modality` es `FACT`, `FORECAST`, `ESTIMATE`, `OPINION`, `CONDITIONAL` o `UNKNOWN`; si
  falta, se guarda `UNKNOWN`, nunca `FACT`;
* ninguna operación puede inventar evidencia: en este camino no hay MAPU, cita, offset ni
  hash.

## 4. Estados del resultado

| Estado | Significado | ¿Versión nueva? |
| --- | --- | --- |
| `COMMITTED` | la propuesta se validó y se confirmó | sí |
| `VALIDATED` | `dry_run=True`: validada, no escrita | no |
| `REJECTED` | alguna operación o el candidato completo no cumple el contrato | no |
| `CLARIFICATION_REQUIRED` | la instrucción es ambigua; el modelo pide precisión | no |
| `CONFLICT` | la instrucción contradice el grafo o la base cambió (`STALE_BASE`) | no |
| `NO_CHANGES` | la interpretación no produce operaciones | no |
| `INTERPRETATION_FAILED` | la salida del modelo no es el contrato | no |
| `REPLAYED` | ese `antu_id` ya terminó; se devuelve el resultado anterior | no |

Un rechazo deja el grafo intacto y queda registrado en el ledger para siempre.

## 5. Procedencia

Cada objeto creado o modificado por una instrucción lleva:

```json
"origin": {
  "kind": "ANTU_INSTRUCTION",
  "antu_id": "ANTU-...",
  "instruction": "texto literal",
  "instruction_sha256": "…",
  "base_version_id": "VER-…",
  "actor": {"authenticated_user": "…"},
  "model": {"provider": "…", "model": "…"},
  "reason": "…",
  "documentary_verification": false
}
```

y `status: "INSTRUCTED"`. `kuyen.validation.canonical` **rechaza** cualquier objeto con
origen `ANTU_INSTRUCTION` que declare `SOURCE_VERIFIED`.


## 6. Correcciones y retractaciones

* corregir una afirmación o relación **no borra** la anterior: la anterior queda
  `SUPERSEDED` con `superseded_by`, la nueva apunta con `supersedes` y no hereda evidencia;
* retirar deja el objeto con `status: "RETRACTED"`, `retracted: true` y `retraction`
  (ANTÜ, motivo, fecha, hash de la instrucción);
* `memory.current_objects(group)` devuelve sólo lo vigente; `memory.graph()` devuelve el
  registro completo, historia incluida.

## 7. Diferencias entre versiones

`memory.diff(antes, despues)` devuelve, por colección: `added`, `modified` (con los campos
que cambiaron), `removed_from_current_view` (retractado o superado), `restored`, `deleted`
(siempre vacío: KÜYEN no borra) y `unchanged`. Es determinista: el mismo par de versiones
produce siempre el mismo documento. Sin argumentos compara la versión actual con su padre.

## 8. Configuración del editor

| Variable | Significado |
| --- | --- |
| `KUYEN_EDITOR_PROVIDER` | hoy sólo `openai-compatible` |
| `KUYEN_EDITOR_MODEL` | obligatorio: no hay modelo por defecto ni fallback |
| `KUYEN_EDITOR_ENDPOINT` | base del endpoint (`/chat/completions` se añade) |
| `KUYEN_EDITOR_API_KEY_ENV` | nombre de la variable que contiene la credencial |
| `KUYEN_EDITOR_TEMPERATURE`, `KUYEN_EDITOR_MAX_TOKENS`, `KUYEN_EDITOR_TIMEOUT_S` | parámetros |
| `KUYEN_EDITOR_JSON_MODE` | `true` para pedir `response_format: json_object` |

La credencial se lee en el momento de la llamada, nunca se guarda en la configuración, no
viaja en el prompt y no aparece en el ledger ni en los resultados (sólo proveedor, modelo y
huella de la propuesta).

El **consumo** (`usage`: tokens de entrada y salida) se registra en el ledger y en el
resultado de la operación, **nunca** en la procedencia que entra en el hash canónico de la
versión: la identidad del conocimiento no puede depender de la facturación.

`RecordedGraphEditor` reproduce una propuesta ya grabada, indexada por `prompt_sha256`:
permite auditar y demostrar una edición sin llamar a ningún modelo.

## 9. Contexto que recibe el modelo

* grafo pequeño (≤200 objetos): índice completo, para que no falte nada relevante;
* grafo grande: selección por palabras clave de la instrucción + cierre de un salto, con
  informe de qué quedó fuera (`selection.truncated`);
* en ambos casos el conjunto incluido es el **ámbito autorizado**: una operación sobre un
  objeto que existe pero no está en el contexto se rechaza con `TARGET_NOT_IN_CONTEXT`
  (distinto de `TARGET_NOT_FOUND`, que significa que el objeto no existe en esa versión).

## 10. Qué NO hace este camino

* no lee documentos ni MAPU;
* no rellena evidencia ni citas;
* no convierte una previsión en hecho;
* no aplica nada parcialmente: una operación inválida rechaza el ANTÜ completo;
* no reescribe ni elimina versiones anteriores.

## 11. Ejemplo mínimo

```python
from kuyen import KuyenMemory, EditorConfig, OpenAICompatibleGraphEditor

memory = KuyenMemory.open("/var/lib/kuyen")
editor = OpenAICompatibleGraphEditor(EditorConfig.from_env())

resultado = memory.apply_antu(
    "Cambia la cantidad de luminarias de 12 a 18",
    editor=editor,
    actor={"leftraru_id": "LR-1", "authenticated_user": "ana"},
    dry_run=True,          # valida y no escribe; quítalo para confirmar
)

resultado.status            # COMMITTED | VALIDATED | REJECTED | CONFLICT | ...
resultado.version_id        # la versión nueva, o None
resultado.operations        # operaciones aceptadas
resultado.rejected          # [{operation_id, op, code, message}]
resultado.provenance        # {kind: ANTU_INSTRUCTION, documentary_verification: False, ...}
resultado.diff              # qué cambió exactamente
resultado.clarification     # la pregunta, si la instrucción era ambigua
resultado.model             # proveedor, modelo, hashes y consumo
```

`dry_run=True` produce `VALIDATED` y no escribe nada: sirve para revisar antes de
confirmar. Sin `dry_run`, o con `commit`, el resultado es `COMMITTED` y el grafo tiene una
versión nueva.

