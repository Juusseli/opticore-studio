# Development

How to run, test and extend OptiCore Studio, and the rules that keep it
correct. Read this before a pull request. [CONTRIBUTING.md](../CONTRIBUTING.md)
covers the licence of contributions.

## Running

* `scripts/dev.ps1` (Windows) or `scripts/dev.sh` (macOS/Linux) starts the
  engine on `:8000` and the user interface on `:5173`.
* The dev server proxies `/api` to the engine, or to `OPTICORE_ENGINE_URL`
  when that is set.
* For checks next to a running working instance, start a second engine and
  user interface on other ports, for example `:8001` and `:5174` with
  `OPTICORE_ENGINE_URL=http://127.0.0.1:8001`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest      # engine: physics, analyses, optimisation, formats, API
cd frontend && npm test                        # user interface logic, canonical JSON parity, i18n
cd frontend && npm run typecheck
cd frontend && npm run lint
```

All of them run on every push (`.github/workflows/ci.yml`). The linter must report
no warnings; keep helpers and constants out of component files (React fast
refresh), in a sibling `.ts` module.

## Invariants

* **One source of numbers.** The Python engine (`backend/opticore`) computes
  every optical result. The user interface never computes physics, apart from
  drawing sags.
* **One schema.** `backend/opticore/model.py` and `project.py` are mirrored in
  `frontend/src/lib/types.ts`. Change both together. If the file format
  changes, bump `schema_version` and add a migration.
* **Identical checksums.** Canonical JSON and checksums must stay
  byte-identical between `project.py` and `frontend/src/lib/canonical.ts`.
  Fixture tests enforce this. Regenerate the fixtures from the engine when the
  samples change.
* **Undo for everything.** Every modelling edit goes through
  `projectStore.commit`. Optimisation results are applied only as a new
  revision, never over the original design.
* **Two languages.** New UI strings go into both `en` and `fi` in
  `frontend/src/lib/i18n.ts`. A test checks this. English is the main language
  of the code, the documentation and every public text.
* **No dead controls.** Do not add UI controls for unimplemented features.
  Document them in `docs/ROADMAP.md` instead.
* **Validated physics.** Every physics addition needs an analytic or
  independent benchmark in `backend/tests` and an entry in `docs/VALIDATION.md`.
* **Honest limits.** An analysis that does not apply to a kind of system
  raises `NotApplicable` (code `NOT_APPLICABLE`, shown as information).
  `tests/test_analysis_matrix.py` runs every analysis on every sample and
  accepts only finite results or `NOT_APPLICABLE`.
* **Reproducible samples.** Frozen sample designs in `samples.py` must be
  reproducible with `python -m opticore.tools.reoptimize_sample <id>`. When they
  change, update the baselines in the tests and docs.
* **Recorded decisions.** Major decisions get an ADR in `docs/DECISIONS.md`.
* **Cited data.** Third-party data needs its source and licence in
  `THIRD_PARTY_NOTICES.md` and in the README of its folder.

## Independent implementation

All physics is derived from published optics and numerical methods, cited in
`docs/OPTICAL_ENGINE.md`. Do not copy code, algorithms, assets or catalogue
databases from proprietary software, and do not analyse proprietary software to
reproduce it. Workflows may follow general engineering practice and public
documentation.
