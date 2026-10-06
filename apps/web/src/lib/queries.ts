"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

// 쿼리 키는 한곳에서 만든다. 변경 후 무효화할 때 같은 키를 쓴다.
export const keys = {
  me: ["me"] as const,
  docTypes: ["doc-types"] as const,
  tenant: (tenant: string) => ["t", tenant] as const,
  orgUnits: (tenant: string) => ["t", tenant, "org-units"] as const,
  systems: (tenant: string) => ["t", tenant, "systems"] as const,
  system: (tenant: string, system: string) => ["t", tenant, "systems", system] as const,
  members: (tenant: string) => ["t", tenant, "members"] as const,
  scopeCodes: (tenant: string) => ["t", tenant, "scope-codes"] as const,
  inbox: (tenant: string) => ["t", tenant, "inbox"] as const,
  auditLog: (tenant: string) => ["t", tenant, "audit-log"] as const,
  sources: (tenant: string) => ["t", tenant, "sources"] as const,
  source: (tenant: string, id: string) => ["t", tenant, "sources", id] as const,
  clauses: (tenant: string, sourceId: string) => ["t", tenant, "sources", sourceId, "clauses"] as const,
  clause: (tenant: string, clauseId: string) => ["t", tenant, "clause", clauseId] as const,
  basis: (tenant: string, system: string) => ["t", tenant, "build", system, "basis"] as const,
  basisRequirements: (tenant: string, system: string, sourceId: string) =>
    ["t", tenant, "build", system, "basis", sourceId] as const,
  plans: (tenant: string, system: string) => ["t", tenant, "build", system, "plans"] as const,
  revisionRequirements: (tenant: string, revisionId: string) =>
    ["t", tenant, "docs", "revision-requirements", revisionId] as const,
  documents: (tenant: string, system: string) => ["t", tenant, "docs", "list", system] as const,
  docsAll: (tenant: string) => ["t", tenant, "docs"] as const,
  document: (tenant: string, id: string) => ["t", tenant, "docs", "detail", id] as const,
  revisions: (tenant: string, id: string) => ["t", tenant, "docs", "revisions", id] as const,
  revision: (tenant: string, id: string) => ["t", tenant, "docs", "revision", id] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => unwrap(api.GET("/api/me")) });
}

export function useDocTypes() {
  return useQuery({
    queryKey: keys.docTypes,
    queryFn: () => unwrap(api.GET("/api/ref/doc-types")),
    staleTime: Infinity,
  });
}

export function useTenant(tenant: string) {
  return useQuery({
    queryKey: keys.tenant(tenant),
    queryFn: () =>
      unwrap(api.GET("/api/t/{tenant_slug}", { params: { path: { tenant_slug: tenant } } })),
  });
}

export function useOrgUnits(tenant: string) {
  return useQuery({
    queryKey: keys.orgUnits(tenant),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/org-units", { params: { path: { tenant_slug: tenant } } }),
      ),
  });
}

export function useSystems(tenant: string) {
  return useQuery({
    queryKey: keys.systems(tenant),
    queryFn: () =>
      unwrap(api.GET("/api/t/{tenant_slug}/systems", { params: { path: { tenant_slug: tenant } } })),
  });
}

export function useSystem(tenant: string, system: string | undefined) {
  return useQuery({
    queryKey: keys.system(tenant, system ?? ""),
    enabled: Boolean(system),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/systems/{system_slug}", {
          params: { path: { tenant_slug: tenant, system_slug: system! } },
        }),
      ),
  });
}

export function useMembers(tenant: string) {
  return useQuery({
    queryKey: keys.members(tenant),
    queryFn: () =>
      unwrap(api.GET("/api/t/{tenant_slug}/members", { params: { path: { tenant_slug: tenant } } })),
  });
}

export function useScopeCodes(tenant: string) {
  return useQuery({
    queryKey: keys.scopeCodes(tenant),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/scope-codes", { params: { path: { tenant_slug: tenant } } }),
      ),
  });
}

export function useInbox(tenant: string) {
  return useQuery({
    queryKey: keys.inbox(tenant),
    queryFn: () =>
      unwrap(api.GET("/api/t/{tenant_slug}/inbox", { params: { path: { tenant_slug: tenant } } })),
    refetchInterval: 60_000,
  });
}

export function useAuditLog(tenant: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.auditLog(tenant),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/audit-log", {
          params: { path: { tenant_slug: tenant }, query: { limit: 200 } },
        }),
      ),
  });
}

export function useDocuments(tenant: string, system: string | undefined) {
  return useQuery({
    queryKey: keys.documents(tenant, system ?? ""),
    enabled: Boolean(system),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/systems/{system_slug}/documents", {
          params: { path: { tenant_slug: tenant, system_slug: system! } },
        }),
      ),
  });
}

export function useDocument(tenant: string, documentId: string) {
  return useQuery({
    queryKey: keys.document(tenant, documentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/documents/{document_id}", {
          params: { path: { tenant_slug: tenant, document_id: documentId } },
        }),
      ),
  });
}

export function useRevisions(tenant: string, documentId: string) {
  return useQuery({
    queryKey: keys.revisions(tenant, documentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/documents/{document_id}/revisions", {
          params: { path: { tenant_slug: tenant, document_id: documentId } },
        }),
      ),
  });
}

export function useRevision(tenant: string, revisionId: string | null) {
  return useQuery({
    queryKey: keys.revision(tenant, revisionId ?? ""),
    enabled: Boolean(revisionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/revisions/{revision_id}", {
          params: { path: { tenant_slug: tenant, revision_id: revisionId! } },
        }),
      ),
  });
}

const isBusy = (status: string | undefined) => status === "queued" || status === "running";

export function useSources(tenant: string) {
  return useQuery({
    queryKey: keys.sources(tenant),
    queryFn: () =>
      unwrap(api.GET("/api/t/{tenant_slug}/sources", { params: { path: { tenant_slug: tenant } } })),
    // 요건을 도출하는 동안에는 진행 상황을 계속 받아온다.
    refetchInterval: (query) =>
      query.state.data?.some((source) => isBusy(source.run?.status)) ? 2500 : false,
  });
}

export function useSource(tenant: string, sourceId: string) {
  return useQuery({
    queryKey: keys.source(tenant, sourceId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/sources/{source_id}", {
          params: { path: { tenant_slug: tenant, source_id: sourceId } },
        }),
      ),
    refetchInterval: (query) => (isBusy(query.state.data?.run?.status) ? 2000 : false),
  });
}

export function useClauses(tenant: string, sourceId: string) {
  return useQuery({
    queryKey: keys.clauses(tenant, sourceId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/sources/{source_id}/clauses", {
          params: { path: { tenant_slug: tenant, source_id: sourceId } },
        }),
      ),
  });
}

export function useClause(tenant: string, clauseId: string | null) {
  return useQuery({
    queryKey: keys.clause(tenant, clauseId ?? ""),
    enabled: Boolean(clauseId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/clauses/{clause_id}", {
          params: { path: { tenant_slug: tenant, clause_id: clauseId! } },
        }),
      ),
  });
}

export function useBasis(tenant: string, system: string) {
  return useQuery({
    queryKey: keys.basis(tenant, system),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/systems/{system_slug}/basis", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
        }),
      ),
  });
}

export function basisRequirementsQuery(tenant: string, system: string, sourceId: string) {
  return {
    queryKey: keys.basisRequirements(tenant, system, sourceId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/systems/{system_slug}/basis/{source_id}/requirements", {
          params: { path: { tenant_slug: tenant, system_slug: system, source_id: sourceId } },
        }),
      ),
  };
}

export function useBasisRequirements(tenant: string, system: string, sourceId: string | null) {
  return useQuery({
    ...basisRequirementsQuery(tenant, system, sourceId ?? ""),
    enabled: Boolean(sourceId),
  });
}

export function usePlans(tenant: string, system: string) {
  return useQuery({
    queryKey: keys.plans(tenant, system),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/systems/{system_slug}/plans", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
        }),
      ),
    // 설계나 문서 작성이 도는 동안에는 진행 상황을 계속 받아온다.
    refetchInterval: (query) =>
      query.state.data?.some((plan) => isBusy(plan.run?.status)) ? 2000 : false,
  });
}

export function useRevisionRequirements(tenant: string, revisionId: string | null) {
  return useQuery({
    queryKey: keys.revisionRequirements(tenant, revisionId ?? ""),
    enabled: Boolean(revisionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/t/{tenant_slug}/revisions/{revision_id}/requirements", {
          params: { path: { tenant_slug: tenant, revision_id: revisionId! } },
        }),
      ),
  });
}
