# PubMed Newsroom

An art-project demo that curates a read-only gallery of news articles generated from peer-reviewed research using a single tuned prompt.

## Experience
- Admin: search PubMed, generate once, publish to the gallery.
- Public: browse the gallery and compare Abstract -> Prompt -> Final article.

## Status
- Migration in progress toward the curated gallery experience.

## Requirements
- Python 3.10+ installed

## Run (one command)
```bash
./scripts/dev
```

## Environment setup (recommended)
```bash
cp .env.example .env
```
Then fill in `OPENAI_API_KEY` and `PUBMED_EMAIL` in `.env`.

## Setup (manual)
```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Run (manual)
```bash
python3 -m apps.web.main
```

Then open: `http://127.0.0.1:8000`
Admin panel: `http://127.0.0.1:8000/admin`

## Run tests (one command)
```bash
./scripts/test
```

## Environment variables
- `PUBMED_EMAIL` (required): contact email for NCBI eUtils (admin search).
- `PUBMED_API_KEY` (optional): increases PubMed rate limits.
- `OPENAI_API_KEY` (required for generation): enables admin story generation.
- `ADMIN_PASSWORD` (required for admin login): password for the curator panel.
- `ADMIN_SESSION_SECRET` (optional): signing secret for admin sessions (defaults to `ADMIN_PASSWORD`).
- Model is pinned to `gpt-4.1-2025-04-14`.

## Prompt template
The generation prompt lives in `apps/web/prompts/newsroom_prompt.txt` so you can edit and version it independently.
Published artifacts store a snapshot of the prompt used at generation time.

Example:
```bash
export PUBMED_EMAIL="you@company.com"
export PUBMED_API_KEY="your_key"
```

## Notes
- PubMed search runs live and requires network access for admin curation.
- Results are filtered to primary research articles and require title + abstract + journal + year.
