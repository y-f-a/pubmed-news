# engineering plan (local-only screenshot demo)

## Goals
- Local-only app run to generate screenshot-ready pages for a blog post.
- Admin-curated content with a read-only gallery (local).
- Single fixed prompt only; no framing variants or public generation.
- SQLite as the system of record for cached PubMed results and published artifacts.

## Constraints
- Public outcome is a blog post with screenshots; no public hosting.
- Desktop capture target: 1440x900.
- No imagery or placeholders; text-first presentation.
- Admin-only generation; no public API spend.

## Proposed stack
- Backend API: FastAPI + Uvicorn.
- Frontend: Server-rendered templates (Jinja2) + minimal JS.
- Data layer: SQLite for caching PubMed results and published artifacts.
- Background tasks: in-process job queue (simple, no external broker).
- Tooling: `uv` for env + deps, `ruff` for lint, `pytest` for tests.

## Monorepo layout
- `apps/web/` FastAPI app (routes, templates, static assets).
- `packages/pubmed/` PubMed client + XML parsing.
- `packages/storage/` SQLite schema + data access layer.
- `scripts/` dev scripts + data seeding.

## Key modules
- `apps/web/main.py`: app init plus public/admin routes.
- `apps/web/templates/public/`: gallery index and story detail templates.
- `apps/web/templates/admin/`: login, search, artifact review, gallery manager templates.
- `apps/web/static/`: editorial styles, typography, and minimal UI JS.
- `packages/pubmed/client.py`: eSearch + eFetch.
- `apps/web/prompts/newsroom_prompt.txt`: single fixed prompt text (stored raw for display).
- `packages/ranking/readability.py`: readability scoring for admin sorting.
- `packages/storage/db.py`: SQLite connection + migrations.

## Data model (SQLite)
- `queries`: id, term, created_at.
- `records`: pmid, title, abstract, journal, year, authors, doi, pmcid.
- `artifacts`: pmid (primary key), headline, standfirst, story, prompt_text, abstract_snapshot, metadata_snapshot, featured_rank, published_at, created_at.

## API surface (server routes)
Local public
- `GET /`: gallery index.
- `GET /story/{pmid}`: story detail.

Admin
- `GET /admin/login`: login page.
- `POST /admin/login`: session creation (env-based password).
- `GET /admin/search?term=...`: PubMed search (full abstracts, default readability sort).
- `POST /admin/generate`: generate draft for a pmid.
- `GET /admin/artifact/{pmid}`: draft review and publish form (story layout).
- `POST /admin/publish`: publish artifact (as-is) and set featured order.
- `GET /admin/gallery`: manage published artifacts (list, unpublish, reorder).
- `POST /admin/feature`: update featured order.
- `POST /admin/unpublish`: unpublish artifact.

## Runtime flow
1) Admin search term -> PubMed fetch -> cache records.
2) Admin generate -> store artifact draft with raw prompt and abstract/metadata snapshot.
3) Admin review -> publish -> artifact appears in gallery with featured ordering.
4) Capture screenshots (gallery, story, admin search, admin artifact review, admin gallery).

## Screenshot workflow
- Use desktop viewport 1440x900.
- Capture the defined set of pages after curating 9 artifacts.
- Publish screenshots to the blog as the public-facing artifact.

## One-command run
- `./scripts/dev`
- Open `http://localhost:8000`

## Testing plan
- Unit tests for PubMed parsing and prompt guardrails.
- Basic integration tests for admin publish and public story routes.
