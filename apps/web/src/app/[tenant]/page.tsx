"use client";

import { CheckCircle2Icon, ChevronRightIcon, LibraryIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  DocCode,
  EmptyState,
  ErrorState,
  LinkButton,
  PageHeader,
  StatusBadge,
  TypeBadge,
} from "@/components/bits";
import { systemTree } from "@/components/shell/app-shell";
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
          return (
            <div key={group.kind}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2 className="text-sm font-semibold">{group.title}</h2>
                <span className="text-sm text-muted-foreground">{rows.length}</span>
                <span className="hidden text-xs text-muted-foreground sm:inline">
                  · {group.hint}
                </span>
              </div>
              <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
                {rows.map((item) => (
                  <li key={item.revision.id}>
                    <InboxRow tenant={tenant} item={item} />
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </section>

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
      className="flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-muted/50 sm:px-4"
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
