"""기존 산출물 파일에서 글자를 뽑는다.

결과는 위치가 붙은 조각(Segment)의 목록이다. 정규화한 값이 원본의 어디에서 왔는지
보여줄 수 있어야 하므로, 조각마다 사람이 찾아갈 수 있는 위치(쪽, 문단, 시트의 행)를 남긴다.

지원: 글자가 있는 PDF, DOCX, XLSX, PPTX, HWPX, TXT/MD. 오피스 문서와 HWPX 는 ZIP 안의
XML 이라 표준 라이브러리만으로 읽는다. 스캔 이미지(문자 인식)와 옛 이진 형식(DOC, HWP, XLS)은
지원하지 않는다.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from xml.etree import ElementTree

from .pdf import extract_pages

SUPPORTED = (".pdf", ".docx", ".xlsx", ".pptx", ".hwpx", ".txt", ".md")
_LEGACY = {".doc": "DOCX", ".hwp": "HWPX", ".xls": "XLSX", ".ppt": "PPTX"}
_MAX_MEMBER_BYTES = 30 * 1024 * 1024  # ZIP 안의 파일 하나를 풀었을 때의 상한
MAX_CHARS = 600_000


class UnsupportedArtifact(ValueError):
    """읽을 수 없는 파일. 메시지는 사용자에게 그대로 보여준다."""


@dataclass
class Segment:
    loc: str  # "3쪽", "문단 12", "시트 '점검' 5행", "슬라이드 2"
    text: str


def extract_segments(filename: str, data: bytes) -> list[Segment]:
    suffix = PurePath(filename).suffix.lower()
    if suffix in _LEGACY:
        raise UnsupportedArtifact(
            f"옛 형식({suffix})은 읽을 수 없습니다. {_LEGACY[suffix]} 로 다시 저장해 올리세요."
        )
    if suffix not in SUPPORTED:
        raise UnsupportedArtifact(
            "지원하지 않는 형식입니다. PDF, DOCX, XLSX, PPTX, HWPX, TXT 를 올릴 수 있습니다."
        )
    try:
        segments = _READERS[suffix](data)
    except UnsupportedArtifact:
        raise
    except Exception as exc:  # 손상된 파일은 형식마다 다른 예외를 낸다
        raise UnsupportedArtifact("파일을 읽지 못했습니다. 손상됐을 수 있습니다.") from exc

    segments = [Segment(s.loc, _tidy(s.text)) for s in segments]
    segments = [s for s in segments if s.text]
    if not segments:
        raise UnsupportedArtifact(
            "글자를 읽을 수 없는 파일입니다(스캔 이미지로 보입니다). "
            "문자 인식은 아직 지원하지 않습니다."
        )
    if sum(len(s.text) for s in segments) > MAX_CHARS:
        raise UnsupportedArtifact("문서가 너무 깁니다. 나눠서 올리세요.")
    return segments


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# ── 형식별 ───────────────────────────────────────────────────────────────────


def _pdf(data: bytes) -> list[Segment]:
    pages = extract_pages(data)
    if sum(not p.sparse for p in pages) < max(1, len(pages) // 2):
        return []
    return [Segment(f"{p.page_no}쪽", p.text) for p in pages]


def _text(data: bytes) -> list[Segment]:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnsupportedArtifact("글자 인코딩을 알 수 없는 파일입니다. UTF-8 로 저장해 올리세요.")
    segments, start, block = [], 1, []
    for number, line in enumerate([*text.splitlines(), ""], start=1):
        if line.strip():
            if not block:
                start = number
            block.append(line)
        elif block:
            segments.append(Segment(f"{start}행", "\n".join(block)))
            block = []
    return segments


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    info = archive.getinfo(name)
    if info.file_size > _MAX_MEMBER_BYTES:
        raise UnsupportedArtifact("문서가 너무 큽니다. 나눠서 올리세요.")
    raw = archive.read(name)
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise UnsupportedArtifact("읽을 수 없는 문서입니다.")
    return ElementTree.fromstring(raw)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texts(element: ElementTree.Element, leaf: str = "t") -> str:
    """요소 아래의 글자를 이어 붙인다. 줄바꿈·탭 요소는 공백으로 본다."""
    parts = []
    for node in element.iter():
        name = _local(node.tag)
        if name == leaf and node.text:
            parts.append(node.text)
        elif name in ("br", "tab", "lineBreak"):
            parts.append(" ")
    return "".join(parts)


def _docx(data: bytes) -> list[Segment]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        body = next(e for e in _xml(archive, "word/document.xml") if _local(e.tag) == "body")
    segments, paragraph, table = [], 0, 0
    for block in body:
        name = _local(block.tag)
        if name == "p":
            paragraph += 1
            segments.append(Segment(f"문단 {paragraph}", _texts(block)))
        elif name == "tbl":
            table += 1
            rows = [r for r in block.iter() if _local(r.tag) == "tr"]
            for index, row in enumerate(rows, start=1):
                cells = [_texts(c).strip() for c in row if _local(c.tag) == "tc"]
                segments.append(Segment(f"표 {table} {index}행", " | ".join(cells)))
    return segments


def _xlsx(data: bytes) -> list[Segment]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [
                _texts(item)
                for item in _xml(archive, "xl/sharedStrings.xml")
                if _local(item.tag) == "si"
            ]
        targets = {
            rel.get("Id"): rel.get("Target", "")
            for rel in _xml(archive, "xl/_rels/workbook.xml.rels")
        }
        segments = []
        for sheet in (
            e for e in _xml(archive, "xl/workbook.xml").iter() if _local(e.tag) == "sheet"
        ):
            rel_id = next((v for k, v in sheet.attrib.items() if _local(k) == "id"), None)
            target = targets.get(rel_id, "").lstrip("/")
            path = target if target.startswith("xl/") else f"xl/{target}"
            if path not in names:
                continue
            for row in (e for e in _xml(archive, path).iter() if _local(e.tag) == "row"):
                cells = []
                for cell in (c for c in row if _local(c.tag) == "c"):
                    value = next((v.text or "" for v in cell if _local(v.tag) == "v"), "")
                    if cell.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = _texts(cell)
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    loc = f"시트 '{sheet.get('name', '')}' {row.get('r', '?')}행"
                    segments.append(Segment(loc, " | ".join(cells)))
    return segments


def _numbered(names: list[str], pattern: str) -> list[str]:
    found = [(int(m.group(1)), n) for n in names if (m := re.fullmatch(pattern, n))]
    return [name for _, name in sorted(found)]


def _pptx(data: bytes) -> list[Segment]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = _numbered(archive.namelist(), r"ppt/slides/slide(\d+)\.xml")
        segments = []
        for number, name in enumerate(slides, start=1):
            paragraphs = [_texts(p) for p in _xml(archive, name).iter() if _local(p.tag) == "p"]
            segments.append(Segment(f"슬라이드 {number}", "\n".join(paragraphs)))
    return segments


def _hwpx(data: bytes) -> list[Segment]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sections = _numbered(archive.namelist(), r"Contents/section(\d+)\.xml")
        segments, paragraph = [], 0
        for name in sections:
            for block in (e for e in _xml(archive, name).iter() if _local(e.tag) == "p"):
                # 표 안의 문단은 바깥 문단에도 들어 있으므로, 자기 줄의 글자만 센다.
                runs = [r for r in block if _local(r.tag) == "run"]
                text = "".join(t.text or "" for run in runs for t in run if _local(t.tag) == "t")
                if text.strip():
                    paragraph += 1
                    segments.append(Segment(f"문단 {paragraph}", text))
    return segments


_READERS = {
    ".pdf": _pdf,
    ".txt": _text,
    ".md": _text,
    ".docx": _docx,
    ".xlsx": _xlsx,
    ".pptx": _pptx,
    ".hwpx": _hwpx,
}
