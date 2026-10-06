"""문서 유형과 계층 규칙 — tools/vault_rules/rules.py 에서 이식.

MAT(매핑·관리대장)은 작성 문서가 아니라 조회 화면으로 제공하므로 여기 없다.
REC(기록)는 문서가 아닌 별도 엔터티로 다룬다.
"""

# 작성 가능한 문서 유형
DOC_TYPES = ["POL", "PRO", "WI", "TMP", "EX", "REF"]

# 유형 → 상위 문서 유형. 없으면 최상위.
# EX 는 번호체계상 TMP 와 같은 WI 아래 일련번호를 쓴다(generator.py 기준).
PARENT_TYPE: dict[str, str] = {
    "PRO": "POL",
    "WI": "PRO",
    "TMP": "WI",
    "EX": "WI",
}

# 영역코드가 필요한 최상위 유형
SCOPED_ROOT_TYPES = {"POL"}


def is_root_type(doc_type: str) -> bool:
    return doc_type not in PARENT_TYPE


def allowed_child_types(doc_type: str) -> list[str]:
    return [child for child, parent in PARENT_TYPE.items() if parent == doc_type]
