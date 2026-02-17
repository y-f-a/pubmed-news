from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit

import requests
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from packages.pubmed.client import PubMedClient
from packages.ranking.readability import score_records
from packages.storage.db import Storage

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency at runtime
    OpenAI = None

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "standfirst": {"type": "string"},
        "story_paragraphs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "what_happens_next": {"type": "string"},
    },
    "required": ["headline", "standfirst", "story_paragraphs"],
    "additionalProperties": False,
}

STORY_CACHE: Dict[str, Dict[str, Any]] = {}


BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "newsroom_prompt.txt")
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "pubmed_news.db")
LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")

SESSION_COOKIE = "admin_session"

SEARCH_SOURCE_CURATOR = "curator_search_action"
SEARCH_SOURCE_INFERRED = "query_history_inferred"
SEARCH_SOURCE_UNKNOWN = "unknown"

PUBLICATION_DATE_SOURCE_ELECTRONIC = "electronic_pub_date"
PUBLICATION_DATE_SOURCE_JOURNAL = "journal_issue_pub_date"
PUBLICATION_DATE_SOURCE_YEAR_FALLBACK = "year_fallback"
PUBLICATION_DATE_SOURCE_UNKNOWN = "unknown"

VALID_SEARCH_SOURCES = {
    SEARCH_SOURCE_CURATOR,
    SEARCH_SOURCE_INFERRED,
    SEARCH_SOURCE_UNKNOWN,
}
VALID_PUBLICATION_DATE_SOURCES = {
    PUBLICATION_DATE_SOURCE_ELECTRONIC,
    PUBLICATION_DATE_SOURCE_JOURNAL,
    PUBLICATION_DATE_SOURCE_YEAR_FALLBACK,
    PUBLICATION_DATE_SOURCE_UNKNOWN,
}

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pubmed_news")

storage = Storage(DB_PATH)

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _require_pubmed_email() -> str:
    email = os.getenv("PUBMED_EMAIL", "").strip()
    if not email or email == "you@example.com":
        raise ValueError("PUBMED_EMAIL must be set to a real contact email for PubMed eUtils.")
    return email


def _client() -> PubMedClient:
    email = _require_pubmed_email()
    api_key = os.getenv("PUBMED_API_KEY")
    return PubMedClient(email=email, api_key=api_key, storage=storage)


def _model_name() -> str:
    return "gpt-4.1-2025-04-14"


def _load_prompt_template() -> str:
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError as exc:
        logger.exception("Prompt template could not be loaded")
        raise RuntimeError("Prompt template could not be loaded.") from exc
    if "{kernel}" not in content:
        logger.error("Prompt template is missing the {kernel} placeholder")
        raise RuntimeError("Prompt template is invalid: missing {kernel} placeholder.")
    return content


def _static_version(filename: str) -> str:
    path = os.path.join(STATIC_DIR, filename)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "1"


def _build_prompt(record: Dict[str, Any]) -> str:
    authors = ", ".join(record.get("authors", [])[:6])
    kernel = "\n".join(
        [
            f"Title: {record.get('title') or ''}",
            f"Journal: {record.get('journal') or ''}",
            f"Year: {record.get('year') or ''}",
            f"Authors: {authors}",
            f"PMID: {record.get('pmid') or ''}",
            "Abstract:",
            record.get("abstract") or "",
        ]
    ).strip()
    template = _load_prompt_template()
    return template.replace("{kernel}", kernel)


def _cache_key(pmid: str, model: str, prompt_text: str) -> str:
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:10]
    return f"{pmid}:{model}:{digest}"


def _extract_response_text(resp: Any) -> str:
    text = getattr(resp, "output_text", "")
    if text:
        return text
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            content_text = getattr(content, "text", "")
            if content_text:
                return content_text
    for choice in getattr(resp, "choices", []) or []:
        message = getattr(choice, "message", None)
        content_text = getattr(message, "content", "")
        if content_text:
            return content_text
    return ""


def _normalize_story(data: Dict[str, Any], fallback_title: str) -> Dict[str, Any]:
    headline = str(data.get("headline", "")).strip() or fallback_title
    standfirst = str(data.get("standfirst", "")).strip()
    paragraphs_raw = data.get("story_paragraphs")
    if isinstance(paragraphs_raw, str):
        paragraph_items = [paragraphs_raw]
    elif isinstance(paragraphs_raw, (list, tuple)):
        paragraph_items = list(paragraphs_raw)
    else:
        paragraph_items = []
    paragraphs: List[str] = []
    for item in paragraph_items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            paragraphs.append(text)
    what_happens_next = str(data.get("what_happens_next", "")).strip()
    return {
        "headline": headline,
        "standfirst": standfirst,
        "story_paragraphs": paragraphs,
        "what_happens_next": what_happens_next,
    }


def _generate_story(
    record: Dict[str, Any],
    prompt_text: str,
    regenerate: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    if OpenAI is None:
        return None, "openai package is not installed.", None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set.", None

    model = _model_name()
    cache_key = _cache_key(record.get("pmid") or "", model, prompt_text)
    if not regenerate and cache_key in STORY_CACHE:
        return STORY_CACHE[cache_key], None, model

    try:
        client = OpenAI(api_key=api_key)
    except Exception as exc:
        logger.exception("OpenAI client initialization failed")
        return None, f"LLM client initialization failed: {exc}", None
    try:
        if hasattr(client, "responses"):
            resp = client.responses.create(
                model=model,
                input=prompt_text,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "news_story",
                        "schema": STORY_SCHEMA,
                        "strict": True,
                    },
                },
            )
        else:
            logger.warning("OpenAI client missing responses API; falling back to chat completions")
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt_text}],
                response_format={"type": "json_object"},
            )
    except Exception as exc:
        logger.exception("LLM request failed")
        return None, f"LLM request failed: {exc}", model

    text = _extract_response_text(resp)
    if not text:
        return None, "LLM returned an empty response.", model

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.exception("LLM returned invalid JSON")
        return None, "LLM returned invalid JSON.", model

    story = _normalize_story(data, record.get("title") or "Untitled study")
    STORY_CACHE[cache_key] = story
    return story, None, model


def _admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "").strip()


def _session_secret() -> str:
    return os.getenv("ADMIN_SESSION_SECRET", "").strip() or _admin_password()


def _sign_session(value: str) -> str:
    secret = _session_secret()
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def _verify_session(token: str) -> bool:
    if not token or "." not in token:
        return False
    value, digest = token.rsplit(".", 1)
    expected = _sign_session(value).rsplit(".", 1)[1]
    return hmac.compare_digest(digest, expected)


def _is_admin(request: Request) -> bool:
    if not _session_secret():
        return False
    token = request.cookies.get(SESSION_COOKIE, "")
    return _verify_session(token)


def _admin_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(f"/admin/login?next={quote(next_path)}", status_code=303)


def _coerce_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_publication_date(record: Dict[str, Any]) -> Tuple[str, str, str]:
    publication_date = str(record.get("publication_date") or "").strip()
    publication_date_raw = str(record.get("publication_date_raw") or "").strip()
    publication_date_source = str(record.get("publication_date_source") or "").strip()

    if publication_date:
        if not publication_date_raw:
            publication_date_raw = publication_date
        if publication_date_source not in VALID_PUBLICATION_DATE_SOURCES:
            year = str(record.get("year") or "").strip()
            if year and publication_date == year:
                publication_date_source = PUBLICATION_DATE_SOURCE_YEAR_FALLBACK
            else:
                publication_date_source = PUBLICATION_DATE_SOURCE_UNKNOWN
        return publication_date, publication_date_raw, publication_date_source

    year = str(record.get("year") or "").strip()
    if year:
        return year, year, PUBLICATION_DATE_SOURCE_YEAR_FALLBACK
    return "", "", PUBLICATION_DATE_SOURCE_UNKNOWN


def _artifact_metadata(
    record: Dict[str, Any],
    search_term: str = "",
    search_ran_at: Optional[float] = None,
    search_ran_at_source: str = SEARCH_SOURCE_UNKNOWN,
) -> Dict[str, Any]:
    publication_date, publication_date_raw, publication_date_source = _resolve_publication_date(record)
    normalized_search_ran_at = _coerce_epoch(search_ran_at)
    normalized_search_source = (
        search_ran_at_source if search_ran_at_source in VALID_SEARCH_SOURCES else SEARCH_SOURCE_UNKNOWN
    )
    return {
        "title": record.get("title") or "",
        "journal": record.get("journal") or "",
        "year": record.get("year") or "",
        "authors": record.get("authors") or [],
        "doi": record.get("doi") or "",
        "pmcid": record.get("pmcid") or "",
        "search_term": (search_term or "").strip(),
        "search_ran_at": normalized_search_ran_at,
        "search_ran_at_source": normalized_search_source,
        "publication_date": publication_date,
        "publication_date_raw": publication_date_raw,
        "publication_date_source": publication_date_source,
    }


def _format_date(epoch: Optional[float]) -> str:
    if not epoch:
        return ""
    return time.strftime("%b %d, %Y", time.localtime(epoch))


def _format_datetime(epoch: Optional[float]) -> str:
    if not epoch:
        return ""
    return time.strftime("%b %d, %Y %H:%M", time.localtime(epoch))


def _format_publication_date(value: str, raw_value: str = "") -> str:
    publication_date = (value or "").strip()
    raw_date = (raw_value or "").strip()
    if publication_date:
        parts = publication_date.split("-")
        if len(parts) == 3:
            year, month, day = parts
            if year.isdigit() and month.isdigit() and day.isdigit():
                try:
                    parsed = time.strptime(f"{year}-{month}-{day}", "%Y-%m-%d")
                    return time.strftime("%b %d %Y", parsed)
                except ValueError:
                    pass
        elif len(parts) == 2:
            year, month = parts
            if year.isdigit() and month.isdigit():
                try:
                    parsed = time.strptime(f"{year}-{month}", "%Y-%m")
                    return time.strftime("%b %d %Y", parsed)
                except ValueError:
                    pass
        elif len(parts) == 1:
            year = parts[0]
            if year.isdigit() and not raw_date:
                try:
                    parsed = time.strptime(year, "%Y")
                    return time.strftime("%b %d %Y", parsed)
                except ValueError:
                    pass

    if raw_date:
        cleaned = " ".join(raw_date.replace(",", " ").split())
        for input_fmt, output_fmt in [
            ("%Y %b %d", "%b %d %Y"),
            ("%Y %B %d", "%b %d %Y"),
            ("%b %d %Y", "%b %d %Y"),
            ("%B %d %Y", "%b %d %Y"),
            ("%Y %b", "%b %Y"),
            ("%Y %B", "%b %Y"),
            ("%b %Y", "%b %Y"),
            ("%B %Y", "%b %Y"),
            ("%Y", "%b %d %Y"),
        ]:
            try:
                parsed = time.strptime(cleaned, input_fmt)
                return time.strftime(output_fmt, parsed)
            except ValueError:
                continue

    return publication_date or raw_date


def _metadata_for_display(metadata: Dict[str, Any]) -> Dict[str, Any]:
    display = dict(metadata or {})
    search_ran_at = _coerce_epoch(display.get("search_ran_at"))
    search_term = str(display.get("search_term") or "").strip()
    publication_date = str(display.get("publication_date") or "").strip()
    publication_date_raw = str(display.get("publication_date_raw") or "").strip()

    display["search_ran_at"] = search_ran_at
    display["search_term_display"] = search_term or "Unknown"
    display["search_ran_at_display"] = _format_datetime(search_ran_at) if search_ran_at else "Unknown"
    display["publication_date_display"] = (
        _format_publication_date(publication_date, publication_date_raw) or "Unknown"
    )
    return display


def _enrich_record_publication_date(record: Dict[str, Any], pmid: str) -> Dict[str, Any]:
    publication_date = str(record.get("publication_date") or "").strip()
    if publication_date:
        return record
    try:
        client = _client()
    except ValueError:
        return record
    try:
        records = client.fetch_primary_records_with_required_fields(
            [pmid],
            require={"title": False},
            force_refresh=True,
        )
    except requests.RequestException:
        logger.exception("PubMed enrichment fetch failed for publication date")
        return record
    if not records:
        return record
    enriched = records[0]
    merged = dict(record)
    merged.update(enriched)
    return merged


def _backfill_artifact_provenance() -> None:
    try:
        artifacts = storage.list_artifacts(published_only=False)
    except sqlite3.Error:
        logger.exception("Failed to load artifacts for provenance backfill")
        return

    updates = 0
    for artifact in artifacts:
        pmid = str(artifact.get("pmid") or "").strip()
        if not pmid:
            continue

        metadata = dict(artifact.get("metadata_snapshot") or {})
        changed = False

        search_term = str(metadata.get("search_term") or "").strip()
        if metadata.get("search_term") != search_term:
            metadata["search_term"] = search_term
            changed = True

        search_ran_at = _coerce_epoch(metadata.get("search_ran_at"))
        if metadata.get("search_ran_at") != search_ran_at:
            metadata["search_ran_at"] = search_ran_at
            changed = True

        inferred_used = False
        if not search_term or search_ran_at is None:
            inferred = storage.find_latest_query_for_pmid(
                pmid,
                before_created_at=artifact.get("created_at"),
            )
            if inferred:
                inferred_term = str(inferred.get("term") or "").strip()
                inferred_created_at = _coerce_epoch(inferred.get("created_at"))
                if not search_term and inferred_term:
                    metadata["search_term"] = inferred_term
                    search_term = inferred_term
                    changed = True
                    inferred_used = True
                if search_ran_at is None and inferred_created_at is not None:
                    metadata["search_ran_at"] = inferred_created_at
                    search_ran_at = inferred_created_at
                    changed = True
                    inferred_used = True

        search_source = str(metadata.get("search_ran_at_source") or "").strip()
        if search_source not in VALID_SEARCH_SOURCES:
            metadata["search_ran_at_source"] = (
                SEARCH_SOURCE_INFERRED if inferred_used else SEARCH_SOURCE_UNKNOWN
            )
            changed = True

        publication_date, publication_date_raw, publication_date_source = _resolve_publication_date(metadata)
        if metadata.get("publication_date") != publication_date:
            metadata["publication_date"] = publication_date
            changed = True
        if metadata.get("publication_date_raw") != publication_date_raw:
            metadata["publication_date_raw"] = publication_date_raw
            changed = True
        if metadata.get("publication_date_source") != publication_date_source:
            metadata["publication_date_source"] = publication_date_source
            changed = True

        if changed:
            storage.update_artifact_metadata_snapshot(pmid, metadata)
            updates += 1

    if updates:
        logger.info("Backfilled artifact provenance for %s artifact(s)", updates)


def _safe_next(next_path: str) -> str:
    default_path = "/admin/search"
    candidate = (next_path or "").strip()
    if not candidate:
        return default_path
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return default_path
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default_path
    return candidate


_backfill_artifact_provenance()


@app.get("/", response_class=HTMLResponse)
def gallery(request: Request) -> HTMLResponse:
    artifacts = storage.list_artifacts(published_only=True)
    cards = []
    for artifact in artifacts:
        metadata = _metadata_for_display(artifact.get("metadata_snapshot", {}))
        cards.append(
            {
                "pmid": artifact.get("pmid"),
                "headline": artifact.get("headline"),
                "standfirst": artifact.get("standfirst"),
                "journal": metadata.get("journal", ""),
                "year": metadata.get("year", ""),
                "search_term": metadata.get("search_term_display", "Unknown"),
                "article_published": metadata.get("publication_date_display", "Unknown"),
            }
        )
    return templates.TemplateResponse(
        "public/index.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "artifacts": cards,
        },
    )


@app.get("/story/{pmid}", response_class=HTMLResponse)
def story(request: Request, pmid: str) -> HTMLResponse:
    artifact = storage.get_artifact(pmid)
    if not artifact or not artifact.get("published_at"):
        return templates.TemplateResponse(
            "public/story.html",
            {
                "request": request,
                "css_version": _static_version("styles.css"),
                "not_found": True,
                "pmid": pmid,
            },
            status_code=404,
        )
    metadata = _metadata_for_display(artifact.get("metadata_snapshot", {}))
    return templates.TemplateResponse(
        "public/story.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "artifact": artifact,
            "metadata": metadata,
            "published_at": _format_date(artifact.get("published_at")),
            "not_found": False,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_root(request: Request) -> RedirectResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    return RedirectResponse("/admin/search", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, next: str = "/admin/search") -> HTMLResponse:
    return templates.TemplateResponse(
        "admin/login.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "next": _safe_next(next),
        },
    )


@app.post("/admin/login")
async def admin_login_submit(
    request: Request,
    password: str = Form(""),
    next: str = Form("/admin/search"),
) -> HTMLResponse:
    admin_password = _admin_password()
    next_path = _safe_next(next)
    if not admin_password:
        return templates.TemplateResponse(
            "admin/login.html",
            {
                "request": request,
                "css_version": _static_version("styles.css"),
                "js_version": _static_version("app.js"),
                "next": next_path,
                "error": "ADMIN_PASSWORD is not configured.",
            },
            status_code=500,
        )
    if password != admin_password:
        return templates.TemplateResponse(
            "admin/login.html",
            {
                "request": request,
                "css_version": _static_version("styles.css"),
                "js_version": _static_version("app.js"),
                "next": next_path,
                "error": "Incorrect password.",
            },
            status_code=401,
        )
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        _sign_session("admin"),
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/admin/logout")
def admin_logout(request: Request) -> RedirectResponse:
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/admin/search", response_class=HTMLResponse)
def admin_search(
    request: Request,
    term: str = Query(default=""),
    sort: str = Query(default=""),
    error: str = Query(default=""),
    message: str = Query(default=""),
) -> HTMLResponse:
    if not _is_admin(request):
        return _admin_redirect(request)

    term = term.strip()
    sort = sort.strip().lower()
    if not sort:
        sort = "readability"
    results: List[Dict[str, Any]] = []
    rankings: Dict[str, Optional[float]] = {}
    search_ran_at: Optional[float] = time.time() if term else None

    if term:
        try:
            client = _client()
        except ValueError as exc:
            error = str(exc)
            client = None
        if client:
            try:
                pmids = client.search_primary_research_pmids(term, retmax=20)
                records = client.fetch_primary_records_with_required_fields(
                    pmids,
                    require={"title": True, "abstract": True, "journal": True, "year": True},
                )
            except requests.RequestException:
                logger.exception("PubMed request failed")
                error = "PubMed request failed. Please try again."
            else:
                if sort == "readability":
                    scores = storage.get_scores(pmids)
                    missing_records = [rec for rec in records if rec.get("pmid") not in scores]
                    new_scores = score_records(missing_records)
                    if new_scores:
                        storage.upsert_scores(new_scores)
                        scores.update(new_scores)

                    def score_key(record: Dict[str, Any]) -> float:
                        score = scores.get(record.get("pmid") or "")
                        return score if score is not None else float("-inf")

                    records = sorted(records, key=score_key, reverse=True)
                    rankings = scores

                for rec in records:
                    pmid = rec.get("pmid") or ""
                    if not pmid:
                        continue
                    artifact = storage.get_artifact(pmid)
                    results.append(
                        {
                            "pmid": pmid,
                            "title": rec.get("title") or "",
                            "abstract": rec.get("abstract") or "",
                            "journal": rec.get("journal") or "",
                            "year": rec.get("year") or "",
                            "publication_types": rec.get("publication_types") or [],
                            "doi": rec.get("doi") or "",
                            "readability_score": rankings.get(pmid),
                            "has_artifact": artifact is not None,
                            "is_published": bool(artifact and artifact.get("published_at")),
                        }
                    )

    return templates.TemplateResponse(
        "admin/search.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "term": term,
            "sort": sort,
            "results": results,
            "search_ran_at": search_ran_at,
            "error": error,
            "message": message,
        },
    )


@app.post("/admin/generate")
def admin_generate(
    request: Request,
    pmid: str = Form(""),
    term: str = Form(""),
    sort: str = Form(""),
    search_ran_at: str = Form(""),
    regenerate: str = Form(""),
) -> RedirectResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    pmid = pmid.strip()
    term = term.strip()
    sort = sort.strip().lower()
    search_ran_at_value = _coerce_epoch(search_ran_at)
    if not pmid:
        return RedirectResponse("/admin/search?error=PMID%20required", status_code=303)
    record = storage.get_record(pmid)
    if not record:
        try:
            client = _client()
            records = client.fetch_primary_records_with_required_fields(
                [pmid],
                require={"title": True, "abstract": True, "journal": True, "year": True},
            )
            record = records[0] if records else None
        except requests.RequestException:
            logger.exception("PubMed fetch failed")
            return RedirectResponse(
                f"/admin/search?term={quote(term)}&sort={quote(sort)}&error="
                f"{quote('PubMed fetch failed. Please try again.')}",
                status_code=303,
            )
    if not record:
        return RedirectResponse(
            f"/admin/search?term={quote(term)}&sort={quote(sort)}&error="
            f"{quote('Record not found for that PMID.')}",
            status_code=303,
        )

    record = _enrich_record_publication_date(record, pmid)
    try:
        prompt_text = _build_prompt(record)
    except RuntimeError as exc:
        return RedirectResponse(
            f"/admin/search?term={quote(term)}&sort={quote(sort)}&error={quote(str(exc))}",
            status_code=303,
        )
    story, story_error, _model = _generate_story(
        record,
        prompt_text,
        regenerate=bool(regenerate),
    )
    if story_error:
        return RedirectResponse(
            f"/admin/search?term={quote(term)}&sort={quote(sort)}&error="
            f"{quote(story_error)}",
            status_code=303,
        )

    metadata_snapshot = _artifact_metadata(
        record,
        search_term=term,
        search_ran_at=search_ran_at_value,
        search_ran_at_source=SEARCH_SOURCE_CURATOR if term else SEARCH_SOURCE_UNKNOWN,
    )
    storage.upsert_artifact(
        pmid=pmid,
        headline=story.get("headline", ""),
        standfirst=story.get("standfirst", ""),
        story=story,
        prompt_text=prompt_text,
        abstract_snapshot=record.get("abstract") or "",
        metadata_snapshot=metadata_snapshot,
    )
    return RedirectResponse(f"/admin/artifact/{pmid}", status_code=303)


@app.get("/admin/artifact/{pmid}", response_class=HTMLResponse)
def admin_artifact(request: Request, pmid: str, message: str = "") -> HTMLResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    artifact = storage.get_artifact(pmid)
    if not artifact:
        return templates.TemplateResponse(
            "admin/artifact.html",
            {
                "request": request,
                "css_version": _static_version("styles.css"),
                "js_version": _static_version("app.js"),
                "pmid": pmid,
                "not_found": True,
                "message": message,
            },
            status_code=404,
        )
    metadata = _metadata_for_display(artifact.get("metadata_snapshot", {}))
    return templates.TemplateResponse(
        "admin/artifact.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "artifact": artifact,
            "metadata": metadata,
            "published_at": _format_date(artifact.get("published_at")),
            "not_found": False,
            "message": message,
        },
    )


@app.post("/admin/publish")
def admin_publish(
    request: Request,
    pmid: str = Form(""),
    featured_rank: str = Form(""),
) -> RedirectResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    pmid = pmid.strip()
    if not pmid:
        return RedirectResponse("/admin/gallery?error=PMID%20required", status_code=303)
    rank_value: Optional[int]
    if featured_rank.strip():
        try:
            rank_value = int(featured_rank)
        except ValueError:
            return RedirectResponse(
                f"/admin/artifact/{quote(pmid)}?message={quote('Featured rank must be a number.')}",
                status_code=303,
            )
    else:
        rank_value = None
    storage.publish_artifact(pmid, rank_value)
    return RedirectResponse("/admin/gallery?message=Published", status_code=303)


@app.get("/admin/gallery", response_class=HTMLResponse)
def admin_gallery(request: Request, message: str = "", error: str = "") -> HTMLResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    artifacts = storage.list_artifacts(published_only=True)
    entries = []
    for artifact in artifacts:
        metadata = _metadata_for_display(artifact.get("metadata_snapshot", {}))
        published_at = _format_date(artifact.get("published_at"))
        entries.append(
            {
                "pmid": artifact.get("pmid"),
                "headline": artifact.get("headline"),
                "journal": metadata.get("journal", ""),
                "year": metadata.get("year", ""),
                "search_term": metadata.get("search_term_display", "Unknown"),
                "publication_date": metadata.get("publication_date_display", "Unknown"),
                "featured_rank": artifact.get("featured_rank"),
                "published_at": published_at or "Unknown",
            }
        )
    return templates.TemplateResponse(
        "admin/gallery.html",
        {
            "request": request,
            "css_version": _static_version("styles.css"),
            "js_version": _static_version("app.js"),
            "artifacts": entries,
            "message": message,
            "error": error,
        },
    )


@app.post("/admin/feature")
def admin_feature(
    request: Request,
    pmid: str = Form(""),
    featured_rank: str = Form(""),
) -> RedirectResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    pmid = pmid.strip()
    if not pmid:
        return RedirectResponse("/admin/gallery?error=PMID%20required", status_code=303)
    if not featured_rank.strip():
        storage.update_featured_rank(pmid, None)
        return RedirectResponse("/admin/gallery?message=Updated", status_code=303)
    try:
        rank_value = int(featured_rank)
    except ValueError:
        return RedirectResponse("/admin/gallery?error=Featured%20rank%20must%20be%20a%20number", status_code=303)
    storage.update_featured_rank(pmid, rank_value)
    return RedirectResponse("/admin/gallery?message=Updated", status_code=303)


@app.post("/admin/unpublish")
def admin_unpublish(request: Request, pmid: str = Form("")) -> RedirectResponse:
    if not _is_admin(request):
        return _admin_redirect(request)
    pmid = pmid.strip()
    if not pmid:
        return RedirectResponse("/admin/gallery?error=PMID%20required", status_code=303)
    storage.unpublish_artifact(pmid)
    return RedirectResponse("/admin/gallery?message=Unpublished", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.web.main:app", host="127.0.0.1", port=8000, reload=True)
