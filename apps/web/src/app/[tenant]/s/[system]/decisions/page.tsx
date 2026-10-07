"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2Icon, ChevronLeftIcon, SearchIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DocCode, EmptyState, ErrorState, LinkButton, TypeBadge } from "@/components/bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DecisionGroup, type DecisionOccurrence, unwrap } from "@/lib/api";
import { keys, useAiDecisions, useDecisions, useSystem } from "@/lib/queries";
import { routes } from "@/lib/routes";

type Target = { revision_id: string; section_key: string };
type Fill = (input: { label: string; value: string; targets: Target[] }) => void;

export default function DecisionsPage() {
  // 주소의 검색어(?q=)를 읽으므로 Suspense 안에서 그린다.
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <Decisions />
    </Suspense>
  );
}

/**
 * 조직이 정할 항목: 표준이 값을 정하지 않아 초안에 〔조직 결정: …〕 으로 남은 곳을 모아 채운다.
 * 이 표시가 남은 문서는 검토를 요청할 수 없다.
 */
function Decisions() {
  const { tenant, system } = useParams<{ tenant: string; system: string }>();
  const queryClient = useQueryClient();
  const systemQuery = useSystem(tenant, system);
  const decisions = useDecisions(tenant, system);
  const [query, setQuery] = useState(useSearchParams().get("q") ?? "");
  const canFill = systemQuery.data?.actions.includes("doc.edit") ?? false;

  const fill = useMutation({
    mutationFn: (body: { label: string; value: string; targets: Target[] }) =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/decisions", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
          body,
        }),
      ),
    onSuccess: async (result) => {
      toast.success(
        result.documents > 1
          ? `문서 ${result.documents}건의 ${result.places}곳을 채웠습니다.`
          : `${result.places}곳을 채웠습니다.`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.decisions(tenant, system) }),
        queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) }),
      ]);
    },
  });

  const all = useMemo(() => decisions.data ?? [], [decisions.data]);
  const totals = useMemo(() => {
    const documents = new Set(all.flatMap((g) => g.occurrences.map((o) => o.document.id)));
    return { places: all.reduce((sum, g) => sum + g.occurrences.length, 0), documents: documents.size };
  }, [all]);

  // 항목 이름이 맞으면 그 항목 전체를, 아니면 문서 번호·제목이 맞는 곳만 남긴다.
  const needle = query.trim().toLowerCase();
  const shown = useMemo<DecisionGroup[]>(() => {
    if (!needle) return all;
    return all.flatMap((group) => {
      if (group.label.toLowerCase().includes(needle)) return [group];
      const occurrences = group.occurrences.filter(
        (o) =>
          o.document.code.toLowerCase().includes(needle) ||
          o.document.title.toLowerCase().includes(needle),
      );
      return occurrences.length > 0 ? [{ ...group, occurrences }] : [];
    });
  }, [all, needle]);

  return (
    <div className="space-y-5">
      <div>
        <Link
          href={routes.library(tenant, system)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeftIcon className="size-4" />
          {systemQuery.data?.name ?? "체계"}
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">조직이 정할 항목</h1>
        <p className="mt-1 text-sm text-muted-foreground text-pretty">
          표준이 값을 정하지 않아 조직이 스스로 정해야 하는 곳입니다(주기, 기한, 담당, 기준값 등).
          채운 내용은 문서 본문에 들어가고, 누가 언제 정했는지 기록됩니다. 항목이 남은 문서는
          검토를 요청할 수 없습니다.
        </p>
      </div>

      <AiFill
        tenant={tenant}
        system={system}
        remaining={totals.places}
        canFill={canFill}
      />

      {decisions.isPending && <Skeleton className="h-48" />}
      {decisions.error && <ErrorState error={decisions.error} />}

      {decisions.data && all.length === 0 && (
        <EmptyState
          icon={<CheckCircle2Icon />}
          title="정할 항목이 남아 있지 않습니다"
          description="초안의 모든 항목이 채워졌습니다. 문서 목록에서 검토를 요청하세요."
          action={<LinkButton href={routes.library(tenant, system)}>문서 목록으로</LinkButton>}
        />
      )}

      {all.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <div className="relative min-w-48 flex-1 sm:max-w-xs">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="항목 이름, 문서 번호 또는 제목"
                className="pl-8"
                aria-label="항목 검색"
              />
            </div>
            <span className="ml-auto text-sm text-muted-foreground">
              남은 항목 {totals.places}곳 · 문서 {totals.documents}건
            </span>
          </div>

          {shown.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">조건에 맞는 항목이 없습니다.</p>
          )}
          <ul className="space-y-3">
            {shown.map((group) => (
              <li key={group.label}>
                <GroupCard
                  tenant={tenant}
                  system={system}
                  group={group}
                  canFill={canFill}
                  pending={fill.isPending}
                  onFill={fill.mutate}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

const targetOf = (o: DecisionOccurrence): Target => ({
  revision_id: o.revision_id,
  section_key: o.section_key,
});

function GroupCard({
  tenant,
  system,
  group,
  canFill,
  pending,
  onFill,
}: {
  tenant: string;
  system: string;
  group: DecisionGroup;
  canFill: boolean;
  pending: boolean;
  onFill: Fill;
}) {
  const many = group.occurrences.length > 1;
  return (
    <section className="rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2.5">
        <h2 className="min-w-0 flex-1 basis-48 font-medium">
          {group.label}
          {many && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {group.occurrences.length}곳
            </span>
          )}
        </h2>
        {many && canFill && (
          <FillForm
            placeholder="모든 곳에 같은 내용으로"
            submitLabel={`${group.occurrences.length}곳 모두 채우기`}
            pending={pending}
            onSubmit={(value) =>
              onFill({ label: group.label, value, targets: group.occurrences.map(targetOf) })
            }
            className="basis-full sm:basis-auto"
          />
        )}
      </div>
      <ul className="divide-y divide-border">
        {group.occurrences.map((occurrence, index) => (
          <li
            key={`${occurrence.revision_id}:${occurrence.section_key}:${index}`}
            className="space-y-2 px-4 py-3"
          >
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <TypeBadge type={occurrence.document.doc_type} />
              <Link
                href={routes.document(tenant, system, occurrence.document.id)}
                className="min-w-0 truncate font-medium hover:underline"
              >
                {occurrence.document.title}
              </Link>
              <DocCode className="hidden sm:inline">{occurrence.document.code}</DocCode>
              <span className="text-xs text-muted-foreground">· {occurrence.section_title}</span>
            </p>
            <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm leading-6 break-words">
              {occurrence.before}
              <mark className="rounded bg-amber-500/20 px-1 py-0.5 text-foreground">
                {group.label}
              </mark>
              {occurrence.after}
            </p>
            {canFill && (
              <FillForm
                placeholder="정한 내용"
                submitLabel="채우기"
                pending={pending}
                onSubmit={(value) =>
                  onFill({ label: group.label, value, targets: [targetOf(occurrence)] })
                }
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FillForm({
  placeholder,
  submitLabel,
  pending,
  onSubmit,
  className,
}: {
  placeholder: string;
  submitLabel: string;
  pending: boolean;
  onSubmit: (value: string) => void;
  className?: string;
}) {
  const [value, setValue] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (value.trim()) onSubmit(value.trim());
  }
  return (
    <form onSubmit={submit} className={`flex min-w-0 gap-2 ${className ?? ""}`}>
      <Input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="min-w-0 flex-1 sm:w-64"
      />
      <Button type="submit" variant="outline" disabled={pending || !value.trim()}>
        {submitLabel}
      </Button>
    </form>
  );
}

/**
 * AI 로 남은 항목을 한꺼번에 채운다. 모델이 정한 값은 문서에 들어가고, 무엇을 왜 그렇게 정했는지
 * 목록으로 남아 사람이 검토할 수 있다(문서가 승인되기 전까지 보인다).
 */
function AiFill({
  tenant,
  system,
  remaining,
  canFill,
}: {
  tenant: string;
  system: string;
  remaining: number;
  canFill: boolean;
}) {
  const queryClient = useQueryClient();
  const state = useAiDecisions(tenant, system);
  const [confirming, setConfirming] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const run = state.data?.run;
  const busy = run?.status === "queued" || run?.status === "running";
  const filled = state.data?.filled ?? [];
  const progress = run?.progress as { done?: number; failed?: number; total?: number } | undefined;

  // 작업이 끝나면 남은 항목과 문서 목록도 새로 받아온다.
  const signature = `${run?.id}:${run?.status}:${progress?.done ?? 0}`;
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: keys.decisions(tenant, system), exact: true });
    void queryClient.invalidateQueries({ queryKey: keys.documents(tenant, system) });
  }, [queryClient, tenant, system, signature]);

  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/decisions/ai", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
        }),
      ),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: keys.decisions(tenant, system) });
    },
  });

  if (!busy && remaining === 0 && filled.length === 0) return null;
  const shown = showAll ? filled : filled.slice(0, 12);

  return (
    <section className="space-y-3 rounded-xl border border-violet-500/25 bg-violet-500/5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 basis-64 text-sm text-pretty">
          <SparklesIcon className="mr-1.5 inline size-4 align-[-3px] text-violet-600 dark:text-violet-300" />
          {busy
            ? progress?.total
              ? `AI 가 채우고 있습니다 — ${progress.total}곳 가운데 ${(progress.done ?? 0) + (progress.failed ?? 0)}곳 처리`
              : "AI 가 채울 준비를 하고 있습니다"
            : remaining > 0
              ? `남은 ${remaining}곳을 AI 가 업계에서 흔히 쓰는 값으로 한꺼번에 채울 수 있습니다. 채운 값과 근거는 아래에 남아 검토할 수 있습니다.`
              : `AI 가 채운 값 ${filled.length}곳이 있습니다. 문서를 승인하기 전에 검토하세요.`}
        </p>
        {canFill && remaining > 0 && !busy && (
          <Button size="sm" onClick={() => setConfirming(true)}>
            <SparklesIcon />
            AI 로 모두 채우기
          </Button>
        )}
      </div>
      {busy && (progress?.total ?? 0) > 0 && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-violet-500 transition-[width] duration-500"
            style={{
              width: `${Math.max((((progress?.done ?? 0) + (progress?.failed ?? 0)) / (progress?.total ?? 1)) * 100, 3)}%`,
            }}
          />
        </div>
      )}
      {!busy && run?.status === "failed" && (
        <p className="text-sm text-destructive">채우지 못했습니다: {run.error}</p>
      )}
      {!busy && run?.status === "succeeded" && (progress?.failed ?? 0) > 0 && (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          {progress?.failed}곳은 채우지 못했습니다. 아래 목록에서 직접 채우거나 다시 실행하세요.
        </p>
      )}

      {filled.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
            AI 가 채운 값 {filled.length}곳 · 문서를 승인하기 전까지 여기에 남습니다. 고치려면 문서를
            열어 본문을 수정하세요.
          </p>
          <ul className="divide-y divide-border">
            {shown.map((item, index) => (
              <li key={`${item.revision_id}:${index}`} className="grid gap-x-4 gap-y-0.5 px-3 py-2 text-sm sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{item.label}</span>
                  <Link
                    href={routes.document(tenant, system, item.document.id)}
                    className="block truncate text-xs text-muted-foreground hover:underline"
                  >
                    {item.document.code} · {item.section_title}
                  </Link>
                </span>
                <span className="min-w-0">
                  <span className="block break-words">{item.value}</span>
                  {item.rationale && (
                    <span className="block text-xs text-muted-foreground text-pretty">{item.rationale}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {filled.length > shown.length && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="w-full border-t border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/50"
            >
              {filled.length - shown.length}곳 더 보기
            </button>
          )}
        </div>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>AI 로 모두 채우기</DialogTitle>
            <DialogDescription>
              남은 {remaining}곳에 들어갈 값을 AI 가 정해 문서 본문에 바로 넣습니다. 처음 운영하는
              조직이 지킬 수 있는 일반적인 값(주기, 기한, 담당 역할, 기준값 등)으로 정하고, 이 체계에서
              사람이 이미 정한 값은 그대로 따릅니다. 문서 내용과 위치가 AI 모델로 전송됩니다. 정한 값은
              회사의 실제 운영과 맞는지 검토가 필요합니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              취소
            </Button>
            <Button disabled={start.isPending} onClick={() => start.mutate()}>
              채우기 시작
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
