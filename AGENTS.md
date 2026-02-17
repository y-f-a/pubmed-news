## Read this first

Before changing code, skim:

- `README.md` (setup + how to run)
- `docs/STRATEGY_ENGINEERING.md` (architecture + invariants)
- Work queue: `docs/TASKS.md` (only place for tasks; remove items that are 100% done)

## Non-negotiables

- Single fixed prompt only; no public or user-facing generation variants.
- Prompt text is stored verbatim with each artifact (`apps/web/prompts/newsroom_prompt.txt` is the source).
- Public experience is read-only; admin curates and publishes.
- SQLite is the system of record for cached PubMed results and published artifacts.

## Repo orientation

- Backend: FastAPI app in `apps/web/` with Jinja templates.
- Data access: `packages/storage/` (SQLite schema + access).
- PubMed client: `packages/pubmed/`.
- Prompt: `apps/web/prompts/newsroom_prompt.txt`.

## Run and test

- One-command dev: `./scripts/dev`
- Manual dev: `python3 -m apps.web.main` then open `http://127.0.0.1:8000`
- Tests: `./scripts/test`

## Env setup

- `cp .env.example .env`
- Required: `OPENAI_API_KEY`, `PUBMED_EMAIL`, `ADMIN_PASSWORD`
- Optional: `PUBMED_API_KEY`, `ADMIN_SESSION_SECRET`

## Workflow rules

- Only `docs/TASKS.md` is the task source of truth.
- Remove a task when it is fully complete or clearly no longer needed.
- Keep changes consistent with the curated gallery direction (no framing sliders or public generation).

## Ask before you change

- Data model or schema changes in `packages/storage/`.
- Public story layout or sections in `apps/web/templates/public/`.
- Prompt text in `apps/web/prompts/newsroom_prompt.txt`.

## Guardrails

### Planning and permission
- Do not create, modify, or delete files; run commands; install dependencies; or open PRs until you have:
  1) a short plan, and
  2) explicit permission to proceed.
- If the request is ambiguous, stop and ask targeted questions before planning implementation details.
- When you propose a plan, include: scope, assumptions, steps, and what will change (files/commands).

### Requirements and scope control
- Restate the goal in plain language before proposing a solution.
- Identify constraints early (time, performance, tech stack, “must/should/nice-to-have”).
- If new work is discovered mid-stream, pause and ask before expanding scope.

### Execution style
- Prioritise the simplest viable approach first; only introduce complexity if there is a clear benefit.
- Break work into small deliverables that can be reviewed independently.
- Make changes incrementally; prefer small diffs over sweeping rewrites.

### Safety for code and data
- Do not expose secrets (API keys, tokens, passwords). If any secret appears in logs or files, stop and tell me what to rotate and where it might have leaked.
- Do not run destructive or irreversible actions without explicit confirmation (e.g., deletes, migrations, force pushes, production changes).
- Avoid actions that could incur unexpected cost (cloud resources, paid APIs) without asking first and estimating impact.

### Transparency and explainability
- Avoid jargon. If you must use a technical term, define it in one sentence.
- When offering options, present 2–3 options with clear pros/cons and a recommendation.
- Always give me a way to ask “explain that more” and respond with a simpler explanation if requested.

### Quality checks (lightweight)
- Before implementation, clarify how we’ll know it’s “done” (acceptance criteria).
- Prefer adding or updating tests when changing logic. If you don’t add tests, explain why and how to manually verify.
- Keep formatting and conventions consistent with the existing codebase.

### Communication and defaults
- If I don’t specify, default to:
  - minimal changes,
  - readable code over clever code,
  - safe actions over fast actions.
- If you’re uncertain, say what you’re uncertain about and propose the next smallest step to reduce uncertainty.
