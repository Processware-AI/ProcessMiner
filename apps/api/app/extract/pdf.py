"""PDF 에서 쪽별 텍스트를 뽑는다.

요건의 근거는 '몇 쪽의 어느 구절' 로 남기므로 쪽 경계를 유지한다.
쪽마다 반복되는 머리말·꼬리말(문서 번호, 쪽 번호)은 본문이 아니므로 걷어낸다.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader

# 이보다 글자가 적은 쪽은 스캔 이미지일 가능성이 높다(문자 인식이 필요).
SPARSE_PAGE_CHARS = 100
# 쪽의 위·아래에서 이 줄 수까지만 머리말·꼬리말 후보로 본다.
_EDGE_LINES = 3
# 전체 쪽의 이 비율 이상에서 반복되면 머리말·꼬리말로 본다(홀짝 쪽이 서로 다른 경우 포함).
_REPEAT_RATIO = 0.25


@dataclass
class PageText:
    page_no: int  # 1 부터
    text: str
    sparse: bool  # 글자가 거의 없는 쪽


def _shape(line: str) -> str:
    """쪽마다 숫자만 달라지는 줄을 같은 것으로 보기 위한 모양."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line)).strip()


def _strip_running_lines(pages: list[list[str]]) -> list[list[str]]:
    if len(pages) < 4:
        return pages
    counts: Counter[str] = Counter()
    for lines in pages:
        content = [line for line in lines if line.strip()]
        edges = content[:_EDGE_LINES] + content[-_EDGE_LINES:]
        counts.update({_shape(line) for line in edges})
    threshold = max(3, int(len(pages) * _REPEAT_RATIO))
    running = {shape for shape, n in counts.items() if n >= threshold and shape}

    cleaned: list[list[str]] = []
    for lines in pages:
        content_idx = [i for i, line in enumerate(lines) if line.strip()]
        edge_idx = set(content_idx[:_EDGE_LINES] + content_idx[-_EDGE_LINES:])
        cleaned.append(
            [
                line
                for i, line in enumerate(lines)
                if not (i in edge_idx and _shape(line) in running)
            ]
        )
    return cleaned


def extract_pages(data: bytes) -> list[PageText]:
    """PDF 바이트에서 쪽별 본문을 뽑는다. 암호화돼 열 수 없으면 ValueError."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("암호로 보호된 PDF 는 읽을 수 없습니다.")

    raw = [(page.extract_text() or "").splitlines() for page in reader.pages]
    pages = _strip_running_lines(raw)
    result = []
    for number, lines in enumerate(pages, start=1):
        text = "\n".join(line.rstrip() for line in lines).strip()
        result.append(PageText(page_no=number, text=text, sparse=len(text) < SPARSE_PAGE_CHARS))
    return result
