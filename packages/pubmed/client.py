from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests

from packages.storage.db import Storage


class PubMedClient:
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
    MIN_INTERVAL_WITHOUT_KEY = 1.0 / 3.0
    MIN_INTERVAL_WITH_KEY = 0.11

    def __init__(
        self,
        email: str,
        tool: str = "pubmed_newsroom",
        api_key: Optional[str] = None,
        timeout: int = 30,
        storage: Optional[Storage] = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.email = email
        self.tool = tool
        self.api_key = api_key
        self.timeout = timeout
        self.storage = storage
        self.cache_ttl_seconds = cache_ttl_seconds
        self.session = requests.Session()
        self._last_request_at = 0.0

    def _build_params(self, extra: Dict[str, str]) -> Dict[str, str]:
        params = {"tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        params.update(extra)
        return params

    def _min_interval(self) -> float:
        return self.MIN_INTERVAL_WITH_KEY if self.api_key else self.MIN_INTERVAL_WITHOUT_KEY

    def _throttle(self) -> None:
        min_interval = self._min_interval()
        if self.storage:
            self.storage.acquire_rate_limit("pubmed", min_interval)
            return
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.time()

    def _get(self, endpoint: str, params: Dict[str, str]) -> requests.Response:
        self._throttle()
        url = self.BASE_URL + endpoint + "?" + urlencode(params)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response

    def search_primary_research_pmids(self, term: str, retmax: int = 25) -> List[str]:
        term = term.strip()
        if not term:
            return []

        if self.storage:
            cached = self.storage.get_cached_search(
                term=term,
                retmax=retmax,
                max_age_seconds=self.cache_ttl_seconds,
            )
            if cached is not None:
                return cached

        include_pts = [
            "Clinical Trial",
            "Randomized Controlled Trial",
            "Controlled Clinical Trial",
            "Clinical Trial, Phase I",
            "Clinical Trial, Phase II",
            "Clinical Trial, Phase III",
            "Clinical Trial, Phase IV",
            "Observational Study",
            "Comparative Study",
            "Multicenter Study",
            "Evaluation Study",
            "Validation Study",
        ]
        exclude_pts = [
            "Review",
            "Systematic Review",
            "Meta-Analysis",
            "Editorial",
            "Letter",
            "Comment",
            "Guideline",
            "Practice Guideline",
            "Clinical Trial Protocol",
            "Preprint",
        ]

        include_clause = " OR ".join([f"\"{pt}\"[pt]" for pt in include_pts])
        exclude_clause = " OR ".join([f"\"{pt}\"[pt]" for pt in exclude_pts])

        query = (
            f"({term}) AND \"journal article\"[pt] "
            f"AND ({include_clause}) "
            f"NOT ({exclude_clause})"
        )

        params = self._build_params(
            {
                "db": "pubmed",
                "term": query,
                "retmax": str(retmax),
                "retmode": "json",
            }
        )
        data = self._get("esearch.fcgi", params).json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        if self.storage:
            self.storage.save_search(term, retmax, pmids)
        return pmids

    def fetch_primary_records_with_required_fields(
        self,
        pmids: List[str],
        batch_size: int = 100,
        require: Optional[Dict[str, bool]] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        if not pmids:
            return []

        if require is None:
            require = {"title": True, "abstract": True}

        cached: Dict[str, Dict[str, Any]] = {}
        if self.storage and not force_refresh:
            cached = self.storage.get_records(pmids)

        missing = []
        if force_refresh:
            missing = list(pmids)
        else:
            for pmid in pmids:
                record = cached.get(pmid)
                if record and not self._missing_required(record, require):
                    continue
                missing.append(pmid)

        fetched: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(missing), batch_size):
            chunk = missing[i : i + batch_size]
            params = self._build_params(
                {
                    "db": "pubmed",
                    "id": ",".join(chunk),
                    "retmode": "xml",
                }
            )
            xml_text = self._get("efetch.fcgi", params).text
            records = self._parse_pubmed_xml(xml_text, require=require)
            for record in records:
                pmid = record.get("pmid")
                if pmid:
                    fetched[pmid] = record

        if self.storage and fetched:
            self.storage.upsert_records(list(fetched.values()))

        results = []
        combined = {**cached, **fetched}
        for pmid in pmids:
            record = combined.get(pmid)
            if record and not self._missing_required(record, require):
                results.append(record)
        return results

    def _parse_pubmed_xml(self, xml_text: str, require: Dict[str, bool]) -> List[Dict[str, Any]]:
        root = ET.fromstring(xml_text)
        out: List[Dict[str, Any]] = []

        for article in root.findall(".//PubmedArticle"):
            rec = self._extract_record(article)
            if self._missing_required(rec, require):
                continue
            out.append(rec)

        return out

    def _missing_required(self, rec: Dict[str, Any], require: Dict[str, bool]) -> bool:
        def is_missing(val: Any) -> bool:
            if val is None:
                return True
            if isinstance(val, str) and not val.strip():
                return True
            if isinstance(val, list) and len(val) == 0:
                return True
            return False

        for key, must_have in require.items():
            if must_have and is_missing(rec.get(key)):
                return True
        return False

    def _extract_record(self, article: ET.Element) -> Dict[str, Any]:
        pmid_el = article.find(".//MedlineCitation/PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None

        title_el = article.find(".//Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else None

        abs_nodes = article.findall(".//Article/Abstract/AbstractText")
        abstract = None
        if abs_nodes:
            parts = []
            for node in abs_nodes:
                label = node.attrib.get("Label")
                text = "".join(node.itertext()).strip()
                if not text:
                    continue
                parts.append(f"{label}: {text}" if label else text)
            abstract = "\n".join(parts).strip() if parts else None

        journal_el = article.find(".//Article/Journal/Title")
        journal = "".join(journal_el.itertext()).strip() if journal_el is not None else None

        year = None
        year_el = article.find(".//Article/Journal/JournalIssue/PubDate/Year")
        if year_el is not None and year_el.text:
            year = year_el.text.strip()
        else:
            medline_date_el = article.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
            if medline_date_el is not None and medline_date_el.text:
                medline_date = medline_date_el.text.strip()
                year = medline_date[:4] if len(medline_date) >= 4 and medline_date[:4].isdigit() else medline_date

        publication_date, publication_date_raw, publication_date_source = self._extract_publication_date(article)
        if not year and publication_date:
            year = publication_date.split("-", 1)[0]

        authors = []
        for author in article.findall(".//Article/AuthorList/Author"):
            collective = author.findtext("CollectiveName")
            if collective and collective.strip():
                authors.append(collective.strip())
                continue
            last = author.findtext("LastName") or ""
            fore = author.findtext("ForeName") or ""
            name = (fore + " " + last).strip()
            if name:
                authors.append(name)

        doi = None
        pmcid = None
        for aid in article.findall(".//ArticleIdList/ArticleId"):
            id_type = aid.attrib.get("IdType")
            val = (aid.text or "").strip()
            if not val:
                continue
            if id_type == "doi":
                doi = val
            elif id_type == "pmc":
                pmcid = val if val.startswith("PMC") else f"PMC{val}"

        pub_types = [
            pt.text.strip()
            for pt in article.findall(".//PublicationTypeList/PublicationType")
            if pt.text
        ]

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "publication_date": publication_date,
            "publication_date_raw": publication_date_raw,
            "publication_date_source": publication_date_source,
            "authors": authors,
            "doi": doi,
            "pmcid": pmcid,
            "publication_types": pub_types,
        }

    @staticmethod
    def _month_to_number(month_text: str) -> Optional[int]:
        month = (month_text or "").strip().rstrip(".").lower()
        if not month:
            return None
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        if month in month_map:
            return month_map[month]
        month_match = re.search(r"\b(0?[1-9]|1[0-2])\b", month)
        if month_match:
            return int(month_match.group(1))
        return None

    @classmethod
    def _normalize_date(cls, year_text: str, month_text: str = "", day_text: str = "") -> str:
        year_match = re.search(r"\b(\d{4})\b", (year_text or "").strip())
        if not year_match:
            return ""
        year = year_match.group(1)

        month_num = cls._month_to_number(month_text)
        if month_num is None:
            return year
        month = f"{month_num:02d}"

        day_match = re.search(r"\b([0-2]?\d|3[0-1])\b", (day_text or "").strip())
        if not day_match:
            return f"{year}-{month}"
        day = int(day_match.group(1))
        if day <= 0:
            return f"{year}-{month}"
        return f"{year}-{month}-{day:02d}"

    @classmethod
    def _normalize_medline_date(cls, medline_date: str) -> str:
        text = (medline_date or "").strip()
        if not text:
            return ""
        year_match = re.search(r"\b(\d{4})\b", text)
        if not year_match:
            return ""
        year = year_match.group(1)
        remainder = text[year_match.end() :]

        month_token = ""
        month_match = re.search(r"\b([A-Za-z]{3,9})\.?\b", remainder)
        if month_match:
            month_token = month_match.group(1)

        day_token = ""
        if month_match:
            day_match = re.search(r"\b([0-2]?\d|3[0-1])\b", remainder[month_match.end() :])
            if day_match:
                day_token = day_match.group(1)
        return cls._normalize_date(year, month_token, day_token)

    def _extract_publication_date(self, article: ET.Element) -> tuple[str, str, str]:
        for article_date in article.findall(".//Article/ArticleDate"):
            date_type = (article_date.attrib.get("DateType") or "").strip().lower()
            if date_type != "electronic":
                continue
            year = (article_date.findtext("Year") or "").strip()
            month = (article_date.findtext("Month") or "").strip()
            day = (article_date.findtext("Day") or "").strip()
            normalized = self._normalize_date(year, month, day)
            raw = "-".join(part for part in [year, month, day] if part)
            if normalized:
                return normalized, raw or normalized, "electronic_pub_date"

        pub_date = article.find(".//Article/Journal/JournalIssue/PubDate")
        if pub_date is not None:
            year = (pub_date.findtext("Year") or "").strip()
            month = (pub_date.findtext("Month") or "").strip()
            day = (pub_date.findtext("Day") or "").strip()
            normalized = self._normalize_date(year, month, day)
            raw = " ".join(part for part in [year, month, day] if part)
            if normalized:
                return normalized, raw or normalized, "journal_issue_pub_date"

            medline_date = (pub_date.findtext("MedlineDate") or "").strip()
            normalized_medline = self._normalize_medline_date(medline_date)
            if normalized_medline:
                return normalized_medline, medline_date, "journal_issue_pub_date"

        return "", "", "unknown"
