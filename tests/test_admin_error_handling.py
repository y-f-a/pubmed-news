import requests
from fastapi.testclient import TestClient

from apps.web import main as web_main


class _FailingFetchClient:
    def __init__(self, message: str) -> None:
        self.message = message

    def fetch_primary_records_with_required_fields(self, *args, **kwargs):
        raise requests.RequestException(self.message)


class _FailingSearchClient:
    def __init__(self, message: str) -> None:
        self.message = message

    def search_primary_research_pmids(self, *args, **kwargs):
        raise requests.RequestException(self.message)


def test_admin_generate_redirect_sanitizes_pubmed_exception(monkeypatch) -> None:
    secret_error = "upstream failed: https://example.invalid/?api_key=SECRET_KEY"
    monkeypatch.setattr(web_main, "_is_admin", lambda _request: True)
    monkeypatch.setattr(web_main.storage, "get_record", lambda _pmid: None)
    monkeypatch.setattr(web_main, "_client", lambda: _FailingFetchClient(secret_error))

    with TestClient(web_main.app) as client:
        response = client.post(
            "/admin/generate",
            data={"pmid": "123", "term": "asthma", "sort": "readability"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "PubMed%20fetch%20failed.%20Please%20try%20again." in location
    assert "SECRET_KEY" not in location
    assert "api_key" not in location


def test_admin_search_sanitizes_pubmed_exception(monkeypatch) -> None:
    secret_error = "upstream failed: https://example.invalid/?api_key=SECRET_KEY"
    monkeypatch.setattr(web_main, "_is_admin", lambda _request: True)
    monkeypatch.setattr(web_main, "_client", lambda: _FailingSearchClient(secret_error))

    with TestClient(web_main.app) as client:
        response = client.get("/admin/search?term=asthma")

    assert response.status_code == 200
    assert "PubMed request failed. Please try again." in response.text
    assert "SECRET_KEY" not in response.text
    assert "api_key" not in response.text
