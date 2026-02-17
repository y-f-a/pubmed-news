from packages.ranking.readability import dale_chall_score, score_records


def test_dale_chall_score_empty_returns_none() -> None:
    assert dale_chall_score("") is None


def test_dale_chall_score_simple_vs_complex() -> None:
    simple = "The cat sat on the mat. The dog ran to the tree."
    complex_text = "Neurodegenerative disorders manifest through multifactorial pathophysiological mechanisms."
    simple_score = dale_chall_score(simple)
    complex_score = dale_chall_score(complex_text)
    assert simple_score is not None
    assert complex_score is not None
    assert complex_score > simple_score


def test_score_records_returns_scores() -> None:
    records = [{"pmid": "1", "abstract": "The cat sat on the mat."}]
    scores = score_records(records)
    assert scores["1"] is not None
