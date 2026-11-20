# OptiCore Studio user interface

The browser front end of OptiCore Studio: React 19, TypeScript, Vite and
Tailwind CSS, with three.js (React Three Fiber) for the 3D view and Plotly for
charts. It edits the project and shows results. Every optical number comes from
the Python engine in `../backend` over its HTTP API (`/api/v1`).

See the [main README](../README.md) for installation, and
[docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) for the development rules.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Development server on <http://localhost:5173>. It proxies `/api` to the engine on port 8000, or to `OPTICORE_ENGINE_URL`. |
| `npm run build` | Type check and production build into `dist/` |
| `npm test` | Unit and component tests (Vitest) |
| `npm run typecheck` | TypeScript check without output |
| `npm run lint` | Oxlint |

## Layout

| Folder | Contents |
|---|---|
| `src/lib/` | API client, the project schema types (mirroring `backend/opticore/model.py`), units, canonical JSON and checksums, storage, i18n (English and Finnish) |
| `src/store/` | Zustand stores: project with undo and redo, engine results, optimisation, UI state |
| `src/components/` | Views (layouts, 3D, analyses), editors (Lens Data Editor, merit function, sources), panels, dialogs and the start screen |
| `src/integrity/` | Integration tests: asynchronous results stay bound to the design they were computed for, references follow edits, saving keeps the open project |

The design rules for the interface are in
[docs/UI_DESIGN.md](../docs/UI_DESIGN.md).
