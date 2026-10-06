"""S4: 기존 산출물을 표준 양식의 기록으로 옮긴다.

파일 읽기는 진짜로 하고(작은 문서를 만들어 넣는다) 모델 호출만 가짜로 바꾼다.
확인하는 것은 그 사이의 규칙이다: 동의 없이는 모델로 보내지 않고, 원본과 대조되지 않은 값은
사람이 확인해야 하며, 사람이 채운 값은 원본에서 온 값과 구분된다.
"""

import io
import zipfile

import pytest

from app import llm, worker
from app.extract.artifact import Segment, UnsupportedArtifact, extract_segments
from app.pipelines import harmonize
from app.pipelines.harmonize import (
    ExtractedField,
    MatchCandidate,
    MatchOutput,
    NormalizeOutput,
)
from tests.conftest import add_member, new_system, new_tenant
from tests.test_documents import _create

REPORT = """위험통제 검증 결과 보고
작성: 김개발 (2024-03-05)

대상: 주입펌프 제어 SW v2.3
결과: 합격. 경보 지연 없음.
""".encode()


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# ── 파일 읽기 ────────────────────────────────────────────────────────────────


def test_text_is_extracted_with_locations_from_each_format():
    assert extract_segments("보고.txt", REPORT) == [
        Segment("1행", "위험통제 검증 결과 보고\n작성: 김개발 (2024-03-05)"),
        Segment("4행", "대상: 주입펌프 제어 SW v2.3\n결과: 합격. 경보 지연 없음."),
    ]
    assert extract_segments("보고.txt", "한글 문서".encode("cp949"))[0].text == "한글 문서"

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    docx = _zip(
        {
            "word/document.xml": f"<w:document {w}><w:body>"
            "<w:p><w:r><w:t>검증 </w:t></w:r><w:r><w:t>기록</w:t></w:r></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>작성자</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>김개발</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "<w:p/></w:body></w:document>"
        }
    )
    assert extract_segments("기록.docx", docx) == [
        Segment("문단 1", "검증 기록"),
        Segment("표 1 1행", "작성자 | 김개발"),
    ]

    m = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    xlsx = _zip(
        {
            "xl/workbook.xml": f"<workbook {m} {r}><sheets>"
            '<sheet name="점검" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": "<Relationships>"
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/sharedStrings.xml": f"<sst {m}><si><t>항목</t></si><si><t>결과</t></si></sst>",
            "xl/worksheets/sheet1.xml": f"<worksheet {m}><sheetData>"
            '<row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
            '<row r="3"><c><v>42</v></c><c t="inlineStr"><is><t>합격</t></is></c></row>'
            "</sheetData></worksheet>",
        }
    )
    assert extract_segments("점검.xlsx", xlsx) == [
        Segment("시트 '점검' 1행", "항목 | 결과"),
        Segment("시트 '점검' 3행", "42 | 합격"),
    ]

    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    slide = "<p:sld xmlns:p='p' {a}><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"
    pptx = _zip(
        {
            "ppt/slides/slide10.xml": slide.format(a=a, text="열 번째"),
            "ppt/slides/slide2.xml": slide.format(a=a, text="두 번째"),
        }
    )
    assert [s.text for s in extract_segments("발표.pptx", pptx)] == ["두 번째", "열 번째"]

    hp = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    hwpx = _zip(
        {
            "Contents/section0.xml": f"<hs:sec xmlns:hs='s' {hp}>"
            "<hp:p><hp:run><hp:t>회의록</hp:t></hp:run></hp:p>"
            "<hp:p><hp:run><hp:tbl><hp:tc><hp:p><hp:run><hp:t>참석자: 김개발</hp:t></hp:run>"
            "</hp:p></hp:tc></hp:tbl></hp:run></hp:p></hs:sec>"
        }
    )
    assert extract_segments("회의록.hwpx", hwpx) == [
        Segment("문단 1", "회의록"),
        Segment("문단 2", "참석자: 김개발"),
    ]


def test_unreadable_files_are_refused_with_a_reason():
    with pytest.raises(UnsupportedArtifact, match="DOCX 로 다시 저장"):
        extract_segments("옛문서.doc", b"...")
    with pytest.raises(UnsupportedArtifact, match="지원하지 않는 형식"):
        extract_segments("사진.png", b"...")
    with pytest.raises(UnsupportedArtifact, match="손상"):
        extract_segments("깨진.docx", b"not a zip")
    with pytest.raises(UnsupportedArtifact, match="글자를 읽을 수 없는"):
        extract_segments("빈.txt", b"  \n ")


# ── 양식 항목과 값의 대조(순수 함수) ─────────────────────────────────────────


def test_template_fields_come_from_the_fields_table():
    sections = [
        {"key": "guide", "body_md": "| 항목 | 설명 |\n|---|---|\n| 무시 | 다른 섹션 |"},
        {
            "key": "fields",
            "body_md": "| 항목 | 내용 |\n|---|---|\n| 제목 |  |\n| 작성자 |  |\n"
            "| 제목 |  |\n\n비고",
        },
    ]
    assert harmonize.template_fields(sections) == ["제목", "작성자"]


def test_values_must_be_found_in_the_original():
    segments = extract_segments("보고.txt", REPORT)
    output = NormalizeOutput(
        fields=[
            ExtractedField(
                name="제목", value="검증 결과", quote="위험통제 검증 결과 보고", location="1행"
            ),
            # 위치를 틀리게 적어도 원본 어딘가에 있으면 찾아서 바로잡는다.
            ExtractedField(name="작성자", value="김개발", quote="작성:  김개발", location="9쪽"),
            # 원본에 없는 구절은 근거가 아니다.
            ExtractedField(name="일자", value="2024-03-05", quote="2024년 3월 5일", location="1행"),
            ExtractedField(name="모르는 항목", value="x", quote="대상", location="4행"),
        ]
    )
    values = harmonize.check(["제목", "작성자", "일자", "승인"], output, segments)
    assert [(v.name, v.value, v.location, v.verified) for v in values] == [
        ("제목", "검증 결과", "1행", True),
        ("작성자", "김개발", "1행", True),
        ("일자", "2024-03-05", "1행", False),
        ("승인", "", "", False),  # 모델이 돌려주지 않은 항목은 빈 값
    ]


# ── API 흐름 ─────────────────────────────────────────────────────────────────


def _setup(consultant):
    """체계에 정책 → 절차 → 지침 → 양식(기록 항목: 제목·작성자·일자·내용·승인)을 만든다."""
    tenant = new_tenant(consultant)
    new_system(consultant, tenant)
    owner = add_member(consultant, tenant, "프로세스 오너", ["process_owner"])
    parent = None
    for doc_type, title in (("POL", "품질방침"), ("PRO", "검증 절차"), ("WI", "검증 지침")):
        scope = {"scope_code": "QMS"} if doc_type == "POL" else {"parent_id": parent}
        parent = _create(owner, tenant, doc_type, title, **scope).json()["document"]["id"]
    form = _create(owner, tenant, "TMP", "검증 기록", parent_id=parent).json()
    return tenant, owner, form["document"]


def _upload(client, tenant, name="보고.txt", data=REPORT):
    return client.post(
        f"/api/t/{tenant}/systems/ims/artifacts", files={"file": (name, data, "text/plain")}
    )


def _fake_llm(monkeypatch, *, code, confidence, calls=None):
    def structured(*, system, user, schema, **_):
        if calls is not None:
            calls.append(schema.__name__)
        if schema is MatchOutput:
            output = MatchOutput(
                title="위험통제 검증 결과 보고",
                performed_on="2024-03-05",
                candidates=[
                    MatchCandidate(
                        code=code, confidence=confidence, reason="검증 결과를 적은 기록"
                    ),
                    MatchCandidate(code="TMP-없는-번호", confidence=99, reason="지어낸 양식"),
                ],
            )
        else:
            output = NormalizeOutput(
                fields=[
                    ExtractedField(
                        name="제목",
                        value="위험통제 검증 결과 보고",
                        quote="위험통제 검증 결과 보고",
                        location="1행",
                    ),
                    ExtractedField(
                        name="작성자", value="김개발", quote="작성: 김개발", location="1행"
                    ),
                    ExtractedField(
                        name="일자", value="2024-03-05", quote="2024년 3월 5일", location="1행"
                    ),
                    ExtractedField(
                        name="내용",
                        value="합격",
                        quote="결과: 합격. 경보 지연 없음.",
                        location="4행",
                    ),
                    ExtractedField(name="승인", value="", quote="", location=""),
                ]
            )
        return llm.LLMResult(output, "fake-model", 100, 50)

    monkeypatch.setattr(llm, "structured", structured)


def test_without_consent_nothing_is_sent_and_records_are_filled_by_hand(consultant, monkeypatch):
    tenant, owner, form = _setup(consultant)
    calls: list[str] = []
    _fake_llm(monkeypatch, code=form["code"], confidence=90, calls=calls)

    templates = owner.get(f"/api/t/{tenant}/systems/ims/record-templates").json()
    assert [(t["document"]["code"], t["instruction"], t["approved"]) for t in templates] == [
        ("TMP-QMS-01-01-01-01", "검증 지침", False)
    ]
    assert templates[0]["fields"] == ["제목", "작성자", "일자", "내용", "승인"]

    viewer = add_member(consultant, tenant, "구성원", [])
    assert _upload(viewer, tenant).status_code == 403
    assert (
        _upload(owner, tenant, name="옛문서.doc").json()["detail"]["code"] == "unreadable_artifact"
    )

    uploaded = _upload(owner, tenant)
    assert uploaded.status_code == 201, uploaded.text
    artifact = uploaded.json()
    # 회사가 동의하지 않았으므로 모델로 보내지 않는다. 사람이 양식을 고른다.
    assert artifact["state"] == "needs_template" and artifact["run"] is None
    assert artifact["actions"] == ["set_template", "delete"]
    assert not worker.process_next_run() and calls == []
    path = f"/api/t/{tenant}/artifacts/{artifact['id']}"
    assert owner.post(f"{path}/match").json()["detail"]["code"] == "ai_not_enabled"
    assert _upload(owner, tenant).json()["detail"]["code"] == "duplicate_artifact"
    detail = owner.get(path).json()
    assert [s["loc"] for s in detail["segments"]] == ["1행", "4행"]

    chosen = owner.put(f"{path}/template", json={"document_id": form["id"]}).json()
    assert chosen["state"] == "review" and chosen["template"]["code"] == form["code"]
    record_path = f"/api/t/{tenant}/records/{chosen['record']['id']}"
    record = owner.get(record_path).json()
    assert {f["source"] for f in record["fields"]} == {"empty"} and record["actions"] == ["edit"]
    assert owner.post(f"{record_path}/publish").json()["detail"]["code"] == "empty_record"

    filled = owner.patch(
        record_path,
        json={
            "title": "위험통제 검증 결과",
            "performed_on": "2024-03-05",
            "fields": [{"name": "작성자", "value": " 김개발 "}, {"name": "내용", "value": "합격"}],
        },
    ).json()
    author = next(f for f in filled["fields"] if f["name"] == "작성자")
    assert (author["value"], author["source"], author["filled_by"]["name"]) == (
        "김개발",
        "human",
        "프로세스 오너",
    )
    assert filled["counts"] == {"total": 5, "empty": 3, "unverified": 0, "human": 2}
    unknown = owner.patch(record_path, json={"fields": [{"name": "없는 항목", "value": "x"}]})
    assert unknown.json()["detail"]["code"] == "unknown_field"

    published = owner.post(f"{record_path}/publish").json()
    # 번호는 발행할 때 양식 번호를 따라 발급되고, 어느 판의 양식으로 만들었는지 고정된다.
    assert published["code"] == "REC-QMS-01-01-01-01-001" and published["status"] == "published"
    assert published["legacy"] and published["template_version"] == "1.0"
    assert not published["template_approved"] and published["actions"] == []
    assert owner.patch(record_path, json={"title": "바꿈"}).json()["detail"]["code"] == (
        "record_published"
    )
    assert owner.delete(path).json()["detail"]["code"] == "already_published"
    assert [r["code"] for r in owner.get(f"/api/t/{tenant}/systems/ims/records").json()] == [
        "REC-QMS-01-01-01-01-001"
    ]
    log = consultant.get(f"/api/t/{tenant}/audit-log").json()["entries"]
    publish = next(e for e in log if e["action"] == "record.publish")
    assert (
        publish["data"]["source_file"] == "보고.txt" and len(publish["data"]["source_sha256"]) == 64
    )
    assert calls == []


def test_confident_match_is_normalized_and_unverified_values_need_a_person(consultant, monkeypatch):
    tenant, owner, form = _setup(consultant)
    _fake_llm(monkeypatch, code=form["code"], confidence=82)
    # 동의는 회사 관리자가 켠다.
    assert owner.patch(f"/api/t/{tenant}", json={"artifact_ai": True}).status_code == 403
    assert consultant.patch(f"/api/t/{tenant}", json={"artifact_ai": True}).json()["artifact_ai"]

    executor = add_member(consultant, tenant, "실행자", ["executor"])
    artifact = _upload(executor, tenant).json()
    assert artifact["state"] == "processing" and artifact["actions"] == []
    assert worker.process_next_run()

    path = f"/api/t/{tenant}/artifacts/{artifact['id']}"
    artifact = owner.get(path).json()
    # 일치도가 높으면 항목 값까지 이어서 뽑는다. 지어낸 양식 번호는 버려진다.
    assert artifact["state"] == "review" and artifact["match_state"] == "proposed"
    assert artifact["match_confidence"] == 82 and len(artifact["candidates"]) == 1
    assert (
        artifact["title"] == "위험통제 검증 결과 보고" and artifact["performed_on"] == "2024-03-05"
    )
    assert artifact["run"]["progress"]["input_tokens"] == 200

    record_path = f"/api/t/{tenant}/records/{artifact['record']['id']}"
    record = owner.get(record_path).json()
    by_name = {f["name"]: f for f in record["fields"]}
    assert by_name["작성자"] | {"filled_by": None} == by_name["작성자"]
    assert (
        by_name["내용"]["source"],
        by_name["내용"]["location"],
        by_name["내용"]["verified"],
    ) == (
        "artifact",
        "4행",
        True,
    )
    # 원본에 그 구절이 없는 값은 미검증 제안이고, 원본에 없는 항목은 비어 있다.
    assert by_name["일자"]["needs_check"] and not by_name["일자"]["verified"]
    assert by_name["승인"]["source"] == "empty"
    assert record["counts"] == {"total": 5, "empty": 1, "unverified": 1, "human": 0}
    assert record["generated_by"] == "fake-model" and record["performed_on"] == "2024-03-05"
    assert record["actions"] == ["edit"]
    blocked = owner.post(f"{record_path}/publish")
    assert blocked.json()["detail"]["code"] == "unverified_fields"

    # 사람이 원본을 보고 맞다고 확인하거나, 고친다. 고치면 원래 제안이 남는다.
    confirmed = owner.patch(record_path, json={"confirm": ["일자"]}).json()
    date_field = next(f for f in confirmed["fields"] if f["name"] == "일자")
    assert not date_field["needs_check"] and date_field["confirmed_by"]["name"] == "프로세스 오너"
    edited = owner.patch(
        record_path, json={"fields": [{"name": "내용", "value": "합격(경보 지연 없음)"}]}
    ).json()
    content = next(f for f in edited["fields"] if f["name"] == "내용")
    assert (content["source"], content["original_value"]) == ("human", "합격")
    assert edited["actions"] == ["edit", "publish"]
    published = owner.post(f"{record_path}/publish").json()
    assert published["code"] == "REC-QMS-01-01-01-01-001"
    assert published["artifact_filename"] == "보고.txt"


def test_uncertain_matches_wait_for_a_person(consultant, monkeypatch):
    tenant, owner, form = _setup(consultant)
    consultant.patch(f"/api/t/{tenant}", json={"artifact_ai": True})
    calls: list[str] = []

    # 일치도가 애매하면 양식만 제안하고 사람의 확인을 기다린다.
    _fake_llm(monkeypatch, code=form["code"], confidence=60, calls=calls)
    artifact = _upload(owner, tenant).json()
    worker.process_next_run()
    path = f"/api/t/{tenant}/artifacts/{artifact['id']}"
    artifact = owner.get(path).json()
    assert artifact["state"] == "needs_confirm" and artifact["record"] is None
    assert artifact["template"]["code"] == form["code"] and calls == ["MatchOutput"]
    assert artifact["actions"] == ["match", "set_template", "delete"]

    confirmed = owner.put(f"{path}/template", json={"document_id": form["id"]}).json()
    assert confirmed["state"] == "processing" and confirmed["match_state"] == "confirmed"
    worker.process_next_run()
    assert owner.get(path).json()["state"] == "review" and calls[-1] == "NormalizeOutput"

    # 일치도가 낮으면 제안하지 않는다. 사람이 직접 고르거나 지울 수 있다.
    _fake_llm(monkeypatch, code=form["code"], confidence=30)
    other = _upload(
        owner, tenant, name="회의록.txt", data="주간 회의록\n참석: 전원".encode()
    ).json()
    worker.process_next_run()
    other_path = f"/api/t/{tenant}/artifacts/{other['id']}"
    other = owner.get(other_path).json()
    assert other["state"] == "needs_template" and other["template"] is None
    assert other["candidates"][0]["confidence"] == 30
    assert owner.delete(other_path).status_code == 204
    listed = owner.get(f"/api/t/{tenant}/systems/ims/artifacts").json()
    assert [a["filename"] for a in listed] == ["보고.txt"]

    # 이 체계에 없는 문서는 양식으로 고를 수 없다.
    wrong = owner.put(f"{path}/template", json={"document_id": tenant_document(owner, tenant)})
    assert wrong.json()["detail"]["code"] == "template_not_found"


def tenant_document(client, tenant) -> str:
    """양식이 아닌 문서(정책) 하나의 id."""
    documents = client.get(f"/api/t/{tenant}/systems/ims/documents").json()
    return next(d["id"] for d in documents if d["doc_type"] == "POL")
