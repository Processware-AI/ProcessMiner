from .audit import AuditLog
from .base import Base
from .documents import (
    DocSequence,
    Document,
    DocumentExclusion,
    DocumentLink,
    DocumentRevision,
)
from .generation import (
    DocumentRequirement,
    GenerationPlan,
    PlanSource,
    RequirementExclusion,
    SystemBasis,
)
from .platform import (
    AppUser,
    AuthSession,
    DeletedTenant,
    DocTypeDef,
    LoginToken,
    Membership,
    StandardDef,
    Tenant,
)
from .sources import Requirement, Run, RunEvent, SourceClause, SourceDocument, SourcePage
from .tenancy import OrgUnit, ProcessSystem, RoleAssignment, ScopeCode

# 행 수준 보안으로 회사별 격리하는 테이블
TENANT_TABLES = [
    "org_unit",
    "process_system",
    "role_assignment",
    "document",
    "document_revision",
    "document_link",
    "document_exclusion",
    "doc_sequence",
    "audit_log",
    "source_document",
    "source_page",
    "source_clause",
    "requirement",
    "run",
    "run_event",
    "system_basis",
    "requirement_exclusion",
    "generation_plan",
    "plan_source",
    "document_requirement",
]

__all__ = [
    "AppUser",
    "AuditLog",
    "AuthSession",
    "Base",
    "DeletedTenant",
    "DocSequence",
    "DocTypeDef",
    "Document",
    "DocumentExclusion",
    "DocumentLink",
    "DocumentRequirement",
    "DocumentRevision",
    "GenerationPlan",
    "LoginToken",
    "Membership",
    "OrgUnit",
    "PlanSource",
    "ProcessSystem",
    "Requirement",
    "RequirementExclusion",
    "RoleAssignment",
    "Run",
    "RunEvent",
    "ScopeCode",
    "SourceClause",
    "SourceDocument",
    "SourcePage",
    "StandardDef",
    "SystemBasis",
    "TENANT_TABLES",
    "Tenant",
]
