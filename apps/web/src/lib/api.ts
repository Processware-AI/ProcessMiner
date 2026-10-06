import createClient from "openapi-fetch";

import type { components, paths } from "./api-types";

// 타입은 API 의 OpenAPI 스키마에서 생성한다: pnpm gen:api
type Schemas = components["schemas"];

export type Me = Schemas["MeOut"];
export type User = Schemas["UserOut"];
export type UserRef = Schemas["UserRef"];
export type TenantSummary = Schemas["TenantSummary"];
export type Tenant = Schemas["TenantOut"];
export type OrgUnit = Schemas["OrgUnitOut"];
export type System = Schemas["SystemOut"];
export type SystemDetail = Schemas["SystemDetail"];
export type Member = Schemas["MemberOut"];
export type RoleGrant = Schemas["RoleGrantIO"];
export type DocType = Schemas["DocTypeOut"];
export type SectionSpec = Schemas["SectionSpec"];
export type ScopeCode = Schemas["ScopeCodeOut"];
export type DocumentSummary = Schemas["DocumentSummary"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type DocumentRef = Schemas["DocumentRef"];
export type Revision = Schemas["RevisionOut"];
export type RevisionMeta = Schemas["RevisionMeta"];
export type Section = Schemas["Section"];
export type InboxItem = Schemas["InboxItem"];
export type AuditLog = Schemas["AuditLogOut"];
export type AuditEntry = Schemas["AuditEntryOut"];
export type Source = Schemas["SourceOut"];
export type Run = Schemas["RunOut"];
export type ClauseSummary = Schemas["ClauseSummary"];
export type ClauseDetail = Schemas["ClauseDetail"];
export type Requirement = Schemas["RequirementOut"];
export type Basis = Schemas["BasisOut"];
export type BasisItem = Schemas["BasisItem"];
export type BasisRequirement = Schemas["BasisRequirementOut"];
export type Plan = Schemas["PlanOut"];
export type PlanNode = Schemas["PlanNodeOut"];
export type RevisionRequirement = Schemas["RevisionRequirementOut"];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = createClient<paths>({ baseUrl: "/", credentials: "same-origin" });

type ValidationIssue = { msg?: string };

function toApiError(error: unknown, status: number): ApiError {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  // 업무 규칙 오류: {code, message}
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { code, message } = detail as { code?: string; message?: string };
    return new ApiError(message ?? "요청을 처리하지 못했습니다.", status, code ?? "error");
  }
  // 입력 검증 오류: [{msg}]
  if (Array.isArray(detail)) {
    const message = (detail as ValidationIssue[])
      .map((issue) => (issue.msg ?? "").replace(/^Value error, /, ""))
      .filter(Boolean)
      .join(" ");
    return new ApiError(message || "입력값을 확인하세요.", status, "validation");
  }
  if (status === 401) return new ApiError("로그인이 필요합니다.", status, "unauthenticated");
  if (status >= 500) {
    return new ApiError("서버에 문제가 생겼습니다. 잠시 후 다시 시도하세요.", status, "server");
  }
  return new ApiError("요청을 처리하지 못했습니다.", status, "error");
}

/** openapi-fetch 결과에서 데이터를 꺼내고, 실패면 ApiError 를 던진다. */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request;
  } catch {
    throw new ApiError("서버에 연결할 수 없습니다.", 0, "network");
  }
  if (!result.response.ok) throw toApiError(result.error, result.response.status);
  return result.data as T;
}

/** 원문 파일을 올린다. 파일 전송이라 생성된 클라이언트 대신 fetch 를 직접 쓴다. */
export async function uploadSource(
  tenant: string,
  fields: { file: File; title: string; code: string; edition: string },
): Promise<Source> {
  const body = new FormData();
  body.set("file", fields.file);
  body.set("title", fields.title);
  body.set("code", fields.code);
  body.set("edition", fields.edition);
  let response: Response;
  try {
    response = await fetch(`/api/t/${encodeURIComponent(tenant)}/sources`, {
      method: "POST",
      body,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("서버에 연결할 수 없습니다.", 0, "network");
  }
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw toApiError(payload, response.status);
  return payload as Source;
}
