import uuid

import pytest

from app.domain import revisions as rev
from app.domain.doc_ids import (
    cascade_ids,
    increment_version,
    new_child_id,
    new_root_id,
    parse_doc_id,
)
from app.domain.permissions import Actor, RoleGrant, can, violates_four_eyes

# ── 문서 번호 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "POL-QMS-01",
        "PRO-QMS-01-02",
        "WI-QMS-01-02-03",
        "TMP-QMS-01-02-03-01",
        "EX-ISMS-04-01-02-01",
        "REC-QMS-01-01-02-01-2026-001",
        "REF-012",
    ],
)
def test_doc_id_round_trip(raw):
    assert str(parse_doc_id(raw)) == raw


@pytest.mark.parametrize("raw", ["POL-QMS-1", "PRO-QMS-101", "WI-102-01", "MAT-001", "pol-qms-01"])
def test_doc_id_rejects_non_canonical_forms(raw):
    with pytest.raises(ValueError):
        parse_doc_id(raw)


def test_child_ids_inherit_parent_numbers():
    assert new_root_id("POL", "QMS", 1) == "POL-QMS-01"
    assert new_child_id("POL-QMS-01", "PRO", 2) == "PRO-QMS-01-02"
    assert new_child_id("PRO-QMS-01-02", "WI", 3) == "WI-QMS-01-02-03"
    assert new_child_id("WI-QMS-01-02-03", "TMP", 1) == "TMP-QMS-01-02-03-01"
    assert new_child_id("WI-QMS-01-02-03", "EX", 1) == "EX-QMS-01-02-03-01"
    assert (
        new_child_id("TMP-QMS-01-02-03-01", "REC", 7, year=2026) == "REC-QMS-01-02-03-01-2026-007"
    )
    assert new_root_id("REF", "", 12) == "REF-012"


def test_child_id_rejects_wrong_parent_type_and_overflow():
    with pytest.raises(ValueError):
        new_child_id("POL-QMS-01", "WI", 1)
    with pytest.raises(ValueError):
        new_child_id("POL-QMS-01", "PRO", 100)
    with pytest.raises(ValueError):
        new_root_id("POL", "qms", 1)


def test_cascade_renames_only_descendants_of_the_policy():
    mapping = cascade_ids(
        "POL-QMS-01", "POL-QMS-05", ["PRO-QMS-01-02", "WI-QMS-01-02-03", "PRO-QMS-02-01"]
    )
    assert mapping == {"PRO-QMS-01-02": "PRO-QMS-05-02", "WI-QMS-01-02-03": "WI-QMS-05-02-03"}


# ── 버전과 상태 전이 ─────────────────────────────────────────────────────────


def test_versions():
    assert rev.target_version(None, "major") == "1.0"
    assert rev.target_version("1.0", "minor") == "1.1"
    assert rev.target_version("1.9", "minor") == "1.10"
    assert rev.target_version("1.3", "major") == "2.0"
    assert increment_version("v2.4") == "2.5"


def test_revision_transitions():
    assert rev.next_status("draft", "submit") == "in_review"
    assert rev.next_status("in_review", "approve") == "approved"
    assert rev.next_status("in_review", "reject") == "draft"
    assert rev.next_status("approved", "supersede") == "superseded"
    for status, action in [("draft", "approve"), ("approved", "submit"), ("superseded", "approve")]:
        with pytest.raises(rev.InvalidTransition):
            rev.next_status(status, action)


def test_content_hash_changes_with_content_only():
    sections = [{"key": "purpose", "title": "목적", "body_md": "가"}]
    base = rev.content_hash("제목", sections, {})
    assert base == rev.content_hash("제목", [dict(sections[0])], {})
    assert base != rev.content_hash("제목", [{**sections[0], "body_md": "나"}], {})
    assert base != rev.content_hash("다른 제목", sections, {})


def test_missing_required_sections():
    schema = [
        {"key": "purpose", "title": "목적", "required": True},
        {"key": "scope", "title": "적용 범위", "required": True},
        {"key": "note", "title": "비고", "required": False},
    ]
    sections = [{"key": "purpose", "body_md": "내용"}, {"key": "scope", "body_md": "  \n"}]
    assert rev.missing_required_sections(sections, schema) == ["적용 범위"]


# ── 권한 ─────────────────────────────────────────────────────────────────────

SYSTEM_A, SYSTEM_B = uuid.uuid4(), uuid.uuid4()


def _actor(tenant_role="member", platform_role=None, grants=()):
    return Actor(
        user_id=uuid.uuid4(), platform_role=platform_role, tenant_role=tenant_role, grants=grants
    )


def test_non_member_can_do_nothing():
    assert not can(_actor(tenant_role=None), "doc.read", SYSTEM_A)


def test_platform_admin_can_do_everything_without_membership():
    assert can(_actor(tenant_role=None, platform_role="platform_admin"), "member.manage")


def test_consultant_needs_membership():
    assert not can(_actor(tenant_role=None, platform_role="consultant"), "doc.read", SYSTEM_A)


def test_member_reads_but_does_not_write():
    actor = _actor()
    assert can(actor, "doc.read", SYSTEM_A)
    assert not can(actor, "doc.edit", SYSTEM_A)
    assert not can(actor, "member.manage")


def test_system_scoped_role_applies_only_to_that_system():
    actor = _actor(grants=(RoleGrant("process_owner", SYSTEM_A),))
    assert can(actor, "doc.edit", SYSTEM_A)
    assert not can(actor, "doc.edit", SYSTEM_B)


def test_tenant_wide_role_applies_to_every_system():
    actor = _actor(grants=(RoleGrant("qmr", None),))
    assert can(actor, "doc.review", SYSTEM_A) and can(actor, "doc.review", SYSTEM_B)
    assert not can(actor, "doc.edit", SYSTEM_A)


def test_read_only_roles_cannot_review():
    for role in ("executor", "auditor", "viewer"):
        assert not can(_actor(grants=(RoleGrant(role, None),)), "doc.review", SYSTEM_A)


def test_unknown_action_is_a_programming_error():
    with pytest.raises(ValueError):
        can(_actor(), "doc.destroy")


def test_four_eyes():
    author = uuid.uuid4()
    assert violates_four_eyes(author, author)
    assert not violates_four_eyes(author, uuid.uuid4())
