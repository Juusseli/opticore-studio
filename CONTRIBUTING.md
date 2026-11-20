# Contributing

Thank you for your interest in OptiCore Studio.

## Licence of contributions

OptiCore Studio is licensed under the GNU Affero General Public License,
version 3 or later (AGPL-3.0-or-later), and contributions are accepted under the
same licence. By submitting a contribution (a pull request, patch or other
material), you agree that it is licensed under AGPL-3.0-or-later. There is no
copyright assignment and no separate contributor licence agreement, and the code
is not offered under any other licence.

You also confirm that you have the right to submit the contribution, and that it
contains no code, data or assets copied from proprietary software or from
sources whose licence does not allow this.

## Engineering rules

The development rules are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (how to
run and test, and the invariants) and the docs folder:

* The Python engine is the only source of optical numbers.
* Every physics addition needs an analytic or independent benchmark in
  `backend/tests` and an entry in `docs/VALIDATION.md`.
* New UI strings go into both English and Finnish in `frontend/src/lib/i18n.ts`.
* Major decisions are recorded in `docs/DECISIONS.md`.

Run the tests before submitting:

```bash
cd backend && .venv/bin/python -m pytest
cd frontend && npm test && npm run typecheck
```

New third-party data needs its source and licence in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
