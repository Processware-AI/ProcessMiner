"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GitBranchIcon, GitForkIcon, MinusCircleIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { RevisionCompare } from "@/components/docs/revision-view";
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
import { api, type DocumentDetail, type Revision, unwrap } from "@/lib/api";
import { keys, useRevision } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

export const TAILORING_LABEL: Record<string, string> = {
  inherited: "상속",
  override: "재정의",
  added: "추가",
  excluded: "제외",
};
export const TAILORING_STYLE: Record<string, string> = {
  inherited: "bg-muted text-muted-foreground",
  override: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
  added: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  excluded: "bg-muted text-muted-foreground line-through",
};

/**
 * 하위 체계에서 본 문서의 테일러링 상태와 할 수 있는 일.
 * 기준선 체계의 문서(own)에는 아무것도 그리지 않는다.
 */
export function TailoringPanel({
  tenant,
  system,
  detail,
  current,
}: {
  tenant: string;
  system: string;
  detail: DocumentDetail;
  /** 이 체계의 문서에서 지금 유효한 판(승인판, 없으면 진행 중인 판). 상위 문서와 비교할 때 쓴다. */
  current: Revision | null;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { tailoring: info, document: doc } = detail;
  const [dialog, setDialog] = useState<"override" | "exclude" | "compare" | null>(null);
  const can = (action: string) => info.actions.includes(action);
  const path = { tenant_slug: tenant, system_slug: system, document_id: doc.id };

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) });
  }

  const override = useMutation({
    mutationFn: (reason: string) =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/tailoring/{document_id}/override", {
          params: { path },
          body: { reason },
        }),
      ),
    onSuccess: async (created) => {
      toast.success("이 체계의 문서로 재정의했습니다. 내용을 고친 뒤 검토를 요청하세요.");
      await refresh();
      router.push(routes.document(tenant, system, created.document.id));
    },
  });
  const exclude = useMutation({
    mutationFn: (reason: string) =>
      unwrap(
        api.PUT("/api/t/{tenant_slug}/systems/{system_slug}/tailoring/{document_id}/exclusion", {
          params: { path },
          body: { reason },
        }),
      ),
    onSuccess: async () => {
      setDialog(null);
      toast.success("이 체계에서 제외했습니다.");
      await refresh();
    },
  });
  const include = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/systems/{system_slug}/tailoring/{document_id}/exclusion", {
          params: { path },
        }),
      ),
    onSuccess: async () => {
      toast.success("다시 상위 문서를 그대로 씁니다.");
      await refresh();
    },
  });

  if (info.state === "own") return null;

  return (
    <>
      {info.state === "inherited" && (
        <Banner icon={<GitBranchIcon />}>
          <p className="min-w-0 flex-1 basis-64 text-pretty">
            상위 체계 <b className="font-medium">{info.home_system.name}</b>의 문서를 그대로 쓰고
            있습니다. 상위 문서가 개정되면 이 체계에도 자동으로 반영됩니다.
          </p>
          {can("override") && (
            <Button size="sm" variant="outline" onClick={() => setDialog("override")}>
              <GitForkIcon />이 체계에 맞게 재정의
            </Button>
          )}
          {can("exclude") && (
            <Button size="sm" variant="ghost" onClick={() => setDialog("exclude")}>
              <MinusCircleIcon />
              제외
            </Button>
          )}
        </Banner>
      )}

      {info.state === "excluded" && (
        <Banner icon={<MinusCircleIcon />} tone="muted">
          <p className="min-w-0 flex-1 basis-64 text-pretty">
            {info.implied
              ? "상위 문서를 제외해서 이 문서도 이 체계에 적용되지 않습니다."
              : "이 체계에는 적용하지 않는 문서입니다."}
            {info.reason && <span className="mt-0.5 block text-muted-foreground">사유: {info.reason}</span>}
          </p>
          {can("include") && (
            <Button size="sm" variant="outline" disabled={include.isPending} onClick={() => include.mutate()}>
              다시 적용
            </Button>
          )}
        </Banner>
      )}

      {info.state === "added" && (
        <Banner icon={<GitBranchIcon />}>
          <p className="min-w-0 flex-1 text-pretty">
            이 체계에만 있는 문서입니다. 상위 체계에는 없습니다.
          </p>
        </Banner>
      )}

      {info.state === "override" && info.base && info.base_system && (
        <Banner icon={<GitForkIcon />}>
          <p className="min-w-0 flex-1 basis-64 text-pretty">
            상위 체계 <b className="font-medium">{info.base_system.name}</b>의 문서를 이 체계에 맞게
            재정의한 문서입니다.
            {info.reason && <span className="mt-0.5 block text-muted-foreground">사유: {info.reason}</span>}
          </p>
          <Link
            href={routes.document(tenant, info.base_system.slug, info.base.id)}
            className="text-sm font-medium underline-offset-4 hover:underline"
          >
            상위 문서 보기
          </Link>
        </Banner>
      )}

      {info.state === "override" && info.base_changed && info.base_current && (
        <Banner icon={<TriangleAlertIcon />} tone="warn">
          <p className="min-w-0 flex-1 basis-64 text-pretty">
            재정의한 뒤 상위 문서가 개정됐습니다
            {info.base_forked && ` (v${info.base_forked.version} → v${info.base_current.version})`}.
            바뀐 내용을 이 문서에 반영할지 확인하세요.
          </p>
          <Button size="sm" onClick={() => setDialog("compare")}>
            변경 내용 보기
          </Button>
        </Banner>
      )}

      <ReasonDialog
        open={dialog === "override"}
        onOpenChange={(open) => !open && setDialog(null)}
        title="이 체계에 맞게 재정의"
        description="상위 문서의 승인판을 복사한 초안이 이 체계에 만들어집니다. 그 초안을 고쳐 승인받으면 이 체계에서는 상위 문서 대신 그 문서를 씁니다. 이후 상위 문서가 개정되면 자동으로 따라가지 않고, 바뀌었다는 표시가 나옵니다."
        placeholder="왜 다르게 해야 하는지 (심사에서 설명해야 합니다)"
        submitLabel="재정의"
        pending={override.isPending}
        onSubmit={(reason) => override.mutate(reason)}
      />
      <ReasonDialog
        open={dialog === "exclude"}
        onOpenChange={(open) => !open && setDialog(null)}
        title="이 체계에서 제외"
        description="이 문서와 그 아래 문서를 이 체계에 적용하지 않습니다. 이 문서들이 이행하던 표준 요건은 이 체계의 커버리지에서 빠지므로, 제외한 뒤 표준 커버리지를 확인하세요."
        placeholder="왜 적용하지 않는지 (심사에서 설명해야 합니다)"
        submitLabel="제외"
        pending={exclude.isPending}
        onSubmit={(reason) => exclude.mutate(reason)}
      />
      {dialog === "compare" && (
        <BaseChangeDialog
          tenant={tenant}
          detail={detail}
          current={current}
          canAcknowledge={can("ack_base")}
          onClose={() => setDialog(null)}
          onAcknowledged={refresh}
        />
      )}
    </>
  );
}

function Banner({
  icon,
  tone = "info",
  children,
}: {
  icon: ReactNode;
  tone?: "info" | "muted" | "warn";
  children: ReactNode;
}) {
  const tones = {
    info: "border-violet-500/25 bg-violet-500/6",
    muted: "border-border bg-muted/50",
    warn: "border-amber-500/30 bg-amber-500/8",
  };
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-2.5 text-sm",
        tones[tone],
      )}
    >
      <span className="shrink-0 text-muted-foreground [&_svg]:size-4">{icon}</span>
      {children}
    </div>
  );
}

function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  placeholder,
  submitLabel,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  placeholder: string;
  submitLabel: string;
  pending: boolean;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason.trim()) onSubmit(reason.trim());
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid min-w-0 gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={placeholder}
            aria-label="사유"
            rows={3}
            required
            autoFocus
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              취소
            </Button>
            <Button type="submit" disabled={pending || !reason.trim()}>
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** 상위 문서가 어떻게 바뀌었는지, 그리고 이 체계의 문서와 어떻게 다른지 나란히 본다. */
function BaseChangeDialog({
  tenant,
  detail,
  current,
  canAcknowledge,
  onClose,
  onAcknowledged,
}: {
  tenant: string;
  detail: DocumentDetail;
  current: Revision | null;
  canAcknowledge: boolean;
  onClose: () => void;
  onAcknowledged: () => Promise<void>;
}) {
  const info = detail.tailoring;
  const forked = useRevision(tenant, info.base_forked?.id ?? null);
  const latest = useRevision(tenant, info.base_current?.id ?? null);
  const [tab, setTab] = useState<"base" | "mine">(info.base_forked ? "base" : "mine");

  const acknowledge = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/documents/{document_id}/ack-base", {
          params: { path: { tenant_slug: tenant, document_id: detail.document.id } },
        }),
      ),
    onSuccess: async () => {
      toast.success("상위 문서의 변경을 확인했습니다.");
      await onAcknowledged();
      onClose();
    },
  });

  const tabs = [
    ...(info.base_forked
      ? [{ key: "base" as const, label: `상위 문서의 변경 (v${info.base_forked.version} → v${info.base_current?.version})` }]
      : []),
    { key: "mine" as const, label: "상위 신판과 이 체계 문서의 차이" },
  ];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-4xl">
        <div className="grid min-w-0 gap-4">
          <DialogHeader>
            <DialogTitle>상위 문서가 개정됐습니다</DialogTitle>
            <DialogDescription>
              재정의한 문서는 상위 문서를 자동으로 따라가지 않습니다. 바뀐 내용을 보고, 반영이
              필요하면 이 문서를 개정하세요. 확인을 마치면 표시가 사라집니다.
            </DialogDescription>
          </DialogHeader>
          <div className="flex w-fit max-w-full flex-wrap rounded-lg bg-muted p-0.5" role="group">
            {tabs.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={tab === item.key}
                onClick={() => setTab(item.key)}
                className={cn(
                  "h-7 rounded-md px-2.5 text-sm transition-colors",
                  tab === item.key
                    ? "bg-background font-medium shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="min-w-0">
            {tab === "base" &&
              (forked.data && latest.data ? (
                <RevisionCompare base={forked.data} target={latest.data} />
              ) : (
                <Skeleton className="h-48" />
              ))}
            {tab === "mine" &&
              (latest.data && current ? (
                <RevisionCompare base={latest.data} target={current} />
              ) : (
                <Skeleton className="h-48" />
              ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              닫기
            </Button>
            {canAcknowledge && (
              <Button onClick={() => acknowledge.mutate()} disabled={acknowledge.isPending}>
                변경을 확인했습니다
              </Button>
            )}
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
