"use client";

import { CheckCircle2Icon, ChevronRightIcon, LibraryIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  DocCode,
  EmptyState,
  ErrorState,
  LinkButton,
  PageHeader,
  StatusBadge,
  TypeBadge,
} from "@/components/bits";
import { BatchReviewDialog } from "@/components/docs/batch-review";
import { systemTree } from "@/components/shell/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { InboxItem } from "@/lib/api";
import { formatRelative } from "@/lib/labels";
import { useInbox, useMe, useSystems, useTenant } from "@/lib/queries";
import { routes } from "@/lib/routes";

const GROUPS: { kind: InboxItem["kind"]; title: string; hint: string }[] = [
  { kind: "to_review", title: "검토 요청", hint: "내 검토를 기다리는 개정판" },
  { kind: "returned", title: "반려됨", hint: "사유를 반영해 다시 제출해야 하는 개정판" },
  { kind: "my_draft", title: "작성 중", hint: "내가 작성 중인 초안" },
  { kind: "my_in_review", title: "검토 대기", hint: "내가 제출해 검토를 기다리는 개정판" },
];

/** 받은 일: 내가 처리할 개정판과 체계 바로가기. */
export default function HomePage() {
  const { tenant } = useParams<{ tenant: string }>();
  const me = useMe();
  const tenantQuery = useTenant(tenant);
  const inbox = useInbox(tenant);
  const systems = useSystems(tenant);

  const items = inbox.data ?? [];
  // 검토 요청은 골라서 한 번에 승인할 수 있다. 목록이 바뀌어 사라진 것은 선택에서 뺀다.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);
  const reviewable = items.filter((item) => item.kind === "to_review").map((i) => i.revision.id);
  const selected = reviewable.filter((id) => picked.has(id));
  const allPicked = reviewable.length > 0 && selected.length === reviewable.length;

  function togglePick(id: string) {
    setPicked((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="받은 일"
        description={
          me.data && tenantQuery.data
            ? `${me.data.user.name} 님, ${tenantQuery.data.name} 에서 처리할 일입니다.`
            : undefined
        }
      />

      <section className="space-y-6">
        {inbox.isPending && <Skeleton className="h-24" />}
        {inbox.error && <ErrorState error={inbox.error} />}
        {inbox.data && items.length === 0 && (
          <EmptyState
            icon={<CheckCircle2Icon />}
            title="처리할 일이 없습니다"
            description="검토 요청이 오거나 초안을 작성하면 여기에 모입니다."
          />
        )}
        {GROUPS.map((group) => {
          const rows = items.filter((item) => item.kind === group.kind);
          if (rows.length === 0) return null;
          const pickable = group.kind === "to_review";
          return (
            <div key={group.kind}>
              <div className="mb-2 flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1">
                <h2 className="text-sm font-semibold">{group.title}</h2>
                <span className="text-sm text-muted-foreground">{rows.length}</span>
                <span className="hidden text-xs text-muted-foreground sm:inline">
                  · {group.hint}
                </span>
                {pickable && rows.length > 1 && (
                  <span className="ml-auto flex items-center gap-3">
                    <label className="flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground">
                      <input
                        type="checkbox"
                        className="size-4 accent-primary"
                        checked={allPicked}
                        onChange={() => setPicked(allPicked ? new Set() : new Set(reviewable))}
                      />
                      모두 선택
                    </label>
                    <Button
                      size="sm"
                      disabled={selected.length === 0}
                      onClick={() => setApproving(true)}
                    >
                      {selected.length > 0 ? `선택한 ${selected.length}건 승인` : "선택한 문서 승인"}
                    </Button>
                  </span>
                )}
              </div>
              <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
                {rows.map((item) => (
                  <li key={item.revision.id} className="flex items-center">
                    {pickable && rows.length > 1 && (
                      <input
                        type="checkbox"
                        className="ml-3 size-4 shrink-0 accent-primary sm:ml-4"
                        checked={picked.has(item.revision.id)}
                        onChange={() => togglePick(item.revision.id)}
                        aria-label={`${item.revision.title} 선택`}
                      />
                    )}
                    <InboxRow tenant={tenant} item={item} />
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </section>

      <BatchReviewDialog
        tenant={tenant}
        action="approve"
        revisionIds={selected}
        open={approving}
        onOpenChange={setApproving}
        description={
          <>
            선택한 개정판을 한 번에 승인합니다. 승인하면 조직의 기준이 되고, 문서마다 검토자로
            기록됩니다. 내용을 확인한 문서만 선택하세요. 상위 문서가 승인되지 않은 문서는 제외되고
            사유가 표시됩니다.
          </>
        }
        onDone={() => setPicked(new Set())}
      />

      <section>
        <h2 className="mb-2 text-sm font-semibold">체계</h2>
        {systems.isPending && <Skeleton className="h-16" />}
        {systems.data?.length === 0 && (
          <EmptyState
            icon={<LibraryIcon />}
            title="아직 체계가 없습니다"
            description="회사 기준선 체계를 만든 뒤 조직별 변형 체계를 추가할 수 있습니다."
            action={
              tenantQuery.data?.actions.includes("system.create") && (
                <LinkButton href={routes.org(tenant)}>체계 만들기</LinkButton>
              )
            }
          />
        )}
        <ul className="grid gap-2 sm:grid-cols-2">
          {systemTree(systems.data ?? []).map(({ system, depth }) => (
            <li key={system.id}>
              <Link
                href={routes.library(tenant, system.slug)}
                className="group flex h-full items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:border-ring/60"
              >
                <LibraryIcon className="size-5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{system.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {depth === 0 ? "기준선 체계" : "조직 변형 체계"}
                    {system.description && ` · ${system.description}`}
                  </span>
                </span>
                <ChevronRightIcon className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function InboxRow({ tenant, item }: { tenant: string; item: InboxItem }) {
  const { document, revision } = item;
  return (
    <Link
      href={routes.document(tenant, item.system_slug, document.id)}
      className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2.5 transition-colors hover:bg-muted/50 sm:px-4"
    >
      <TypeBadge type={document.doc_type} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{revision.title}</span>
        <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <DocCode>{document.code}</DocCode>
          <span>{item.system_name}</span>
          {item.kind === "to_review" && revision.author && (
            <span>작성 {revision.author.name}</span>
          )}
          <span>{formatRelative(revision.updated_at)}</span>
        </span>
        {item.kind === "returned" && revision.review_comment && (
          <span className="mt-1 block truncate text-xs text-amber-700 dark:text-amber-300">
            반려 사유: {revision.review_comment}
          </span>
        )}
      </span>
      <StatusBadge status={revision.status} version={revision.version} />
    </Link>
  );
}
