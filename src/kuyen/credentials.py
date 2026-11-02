"""Credential references and resolution at the privileged service boundary."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .errors import CredentialUnavailableError


@dataclass(frozen=True)
class SecretReference:
    """A non-secret pointer to a credential; safe to serialize."""

    env_var: str

    def __repr__(self) -> str:
        return f"SecretReference(env_var={self.env_var!r})"


class CredentialProvider(Protocol):
    def resolve(self, reference: SecretReference) -> str: ...


class EnvironmentCredentialProvider:
    """Resolve a secret only inside the trusted service process."""

    def resolve(self, reference: SecretReference) -> str:
        value = os.environ.get(reference.env_var)
        if not value:
            raise CredentialUnavailableError(f"credential unavailable: {reference.env_var}")
        return value
