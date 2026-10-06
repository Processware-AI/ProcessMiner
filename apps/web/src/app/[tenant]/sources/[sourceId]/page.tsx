"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  ChevronLeftIcon,
  CircleAlertIcon,
  PencilIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
  Undo2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/bits";
import { RunProgress, SourceStatusBadge } from "@/components/sources/source-bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type ClauseSummary, type Requirement, type Source, unwrap } from "@/lib/api";
import {
  formatDate,
  OBLIGATION_LABEL,
  OBLIGATION_STYLE,
  REQUIREMENT_CATEGORY_LABEL,
} from "@/lib/labels";
import { keys, useClause, useClauses, useSource } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * 인용문을 읽기 좋게 보여준다. PDF 의 줄바꿈은 문장 중간에 들어가 있으므로 이어 붙이고,
 * 나열 항목(a) b) … 또는 – •)이 시작하는 곳의 줄바꿈만 남긴다. 저장된 원문은 바꾸지 않는다.
 */
function displayQuote(quote: string): string {
  const startsListItem = /^([a-z0-9]{1,2}\)|[–•-]\s)/i;
  return quote
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce((text, line) => {
      if (!text) return line;
      return startsListItem.test(line) ? `${text}\n${line}` : `${text} ${line}`;
    }, "")
    .replace(/ {2,}/g, " ");
}

const isBusy = (source: Source) =>
  source.run?.status === "queued" || source.run?.status === "running";

/** 원문 한 건: 조항을 훑어보고, 요건을 도출·검토·확정한다. */
export default function SourcePage() {
  const { tenant, sourceId } = useParams<{ tenant: string; sourceId: string }>();
  const source = useSource(tenant, sourceId);

  if (source.error) return <ErrorState error={source.error} />;
  if (!source.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-96 max-w-full" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  return <SourceScreen tenant={tenant} source={source.data} />;
}

function SourceScreen({ tenant, source }: { tenant: string; source: Source }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const clauses = useClauses(tenant, source.id);
  const [chosen, setChosen] = useState<string | null>(null);
  const [onlyWithRequirements, setOnlyWithRequirements] = useState(true);
  const [dialog, setDialog] = useState<"confirm" | "delete" | null>(null);

  const can = (action: string) => source.actions.includes(action);
  const busy = isBusy(source);
  const { requirements } = source;
  const hasRequirements = requirements.proposed + requirements.confirmed + requirements.rejected > 0;

  // 절 하나가 끝날 때마다, 그리고 작업이 끝났을 때 조항 목록을 다시 받는다.
  const finishedUnits = Number((source.run?.progress as { done?: number } | undefined)?.done ?? 0);
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: keys.clauses(tenant, source.id) });
    void queryClient.invalidateQueries({ queryKey: ["t", tenant, "clause"] });
  }, [queryClient, tenant, source.id, finishedUnits, source.run?.status]);

  const all = useMemo(() => clauses.data ?? [], [clauses.data]);
  const visible = useMemo(() => {
    if (!hasRequirements || !onlyWithRequirements) return all;
    // 요건이 있는 조항과, 그 위치를 알 수 있도록 상위 조항만 남긴다.
    const keep = new Set<string>();
    for (const clause of all) {
      if (clause.requirement_count === 0) continue;
      keep.add(clause.number);
      let parent = clause.parent_number;
      while (parent) {
        keep.add(parent);
        parent = all.find((c) => c.number === parent)?.parent_number ?? null;
      }
    }
    return all.filter((clause) => keep.has(clause.number));
  }, [all, hasRequirements, onlyWithRequirements]);

  const fallback =
    visible.find((c) => c.requirement_count > 0) ?? visible.find((c) => c.has_obligation) ?? visible[0];
  const selectedId = visible.some((c) => c.id === chosen) ? chosen : (fallback?.id ?? null);

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.sources(tenant) }),
      queryClient.invalidateQueries({ queryKey: ["t", tenant, "clause"] }),
    ]);
  }

  const mine = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/sources/{source_id}/mine", {
          params: { path: { tenant_slug: tenant, source_id: source.id } },
        }),
      ),
    onSuccess: refresh,
  });
  const confirm = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/sources/{source_id}/confirm", {
          params: { path: { tenant_slug: tenant, source_id: source.id } },
        }),
      ),
    onSuccess: async () => {
      setDialog(null);
      await refresh();
      toast.success("요건을 확정했습니다.");
    },
    onError: () => setDialog(null),
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/sources/{source_id}", {
          params: { path: { tenant_slug: tenant, source_id: source.id } },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.sources(tenant) });
      router.replace(routes.sources(tenant));
    },
  });

  return (
    <div className="space-y-5">
      <Link
        href={routes.sources(tenant)}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeftIcon className="size-4" />
        원문과 요건
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-muted-foreground">{source.code}</span>
            <SourceStatusBadge status={source.status} />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">
            {source.title}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {source.edition && `${source.edition} · `}
            {source.page_count}쪽 · 조항 {source.clause_count}개 · 요건 도출 대상{" "}
            {source.obligation_clause_count}개
            {source.uploaded_by && ` · ${source.uploaded_by.name} 등록`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {can("delete") && (
            <Button variant="outline" size="icon" aria-label="원문 삭제" onClick={() => setDialog("delete")}>
              <Trash2Icon />
            </Button>
          )}
          {can("mine") && (
            <Button
              variant={hasRequirements ? "outline" : "default"}
              onClick={() => mine.mutate()}
              disabled={mine.isPending}
            >
              <SparklesIcon />
              {source.failed_units.length > 0 ? "실패한 절 다시 도출" : "요건 도출 시작"}
            </Button>
          )}
          {can("confirm") && (
            <Button onClick={() => setDialog("confirm")}>
              <ShieldCheckIcon />
              요건 확정
            </Button>
          )}
        </div>
      </header>

      {source.sparse_pages.length > 0 && (
        <Notice tone="warn">
          글자를 읽지 못한 쪽이 있습니다({source.sparse_pages.join(", ")}쪽). 그림이나 스캔 이미지로
          보이며, 이 쪽의 내용은 요건 도출에서 빠집니다.
        </Notice>
      )}
      {busy && source.run && (
        <div className="rounded-xl border border-border bg-card px-4 py-3">
          <RunProgress run={source.run} />
        </div>
      )}
      {!busy && source.run?.status === "failed" && (
        <Notice tone="error">요건 도출에 실패했습니다: {source.run.error}</Notice>
      )}
      {!busy && source.failed_units.length > 0 && (
        <Notice tone="warn">
          도출하지 못한 절이 있습니다({source.failed_units.join(", ")}). 다시 도출하면 이 절들만
          처리합니다.
        </Notice>
      )}
      {source.status === "extracted" && !busy && !hasRequirements && can("mine") && (
        <Notice tone="info">
          조항 분석이 끝났습니다. 요건 도출을 시작하면 의무 표현이 있는 조항{" "}
          {source.obligation_clause_count}개에서 요건을 뽑습니다. 몇 분 걸리고, 원문 내용이 AI
          모델로 전송됩니다.
        </Notice>
      )}
      {source.status === "confirmed" && (
        <Notice tone="ok">
          {formatDate(source.confirmed_at)} {source.confirmed_by?.name} 님이 요건{" "}
          {requirements.confirmed}건을 확정했습니다. 확정한 요건은 고칠 수 없습니다.
        </Notice>
      )}

      {hasRequirements && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <Stat label={source.status === "confirmed" ? "확정" : "검토 대상"}>
            {requirements.proposed + requirements.confirmed}건
          </Stat>
          <Stat label="제외">{requirements.rejected}건</Stat>
          <Stat label="인용 미확인" alert={requirements.unverified > 0}>
            {requirements.unverified}건
          </Stat>
          <label className="ml-auto flex items-center gap-2 text-muted-foreground">
            <input
              type="checkbox"
              checked={onlyWithRequirements}
              onChange={(e) => setOnlyWithRequirements(e.target.checked)}
              className="size-4 accent-primary"
            />
            요건이 있는 조항만
          </label>
        </div>
      )}

      {clauses.isPending && <Skeleton className="h-72" />}
      {clauses.error && <ErrorState error={clauses.error} />}
      {clauses.data && (
        <div className="grid gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <ClauseList clauses={visible} selectedId={selectedId} onSelect={setChosen} />
          <ClausePanel
            tenant={tenant}
            clauseId={selectedId}
            editable={can("review")}
            onChanged={refresh}
          />
        </div>
      )}

      <Dialog open={dialog === "confirm"} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>요건을 확정할까요?</DialogTitle>
            <DialogDescription>
              검토 대상 {requirements.proposed}건을 확정하고, 제외한 {requirements.rejected}건은
              쓰지 않습니다. 확정한 뒤에는 요건을 고칠 수 없고, 이 요건이 프로세스 문서의 근거가
              됩니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              취소
            </Button>
            <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
              확정
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dialog === "delete"} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>원문을 삭제할까요?</DialogTitle>
            <DialogDescription>
              올린 파일과 조항, 도출한 요건이 모두 지워집니다. 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              취소
            </Button>
            <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Notice({
  tone,
  children,
}: {
  tone: "info" | "warn" | "error" | "ok";
  children: React.ReactNode;
}) {
  const styles = {
    info: "border-sky-500/30 bg-sky-500/8",
    warn: "border-amber-500/40 bg-amber-500/10",
    error: "border-destructive/40 bg-destructive/8 text-destructive",
    ok: "border-emerald-500/30 bg-emerald-500/8",
  };
  return (
    <div className={cn("rounded-xl border px-4 py-2.5 text-sm text-pretty", styles[tone])}>
      {children}
    </div>
  );
}

function Stat({
  label,
  alert = false,
  children,
}: {
  label: string;
  alert?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-medium", alert && "text-amber-700 dark:text-amber-300")}>
        {children}
      </span>
    </span>
  );
}

function ClauseList({
  clauses,
  selectedId,
  onSelect,
}: {
  clauses: ClauseSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <nav
      aria-label="조항"
      className="max-h-80 overflow-y-auto rounded-xl border border-border bg-card p-1 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)]"
    >
      <ul>
        {clauses.map((clause) => (
          <li key={clause.id}>
            <button
              type="button"
              onClick={() => onSelect(clause.id)}
              aria-current={clause.id === selectedId ? "true" : undefined}
              style={{ paddingLeft: `${0.5 + (clause.level - 1) * 0.75}rem` }}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-sm transition-colors hover:bg-muted",
                clause.id === selectedId && "bg-muted font-medium",
                !clause.normative && "text-muted-foreground",
              )}
            >
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {clause.number}
              </span>
              <span className="min-w-0 flex-1 truncate">{clause.title}</span>
              {clause.unverified_count > 0 && (
                <CircleAlertIcon
                  className="size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
                  aria-label="인용 미확인 요건 있음"
                />
              )}
              {clause.requirement_count > 0 && (
                <span className="shrink-0 rounded-full bg-primary/10 px-1.5 text-[11px] leading-5 font-medium text-primary">
                  {clause.requirement_count}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function ClausePanel({
  tenant,
  clauseId,
  editable,
  onChanged,
}: {
  tenant: string;
  clauseId: string | null;
  editable: boolean;
  onChanged: () => Promise<void>;
}) {
  const clause = useClause(tenant, clauseId);
  if (!clauseId) return null;
  if (clause.error) return <ErrorState error={clause.error} />;
  if (!clause.data) return <Skeleton className="h-72" />;
  const data = clause.data;

  return (
    <div className="min-w-0 space-y-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">
          <span className="mr-2 font-mono text-base font-normal text-muted-foreground">
            {data.number}
          </span>
          {data.title}
        </h2>
        <p className="text-xs text-muted-foreground">
          {data.page_start === data.page_end
            ? `${data.page_start}쪽`
            : `${data.page_start}–${data.page_end}쪽`}
          {!data.normative && " · 참고용 부속서(요건 도출 대상 아님)"}
        </p>
      </div>

      {data.requirements.map((requirement) => (
        <RequirementCard
          key={requirement.id}
          tenant={tenant}
          requirement={requirement}
          editable={editable}
          onChanged={onChanged}
        />
      ))}
      {data.requirements.length === 0 && data.has_obligation && (
        <p className="text-sm text-muted-foreground">이 조항에서 도출한 요건이 아직 없습니다.</p>
      )}

      <details className="group rounded-xl border border-border bg-card" open={data.requirements.length === 0}>
        <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium select-none">
          조항 원문
        </summary>
        <p className="border-t border-border px-4 py-3 text-[0.8125rem] leading-6 whitespace-pre-wrap text-muted-foreground">
          {data.text || "본문 없음 (하위 조항에 내용이 있습니다)"}
        </p>
      </details>
    </div>
  );
}

function RequirementCard({
  tenant,
  requirement,
  editable,
  onChanged,
}: {
  tenant: string;
  requirement: Requirement;
  editable: boolean;
  onChanged: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const rejected = requirement.status === "rejected";

  const patch = useMutation({
    mutationFn: (body: { summary?: string; status?: "proposed" | "rejected" }) =>
      unwrap(
        api.PATCH("/api/t/{tenant_slug}/requirements/{requirement_id}", {
          params: { path: { tenant_slug: tenant, requirement_id: requirement.id } },
          body,
        }),
      ),
    onSuccess: async () => {
      setDraft(null);
      await onChanged();
    },
  });

  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3",
        rejected && "border-dashed bg-transparent opacity-60",
      )}
    >
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-xs text-muted-foreground">{requirement.code}</span>
        <span
          className={cn(
            "inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium",
            OBLIGATION_STYLE[requirement.obligation],
          )}
        >
          {OBLIGATION_LABEL[requirement.obligation] ?? requirement.obligation}
        </span>
        <span className="inline-flex h-5 items-center rounded-md bg-muted px-1.5 text-xs">
          {REQUIREMENT_CATEGORY_LABEL[requirement.category] ?? requirement.category}
        </span>
        {requirement.applicability && (
          <span className="text-xs text-muted-foreground">{requirement.applicability}</span>
        )}
        {rejected && <span className="text-xs font-medium">제외됨</span>}
        {editable && (
          <span className="ml-auto flex gap-1">
            {!rejected && draft === null && (
              <Button variant="ghost" size="icon-sm" aria-label="요약 고치기" onClick={() => setDraft(requirement.summary)}>
                <PencilIcon />
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              disabled={patch.isPending}
              onClick={() => patch.mutate({ status: rejected ? "proposed" : "rejected" })}
            >
              {rejected ? <Undo2Icon /> : <XIcon />}
              {rejected ? "되돌리기" : "제외"}
            </Button>
          </span>
        )}
      </div>

      {draft === null ? (
        <p className="text-[0.9375rem] leading-7">{requirement.summary}</p>
      ) : (
        <div className="space-y-2">
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setDraft(null)}>
              취소
            </Button>
            <Button
              size="sm"
              disabled={!draft.trim() || patch.isPending}
              onClick={() => patch.mutate({ summary: draft.trim() })}
            >
              저장
            </Button>
          </div>
        </div>
      )}

      {requirement.evidence.length > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          증적
          {requirement.evidence.map((item) => (
            <span key={item} className="rounded-md bg-muted px-1.5 py-0.5 text-foreground">
              {item}
            </span>
          ))}
        </p>
      )}

      <blockquote
        className={cn(
          "mt-3 border-l-2 pl-3 text-[0.8125rem] leading-6 whitespace-pre-wrap text-muted-foreground",
          requirement.quote_verified ? "border-border" : "border-amber-500",
        )}
      >
        {displayQuote(requirement.quote)}
      </blockquote>
      <p className="mt-1.5 flex items-center gap-1 text-xs">
        {requirement.quote_verified ? (
          <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
            <CheckIcon className="size-3.5" />
            원문에서 확인됨{requirement.page_no && ` · ${requirement.page_no}쪽`}
          </span>
        ) : (
          <span className="flex items-center gap-1 text-amber-700 dark:text-amber-300">
            <CircleAlertIcon className="size-3.5" />
            원문에서 이 문장을 찾지 못했습니다. 근거가 없으므로 제외해야 확정할 수 있습니다.
          </span>
        )}
      </p>
    </article>
  );
}
