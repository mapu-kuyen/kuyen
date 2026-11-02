"""OpenAI Responses API extraction provider.

Separate from the OpenViking adapter. It resolves `OPENAI_API_KEY` inside the
trusted process, sends a strict JSON Schema, records real usage, and never retries
implicitly. It does not interpret the candidate as truth.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..credentials import CredentialProvider, EnvironmentCredentialProvider, SecretReference
from ..errors import OpenAIExtractionError, OpenAIProviderError
from ..models import Antu
from ..ontology import Ontology
from .budget import BudgetLedger, PricingSnapshot
from .schema import (
    EXTRACTION_SCHEMA_VERSION, EXTRACTION_SCHEMA_VERSION_V2, build_extraction_schema,
    build_extraction_schema_v2, schema_hash, validate_strict_schema,
)

OPENAI_MODEL = "gpt-6-luna"
EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass(frozen=True)
class OpenAIExtractionConfig:
    model: str = OPENAI_MODEL
    prompt_revision: str = "2026-10-30.2"
    reasoning_effort: str = "low"
    max_output_tokens: int = 6000
    timeout_s: float = 180.0
    store: bool = False
    service_tier: str = "default"
    schema_version: str = EXTRACTION_SCHEMA_VERSION
    sections: tuple[dict[str, Any], ...] = ()
    source_sha256: str | None = None
    source_characters: int | None = None
    context_notes: str | None = None
    completeness_mode: bool = False


@dataclass
class OpenAIUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens, "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass
class OpenAIExtractionResult:
    response_id: str
    model: str
    status: str
    candidate: dict[str, Any]
    output_text: str
    usage: OpenAIUsage | None
    cost_usd: float | None
    estimated_usd: float
    request: dict[str, Any]
    response_metadata: dict[str, Any]
    raw_response: dict[str, Any]
    refusal: str | None = None
    incomplete_reason: str | None = None
    output_items: list[str] = field(default_factory=list)
    budget_exceeded: bool = False


class OpenAIExtractionProvider:
    def __init__(
        self,
        *,
        config: OpenAIExtractionConfig | None = None,
        ledger: BudgetLedger,
        pricing: PricingSnapshot,
        credential_provider: CredentialProvider | None = None,
        credential_reference: SecretReference | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or OpenAIExtractionConfig()
        self.ledger = ledger
        self.pricing = pricing
        self._credential_provider = credential_provider or EnvironmentCredentialProvider()
        self._credential_reference = credential_reference or SecretReference("OPENAI_API_KEY")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            key = self._credential_provider.resolve(self._credential_reference)
            try:
                from openai import OpenAI
            except Exception as exc:  # noqa: BLE001
                raise OpenAIProviderError("openai SDK is not installed") from exc
            self._client = OpenAI(api_key=key, timeout=self.config.timeout_s, max_retries=0)
        return self._client

    def preflight_models(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for label, model in (("extraction", self.config.model), ("embedding", EMBEDDING_MODEL)):
            try:
                item = self.client.models.retrieve(model)
                result[label] = {
                    "model": model, "available": True,
                    "owned_by": getattr(item, "owned_by", None),
                    "created": getattr(item, "created", None),
                }
            except Exception as exc:  # noqa: BLE001
                result[label] = {
                    "model": model, "available": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
        return result

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        try:
            import tiktoken

            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception:  # noqa: BLE001
            return max(1, len(text) // 4)

    def _messages(self, *, antu: Antu, ontology: Ontology, source_text: str, source_uri: str,
                  mapu_id: str, unit_ids: list[str], sections: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
        entity_types = ", ".join(antu.entity_types)
        relation_types = ", ".join(antu.relation_types)
        scalars = ", ".join(sorted(ontology.scalar_predicates))
        units = ", ".join(unit_ids)
        section_lines = "\n".join(
            f"- {item['unit_id']}: {item['section']} (order {item['order']}, chars {item.get('char_start')}:{item.get('char_end')})" for item in (sections or [])
        ) or "- (single unit)"
        system = (
            "You are the KÜYEN extraction engine. Extract only facts explicitly stated in the "
            "source. Do not use prior knowledge, do not infer absent facts, and do not fill gaps. "
            "Return only the structured object required by the schema. "
            "Every entity, relation and assertion must reference evidence objects by evidence_ref. "
            "Quotes must be exact substrings of the source. Do not output character offsets. "
            "Do not create entities for numbers, dates, quantities or units; use assertion values. "
            "Every relation endpoint and assertion subject must be a declared entity source_ref. "
            "Do not create self-relations. "
            "A negative statement must remain negative; never turn it into a positive relation. "
            "Every sentence containing a negation (no, nunca, sin, tampoco) MUST produce an "
            "assertion with polarity NEGATIVE and the negated proposition in text_value. "
            "Omitting a negated sentence is an extraction failure. "
            "Before returning, enumerate every sentence of the source and confirm that each "
            "sentence is represented by at least one entity, relation or assertion. "
            "Use epistemic_status UNRESOLVED or NOT_EVALUATED; never claim verification. "
            "Use only the allowed types, predicates and units. "
            "Preserve polarity, temporal scope and scalar values exactly. "
            "For a recurrence such as 'cada abril', set temporal.kind=RECURRENCE, "
            "temporal.frequency='annual', temporal.month=4, temporal.expression to the exact quote, "
            "and leave day/start/end/timezone null unless the source states them. Never invent a day or year. "
            "For every assertion/relation that has a temporal expression, fill temporal; otherwise use kind=UNKNOWN. "
            "Account for every section: populate coverage.units_used with every unit that you actually read. "
            + (
                "COMPLETENESS MODE: the source has eight contiguous units. You must traverse all eight unit ranges, "
                "not a sample. For every unit, extract all substantive entities, relations and scalar/temporal facts "
                "explicitly stated. Return coverage.units_used containing every unit ID. A response with entities from "
                "only one or two units is invalid. Use related_to for a sourced relation that has no more specific "
                "allowed predicate, and has_value for sourced scalar, date or quantity values. Do not invent facts "
                "to satisfy this completeness requirement; a unit with no graphable fact may be represented only "
                "by coverage. " if self.config.completeness_mode else ""
            )
            + "Omit a fact if you cannot support it with an exact quote. "
            "The source is in Spanish; keep names, labels and quotes in Spanish."
        )
        user = (
            f"MAPU id: {mapu_id}\n"
            f"Source URI: {source_uri}\n"
            f"Coverage units: {units}\n"
            f"Document sections:\n{section_lines}\n"
            f"Allowed entity types: {entity_types}\n"
            f"Allowed relation predicates: {relation_types}\n"
            f"Allowed scalar predicates: {scalars}\n"
            "Allowed relation labels are the ontology labels for those predicates.\n"
            "Allowed evidence unit IDs: " + units + ".\n"
            "Format coverage.units_used only with those unit IDs. KÜYEN derives final coverage.\n"
            "SOURCE BEGINS\n" + source_text + "\nSOURCE ENDS\n"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def extract(
        self,
        *,
        antu: Antu,
        ontology: Ontology,
        source_text: str,
        source_uri: str,
        mapu_id: str,
        unit_ids: list[str],
        phase: str = "extraction",
        operation: str = "K02 extraction",
    ) -> OpenAIExtractionResult:
        if self.config.schema_version == EXTRACTION_SCHEMA_VERSION_V2:
            if not self.config.source_sha256 or self.config.source_characters is None:
                raise OpenAIExtractionError("v2 schema requires source_sha256 and source_characters")
            schema = build_extraction_schema_v2(
                antu=antu, ontology=ontology, mapu_ids=[mapu_id], unit_ids=unit_ids,
                source_uris=[source_uri], source_sha256=self.config.source_sha256,
                source_characters=self.config.source_characters,
                sections=list(self.config.sections),
            )
        else:
            schema = build_extraction_schema(
                antu=antu, ontology=ontology, mapu_ids=[mapu_id],
                unit_ids=unit_ids, source_uris=[source_uri],
            )
        errors = validate_strict_schema(schema)
        if errors:
            raise OpenAIExtractionError("extraction schema is not strict", details={"errors": errors})
        messages = self._messages(
            antu=antu, ontology=ontology, source_text=source_text,
            source_uri=source_uri, mapu_id=mapu_id, unit_ids=unit_ids,
            sections=list(self.config.sections),
        )
        input_text = "\n".join(item["content"] for item in messages)
        estimated_input = self._estimate_tokens(input_text) + 32
        estimated_cost = self.pricing.cost(
            input_tokens=int(estimated_input * 1.2), output_tokens=self.config.max_output_tokens,
        )
        self.ledger.authorize(phase=phase, operation=operation, estimated_usd=estimated_cost)
        request = {
            "model": self.config.model, "messages": messages,
            "text": {"format": {
                "type": "json_schema", "name": self.config.schema_version,
                "strict": True, "schema": schema,
            }},
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
            "service_tier": self.config.service_tier, "store": self.config.store,
            "schema_sha256": schema_hash(schema), "schema_version": self.config.schema_version,
            "prompt_revision": self.config.prompt_revision,
        }
        try:
            response = self.client.responses.create(
                model=self.config.model, input=messages, text=request["text"],
                reasoning=request["reasoning"], max_output_tokens=self.config.max_output_tokens,
                service_tier=self.config.service_tier, store=self.config.store,
            )
        except Exception as exc:  # noqa: BLE001
            raise OpenAIProviderError(
                f"OpenAI request failed: {type(exc).__name__}: {str(exc)[:500]}",
                details={"request": request, "exception_type": type(exc).__name__},
            ) from exc
        return self._parse_result(response, request=request, schema=schema,
                                  phase=phase, operation=operation, estimated_usd=estimated_cost)

    def _parse_result(
        self, response: Any, *, request: dict[str, Any], schema: dict[str, Any],
        phase: str, operation: str, estimated_usd: float,
    ) -> OpenAIExtractionResult:
        raw = response.model_dump(mode="json") if hasattr(response, "model_dump") else {}
        status = str(getattr(response, "status", "") or "")
        response_id = str(getattr(response, "id", "") or "")
        model = str(getattr(response, "model", self.config.model) or self.config.model)
        texts: list[str] = []
        refusals: list[str] = []
        output_items: list[str] = []
        for item in getattr(response, "output", None) or []:
            item_type = str(getattr(item, "type", "") or "")
            output_items.append(item_type)
            if item_type != "message":
                continue
            for content in getattr(item, "content", None) or []:
                content_type = str(getattr(content, "type", "") or "")
                if content_type == "output_text":
                    texts.append(str(getattr(content, "text", "") or ""))
                elif content_type == "refusal":
                    refusals.append(str(getattr(content, "refusal", "") or ""))
        output_text = "".join(texts)
        incomplete = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete, "reason", None) if incomplete is not None else None
        usage_obj = getattr(response, "usage", None)
        usage: OpenAIUsage | None = None
        if usage_obj is not None:
            details = getattr(usage_obj, "output_tokens_details", None)
            usage = OpenAIUsage(
                input_tokens=int(getattr(usage_obj, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage_obj, "output_tokens", 0) or 0),
                total_tokens=int(getattr(usage_obj, "total_tokens", 0) or 0),
                reasoning_tokens=int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
            )
        metadata = {
            "response_id": response_id, "model": model, "status": status,
            "created_at": getattr(response, "created_at", None),
            "incomplete_details": raw.get("incomplete_details"),
            "usage": usage.to_dict() if usage else None,
            "output_items": output_items,
            "refusal": "\n".join(refusals) if refusals else None,
        }
        if status != "completed":
            raise OpenAIExtractionError(
                f"OpenAI response status is {status or '<missing>'}",
                details={"response": metadata, "raw_response": raw, "request": request},
            )
        if refusals:
            raise OpenAIExtractionError(
                "OpenAI returned a refusal",
                details={"response": metadata, "raw_response": raw, "request": request},
            )
        if not output_text.strip():
            raise OpenAIExtractionError(
                "OpenAI response contains no structured output",
                details={"response": metadata, "raw_response": raw, "request": request},
            )
        try:
            candidate = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIExtractionError(
                f"OpenAI structured output is not JSON: {exc}",
                details={"response": metadata, "raw_response": raw, "request": request},
            ) from exc
        try:
            import jsonschema

            jsonschema.validate(candidate, schema)
        except Exception as exc:  # noqa: BLE001
            raise OpenAIExtractionError(
                f"OpenAI structured output does not match the schema: {str(exc)[:500]}",
                details={"response": metadata, "raw_response": raw, "request": request, "candidate": candidate},
            ) from exc
        cost = None
        if usage is not None:
            cost = self.pricing.cost(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
            self.ledger.record(
                phase=phase, operation=operation, reserved_usd=estimated_usd, actual_usd=cost,
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens, response_id=response_id, model=model,
            )
        return OpenAIExtractionResult(
            response_id=response_id, model=model, status=status, candidate=candidate,
            output_text=output_text, usage=usage, cost_usd=cost, estimated_usd=estimated_usd,
            request=request, response_metadata=metadata, raw_response=raw,
            refusal="\n".join(refusals) if refusals else None,
            incomplete_reason=incomplete_reason, output_items=output_items,
            budget_exceeded=self.ledger.spent_usd > self.ledger.total_usd,
        )
