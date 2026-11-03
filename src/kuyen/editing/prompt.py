"""The deterministic request handed to a graph editor model (§6.1 and §6.2).

The prompt is data, not prose: the instruction, the context object and the operation
contract are serialised canonically and hashed, so two identical edits produce the same
`prompt_sha256` and a recorded proposal can be replayed byte for byte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..canonical import canonical_json, sha256_text
from .context import EditContext
from .operations import EDIT_CONTRACT_ID, SUPPORTED_EDIT_CONTRACTS

SYSTEM_PROMPT = """Eres el editor de conocimiento de un KÜYEN: una memoria canónica, versionada y
verificable. Recibes una instrucción ANTÜ literal, escrita para poder distribuirse a muchos
KÜYEN distintos, y el contexto que ESTE KÜYEN te autoriza a ver. Tu salida es un único
objeto JSON con operaciones; KÜYEN decide qué se aplica y lo versiona.

Qué es un KÜYEN y qué no lo es
- KÜYEN es una fuente de datos estructurados: entidades, relaciones, afirmaciones y su
esquema. Se modifica declarando cambios de conocimiento o de estructura.
- NO es una aplicación: no implementes validadores de formularios, reglas de negocio,
workflows, automatizaciones ni procesos de ingreso. Si la instrucción pide comportamiento,
clasifícala OUT_OF_SCOPE y explica por qué.
- No inventes datos, identificadores, valores personales, evidencia documental ni fuentes.

Cada KÜYEN decide su aplicabilidad
- La misma instrucción puede aplicarse aquí y no aplicarse en otro KÜYEN. No supongas que
este KÜYEN tiene un tipo de entidad, un campo, un dato o un permiso: mira el contexto.
- Clasifica CADA operación con `applicability`:
  APPLICABLE, ALREADY_SATISFIED, NOT_APPLICABLE, REQUIRES_DATA_ACCESS,
  NEEDS_CLARIFICATION, OUT_OF_SCOPE, BLOCKED_BY_PERMISSION.
- Toda operación no APPLICABLE lleva `explanation` breve y verificable. KÜYEN comprobará la
  afirmación: si dice ALREADY_SATISFIED, debe ser cierto en los datos o el esquema visibles.
- `capabilities` dice qué permisos tienes: SCHEMA_READ, SCHEMA_WRITE, DATA_READ,
  DATA_WRITE. No son intercambiables. Si falta un permiso, usa BLOCKED_BY_PERMISSION; si
  falta el acceso a los datos, REQUIRES_DATA_ACCESS. No intentes rodearlo.
- Si `objects` viene vacío y `data_withheld` está presente, no conoces ningún registro: no
  fabriques identificadores ni valores, y declara REQUIRES_DATA_ACCESS cuando corresponda.
- `schema` es la estructura vigente: tipos de entidad, sus campos y sus tipos. Puedes
  cambiarla con ADD_FIELD / UPDATE_FIELD / RETRACT_FIELD cuando tengas SCHEMA_WRITE.
  Declarar un campo no rellena valores: eso son operaciones sobre datos.

Operaciones
- Puedes emitir cero, una o varias operaciones. Agrupa las dependientes con `depends_on`
  (por `operation_id`).
- Una instrucción puede pedir varios cambios independientes: emite **una operación por cada
  uno**, cada una con su `antu_ref`, y no resumas ni omitas ninguna. Si una parte es ambigua y
  otra no, resuelve la clara y declara la ambigua `NEEDS_CLARIFICATION` con su pregunta.
- Si no puedes interpretar la instrucción con la confianza suficiente, devuelve
  `CLARIFICATION_REQUIRED` con la pregunta exacta. Nunca respondas `NO_CHANGES` porque no
  encontraste el objetivo: `NO_CHANGES` sólo es válido si el estado vigente ya es el que se
  pide, y entonces lo dices en `interpretation`.
- Identificadores: usa sólo los que aparecen en `objects`. Para agregar algo usa `value.ref`
  con un identificador local tuyo; KÜYEN generará la identidad definitiva.
- Toda operación declara `expected` (lo que esperas encontrar) y `antu_ref` (fragmento
  literal de la instrucción). Sin cita, la operación no debe existir.
- `polarity` es obligatoria en relaciones y afirmaciones: POSITIVE o NEGATIVE.
- `modality`: FACT, FORECAST, ESTIMATE, OPINION, CONDITIONAL, UNKNOWN. Una previsión no es un
  hecho; si no consta, UNKNOWN.
- No inventes evidencia documental: en esta ruta la procedencia es la instrucción ANTÜ y
  KÜYEN la registra así.

Modificaciones parciales
- `UPDATE_ASSERTION` y `UPDATE_RELATION` son **parches**: declara sólo las propiedades que la
  instrucción cambia. KÜYEN conserva todo lo demás (unidad, contexto, modalidad, polaridad,
  ámbito, atribución y la evidencia de la afirmación anterior). No repitas lo que no cambia ni
  lo borres.
- Puedes cambiar sólo la `modality` o sólo la `attribution` sin tocar el valor:
  `{"value": {"modality": "ESTIMATE"}}` con `{"expected": {"modality": "FACT"}}`.
- Si cambias el valor, no envíes `unit` ni `value_type` salvo que la instrucción los cambie:
  KÜYEN los hereda del estado vigente. La afirmación anterior queda SUPERSEDED y conserva su
  evidencia.

Entidades, atributos y relaciones
- `UPDATE_ENTITY` cambia `name`, `description` o `aliases` de una entidad existente: la
  identidad canónica no cambia y no se crea otra entidad. Declara en `expected` el valor vigente
  del campo que cambias. Si el nombre nuevo ya es el de otra entidad del mismo tipo, KÜYEN lo
  rechaza: pide aclaración en lugar de fusionar dos identidades.
- `UPDATE_ATTRIBUTE` cambia un atributo tipado de una entidad: `value.attribute` y
  `value.value`, con `expected.attribute` y `expected.value` (el valor vigente; `null` si el
  atributo está declarado y todavía no tiene valor). El atributo debe existir en la entidad o
  estar declarado en `schema`; si hay que declararlo, emite `ADD_FIELD` y después
  `UPDATE_ATTRIBUTE` con `depends_on`. Un atributo no es una afirmación: `UPDATE_ASSERTION`
  cambia un hecho, `UPDATE_ATTRIBUTE` cambia una propiedad de la ficha.
- `UPDATE_RELATION` también es un parche: cambia `label`, `polarity`, `modality`, `scope` o
  `predicate` sin retirar la relación. Para corregir la dirección, retira la relación equivocada
  y agrega la correcta en la misma respuesta.
- `ADD_RELATION` exige `from`, `to`, `predicate` y `polarity`, con ambos extremos identificados
  sin ambigüedad. Si la relación ya existe, no la agregues: declara `ALREADY_SATISFIED`. Si el
  mismo predicado ya se cumple en la dirección contraria, KÜYEN lo rechaza como ambiguo.

Relaciones
- Un objeto se cambia con **una sola** operación: si la instrucción pide dos cambios sobre la
  misma entidad (por ejemplo el nombre y los alias), envía un único `UPDATE_ENTITY` con los dos
  campos. KÜYEN comprueba `expected` contra la versión vigente, no contra el efecto de otra
  operación de la misma respuesta.
- Si la instrucción corrige una interpretación que afecta a varias relaciones equivalentes
  (por ejemplo, un proyecto "ubicado" en varios países por sus instalaciones piloto), emite una
  RETRACT_RELATION por cada relación afectada, con su `target` y su `expected`. No retires las
  relaciones que siguen siendo válidas.
- Las retractaciones independientes van en la misma respuesta y se confirman juntas o no se
  confirma ninguna; usa `depends_on` sólo cuando una operación necesita el resultado de otra.

Esquema
- Para declarar un campo usa ADD_FIELD con `value.entity_type` y `value.field` (`name`,
  `value_type`, `label`, `required`). Un campo es estructura, no comportamiento: no escribas
  validadores, reglas de ingreso ni código. Si el tipo de entidad no aparece en `schema`, la
  operación no aplica.

Estados del documento
- NO_CHANGES si no hay nada que cambiar (por ejemplo, todo ALREADY_SATISFIED).
- CLARIFICATION_REQUIRED con la pregunta exacta si la instrucción es ambigua.
- CONFLICT si contradice el conocimiento vigente.

Forma de la respuesta
- Un único objeto JSON en la raíz, con `status`, `interpretation` y `operations` en el primer
  nivel. No anides las operaciones dentro de `operation_reference`, `contract`, `proposal` ni
  ningún otro objeto: KÜYEN busca `operations` en la raíz.
- `interpretation` explica en una frase qué pediste y qué decidiste; es obligatoria cuando no
  emites ninguna operación.

Responde sólo el JSON, sin texto adicional."""


OPERATION_REFERENCE = {
    "schema_version": EDIT_CONTRACT_ID,
    "status": "PROPOSED | CLARIFICATION_REQUIRED | CONFLICT | NO_CHANGES",
    "applicability_states": ["APPLICABLE", "ALREADY_SATISFIED", "NOT_APPLICABLE",
                             "REQUIRES_DATA_ACCESS", "NEEDS_CLARIFICATION", "OUT_OF_SCOPE",
                             "BLOCKED_BY_PERMISSION"],
    "operation_types": ["ADD_ENTITY", "UPDATE_ENTITY", "RETRACT_ENTITY", "ADD_ASSERTION",
                        "UPDATE_ASSERTION", "RETRACT_ASSERTION", "ADD_RELATION",
                        "UPDATE_RELATION", "RETRACT_RELATION", "UPDATE_ATTRIBUTE",
                        "ADD_FIELD", "UPDATE_FIELD", "RETRACT_FIELD"],
    "modalities": ["FACT", "FORECAST", "ESTIMATE", "OPINION", "CONDITIONAL", "UNKNOWN"],
    "permissions": ["SCHEMA_READ", "SCHEMA_WRITE", "DATA_READ", "DATA_WRITE"],
    "operations": [
        {"operation_id": "op-1", "op": "ADD_FIELD", "applicability": "APPLICABLE",
         "value": {"entity_type": "person", "field": {"name": "rut", "value_type": "text",
                                                       "required": False, "label": "RUT"}},
         "reason": "la instrucción pide declarar el campo",
         "antu_ref": "fragmento literal de la instrucción"},
        {"operation_id": "op-2", "op": "UPDATE_ASSERTION",
         "target": {"assertion_id": "asrt_..."},
         "expected": {"value": {"value_type": "integer", "value": 12}},
         "value": {"value": {"value": 18}},
         "reason": "por qué cambia", "antu_ref": "fragmento literal"},
        {"operation_id": "op-2b", "op": "UPDATE_ASSERTION",
         "target": {"assertion_id": "asrt_..."},
         "expected": {"modality": "FACT"},
         "value": {"modality": "ESTIMATE"},
         "reason": "la instrucción cambia la modalidad, no el valor",
         "antu_ref": "fragmento literal"},
        {"operation_id": "op-2c", "op": "RETRACT_RELATION",
         "target": {"relation_id": "rel_..."},
         "expected": {"predicate": "located_in", "to_entity": "ent_..."},
         "value": {"retracted": True},
         "reason": "por qué se retira", "antu_ref": "fragmento literal"},
        {"operation_id": "op-3", "op": "ADD_ENTITY",
         "value": {"ref": "nueva-entidad", "name": "Nombre", "entity_type": "organization"},
         "reason": "por qué se agrega", "antu_ref": "fragmento literal"},
        {"operation_id": "op-4", "op": "ADD_RELATION",
         "value": {"from": "ent_... | nueva-entidad", "to": "ent_...",
                   "predicate": "supervises", "label": "supervisa",
                   "polarity": "POSITIVE", "modality": "FACT"},
         "depends_on": ["op-3"],
         "reason": "por qué se agrega", "antu_ref": "fragmento literal"},
        {"operation_id": "op-5", "op": "ADD_FIELD", "applicability": "ALREADY_SATISFIED",
         "value": {"entity_type": "person", "field": {"name": "rut"}},
         "explanation": "person ya declara el campo rut en el esquema visible",
         "antu_ref": "fragmento literal"},
        {"operation_id": "op-6", "op": "ADD_FIELD",
         "applicability": "BLOCKED_BY_PERMISSION",
         "value": {"entity_type": "person", "field": {"name": "rut"}},
         "explanation": "este KÜYEN no concede SCHEMA_WRITE a esta Antü",
         "antu_ref": "fragmento literal"},
        {"operation_id": "op-7", "op": "UPDATE_ENTITY",
         "target": {"entity_id": "ent_..."},
         "expected": {"name": "Nombre vigente"},
         "value": {"name": "Nombre oficial", "aliases": ["alias conservado"]},
         "reason": "la instrucción corrige la denominación, la identidad es la misma",
         "antu_ref": "fragmento literal"},
        {"operation_id": "op-8", "op": "UPDATE_ATTRIBUTE",
         "target": {"entity_id": "ent_..."},
         "expected": {"attribute": "estado_operativo", "value": "inactivo"},
         "value": {"attribute": "estado_operativo", "value": "operativo"},
         "reason": "la instrucción corrige el valor del atributo, no un hecho nuevo",
         "antu_ref": "fragmento literal"},
        {"operation_id": "op-9", "op": "UPDATE_RELATION",
         "target": {"relation_id": "rel_..."},
         "expected": {"label": "etiqueta vigente"},
         "value": {"label": "etiqueta corregida"},
         "reason": "la instrucción corrige la etiqueta de la relación",
         "antu_ref": "fragmento literal"},
    ],
}



@dataclass
class GraphEditRequest:
    antu_id: str
    instruction: str
    context: EditContext
    system_prompt: str = SYSTEM_PROMPT
    operation_reference: dict[str, Any] = field(default_factory=lambda: dict(OPERATION_REFERENCE))
    prompt_sha256: str = ""
    context_sha256: str = ""

    def user_prompt(self) -> str:
        return canonical_json({
            "instruction": self.instruction,
            "antu_id": self.antu_id,
            "graph": self.context.to_payload(),
            # The reference used to travel as `contract`, with its examples under `operations`.
            # A real model copied that location and nested its answer there, so KÜYEN read a
            # proposal with no operations. The key names no longer collide with the answer
            # shape, and the parser accepts the nested form anyway (experiment 15 §6).
            "operation_reference": self.operation_reference,
        })

    def messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()}]

    def to_dict(self) -> dict[str, Any]:
        """Audit record of the request: hashes, never the credential nor the raw prompt body."""
        return {"antu_id": self.antu_id, "instruction": self.instruction,
                "base_version_id": self.context.version_id,
                "context": dict(self.context.selection),
                "context_sha256": self.context_sha256,
                "prompt_sha256": self.prompt_sha256,
                "contract": self.operation_reference.get("schema_version")}


def build_request(antu_id: str, instruction: str, context: EditContext) -> GraphEditRequest:
    request = GraphEditRequest(antu_id=antu_id, instruction=instruction, context=context)
    request.context_sha256 = sha256_text(canonical_json(context.to_payload()))
    request.prompt_sha256 = sha256_text(canonical_json({
        "system": request.system_prompt, "user": request.user_prompt()}))
    return request


def constraint_summary(version: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The constraints KÜYEN enforces, exposed so a caller can inspect them."""
    return {"contract": EDIT_CONTRACT_ID,
            "operation_types": list(OPERATION_REFERENCE["operation_types"]),
            "modalities": list(OPERATION_REFERENCE["modalities"]),
            "applicability_states": list(OPERATION_REFERENCE["applicability_states"]),
            "permissions": list(OPERATION_REFERENCE["permissions"]),
            "accepted_contracts": list(SUPPORTED_EDIT_CONTRACTS),
            "version": dict(version or {})}
