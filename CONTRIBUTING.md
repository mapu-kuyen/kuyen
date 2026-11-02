# CONTRIBUTING

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

## Rules

1. **Contracts first.** Changing an identifier, a schema field, a manifest key or a digest
   input is a contract change: update the version constant in `kuyen/contracts.py`, the
   schema under `src/kuyen/schemas/`, the documentation and the tests in the same change.
2. **No duplicate implementations.** Extend the existing module; do not add a second
   storage, validation or projection path.
3. **The core stays independent.** `storage`, `lifecycle`, `sidecar`, native `projection`,
   `backup` and `recovery` must not import a network client, a model SDK or OpenViking.
4. **Fail closed.** A new code path that cannot verify something must refuse, not guess.
5. **Determinism.** No `datetime.now()` inside a digest, no locale-dependent sorting, no
   unordered iteration in canonical output.
6. **Tests protect the public API.** New capability comes with tests against `src/kuyen`,
   not against a script.

## Commit checklist

* `python -m pytest` green;
* wheel and sdist build and install in a clean environment;
* no new dependency without a licence review;
* documentation updated where the contract changed.
