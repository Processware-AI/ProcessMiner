from types import SimpleNamespace

from app.llm import _fell_back_midway


def _block(kind: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(type=kind, text=text)


def test_no_fallback():
    assert not _fell_back_midway([_block("thinking"), _block("text", '{"a":1}')])


def test_fallback_before_any_text():
    # 처음부터 다른 모델이 응답했으면 그 응답을 그대로 쓴다.
    assert not _fell_back_midway([_block("fallback"), _block("text", '{"a":1}')])


def test_fallback_after_partial_text():
    content = [
        _block("thinking"),
        _block("text", '{"sections":[{"key":"sam'),
        _block("fallback"),
        _block("text", '{"sections":[]}'),
    ]
    assert _fell_back_midway(content)
