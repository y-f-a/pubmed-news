import pytest

from apps.web import main as web_main
from apps.web.main import _artifact_metadata, _metadata_for_display, _normalize_story, _safe_next


def test_safe_next_accepts_local_paths() -> None:
    assert _safe_next("/admin/search") == "/admin/search"
    assert _safe_next("/admin/search?term=asthma&sort=readability") == "/admin/search?term=asthma&sort=readability"


def test_safe_next_rejects_external_or_malformed_values() -> None:
    assert _safe_next("") == "/admin/search"
    assert _safe_next("admin/search") == "/admin/search"
    assert _safe_next("//evil.example") == "/admin/search"
    assert _safe_next("https://evil.example/path") == "/admin/search"


def test_normalize_story_handles_non_list_paragraphs() -> None:
    null_paragraphs = _normalize_story({"story_paragraphs": None}, "Fallback title")
    assert null_paragraphs["story_paragraphs"] == []

    string_paragraphs = _normalize_story({"story_paragraphs": "  One paragraph.  "}, "Fallback title")
    assert string_paragraphs["story_paragraphs"] == ["One paragraph."]


def test_normalize_story_sanitizes_paragraph_list_items() -> None:
    story = _normalize_story(
        {"story_paragraphs": ["  First paragraph. ", "", None, 123]},
        "Fallback title",
    )
    assert story["story_paragraphs"] == ["First paragraph.", "123"]


def test_artifact_metadata_includes_curator_search_and_publication_fields() -> None:
    metadata = _artifact_metadata(
        {
            "title": "Study title",
            "journal": "Journal A",
            "year": "2024",
            "publication_date": "2023-11-02",
            "publication_date_raw": "2023-11-02",
            "publication_date_source": "electronic_pub_date",
        },
        search_term="  asthma in children  ",
        search_ran_at=1700000000.5,
        search_ran_at_source="curator_search_action",
    )
    assert metadata["search_term"] == "asthma in children"
    assert metadata["search_ran_at"] == 1700000000.5
    assert metadata["search_ran_at_source"] == "curator_search_action"
    assert metadata["publication_date"] == "2023-11-02"
    assert metadata["publication_date_source"] == "electronic_pub_date"


def test_artifact_metadata_publication_year_fallback_and_unknown_display() -> None:
    metadata = _artifact_metadata(
        {
            "title": "Study title",
            "journal": "Journal A",
            "year": "2020",
        }
    )
    assert metadata["publication_date"] == "2020"
    assert metadata["publication_date_raw"] == "2020"
    assert metadata["publication_date_source"] == "year_fallback"

    display = _metadata_for_display({})
    assert display["search_term_display"] == "Unknown"
    assert display["search_ran_at_display"] == "Unknown"
    assert display["publication_date_display"] == "Unknown"


def test_metadata_for_display_formats_publication_date_long() -> None:
    display = _metadata_for_display({"publication_date": "2026-01-12"})
    assert display["publication_date_display"] == "Jan 12 2026"


def test_metadata_for_display_formats_publication_date_from_raw() -> None:
    display = _metadata_for_display({"publication_date": "2026", "publication_date_raw": "2026 Jan 31"})
    assert display["publication_date_display"] == "Jan 31 2026"


def test_metadata_for_display_formats_year_only_publication_date() -> None:
    display = _metadata_for_display({"publication_date": "2025"})
    assert display["publication_date_display"] == "Jan 01 2025"


def test_metadata_for_display_formats_year_only_publication_date_with_raw_year() -> None:
    display = _metadata_for_display({"publication_date": "2025", "publication_date_raw": "2025"})
    assert display["publication_date_display"] == "Jan 01 2025"


def test_load_prompt_template_raises_when_file_missing(monkeypatch) -> None:
    monkeypatch.setattr(web_main, "PROMPT_PATH", "/tmp/does-not-exist/newsroom_prompt.txt")
    with pytest.raises(RuntimeError, match="could not be loaded"):
        web_main._load_prompt_template()


def test_load_prompt_template_raises_without_kernel_placeholder(tmp_path, monkeypatch) -> None:
    prompt_file = tmp_path / "newsroom_prompt.txt"
    prompt_file.write_text("Return JSON only.", encoding="utf-8")
    monkeypatch.setattr(web_main, "PROMPT_PATH", str(prompt_file))
    with pytest.raises(RuntimeError, match="missing \\{kernel\\} placeholder"):
        web_main._load_prompt_template()
