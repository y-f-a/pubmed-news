from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Set

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENTENCE_RE = re.compile(r"[.!?]+")
_SUFFIXES = ("'s", "s", "es", "ed", "ing", "ly")


def _easy_words_path() -> str:
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "data", "dale_chall_easy_words.txt")


def _load_easy_words() -> Set[str]:
    path = _easy_words_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return {line.strip().lower() for line in handle if line.strip()}
    except OSError:
        return set()


_EASY_WORDS = _load_easy_words()


def _tokenize_words(text: str) -> List[str]:
    if not text:
        return []
    return [match.group(0).lower() for match in _WORD_RE.finditer(text)]


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    parts = [part for part in _SENTENCE_RE.split(text) if part.strip()]
    if parts:
        return len(parts)
    return 1 if _WORD_RE.search(text) else 0


def _is_easy_word(word: str, easy_words: Set[str]) -> bool:
    if not easy_words:
        return True
    if word in easy_words:
        return True
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            root = word[: -len(suffix)]
            if root in easy_words:
                return True
    return False


def dale_chall_score(text: str) -> Optional[float]:
    words = _tokenize_words(text)
    if not words:
        return None
    sentences = _count_sentences(text)
    if sentences <= 0:
        sentences = 1

    difficult = sum(1 for word in words if not _is_easy_word(word, _EASY_WORDS))
    difficult_pct = (difficult / len(words)) * 100.0
    score = 0.1579 * difficult_pct + 0.0496 * (len(words) / sentences)
    if difficult_pct > 5.0:
        score += 3.6365
    return round(score, 3)


def score_records(records: Iterable[dict]) -> dict:
    scores = {}
    for record in records:
        pmid = record.get("pmid")
        abstract = record.get("abstract") or ""
        if not pmid:
            continue
        score = dale_chall_score(abstract)
        if score is not None:
            scores[pmid] = score
    return scores
