from pathlib import Path


def _prompt_text() -> str:
    path = Path(__file__).resolve().parents[1] / "apps" / "web" / "prompts" / "newsroom_prompt.txt"
    return path.read_text(encoding="utf-8")


def test_prompt_contains_kernel_placeholder() -> None:
    text = _prompt_text()
    assert "{kernel}" in text


def test_prompt_enforces_json_output() -> None:
    text = _prompt_text().lower()
    assert "json" in text
    assert "return json only" in text


def test_prompt_includes_no_invention_rule() -> None:
    text = _prompt_text().lower()
    assert "do not invent" in text
    assert "unclear" in text
