import time

from packages.storage.db import Storage


def _artifact_payload(pmid: str) -> dict:
    return {
        "pmid": pmid,
        "headline": f"Headline {pmid}",
        "standfirst": "Standfirst text.",
        "story": {
            "headline": f"Headline {pmid}",
            "standfirst": "Standfirst text.",
            "story_paragraphs": ["Paragraph one.", "Paragraph two."],
            "what_happens_next": "",
        },
        "prompt_text": "Prompt snapshot.",
        "abstract_snapshot": "Abstract snapshot.",
        "metadata_snapshot": {"journal": "Journal A", "year": "2024"},
    }


def test_artifact_publish_and_list(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    payload = _artifact_payload("123")
    storage.upsert_artifact(**payload)

    assert storage.list_artifacts(published_only=True) == []

    storage.publish_artifact("123", featured_rank=2)
    published = storage.list_artifacts(published_only=True)
    assert len(published) == 1
    assert published[0]["pmid"] == "123"
    assert published[0]["featured_rank"] == 2

    storage.unpublish_artifact("123")
    assert storage.list_artifacts(published_only=True) == []


def test_featured_ordering(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    storage.upsert_artifact(**_artifact_payload("1"))
    storage.upsert_artifact(**_artifact_payload("2"))
    storage.publish_artifact("1", featured_rank=3)
    storage.publish_artifact("2", featured_rank=1)

    ordered = storage.list_artifacts(published_only=True)
    assert [item["pmid"] for item in ordered] == ["2", "1"]


def test_find_latest_query_for_pmid_prefers_pre_artifact_query(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    storage.save_search("older term", retmax=20, pmids=["123"])
    time.sleep(0.01)
    storage.upsert_artifact(**_artifact_payload("123"))
    artifact_created_at = storage.get_artifact("123")["created_at"]
    time.sleep(0.01)
    storage.save_search("newer term", retmax=20, pmids=["123"])

    inferred = storage.find_latest_query_for_pmid("123", before_created_at=artifact_created_at)
    assert inferred is not None
    assert inferred["term"] == "older term"

    fallback = storage.find_latest_query_for_pmid("123", before_created_at=0.0)
    assert fallback is not None
    assert fallback["term"] == "newer term"


def test_update_artifact_metadata_snapshot_preserves_publish_and_order(tmp_path) -> None:
    storage = Storage(str(tmp_path / "test.db"))
    storage.upsert_artifact(**_artifact_payload("123"))
    storage.publish_artifact("123", featured_rank=4)
    before = storage.get_artifact("123")

    updated_metadata = {
        "journal": "Journal A",
        "year": "2024",
        "search_term": "asthma",
        "search_ran_at": 1700000000.0,
        "search_ran_at_source": "query_history_inferred",
        "publication_date": "2024",
        "publication_date_raw": "2024",
        "publication_date_source": "year_fallback",
    }
    storage.update_artifact_metadata_snapshot("123", updated_metadata)
    after = storage.get_artifact("123")

    assert after["published_at"] == before["published_at"]
    assert after["featured_rank"] == before["featured_rank"]
    assert after["metadata_snapshot"]["search_term"] == "asthma"
