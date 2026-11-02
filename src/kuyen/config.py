"""Configuration loading for KÜYEN.

Secrets are referenced by environment variable name, never stored in config.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KuyenConfig:
    data_dir: Path
    ontology_path: Path
    skill_dir: Path
    openviking_url: str = "http://127.0.0.1:1933"
    openviking_api_key_env: str = "KUYEN_OPENVIKING_API_KEY"
    task_timeout_s: float = 900.0
    poll_interval_s: float = 3.0
    ingestion_timeout_s: float = 600.0
    coverage_profile: str = "none"
    compile_mode: str = "full"
    provider_contract: str = "kuyen-provider-result-v1"
    provider_result_filename: str = "kuyen_result.json"
    max_entities: int = 1000
    max_relations: int = 5000
    default_output_profile: str = "kuyen-native-v1"
    allow_reuse_accepted: bool = True
    git_sha: str | None = None
    source_container_uri: str = "viking://resources/kuyen/sources"
    candidate_container_uri: str = "viking://resources/kuyen/candidates"
    accepted_container_uri: str = "viking://resources/kuyen"
    publication_root_uri: str = "viking://resources/kuyen"
    publication_namespace: str = "kuyen"
    publication_acl_mode: str = "restricted"
    publication_acl_entries: tuple[dict[str, str], ...] = ()
    publish_source_content: bool = False

    def public_dict(self) -> dict[str, Any]:
        """Serializable configuration with no resolved secret."""
        return {
            "data_dir": str(self.data_dir),
            "ontology_path": str(self.ontology_path),
            "skill_dir": str(self.skill_dir),
            "openviking_url": self.openviking_url,
            "openviking_api_key_env": self.openviking_api_key_env,
            "task_timeout_s": self.task_timeout_s,
            "poll_interval_s": self.poll_interval_s,
            "ingestion_timeout_s": self.ingestion_timeout_s,
            "coverage_profile": self.coverage_profile,
            "compile_mode": self.compile_mode,
            "provider_contract": self.provider_contract,
            "provider_result_filename": self.provider_result_filename,
            "max_entities": self.max_entities,
            "max_relations": self.max_relations,
            "default_output_profile": self.default_output_profile,
            "allow_reuse_accepted": self.allow_reuse_accepted,
            "git_sha": self.git_sha,
            "source_container_uri": self.source_container_uri,
            "candidate_container_uri": self.candidate_container_uri,
            "accepted_container_uri": self.accepted_container_uri,
            "publication_root_uri": self.publication_root_uri,
            "publication_namespace": self.publication_namespace,
            "publication_acl_mode": self.publication_acl_mode,
            "publication_acl_entries": list(self.publication_acl_entries),
            "publish_source_content": self.publish_source_content,
        }

    def to_dict(self) -> dict[str, Any]:
        """Public serialization alias; no resolved credential is included."""
        return self.public_dict()

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir, self.data_dir / "staging", self.data_dir / "versions",
            self.data_dir / "rejected", self.data_dir / "executions",
            self.data_dir / "publications",
        ):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, base: Path | None = None) -> "KuyenConfig":
        base = (base or Path.cwd()).resolve()
        def path_of(name: str, default: str) -> Path:
            raw = Path(str(value.get(name, default)))
            return raw if raw.is_absolute() else (base / raw).resolve()
        return cls(
            data_dir=path_of("data_dir", "data"),
            ontology_path=path_of("ontology_path", "config/ontologies/generic-v1.yaml"),
            skill_dir=path_of("skill_dir", "skills/knowledge-graph"),
            openviking_url=str(value.get("openviking_url", "http://127.0.0.1:1933")),
            openviking_api_key_env=str(value.get("openviking_api_key_env", "KUYEN_OPENVIKING_API_KEY")),
            task_timeout_s=float(value.get("task_timeout_s", 900.0)),
            poll_interval_s=float(value.get("poll_interval_s", 3.0)),
            ingestion_timeout_s=float(value.get("ingestion_timeout_s", 600.0)),
            coverage_profile=str(value.get("coverage_profile", "none")),
            compile_mode=str(value.get("compile_mode", "full")),
            provider_contract=str(value.get("provider_contract", "kuyen-provider-result-v1")),
            provider_result_filename=str(value.get("provider_result_filename", "kuyen_result.json")),
            max_entities=int(value.get("max_entities", 1000)),
            max_relations=int(value.get("max_relations", 5000)),
            default_output_profile=str(value.get("default_output_profile", "kuyen-native-v1")),
            allow_reuse_accepted=bool(value.get("allow_reuse_accepted", True)),
            git_sha=value.get("git_sha"),
            source_container_uri=str(value.get("source_container_uri", "viking://resources/kuyen/sources")),
            candidate_container_uri=str(value.get("candidate_container_uri", "viking://resources/kuyen/candidates")),
            accepted_container_uri=str(value.get("accepted_container_uri", "viking://resources/kuyen")),
            publication_root_uri=str(value.get("publication_root_uri", "viking://resources/kuyen")),
            publication_namespace=str(value.get("publication_namespace", "kuyen")),
            publication_acl_mode=str(value.get("publication_acl_mode", "restricted")),
            publication_acl_entries=tuple(
                dict(item) for item in (value.get("publication_acl_entries") or [])
                if isinstance(item, dict)
            ),
            publish_source_content=bool(value.get("publish_source_content", False)),
        )


def load_config(path: str | Path | None = None) -> KuyenConfig:
    """Load TOML config; absent file means defaults."""
    target = Path(path or os.environ.get("KUYEN_CONFIG", "config/defaults.toml"))
    if target.is_file():
        with target.open("rb") as handle:
            data = tomllib.load(handle)
        return KuyenConfig.from_mapping(data.get("kuyen", data), base=target.parent.parent)
    # Assets ship as package data so a wheel installed anywhere resolves them the
    # same way the source tree does; an explicit config file always overrides this.
    package_root = Path(__file__).resolve().parent
    return KuyenConfig(
        data_dir=(Path.cwd() / "data").resolve(),
        ontology_path=package_root / "config" / "ontologies" / "generic-v1.yaml",
        skill_dir=package_root / "skills" / "knowledge-graph",
    )
