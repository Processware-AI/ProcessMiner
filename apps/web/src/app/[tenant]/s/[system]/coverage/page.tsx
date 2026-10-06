"use client";

import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClipboardCheckIcon,
  DownloadIcon,
  FileSpreadsheetIcon,
  PrinterIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LinkButton, TypeBadge } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { CoverageRequirement, CoverageSource } from "@/lib/api";
import { formatDate, OBLIGATION_LABEL, OBLIGATION_STYLE } from "@/lib/labels";
import { useCoverage, useSystem } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

type Status = CoverageRequirement["status"];

const STATUS: Record<Status, { label: string; hint: string; bar: string; pill: string }> = {
  covered: {
    label: "이행",
    hint: "승인된 문서가 이행합니다",
    bar: "bg-emerald-500",
    pill: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
  },
  drafted: {
    label: "초안",
    hint: "이행하는 문서가 아직 승인되지 않았습니다",
    bar: "bg-amber-400",
    pill: "bg-amber-500/12 text-amber-700 dark:text-amber-300",
  },
  gap: {
    label: "미이행",
    hint: "이행하는 문서가 없습니다",
    bar: "bg-rose-500",
    pill: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
  },
  excluded: {
    label: "제외",
    hint: "이 체계에 적용하지 않기로 했습니다",
    bar: "bg-muted-foreground/30",
    pill: "bg-muted text-muted-foreground",
  },
};
const ORDER: Status[] = ["covered", "drafted", "gap", "excluded"];
const DOCUMENT_STATE: Record<string, string> = { approved: "승인", in_review: "검토 중", draft: "초안" };

const countsOf = (rows: CoverageRequirement[]) =>
  Object.fromEntries(ORDER.map((s) => [s, rows.filter((r) => r.status === s).length])) as Record<
    Status,
    number
  >;

/** 표준 커버리지: 근거로 삼은 표준의 요건이 어느 문서에서 이행되는지 표준별로 본다. */
export default function CoveragePage() {
  const { tenant, system } = useParams<{ tenant: string; system: string }>();
  const systemQuery = useSystem(tenant, system);
  const [period, setPeriod] = useState<{ from?: string; to?: string }>({});
  const coverage = useCoverage(tenant, system, period);
  const [picked, setPicked] = useState<string | null>(null);
  const packUrl = useMemo(() => {
    const query = new URLSearchParams();
    if (period.from) query.set("date_from", period.from);
    if (period.to) query.set("date_to", period.to);
    const suffix = query.size > 0 ? `?${query}` : "";
    return `/api/t/${encodeURIComponent(tenant)}/systems/${encodeURIComponent(system)}/audit-pack.xlsx${suffix}`;
  }, [tenant, system, period]);

  const sources = coverage.data?.sources ?? [];
  const current = sources.find((s) => s.source.id === picked) ?? sources[0];

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={routes.library(tenant, system)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeftIcon className="size-4" />
          {systemQuery.data?.name ?? "체계"}
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
          표준 커버리지와 심사 증적
        </h1>
        <p className="mt-1 text-sm text-muted-foreground text-pretty print:hidden">
          이 체계가 근거로 삼은 표준의 요건이 어느 문서에서 이행되고, 어떤 기록으로 증명되는지
          보여줍니다. 문서의 섹션이 요건을 근거로 인용한 것만 셉니다. 승인된 문서가 인용해야
          “이행”이고, 승인 전 문서만 있으면 “초안”입니다. 기록은 그 요건을 이행하는 지침의 양식으로
          발행한 것입니다.
        </p>
        <p className="mt-1 hidden text-sm print:block">
          {systemQuery.data?.name} · 기록 기간 {period.from || "처음"} ~ {period.to || "지금"}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-xl border border-border bg-card px-4 py-3 print:hidden">
        <label className="grid gap-1 text-xs text-muted-foreground">
          기록 기간 시작
          <Input
            type="date"
            value={period.from ?? ""}
            onChange={(event) => setPeriod((p) => ({ ...p, from: event.target.value || undefined }))}
            className="w-40"
          />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          끝
          <Input
            type="date"
            value={period.to ?? ""}
            onChange={(event) => setPeriod((p) => ({ ...p, to: event.target.value || undefined }))}
            className="w-40"
          />
        </label>
        {(period.from || period.to) && (
          <Button variant="ghost" size="sm" onClick={() => setPeriod({})}>
            기간 지우기
          </Button>
        )}
        <span className="flex-1" />
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <PrinterIcon />
          인쇄 · PDF
        </Button>
        <Button size="sm" nativeButton={false} render={<a href={packUrl} download />}>
          <FileSpreadsheetIcon />
          증적 묶음 XLSX
        </Button>
      </div>

      {coverage.isPending && <Skeleton className="h-40" />}
      {coverage.error && <ErrorState error={coverage.error} />}
      {coverage.data && sources.length === 0 && (
        <EmptyState
          title="근거로 삼은 표준이 없습니다"
          description="표준 원문의 요건을 이 체계의 근거로 추가하면 커버리지를 볼 수 있습니다."
          action={<LinkButton href={routes.build(tenant, system)}>표준에서 문서 만들기</LinkButton>}
        />
      )}

      {sources.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {sources.map((source) => (
            <SourceCard
              key={source.source.id}
              source={source}
              selected={source === current}
              selectable={sources.length > 1}
              onSelect={() => setPicked(source.source.id)}
            />
          ))}
        </div>
      )}

      {current && (
        <SourceDetail key={current.source.id} tenant={tenant} system={system} source={current} />
      )}
    </div>
  );
}

function Bar({ counts, className }: { counts: Record<Status, number>; className?: string }) {
  const total = ORDER.reduce((sum, status) => sum + counts[status], 0);
  return (
    <div className={cn("flex h-2 overflow-hidden rounded-full bg-muted", className)} aria-hidden>
      {ORDER.map(
        (status) =>
          counts[status] > 0 && (
            <div
              key={status}
              className={STATUS[status].bar}
              style={{ width: `${(counts[status] / total) * 100}%` }}
            />
          ),
      )}
    </div>
  );
}

function SourceCard({
  source,
  selected,
  selectable,
  onSelect,
}: {
  source: CoverageSource;
  selected: boolean;
  selectable: boolean;
  onSelect: () => void;
}) {
  const applicable = source.total - source.excluded;
  const counts = { covered: source.covered, drafted: source.drafted, gap: source.gaps, excluded: source.excluded };
  const percent = applicable > 0 ? Math.round((source.covered / applicable) * 100) : 0;
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!selectable}
      aria-pressed={selectable ? selected : undefined}
      className={cn(
        "min-w-0 rounded-xl border bg-card px-4 py-3 text-left transition-colors",
        selected && selectable ? "border-primary/60 ring-2 ring-primary/15" : "border-border",
        selectable && !selected && "hover:border-ring/60",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs text-muted-foreground">
            {source.source.code}
            {source.source.edition && ` · ${source.source.edition}`}
          </p>
          <p className="truncate font-medium">{source.source.title}</p>
        </div>
        <p className="shrink-0 text-right">
          <span className="text-2xl font-semibold tabular-nums">{percent}%</span>
          <span className="block text-xs text-muted-foreground">
            이행 {source.covered} / 적용 {applicable}
          </span>
          <span className="block text-xs text-muted-foreground">기록 있음 {source.evidenced}</span>
        </p>
      </div>
      <Bar counts={counts} className="mt-3" />
      <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {ORDER.map((status) => (
          <span key={status} className="inline-flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", STATUS[status].bar)} />
            {STATUS[status].label} {counts[status]}
          </span>
        ))}
        <span className="ml-auto">
          {source.approved_at ? `적용요건 ${formatDate(source.approved_at)} 승인` : "적용요건 승인 전"}
        </span>
      </p>
    </button>
  );
}

function SourceDetail({ tenant, system, source }: { tenant: string; system: string; source: CoverageSource }) {
  const [filter, setFilter] = useState<Status | "all">("all");
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const total = countsOf(source.requirements);
  const needle = query.trim().toLowerCase();
  const shown = useMemo(
    () =>
      source.requirements.filter(
        (r) =>
          (filter === "all" || r.status === filter) &&
          (!needle ||
            r.code.toLowerCase().includes(needle) ||
            r.records.some((x) => x.code.toLowerCase().includes(needle)) ||
            r.summary.toLowerCase().includes(needle) ||
            r.documents.some(
              (d) => d.code.toLowerCase().includes(needle) || d.title.toLowerCase().includes(needle),
            )),
      ),
    [source.requirements, filter, needle],
  );

  // 인쇄할 때는 접어 둔 장도 모두 펼친다.
  useEffect(() => {
    const expand = () => setCollapsed(new Set());
    window.addEventListener("beforeprint", expand);
    return () => window.removeEventListener("beforeprint", expand);
  }, []);

  function toggle(key: string) {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <div className="flex flex-wrap rounded-lg bg-muted p-0.5" role="group" aria-label="상태로 걸러 보기">
          {(["all", ...ORDER] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              title={value === "all" ? undefined : STATUS[value].hint}
              className={cn(
                "h-7 rounded-md px-2.5 text-sm transition-colors",
                filter === value
                  ? "bg-background font-medium shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {value === "all" ? "전체" : STATUS[value].label}{" "}
              <span className="tabular-nums opacity-70">
                {value === "all" ? source.requirements.length : total[value]}
              </span>
            </button>
          ))}
        </div>
        <div className="relative min-w-40 flex-1 sm:max-w-xs">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="요건 번호·내용 또는 문서"
            className="pl-8"
            aria-label="요건 검색"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto print:hidden"
          onClick={() => downloadCsv(source, system)}
        >
          <DownloadIcon />
          CSV 내려받기
        </Button>
      </div>

      {shown.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">조건에 맞는 요건이 없습니다.</p>
      )}

      {source.chapters.map((chapter) => {
        const rows = shown.filter((r) => r.chapter === chapter.key);
        if (rows.length === 0) return null;
        const open = !collapsed.has(chapter.key);
        return (
          <div key={chapter.key} className="overflow-hidden rounded-xl border border-border bg-card">
            <button
              type="button"
              onClick={() => toggle(chapter.key)}
              aria-expanded={open}
              className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-muted/40 sm:px-4"
            >
              <ChevronRightIcon
                className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
              />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                <span className="mr-2 font-mono text-muted-foreground">{chapter.key}</span>
                {chapter.title}
              </span>
              <Bar counts={countsOf(rows)} className="hidden w-28 shrink-0 sm:flex" />
              <span className="w-12 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
                {rows.length}건
              </span>
            </button>
            {open && (
              <ul className="divide-y divide-border border-t border-border">
                {rows.map((requirement) => (
                  <RequirementRow key={requirement.id} tenant={tenant} system={system} requirement={requirement} />
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </section>
  );
}

function RequirementRow({
  tenant,
  system,
  requirement,
}: {
  tenant: string;
  system: string;
  requirement: CoverageRequirement;
}) {
  const status = STATUS[requirement.status];
  return (
    <li className="grid gap-x-4 gap-y-2 px-3 py-2.5 text-sm sm:px-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-xs text-muted-foreground">{requirement.code}</span>
          <span
            className={cn(
              "inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium",
              OBLIGATION_STYLE[requirement.obligation],
            )}
          >
            {OBLIGATION_LABEL[requirement.obligation]}
          </span>
          <span
            className={cn("inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium", status.pill)}
            title={status.hint}
          >
            {status.label}
          </span>
        </p>
        <p className={cn("mt-1 leading-6", requirement.status === "excluded" && "text-muted-foreground")}>
          {requirement.summary}
        </p>
      </div>
      <div className="min-w-0 text-xs">
        {requirement.status === "excluded" && (
          <p className="text-muted-foreground">제외 사유: {requirement.reason}</p>
        )}
        {requirement.status === "gap" && (
          <p className="text-rose-700 dark:text-rose-300">이행하는 문서가 없습니다.</p>
        )}
        <ul className="space-y-1">
          {requirement.documents.map((document) => (
            <li key={document.id}>
              <Link
                href={routes.document(tenant, system, document.id)}
                className="group flex items-center gap-2"
                title={`${document.code} · 인용한 섹션: ${document.sections.join(", ")}`}
              >
                <TypeBadge type={document.doc_type} />
                <span className="min-w-0 flex-1 truncate group-hover:underline">{document.title}</span>
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-0.5",
                    document.state === "approved"
                      ? "text-emerald-700 dark:text-emerald-400"
                      : "text-muted-foreground",
                  )}
                >
                  {document.state === "approved" && <CheckIcon className="size-3.5" />}
                  {DOCUMENT_STATE[document.state]}
                </span>
              </Link>
            </li>
          ))}
        </ul>
        {requirement.records.length > 0 && (
          <ul className="mt-1.5 space-y-1 border-t border-dashed border-border pt-1.5">
            {requirement.records.map((record) => (
              <li key={record.id}>
                <Link
                  href={record.artifact_id ? routes.artifact(tenant, system, record.artifact_id) : "#"}
                  className="group flex items-center gap-2"
                  title={record.legacy ? "기존 산출물에서 옮긴 기록" : undefined}
                >
                  <ClipboardCheckIcon className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                  <span className="shrink-0 font-mono text-muted-foreground">{record.code}</span>
                  <span className="min-w-0 flex-1 truncate group-hover:underline">{record.title}</span>
                  {record.performed_on && (
                    <span className="shrink-0 text-muted-foreground">{record.performed_on}</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {requirement.status === "covered" && requirement.records.length === 0 && (
          <p className="mt-1 text-muted-foreground">이 기간의 기록 없음</p>
        )}
      </div>
    </li>
  );
}

/** 심사 준비용 표로 내려받는다. 엑셀에서 한글이 깨지지 않게 BOM 을 붙인다. */
function downloadCsv(source: CoverageSource, system: string) {
  const cell = (value: string | number) => `"${String(value).replaceAll('"', '""')}"`;
  const titles = new Map(source.chapters.map((chapter) => [chapter.key, chapter.title]));
  const lines = [
    ["표준", "장", "조항", "요건", "의무", "요건 요약", "상태", "이행 문서", "기록", "제외 사유"],
    ...source.requirements.map((r) => [
      source.source.code,
      `${r.chapter} ${titles.get(r.chapter) ?? ""}`.trim(),
      r.clause_number,
      r.code,
      r.obligation,
      r.summary,
      STATUS[r.status].label,
      r.documents
        .map((d) => `${d.code} ${d.title} (${DOCUMENT_STATE[d.state]}: ${d.sections.join(", ")})`)
        .join("\n"),
      r.records.map((x) => `${x.code} ${x.title}`).join("\n"),
      r.reason,
    ]),
  ];
  const csv = lines.map((line) => line.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `coverage-${system}-${source.source.code}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
