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
from .operations import EDIT_CONTRACT_ID

SYSTEM_PROMPT = """Eres el editor semántico del KÜYEN de una unidad Leftraru.

Recibes una instrucción ANTÜ literal, la versión vigente del grafo y el contexto
autorizado (entidades, relaciones, afirmaciones y evidencias con sus identificadores
canónicos). Tu única salida es un objeto JSON que describe operaciones sobre ese grafo.

Reglas que no puedes romper:
1. No devuelvas el grafo completo: devuelve sólo operaciones.
2. Los identificadores canónicos que no aparezcan en el contexto no existen. No los
   inventes. Para agregar algo usa `value.ref` con un identificador local tuyo; KÜYEN
   generará la identidad definitiva.
3. Sólo puedes tocar objetos incluidos en `objects`. Si lo que la instrucción pide no
   está en el contexto, responde `status: "CLARIFICATION_REQUIRED"`.
4. Toda operación declara `expected` (el valor que esperas encontrar) y `antu_ref` (el
   fragmento literal de la instrucción que la respalda). Si no puedes citar la
   instrucción, la operación no debe existir.
5. `polarity` es obligatoria en relaciones y afirmaciones: POSITIVE o NEGATIVE. No
   inventes una polaridad: si la instrucción no la determina, pide aclaración.
6. `modality` es FACT, FORECAST, ESTIMATE, OPINION, CONDITIONAL o UNKNOWN. Una previsión
   no es un hecho; si no sabes, usa UNKNOWN.
7. No inventes evidencia documental: no hay MAPU, cita, offset ni hash en esta ruta. La
   procedencia de lo que agregues es la instrucción ANTÜ y KÜYEN la registra así.
8. Si la instrucción contradice el grafo, responde `status: "CONFLICT"` explicando el
   conflicto. Si es ambigua, `status: "CLARIFICATION_REQUIRED"` con la pregunta exacta.
9. Si no hay nada que cambiar, responde `status: "NO_CHANGES"` con `operations: []`.

Responde sólo el JSON, sin texto adicional."""

OPERATION_REFERENCE = {
    "schema_version": EDIT_CONTRACT_ID,
    "status": "PROPOSED | CLARIFICATION_REQUIRED | CONFLICT | NO_CHANGES",
    "operations": [
        {"operation_id": "op-1", "op": "UPDATE_ASSERTION",
         "target": {"assertion_id": "asrt_..."},
         "expected": {"value": {"value_type": "integer", "value": 12}},
         "value": {"value": {"value_type": "integer", "value": 18}},
         "reason": "por qué cambia", "antu_ref": "fragmento literal de la instrucción"},
        {"operation_id": "op-2", "op": "ADD_ENTITY",
         "value": {"ref": "nueva-entidad", "name": "Nombre", "entity_type": "organization"},
         "reason": "por qué se agrega", "antu_ref": "fragmento literal"},
        {"operation_id": "op-3", "op": "ADD_RELATION",
         "value": {"from": "ent_... | nueva-entidad", "to": "ent_...",
                   "predicate": "supervises", "label": "supervisa",
                   "polarity": "POSITIVE", "modality": "FACT"},
         "reason": "por qué se agrega", "antu_ref": "fragmento literal"},
        {"operation_id": "op-4", "op": "RETRACT_ASSERTION",
         "target": {"assertion_id": "asrt_..."},
         "expected": {"status": "INSTRUCTED"},
         "value": {"retracted": True},
         "reason": "por qué se retira", "antu_ref": "fragmento literal"},
    ],
    "operation_types": ["ADD_ENTITY", "UPDATE_ENTITY", "ADD_ASSERTION", "UPDATE_ASSERTION",
                        "RETRACT_ASSERTION", "ADD_RELATION", "UPDATE_RELATION",
                        "RETRACT_RELATION", "UPDATE_ATTRIBUTE"],
    "modalities": ["FACT", "FORECAST", "ESTIMATE", "OPINION", "CONDITIONAL", "UNKNOWN"],
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
            "contract": self.operation_reference,
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
            "version": dict(version or {})}
