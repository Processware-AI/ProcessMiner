"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightIcon, CircleAlertIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";

import { DocCode, Field, NativeSelect, TypeBadge } from "@/components/bits";
import { systemTree } from "@/components/shell/app-shell";
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
import { Textarea } from "@/components/ui/textarea";
import { api, type DocumentRef, type OrganizeResult, unwrap } from "@/lib/api";
import { keys, useDocTypes, useDocuments, useSystems } from "@/lib/queries";

/** 정리할 문서. 목록의 문서 요약이나 문서 상세의 문서를 그대로 넘긴다. */
export type OrganizeDocument = DocumentRef & { parent_id?: string | null };

/** 문서를 지우거나 폐지하면 목록·커버리지·받은 일·체계 문서 수가 모두 바뀐다. */
async function refreshAfterOrganize(queryClient: ReturnType<typeof useQueryClient>, tenant: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) }),
    queryClient.invalidateQueries({ queryKey: keys.systems(tenant) }),
    queryClient.invalidateQueries({ queryKey: keys.inbox(tenant) }),
  ]);
}

function DocList({ items, render }: { items: DocumentRef[]; render?: (doc: DocumentRef) => ReactNode }) {
  return (
    <ul className="max-h-40 divide-y divide-border overflow-y-auto rounded-lg border border-border">
      {items.map((doc) => (
        <li key={doc.id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
          <TypeBadge type={doc.doc_type} />
          <span className="min-w-0 flex-1 truncate">{doc.title}</span>
          {render ? render(doc) : <DocCode className="shrink-0">{doc.code}</DocCode>}
        </li>
      ))}
    </ul>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <p className="text-sm font-medium">
        {title}
        {hint && <span className="ml-1.5 font-normal text-muted-foreground">{hint}</span>}
      </p>
      {children}
    </div>
  );
}

/** 바뀔 내용(또는 바뀐 내용)을 종류별로 보여준다. */
function OrganizeSummary({ result }: { result: OrganizeResult }) {
  const codeChange = (from: string, to: string) => (
    <span className="flex shrink-0 items-center gap-1 font-mono text-xs text-muted-foreground">
      {from}
      <ArrowRightIcon className="size-3" />
      <span className="text-foreground">{to}</span>
    </span>
  );
  const created = new Map(result.created.map((c) => [c.document.id, c.source.code]));
  const moved = new Map(result.moved.map((m) => [m.document.id, m.old_code]));
  return (
    <div className="grid gap-3">
      {result.moved.length > 0 && (
        <Group title={`위치 이동 ${result.moved.length}건`} hint="문서와 개정 이력은 그대로, 번호만 바뀝니다.">
          <DocList
            items={result.moved.map((m) => m.document)}
            render={(doc) => codeChange(moved.get(doc.id) ?? "", doc.code)}
          />
        </Group>
      )}
      {result.created.length > 0 && (
        <Group
          title={`${result.target_system?.name ?? "대상 체계"}에 새로 만들 문서 ${result.created.length}건`}
          hint="초안(1.0)으로 만들어지고, 승인을 다시 받아야 합니다."
        >
          <DocList
            items={result.created.map((c) => c.document)}
            render={(doc) => codeChange(created.get(doc.id) ?? "", doc.code)}
          />
        </Group>
      )}
      {result.deleted.length > 0 && (
        <Group title={`삭제 ${result.deleted.length}건`} hint="승인된 적 없는 문서는 지웁니다.">
          <DocList items={result.deleted} />
        </Group>
      )}
      {result.retired.length > 0 && (
        <Group
          title={`폐지 ${result.retired.length}건`}
          hint="승인 이력이 있어 지우지 않고 폐지합니다. 나중에 되살릴 수 있습니다."
        >
          <DocList items={result.retired} />
        </Group>
      )}
    </div>
  );
}

// ── 삭제·폐지 ────────────────────────────────────────────────────────────────

export function RemoveDocumentsDialog({
  tenant,
  documents,
  open,
  onOpenChange,
  onDone,
}: {
  tenant: string;
  documents: OrganizeDocument[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone?: (result: OrganizeResult) => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const ids = documents.map((doc) => doc.id);

  // 무엇이 지워지고 무엇이 폐지되는지 먼저 보여준다(하위 문서 포함).
  const preview = useQuery({
    queryKey: ["t", tenant, "organize", "remove", ...ids],
    enabled: open && ids.length > 0,
    gcTime: 0,
    queryFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/documents/remove", {
          params: { path: { tenant_slug: tenant } },
          body: { document_ids: ids, reason: "", dry_run: true },
        }),
      ),
  });

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/documents/remove", {
          params: { path: { tenant_slug: tenant } },
          body: { document_ids: ids, reason: reason.trim(), dry_run: false },
        }),
      ),
    onSuccess: async (result) => {
      const parts = [
        result.deleted.length > 0 && `${result.deleted.length}건 삭제`,
        result.retired.length > 0 && `${result.retired.length}건 폐지`,
      ].filter(Boolean);
      toast.success(`문서를 정리했습니다: ${parts.join(", ")}`);
      await refreshAfterOrganize(queryClient, tenant);
      // 이 시점에는 아직 처리 중으로 표시되므로 close() 대신 바로 닫는다.
      onOpenChange(false);
      setReason("");
      onDone?.(result);
    },
  });

  function close(next: boolean) {
    if (remove.isPending) return;
    onOpenChange(next);
    if (!next) setReason("");
  }

  const retiring = (preview.data?.retired.length ?? 0) > 0;
  const total = (preview.data?.deleted.length ?? 0) + (preview.data?.retired.length ?? 0);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <div className="grid min-w-0 gap-4">
          <DialogHeader>
            <DialogTitle>
              {documents.length === 1 ? `${documents[0].title} 삭제` : `문서 ${documents.length}건 삭제`}
            </DialogTitle>
            <DialogDescription>
              하위 문서도 함께 정리됩니다. 승인된 적 없는 문서는 지우고, 승인 이력이 있는 문서는
              감사 추적을 위해 폐지로 남깁니다. 폐지한 문서는 목록과 커버리지에서 빠집니다.
            </DialogDescription>
          </DialogHeader>
          {preview.isPending && <Skeleton className="h-24" />}
          {preview.error && <p className="text-sm text-destructive">{preview.error.message}</p>}
          {preview.data && <OrganizeSummary result={preview.data} />}
          {retiring && (
            <Field label="폐지 사유" hint="감사 기록과 폐지한 문서에 남습니다.">
              <Textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={2}
                placeholder="예: 교육 절차와 통합"
              />
            </Field>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => close(false)} disabled={remove.isPending}>
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={() => remove.mutate()}
              disabled={!preview.data || remove.isPending || (retiring && !reason.trim())}
            >
              {remove.isPending ? "정리하는 중…" : `${total}건 정리`}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── 옮기기·복사 ──────────────────────────────────────────────────────────────

export function RelocateDocumentsDialog({
  tenant,
  system,
  mode,
  documents,
  open,
  onOpenChange,
  onDone,
}: {
  tenant: string;
  system: string; // 문서가 있는 체계(주소)
  mode: "move" | "copy";
  documents: OrganizeDocument[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone?: (result: OrganizeResult) => void;
}) {
  const queryClient = useQueryClient();
  const systems = useSystems(tenant);
  const docTypes = useDocTypes();
  const [target, setTarget] = useState(system);
  const [parentId, setParentId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<OrganizeResult | null>(null);
  const targetDocuments = useDocuments(tenant, open ? target : undefined);

  const verb = mode === "move" ? "옮기기" : "복사";
  const ids = documents.map((doc) => doc.id);
  const chosen = new Set(ids);
  // 함께 고른 상위 문서를 따라가는 문서는 놓을 자리를 따로 고르지 않는다.
  const roots = documents.filter((doc) => !doc.parent_id || !chosen.has(doc.parent_id));
  const parentTypes = new Set(
    roots.map((doc) => docTypes.data?.find((t) => t.code === doc.doc_type)?.parent_type ?? null),
  );
  const parentType = parentTypes.size === 1 ? [...parentTypes][0] : undefined;
  const sameSystem = target === system;

  const candidates = (targetDocuments.data ?? []).filter(
    (doc) => doc.doc_type === parentType && doc.tailoring !== "excluded" && !chosen.has(doc.id),
  );

  let problem: string | null = null;
  if (docTypes.data && parentType === undefined) {
    problem = "놓을 자리가 다른 문서가 섞여 있습니다. 같은 유형의 문서끼리 골라 주세요.";
  } else if (mode === "move" && sameSystem && parentType === null) {
    problem = "정책·참고 문서는 체계 안에서 옮길 자리가 없습니다. 다른 체계를 고르세요.";
  } else if (parentType && targetDocuments.data && candidates.length === 0) {
    problem = `대상 체계에 ${parentType} 문서가 없습니다. 먼저 상위 문서를 만드세요.`;
  }
  const needsParent = Boolean(parentType);
  const ready = !problem && (!needsParent || parentId !== "");

  const body = {
    document_ids: ids,
    mode,
    target_system: target,
    parent_id: needsParent ? parentId : null,
    include_children: mode === "move" || includeChildren,
    reason: reason.trim(),
  };

  const relocate = useMutation({
    mutationFn: (dryRun: boolean) =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/documents/relocate", {
          params: { path: { tenant_slug: tenant } },
          body: { ...body, dry_run: dryRun },
        }),
      ),
    onSuccess: async (result) => {
      if (result.dry_run) {
        setPreview(result);
        return;
      }
      toast.success(
        result.moved.length > 0
          ? `문서 ${result.moved.length}건의 위치를 옮겼습니다.`
          : `${result.target_system?.name}에 문서 ${result.created.length}건을 ${mode === "move" ? "옮겼습니다" : "복사했습니다"}.`,
      );
      await refreshAfterOrganize(queryClient, tenant);
      // 이 시점에는 아직 처리 중으로 표시되므로 close() 대신 바로 닫는다.
      onOpenChange(false);
      reset();
      onDone?.(result);
    },
  });

  function reset() {
    setTarget(system);
    setParentId("");
    setIncludeChildren(true);
    setReason("");
    setPreview(null);
  }

  function close(next: boolean) {
    if (relocate.isPending) return;
    onOpenChange(next);
    if (!next) reset();
  }

  // 조건을 바꾸면 미리 본 결과는 더 맞지 않는다.
  function change<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPreview(null);
    };
  }

  const systemOptions = systemTree(systems.data ?? []);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <div className="grid min-w-0 gap-4">
          <DialogHeader>
            <DialogTitle>
              {documents.length === 1 ? documents[0].title : `문서 ${documents.length}건`} {verb}
            </DialogTitle>
            <DialogDescription>
              {mode === "copy"
                ? "고른 자리에 새 번호의 초안으로 복사합니다. 원본은 그대로 남습니다."
                : "같은 체계 안에서는 위치만 바꾸고 번호를 새로 받습니다(개정 이력은 유지). 다른 체계로 옮기면 그 체계에 새 번호로 복사한 뒤 원본을 정리합니다(승인 이력이 있으면 폐지)."}{" "}
              하위 문서도 함께 갑니다.
            </DialogDescription>
          </DialogHeader>

          <Field label="대상 체계">
            <NativeSelect
              value={target}
              onChange={(event) => {
                change(setTarget)(event.target.value);
                setParentId("");
              }}
            >
              {systemOptions.map(({ system: option, depth }) => (
                <option key={option.id} value={option.slug}>
                  {"  ".repeat(depth)}
                  {option.name}
                  {option.slug === system ? " (현재 체계)" : ""}
                </option>
              ))}
            </NativeSelect>
          </Field>

          {needsParent && !problem && (
            <Field label={`놓을 자리 (${parentType} 문서)`}>
              {targetDocuments.isPending ? (
                <Skeleton className="h-9" />
              ) : (
                <NativeSelect value={parentId} onChange={(event) => change(setParentId)(event.target.value)}>
                  <option value="" disabled>
                    상위 문서 선택
                  </option>
                  {candidates.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.code} {doc.title}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          )}

          {mode === "copy" && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeChildren}
                onChange={(event) => change(setIncludeChildren)(event.target.checked)}
                className="size-4 accent-primary"
              />
              하위 문서도 함께 복사
            </label>
          )}

          {mode === "move" && !sameSystem && (
            <Field label="원본 폐지 사유 (선택)" hint="비워 두면 '대상 체계(으)로 옮김'으로 남습니다.">
              <Input value={reason} onChange={(event) => change(setReason)(event.target.value)} />
            </Field>
          )}

          {problem && (
            <p className="flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-300">
              <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
              {problem}
            </p>
          )}

          {preview && (
            <div className="grid gap-2 rounded-lg bg-muted/40 p-3">
              <p className="text-xs font-medium text-muted-foreground">미리 보기</p>
              <OrganizeSummary result={preview} />
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => close(false)} disabled={relocate.isPending}>
              취소
            </Button>
            {preview ? (
              <Button onClick={() => relocate.mutate(false)} disabled={relocate.isPending}>
                {relocate.isPending ? "처리하는 중…" : verb}
              </Button>
            ) : (
              <Button onClick={() => relocate.mutate(true)} disabled={!ready || relocate.isPending}>
                {relocate.isPending ? "확인하는 중…" : "미리 보기"}
              </Button>
            )}
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
