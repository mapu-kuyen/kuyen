"""Identity separation checks for the public KÜYEN boundary."""
from __future__ import annotations

from typing import Any

from .errors import InvalidRequestError
from .models import ActorContext, Antu


def redact(value: Any) -> Any:
    """Remove credential-looking fields before persisting attempt evidence."""
    sensitive = {"api_key", "user_key", "root_api_key", "authorization", "token", "secret"}
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in sensitive else redact(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact(child) for child in value]
    return value


def validate_actor(actor: ActorContext, antu: Antu) -> None:
    required = {
        "leftraru_id": actor.leftraru_id,
        "authenticated_account": actor.authenticated_account,
        "authenticated_user": actor.authenticated_user,
        "service_identity": actor.service_identity,
        "antu_author": actor.antu_author,
        "candidate_producer": actor.candidate_producer,
    }
    missing = [key for key, value in required.items() if not str(value).strip()]
    if missing:
        raise InvalidRequestError(f"actor missing fields: {', '.join(missing)}")
    declared_author = antu.raw.get("author")
    if declared_author and str(declared_author) != actor.antu_author:
        raise InvalidRequestError(
            "actor.antu_author does not match the Antü author",
            details={"declared": declared_author, "actor": actor.antu_author},
        )
    if actor.service_identity.lower() in {"root", "admin"}:
        raise InvalidRequestError("operational KÜYEN must not use a ROOT/ADMIN label as service identity")
