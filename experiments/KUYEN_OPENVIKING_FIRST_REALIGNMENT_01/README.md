# KUYEN_OPENVIKING_FIRST_REALIGNMENT_01 — evidencia

Auditoría y depuración que realinea KÜYEN con su arquitectura OpenViking-first.

- **ADR:** [`docs/adr/0001-openviking-first-realignment.md`](../../docs/adr/0001-openviking-first-realignment.md)
- **Informe de auditoría:** [`docs/architecture/audits/OPENVIKING_FIRST_REALIGNMENT.md`](../../docs/architecture/audits/OPENVIKING_FIRST_REALIGNMENT.md)
- **Base:** `HEAD 5fd8777` · `VERSION 0.2.1rc1` · único commit en el repositorio

## Contenido

| archivo | contenido |
|---|---|
| `git_state_initial.txt` | HEAD, remoto, rama, `status --short` y `diff --stat` antes de tocar nada |
| `hashes_initial.txt` | SHA-256 de 183 archivos (fuente, tests, docs, ejemplos, scripts y metadatos) |
| `graph.json` | mapa de dependencias construido con AST: importadores internos y consumidores externos por módulo |
| `logs/suite_before.xml` · `.log` | suite completa antes del cambio (388 tests) |
| `logs/suite_after.xml` · `.log` | suite completa después (377 tests) |
| `logs/30_distribution.log` · `30_distribution_verification.json` | wheel y sdist × Python 3.11 y 3.13 |
| `archived/` | los tests retirados, el parche con las ediciones locales que tenía el subsistema y su README |

## Qué se retiró

`src/kuyen/extraction/` — el extractor OpenAI directo (`openai_provider`, `schema`, `conversion`,
`budget`, `fact_coverage`, `config`, `__init__`), 1.542 líneas en el árbol de trabajo (1.150 en
`HEAD`), y los 11 casos de prueba que sólo probaban ese subsistema.

## Qué se conservó

Todo el gobierno canónico (procedencia, evidencia, admisión, commit, versionado, ledger, sidecar,
backup, recuperación, consulta) y toda la integración con OpenViking (`engine.py`, `adapters/`,
`ports/`, `vlm.py`, `materialization/`, `validation/validators.py`, `semantics/`, `normalization/`,
`coverage/`, `serialization/`, `publication/`, `projection/`, `skills/`).

## Recuperación

El código retirado es recuperable en cualquier momento:

```bash
git show <commit-de-estas-realineacion>^:src/kuyen/extraction/openai_provider.py
# o el árbol completo anterior al cambio:
tar xzf /tmp/kuyen_realign_01/backup/worktree_src_tests_docs.tgz
```

El parche `archived/e2e_01_uncommitted_edits.patch` conserva, además, las ediciones locales que ese
subsistema tenía **sin commitear** (esquema v3, prompt, `OpenAIConfig`) en el momento de retirarlo.
