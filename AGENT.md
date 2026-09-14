# AGENT.md

## 1. Repository Overview

AOI door-panel inspection dual-platform monorepo, deployed across machines.

| Path | Contents |
|---|---|
| `label_studio/` | Platform A backend: LS 1.x fork (Django + DRF). Upstream modules are read-only; custom work goes only in `label_studio/aoi/` |
| `web/` | Platform A frontend: LS 1.x web (React + TS) |
| `infer-platform/` | Platform B: `backend/` (FastAPI + SQLite), `frontend/` (Vite + React), `deploy/` |
| `packages/skillname` | Cross-platform vocabulary, zero dependencies |
| `packages/pipeline-core` | Slicing / NMS merge / three-tier verdict / `load_config` |
| `tests/contracts/` | Cross-platform contract tests and fixtures |
| `docs/` | Architecture, contracts, plans; start at `docs/README.md` |

Platform A and Platform B share no database, object storage, or middleware. Add no cross-platform shared code outside `packages/`.

## 2. Commands

| Purpose | Command |
|---|---|
| Install backend dependencies | `uv sync --frozen` |
| Start backend dev server | `make run-dev` |
| Apply / create migrations | `make migrate-dev` / `make makemigrations-dev` |
| Backend tests | `make test` |
| Frontend install / dev / build | `make frontend-install` / `make frontend-dev` / `make frontend-build` |
| Format changed files | `make fmt` |
| Check formatting and lint | `make fmt-check` |
| Check the whole repo | `make fmt-check-all` |

Platform B commands are documented in `infer-platform/`.

## 3. Read Before Changing

For any non-trivial change, consult the matching document per the `docs/README.md` index before writing the first line of code:

| Change | Document |
|---|---|
| Platform boundaries, shared layer, deployment topology | `docs/双平台架构与拆分方案.md` |
| A↔B interfaces: image publish/pull, error-image return, auth, idempotent retry | `docs/contracts/跨平台契约_A-B.md` |
| Platform A tables, `/api/*`, training / review / pre-labeling | `docs/contracts/平台A_接口与数据契约.md` |
| Platform B tables, `/api/v1/*`, inference chain, statistics / daily report | `docs/contracts/平台B_接口与数据契约.md` |
| Directory layout, stub behavior, acceptance criteria | `docs/P0骨架设计_双平台.md` |
| Schedule, ownership, current phase | `docs/MVP开发计划.md` |
| Three-bucket pre-label review flow | `docs/设计_预标三桶复审流程.md` |
| Outstanding issues and their order | `docs/D3_工程卫生清单.md` |

Constraints:

- Contracts were frozen at D2; change windows are D9 and D15. A breaking change requires all four: updated docs + updated stub + updated fixture + passing contract tests on both sides. A change without synced docs is incomplete.
- Everything under `label_studio/` except `label_studio/aoi/` is upstream code and must not be modified.
- Structural changes (new module, new endpoint, new table) go into docs first, then into code.
- When a requirement is ambiguous or admits several interpretations, state the assumptions and tradeoffs and confirm before proceeding; never pick a solution silently.

## 4. Code Style

### 4.1 General

- Implement only what was requested: no unrequested config options, extension points, fallback branches, or "might need later" flexibility.
- Write no abstraction for single-use code; extract on the third real repetition.
- Name for intent; one function does one thing; flatten deep nesting with early returns.
- Keep changes inside the scope of the request: do not refactor unrelated code, do not reformat or reword adjacent code and comments, do not delete unrelated dead code (raise it instead).
- Delete unused imports, variables, and functions that your own change orphaned.
- Before adding a dependency, confirm the standard library or an existing dependency cannot do the job.
- Rewrite any implementation over 200 lines that could be 50.

### 4.2 Python

- ruff owns formatting and lint: line length 119, single quotes. Run `make fmt` before committing.
- Manage dependencies with uv; install via `uv sync --frozen`.
- Route Django model changes through migrations; never hand-edit an applied migration.
- Keep `packages/skillname` dependency-free; `packages/pipeline-core` depends only on numpy and pillow.

### 4.3 Frontend

- `web/` must pass the biome check before commit.
- Implement `infer-platform/frontend` independently; do not reuse LS components.

### 4.4 Tests

- Update `tests/contracts/` and the matching fixtures with any contract change.
- Cover new endpoints and verdict logic with tests; write no assertion-free coverage padding.
- For a bug fix, write the failing test first, then make it pass.

## 5. Comments and Logging

- Comments explain only what code cannot: non-obvious business rules, contract references, necessary workarounds.
- Write no decision history. Rejected approaches, design evolution, and tradeoffs belong in `docs/`, not in code.
- Write no timestamps, author names, "added/changed" markers, or commented-out code.
- Write no self-justifying comments such as "X is not done here" or "this could be cleaner".
- Log only key events: task start and end, failure causes, external call errors. No logging inside loops or hot paths.
- Leave no `print` debug output.

## 6. Pre-Submit Checklist

1. Relevant docs reviewed; all four artifacts in place when contracts are touched.
2. `make fmt` and the relevant tests pass.
3. Every changed line traces to the request.
4. No leftover debug comments, logs, or output.
5. User-visible behavior changes recorded in `CHANGES.md`.
