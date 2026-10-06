"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  ChevronRightIcon,
  EllipsisIcon,
  FilePenLineIcon,
  PlusIcon,
  SparklesIcon,
  Trash2Icon,
  Undo2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { DocCode, ErrorState, Field, StatusBadge, TypeBadge } from "@/components/bits";
import { NewDocumentDialog } from "@/components/docs/new-document-dialog";
import { RevisionEditor } from "@/components/docs/revision-editor";
import { RevisionCompare, RevisionView } from "@/components/docs/revision-view";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type DocumentDetail, type Revision, type RevisionMeta, unwrap } from "@/lib/api";
import { CHANGE_KIND_LABEL, formatDate, formatDateTime, formatRelative } from "@/lib/labels";
import {
  keys,
  useDocTypes,
  useDocument,
  useRevision,
  useRevisionRequirements,
  useRevisions,
} from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/** 보고 있는 판: 진행 중인 개정판, 승인판, 둘의 비교, 또는 이력에서 고른 과거 판(id). */
type View = "open" | "approved" | "compare" | { revisionId: string };

export default function DocumentPage() {
  const { tenant, system, docId } = useParams<{ tenant: string; system: string; docId: string }>();
  const detail = useDocument(tenant, docId);

  if (detail.error) return <ErrorState error={detail.error} />;
  if (!detail.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-9 w-96 max-w-full" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  // 문서가 바뀌면 보기 상태를 새로 잡는다.
  return <DocumentScreen key={docId} tenant={tenant} system={system} detail={detail.data} />;
}

function DocumentScreen({
  tenant,
  system,
  detail,
}: {
  tenant: string;
  system: string;
  detail: DocumentDetail;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const docTypes = useDocTypes();
  const { document: doc, approved, open, actions } = detail;
  const revisions = useRevisions(tenant, doc.id);

  const can = (action: string) => actions.includes(action);
  const childTypes = actions
    .filter((a) => a.startsWith("create_child:"))
    .map((a) => a.split(":")[1]);

  // 내가 처리할 개정판이 있으면 그것부터, 아니면 승인판을 보여준다.
  const [chosen, setChosen] = useState<View | null>(null);
  const fallback: View = open && (!approved || actions.length > 0) ? "open" : "approved";
  let view: View = chosen ?? fallback;
  if (view === "open" && !open) view = "approved";
  if (view === "approved" && !approved) view = "open";
  if (view === "compare" && !(open && approved)) view = fallback;

  const [dialog, setDialog] = useState<
    "start" | "approve" | "reject" | "discard" | "child" | null
  >(null);

  const historical = useRevision(tenant, typeof view === "object" ? view.revisionId : null);
  const schema = docTypes.data?.find((t) => t.code === doc.doc_type)?.sections ?? [];
  const editing = view === "open" && open?.status === "draft" && can("edit");

  async function refresh() {
    setChosen(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) }),
      queryClient.invalidateQueries({ queryKey: keys.inbox(tenant) }),
    ]);
  }

  const withdraw = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/revisions/{revision_id}/withdraw", {
          params: { path: { tenant_slug: tenant, revision_id: open!.id } },
        }),
      ),
    onSuccess: async () => {
      toast.success("검토 요청을 회수했습니다.");
      await refresh();
    },
  });

  const shown: Revision | null | undefined =
    view === "open" ? open : view === "approved" ? approved : null;
  // 지금 보고 있는 판의 섹션별 근거 요건(표준에서 생성한 문서에만 있다).
  const viewedRevisionId =
    typeof view === "object" ? view.revisionId : (shown?.id ?? null);
  const citations = useRevisionRequirements(tenant, viewedRevisionId);
  const draftedByModel = (view === "open" ? open : approved)?.generated_by;

  return (
    <div className="space-y-5">
      <nav aria-label="위치" className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
        <Link href={routes.library(tenant, system)} className="hover:text-foreground">
          {detail.system.name}
        </Link>
        {detail.ancestors.map((ancestor) => (
          <span key={ancestor.id} className="flex items-center gap-1">
            <ChevronRightIcon className="size-3.5" />
            <Link
              href={routes.document(tenant, system, ancestor.id)}
              className="font-mono text-xs hover:text-foreground"
              title={ancestor.title}
            >
              {ancestor.code}
            </Link>
          </span>
        ))}
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <TypeBadge type={doc.doc_type} />
            <DocCode className="text-sm">{doc.code}</DocCode>
            {approved && <StatusBadge status="approved" version={approved.version} />}
            {open && <StatusBadge status={open.status} version={open.version} />}
            {draftedByModel && (
              <span
                className="inline-flex h-5 items-center gap-1 rounded-md bg-primary/10 px-1.5 text-xs text-primary"
                title={`모델 ${draftedByModel} 이(가) 요건을 근거로 쓴 초안입니다. 사람의 검토가 필요합니다.`}
              >
                <SparklesIcon className="size-3" />
                AI 초안
              </span>
            )}
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">
            {(view === "open" ? open?.title : null) ?? doc.title}
          </h1>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {can("review") && (
            <>
              <Button variant="outline" onClick={() => setDialog("reject")}>
                <XIcon />
                반려
              </Button>
              <Button onClick={() => setDialog("approve")}>
                <CheckIcon />
                승인
              </Button>
            </>
          )}
          {can("withdraw") && (
            <Button
              variant="outline"
              onClick={() => withdraw.mutate()}
              disabled={withdraw.isPending}
            >
              <Undo2Icon />
              검토 요청 회수
            </Button>
          )}
          {can("start_revision") && (
            <Button onClick={() => setDialog("start")}>
              <FilePenLineIcon />
              개정 시작
            </Button>
          )}
          {(childTypes.length > 0 || can("discard")) && (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="outline" size="icon" aria-label="더 보기" />}
              >
                <EllipsisIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-44">
                {childTypes.length > 0 && (
                  <DropdownMenuItem onClick={() => setDialog("child")}>
                    <PlusIcon />
                    하위 문서 추가
                  </DropdownMenuItem>
                )}
                {can("discard") && (
                  <DropdownMenuItem variant="destructive" onClick={() => setDialog("discard")}>
                    <Trash2Icon />
                    {approved ? "초안 폐기" : "문서 삭제"}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </header>

      {open && approved && (
        <div className="flex w-fit rounded-lg bg-muted p-0.5" role="group" aria-label="볼 판 선택">
          <ViewTab active={view === "open"} onClick={() => setChosen("open")}>
            진행 중 v{open.version}
          </ViewTab>
          <ViewTab active={view === "approved"} onClick={() => setChosen("approved")}>
            승인판 v{approved.version}
          </ViewTab>
          <ViewTab active={view === "compare"} onClick={() => setChosen("compare")}>
            변경 비교
          </ViewTab>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0 space-y-3">
          {view === "open" && open && <RevisionNotice revision={open} />}
          {typeof view === "object" && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/50 px-4 py-2.5 text-sm">
              <span>
                과거 판을 보고 있습니다
                {historical.data && ` · v${historical.data.version}`}
              </span>
              <Button variant="ghost" size="sm" onClick={() => setChosen(null)}>
                현재 판으로
              </Button>
            </div>
          )}

          {editing && open ? (
            schema.length > 0 ? (
              <RevisionEditor
                key={open.id}
                tenant={tenant}
                revision={open}
                schema={schema}
                isFirstRevision={!approved}
                canSubmit={can("submit")}
                citations={citations.data}
                onSubmitted={refresh}
              />
            ) : (
              <Skeleton className="h-64" />
            )
          ) : view === "compare" && open && approved ? (
            <RevisionCompare base={approved} target={open} />
          ) : typeof view === "object" ? (
            historical.data ? (
              <RevisionView revision={historical.data} citations={citations.data} />
            ) : (
              <Skeleton className="h-64" />
            )
          ) : (
            shown && <RevisionView revision={shown} citations={citations.data} />
          )}
        </div>

        <aside className="space-y-5 text-sm">
          <RevisionFacts
            revision={typeof view === "object" ? historical.data : view === "compare" ? open : shown}
          />

          <RailSection
            title="하위 문서"
            action={
              childTypes.length > 0 && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label="하위 문서 추가"
                  onClick={() => setDialog("child")}
                >
                  <PlusIcon />
                </Button>
              )
            }
          >
            {detail.children.length === 0 ? (
              <p className="text-muted-foreground">없음</p>
            ) : (
              <ul className="space-y-1">
                {detail.children.map((child) => (
                  <li key={child.id}>
                    <Link
                      href={routes.document(tenant, system, child.id)}
                      className="-mx-1.5 flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-muted"
                    >
                      <TypeBadge type={child.doc_type} />
                      <span className="min-w-0 flex-1 truncate">{child.title}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </RailSection>

          <RailSection title="개정 이력">
            <ol className="space-y-1">
              {(revisions.data ?? []).map((revision) => (
                <li key={revision.id}>
                  <HistoryRow
                    revision={revision}
                    active={
                      (typeof view === "object" && view.revisionId === revision.id) ||
                      (view === "open" && open?.id === revision.id) ||
                      (view === "approved" && approved?.id === revision.id)
                    }
                    onSelect={() =>
                      setChosen(
                        revision.id === open?.id
                          ? "open"
                          : revision.id === approved?.id
                            ? "approved"
                            : { revisionId: revision.id },
                      )
                    }
                  />
                </li>
              ))}
            </ol>
          </RailSection>
        </aside>
      </div>

      {open && (
        <>
          <ReviewDialog
            kind={dialog === "approve" ? "approve" : dialog === "reject" ? "reject" : null}
            tenant={tenant}
            revision={open}
            onClose={() => setDialog(null)}
            onDone={refresh}
          />
          <DiscardDialog
            open={dialog === "discard"}
            tenant={tenant}
            revision={open}
            deletesDocument={!approved}
            onClose={() => setDialog(null)}
            onDone={async (documentDeleted) => {
              await refresh();
              if (documentDeleted) router.replace(routes.library(tenant, system));
            }}
          />
        </>
      )}
      {approved && (
        <StartRevisionDialog
          open={dialog === "start"}
          tenant={tenant}
          documentId={doc.id}
          currentVersion={approved.version}
          onClose={() => setDialog(null)}
          onDone={refresh}
        />
      )}
      <NewDocumentDialog
        tenant={tenant}
        system={system}
        parent={doc}
        open={dialog === "child"}
        onOpenChange={(isOpen) => !isOpen && setDialog(null)}
      />
    </div>
  );
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-7 rounded-md px-2.5 text-sm transition-colors",
        active
          ? "bg-background font-medium shadow-xs"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function RevisionNotice({ revision }: { revision: Revision }) {
  if (revision.status === "in_review") {
    return (
      <div className="rounded-xl border border-sky-500/30 bg-sky-500/8 px-4 py-2.5 text-sm">
        검토 중입니다
        {revision.author && ` · 작성 ${revision.author.name}`}
        {revision.submitted_at && ` · ${formatRelative(revision.submitted_at)} 제출`}
        {revision.change_summary && (
          <p className="mt-1 text-muted-foreground">변경 요약: {revision.change_summary}</p>
        )}
      </div>
    );
  }
  if (revision.status === "draft" && revision.review_comment) {
    return (
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm">
        <p className="font-medium">
          반려됨{revision.reviewer && ` · ${revision.reviewer.name}`}
          {revision.reviewed_at && ` · ${formatRelative(revision.reviewed_at)}`}
        </p>
        <p className="mt-1 whitespace-pre-wrap">{revision.review_comment}</p>
      </div>
    );
  }
  return null;
}

function RailSection({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-1.5 flex h-6 items-center justify-between">
        <h2 className="text-xs font-medium text-muted-foreground">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function RevisionFacts({ revision }: { revision: Revision | null | undefined }) {
  if (!revision) return null;
  const facts: [string, ReactNode][] = [
    ["버전", `v${revision.version}`],
    ["개정 구분", CHANGE_KIND_LABEL[revision.change_kind] ?? revision.change_kind],
    ["작성", revision.author?.name ?? "—"],
  ];
  if (revision.reviewer) {
    facts.push([revision.status === "draft" ? "검토" : "승인", revision.reviewer.name]);
  }
  if (revision.approved_at) facts.push(["승인일", formatDate(revision.approved_at)]);
  if (revision.content_hash && revision.status !== "draft") {
    facts.push([
      "내용 지문",
      <span key="hash" className="font-mono text-xs" title={revision.content_hash}>
        {revision.content_hash.slice(0, 12)}
      </span>,
    ]);
  }
  return (
    <RailSection title="이 판의 정보">
      <dl className="grid grid-cols-[5rem_1fr] gap-x-2 gap-y-1.5">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 truncate">{value}</dd>
          </div>
        ))}
      </dl>
      {revision.change_summary && (
        <p className="mt-2 rounded-lg bg-muted/60 px-2.5 py-2 text-[0.8125rem] whitespace-pre-wrap">
          {revision.change_summary}
        </p>
      )}
    </RailSection>
  );
}

function HistoryRow({
  revision,
  active,
  onSelect,
}: {
  revision: RevisionMeta;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "true" : undefined}
      className={cn(
        "-mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-muted",
        active && "bg-muted",
      )}
    >
      <StatusBadge status={revision.status} version={revision.version} />
      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
        {revision.author?.name}
      </span>
      <span
        className="shrink-0 text-xs text-muted-foreground"
        title={formatDateTime(revision.approved_at ?? revision.updated_at)}
      >
        {formatDate(revision.approved_at ?? revision.updated_at)}
      </span>
    </button>
  );
}

// ── 대화상자 ─────────────────────────────────────────────────────────────────

function ReviewDialog({
  kind,
  tenant,
  revision,
  onClose,
  onDone,
}: {
  kind: "approve" | "reject" | null;
  tenant: string;
  revision: Revision;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [comment, setComment] = useState("");
  const review = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      unwrap(
        api.POST(`/api/t/{tenant_slug}/revisions/{revision_id}/${action}`, {
          params: { path: { tenant_slug: tenant, revision_id: revision.id } },
          body: { comment },
        }),
      ),
    onSuccess: async (_, action) => {
      toast.success(action === "approve" ? `v${revision.version} 을 승인했습니다.` : "반려했습니다.");
      setComment("");
      onClose();
      await onDone();
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (kind) review.mutate(kind);
  }

  const approving = kind === "approve";
  return (
    <Dialog open={kind !== null} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{approving ? `v${revision.version} 승인` : "반려"}</DialogTitle>
            <DialogDescription>
              {approving
                ? "승인하면 이 판이 유효한 기준이 되고, 이후에는 내용을 바꿀 수 없습니다."
                : "작성자가 고쳐서 다시 제출할 수 있도록 사유를 적어 주세요."}
            </DialogDescription>
          </DialogHeader>
          <Field label={approving ? "의견 (선택)" : "반려 사유"}>
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              required={!approving}
              autoFocus
            />
          </Field>
          <DialogFooter>
            <Button
              type="submit"
              variant={approving ? "default" : "destructive"}
              disabled={review.isPending}
            >
              {approving ? "승인" : "반려"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DiscardDialog({
  open,
  tenant,
  revision,
  deletesDocument,
  onClose,
  onDone,
}: {
  open: boolean;
  tenant: string;
  revision: Revision;
  deletesDocument: boolean;
  onClose: () => void;
  onDone: (documentDeleted: boolean) => Promise<void>;
}) {
  const discard = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/revisions/{revision_id}", {
          params: { path: { tenant_slug: tenant, revision_id: revision.id } },
        }),
      ),
    onSuccess: async (result) => {
      onClose();
      await onDone(Boolean(result.document_deleted));
    },
  });
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{deletesDocument ? "문서를 삭제할까요?" : "초안을 폐기할까요?"}</DialogTitle>
          <DialogDescription>
            {deletesDocument
              ? "승인된 판이 없는 문서라 문서 자체가 삭제됩니다. 되돌릴 수 없습니다."
              : `v${revision.version} 초안의 변경 내용이 사라집니다. 승인판은 그대로 남습니다.`}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="destructive"
            onClick={() => discard.mutate()}
            disabled={discard.isPending}
          >
            {deletesDocument ? "삭제" : "폐기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StartRevisionDialog({
  open,
  tenant,
  documentId,
  currentVersion,
  onClose,
  onDone,
}: {
  open: boolean;
  tenant: string;
  documentId: string;
  currentVersion: string;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [kind, setKind] = useState<"minor" | "major">("minor");
  const [summary, setSummary] = useState("");
  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/documents/{document_id}/revisions", {
          params: { path: { tenant_slug: tenant, document_id: documentId } },
          body: { change_kind: kind, change_summary: summary },
        }),
      ),
    onSuccess: async () => {
      setSummary("");
      onClose();
      await onDone();
    },
  });

  const [major, minor] = currentVersion.split(".").map(Number);
  const options = [
    {
      value: "minor" as const,
      next: `${major}.${(minor ?? 0) + 1}`,
      hint: "오탈자, 표현, 링크, 소절 수정",
    },
    { value: "major" as const, next: `${major + 1}.0`, hint: "구조, 책임, 범위 변경" },
  ];

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>개정 시작</DialogTitle>
            <DialogDescription>
              승인판 v{currentVersion} 의 내용으로 초안을 만듭니다. 승인 전까지 현재 판이 계속
              유효합니다.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 sm:grid-cols-2">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={kind === option.value}
                onClick={() => setKind(option.value)}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                  kind === option.value
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/50",
                )}
              >
                <span className="flex items-center justify-between font-medium">
                  {CHANGE_KIND_LABEL[option.value]}
                  <span className="font-mono text-xs text-muted-foreground">v{option.next}</span>
                </span>
                <span className="block text-xs text-muted-foreground">{option.hint}</span>
              </button>
            ))}
          </div>
          <Field label="변경 요약 (나중에 적어도 됩니다)">
            <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={start.isPending}>
              초안 만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
