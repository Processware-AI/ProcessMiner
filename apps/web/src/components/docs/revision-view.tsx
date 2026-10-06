"use client";

import { diffWordsWithSpace } from "diff";
import { useMemo } from "react";

import { Markdown } from "@/components/markdown";
import type { Revision, RevisionRequirement } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 개정판 본문을 섹션별로 보여준다(읽기 전용).
 * citations 가 있으면 섹션마다 그 내용이 근거로 삼은 요건을 펼쳐 볼 수 있다.
 */
export function RevisionView({
  revision,
  citations = [],
}: {
  revision: Revision;
  citations?: RevisionRequirement[];
}) {
  const bySection = new Map<string, RevisionRequirement[]>();
  for (const citation of citations) {
    bySection.set(citation.section_key, [...(bySection.get(citation.section_key) ?? []), citation]);
  }
  return (
    <div className="space-y-3">
      {revision.sections.map((section, index) => (
        <section
          key={section.key}
          id={`section-${section.key}`}
          className="scroll-mt-20 rounded-xl border border-border bg-card px-4 py-4 sm:px-5"
        >
          <h2 className="mb-2 flex items-baseline gap-2 text-base font-semibold">
            <span className="font-mono text-xs font-normal text-muted-foreground">{index + 1}</span>
            {section.title}
          </h2>
          {section.body_md.trim() ? (
            <Markdown>{section.body_md}</Markdown>
          ) : (
            <p className="text-sm text-muted-foreground">내용 없음</p>
          )}
          <SectionCitations citations={bySection.get(section.key) ?? []} />
        </section>
      ))}
    </div>
  );
}

/** 한 섹션이 근거로 삼은 요건. 접어 두고 필요할 때 펼쳐 원문 인용까지 본다. */
export function SectionCitations({ citations }: { citations: RevisionRequirement[] }) {
  if (citations.length === 0) return null;
  return (
    <details className="mt-3 rounded-lg bg-muted/50 text-sm">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground select-none">
        근거 요건 {citations.length}건 ·{" "}
        <span className="font-mono font-normal">
          {citations
            .slice(0, 6)
            .map((c) => c.requirement.code)
            .join(", ")}
          {citations.length > 6 && " …"}
        </span>
      </summary>
      <ul className="space-y-3 border-t border-border px-3 py-3">
        {citations.map(({ requirement, source }) => (
          <li key={requirement.id}>
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <span className="font-mono">
                {source.code} {requirement.code}
              </span>
              {requirement.page_no && <span>· {requirement.page_no}쪽</span>}
              {requirement.applicability && <span>· {requirement.applicability}</span>}
            </p>
            <p className="mt-0.5 leading-6">{requirement.summary}</p>
            <blockquote className="mt-1 border-l-2 border-border pl-2.5 text-xs leading-5 text-muted-foreground">
              {requirement.quote.replace(/\s+/g, " ")}
            </blockquote>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 두 개정판의 차이를 섹션별로 보여준다. base 가 이전 판, target 이 새 판. */
export function RevisionCompare({ base, target }: { base: Revision; target: Revision }) {
  const rows = useMemo(() => {
    const before = new Map(base.sections.map((s) => [s.key, s.body_md]));
    return target.sections.map((section) => {
      const previous = before.get(section.key) ?? "";
      return {
        key: section.key,
        title: section.title,
        changed: previous !== section.body_md,
        parts: diffWordsWithSpace(previous, section.body_md),
      };
    });
  }, [base, target]);

  const titleChanged = base.title !== target.title;
  const changedCount = rows.filter((r) => r.changed).length + (titleChanged ? 1 : 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <span>
          v{base.version} → v{target.version} · 바뀐 곳 {changedCount}
        </span>
        <span className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1">
            <span className="size-2.5 rounded-sm bg-emerald-500/30" /> 추가
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2.5 rounded-sm bg-rose-500/30" /> 삭제
          </span>
        </span>
      </div>

      {titleChanged && (
        <CompareCard title="제목" changed>
          <DiffText parts={diffWordsWithSpace(base.title, target.title)} />
        </CompareCard>
      )}
      {rows.map((row) => (
        <CompareCard key={row.key} title={row.title} changed={row.changed}>
          {row.changed && <DiffText parts={row.parts} />}
        </CompareCard>
      ))}
    </div>
  );
}

function CompareCard({
  title,
  changed,
  children,
}: {
  title: string;
  changed: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border px-4 py-3 sm:px-5",
        changed ? "border-border bg-card" : "border-dashed border-border",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className={cn("text-sm font-semibold", !changed && "text-muted-foreground")}>{title}</h2>
        {!changed && <span className="text-xs text-muted-foreground">변경 없음</span>}
      </div>
      {children && <div className="mt-2">{children}</div>}
    </section>
  );
}

function DiffText({ parts }: { parts: { value: string; added?: boolean; removed?: boolean }[] }) {
  return (
    <p className="text-[0.9375rem] leading-7 break-words whitespace-pre-wrap">
      {parts.map((part, index) =>
        part.added ? (
          <ins
            key={index}
            className="rounded-sm bg-emerald-500/20 text-emerald-900 no-underline dark:text-emerald-200"
          >
            {part.value}
          </ins>
        ) : part.removed ? (
          <del key={index} className="rounded-sm bg-rose-500/15 text-rose-800 dark:text-rose-300">
            {part.value}
          </del>
        ) : (
          <span key={index}>{part.value}</span>
        ),
      )}
    </p>
  );
}
