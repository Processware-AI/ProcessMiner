"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2Icon, ChevronLeftIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useMemo, useState } from "react";
import { toast } from "sonner";

import { DocCode, EmptyState, ErrorState, LinkButton, TypeBadge } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DecisionGroup, type DecisionOccurrence, unwrap } from "@/lib/api";
import { keys, useDecisions, useSystem } from "@/lib/queries";
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
