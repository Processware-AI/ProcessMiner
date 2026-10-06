"use client";

import { ChevronRightIcon, FileTextIcon, PlusIcon, SearchIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import {
  DocCode,
  EmptyState,
  ErrorState,
  LinkButton,
  PageHeader,
  StatusBadge,
  TypeBadge,
} from "@/components/bits";
import { NewDocumentDialog, type NewDocumentParent } from "@/components/docs/new-document-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { DocumentSummary } from "@/lib/api";
import { formatRelative } from "@/lib/labels";
import { useDocTypes, useDocuments, useSystem } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

type Row = { doc: DocumentSummary; depth: number; hasChildren: boolean };

/** 상하위 순서로 펼친 행 목록. 접힌 문서의 하위는 건너뛴다. */
function toRows(documents: DocumentSummary[], collapsed: Set<string>): Row[] {
  const byParent = new Map<string | null, DocumentSummary[]>();
  for (const doc of documents) {
    const key = doc.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), doc]);
  }
  const rows: Row[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const doc of byParent.get(parent) ?? []) {
      const hasChildren = byParent.has(doc.id);
      rows.push({ doc, depth, hasChildren });
      if (hasChildren && !collapsed.has(doc.id)) walk(doc.id, depth + 1);
    }
  };
  walk(null, 0);
  return rows;
}

const FILTERS = [
  { value: "all", label: "전체" },
  { value: "open", label: "진행 중" },
  { value: "approved", label: "승인됨" },
] as const;

/** 자산 라이브러리: 한 체계의 문서를 계층으로 본다. */
export default function LibraryPage() {
  const { tenant, system } = useParams<{ tenant: string; system: string }>();
  const systemQuery = useSystem(tenant, system);
  const documents = useDocuments(tenant, system);
  const docTypes = useDocTypes();

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["value"]>("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<{ parent?: NewDocumentParent } | null>(null);

  const canCreate = systemQuery.data?.actions.includes("doc.create") ?? false;
  const parentTypes = useMemo(
    () => new Set((docTypes.data ?? []).map((t) => t.parent_type).filter(Boolean)),
    [docTypes.data],
  );

  const all = useMemo(() => documents.data ?? [], [documents.data]);
  const needle = query.trim().toLowerCase();
  const filtering = needle !== "" || filter !== "all";
  const rows = useMemo<Row[]>(() => {
    if (!filtering) return toRows(all, collapsed);
    // 걸러 볼 때는 계층 없이 일치하는 문서만 나열한다.
    return all
      .filter((doc) => {
        const matchesText =
          !needle ||
          doc.code.toLowerCase().includes(needle) ||
          doc.title.toLowerCase().includes(needle);
        const matchesFilter =
          filter === "all" ||
          (filter === "open" ? doc.open_status !== null : doc.approved_version !== null);
        return matchesText && matchesFilter;
      })
      .map((doc) => ({ doc, depth: 0, hasChildren: false }));
  }, [all, collapsed, filtering, needle, filter]);

  function toggle(id: string) {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  if (systemQuery.error) return <ErrorState error={systemQuery.error} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={
          systemQuery.data && (
            <span className="text-xs font-medium text-muted-foreground">
              {systemQuery.data.parent_system_id ? "조직 변형 체계" : "기준선 체계"}
            </span>
          )
        }
        title={systemQuery.data?.name ?? <Skeleton className="h-8 w-48" />}
        description={systemQuery.data?.description || undefined}
        actions={
          <>
            <LinkButton variant="outline" href={routes.build(tenant, system)}>
              <SparklesIcon />
              표준에서 만들기
            </LinkButton>
            {canCreate && (
              <Button onClick={() => setDialog({})}>
                <PlusIcon />새 문서
              </Button>
            )}
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 sm:max-w-xs">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="번호 또는 제목"
            className="pl-8"
            aria-label="문서 검색"
          />
        </div>
        <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="상태로 걸러 보기">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
              className={cn(
                "h-7 rounded-md px-2.5 text-sm transition-colors",
                filter === option.value
                  ? "bg-background font-medium shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-sm text-muted-foreground">
          {documents.data && `${rows.length}건${filtering ? ` / 전체 ${all.length}건` : ""}`}
        </span>
      </div>

      {documents.isPending && (
        <div className="space-y-2">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      )}
      {documents.error && <ErrorState error={documents.error} />}

      {documents.data && all.length === 0 && (
        <EmptyState
          icon={<FileTextIcon />}
          title="아직 문서가 없습니다"
          description="정책서부터 만들고, 그 아래에 절차서 → 업무지침서 → 템플릿 순으로 내려갑니다."
          action={
            canCreate && (
              <Button onClick={() => setDialog({})}>
                <PlusIcon />첫 문서 만들기
              </Button>
            )
          }
        />
      )}
      {documents.data && all.length > 0 && rows.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">조건에 맞는 문서가 없습니다.</p>
      )}

      {rows.length > 0 && (
        <ul className="overflow-hidden rounded-xl border border-border bg-card">
          {rows.map(({ doc, depth, hasChildren }) => (
            <li
              key={doc.id}
              className="group relative flex items-center border-b border-border last:border-b-0 hover:bg-muted/40"
            >
              <div
                className="flex shrink-0 items-center"
                style={{ paddingLeft: `${0.375 + depth * 1.125}rem` }}
              >
                {hasChildren ? (
                  <button
                    type="button"
                    onClick={() => toggle(doc.id)}
                    aria-label={collapsed.has(doc.id) ? "하위 문서 펼치기" : "하위 문서 접기"}
                    aria-expanded={!collapsed.has(doc.id)}
                    className="grid size-7 place-content-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <ChevronRightIcon
                      className={cn(
                        "size-4 transition-transform",
                        !collapsed.has(doc.id) && "rotate-90",
                      )}
                    />
                  </button>
                ) : (
                  <span className="size-7" />
                )}
              </div>

              <Link
                href={routes.document(tenant, system, doc.id)}
                className="flex min-w-0 flex-1 items-center gap-2.5 py-2.5 pr-3 pl-1"
              >
                <TypeBadge type={doc.doc_type} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{doc.title}</span>
                  <DocCode className="block truncate">{doc.code}</DocCode>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center">
                  {doc.approved_version && (
                    <StatusBadge status="approved" version={doc.approved_version} />
                  )}
                  {doc.open_status && (
                    <StatusBadge status={doc.open_status} version={doc.open_version} />
                  )}
                </span>
                <span className="hidden w-20 shrink-0 text-right text-xs text-muted-foreground md:block">
                  {formatRelative(doc.updated_at)}
                </span>
              </Link>

              {canCreate && parentTypes.has(doc.doc_type) && (
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="하위 문서 추가"
                        className="mr-2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 max-md:hidden"
                        onClick={() => setDialog({ parent: doc })}
                      />
                    }
                  >
                    <PlusIcon />
                  </TooltipTrigger>
                  <TooltipContent>하위 문서 추가</TooltipContent>
                </Tooltip>
              )}
            </li>
          ))}
        </ul>
      )}

      <NewDocumentDialog
        tenant={tenant}
        system={system}
        parent={dialog?.parent}
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
      />
    </div>
  );
}
