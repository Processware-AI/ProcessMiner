"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, CircleAlertIcon } from "lucide-react";
import { type ReactNode, useState } from "react";

import { DocCode, TypeBadge } from "@/components/bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { api, type BatchReview, unwrap } from "@/lib/api";
import { keys } from "@/lib/queries";

// 한 번에 보낼 수 있는 개정판 수(API 의 상한과 같다).
export const BATCH_LIMIT = 500;

/**
 * 여러 개정판을 한 번에 검토 요청하거나 승인한다. 확인 → 처리 → 결과 순서로 보여준다.
 * 건마다 규칙을 따로 판단하므로, 안 된 건은 사유와 함께 결과에 남는다.
 */
export function BatchReviewDialog({
  tenant,
  action,
  revisionIds,
  open,
  onOpenChange,
  description,
  onDone,
}: {
  tenant: string;
  action: "submit" | "approve" | "approve_draft";
  revisionIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  description: ReactNode;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<BatchReview | null>(null);
  const count = Math.min(revisionIds.length, BATCH_LIMIT);
  const verb = action === "submit" ? "검토 요청" : "승인";
  const approving = action !== "submit";

  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/review-batch", {
          params: { path: { tenant_slug: tenant } },
          body: { action, revision_ids: revisionIds.slice(0, BATCH_LIMIT), comment },
        }),
      ),
    onSuccess: async (data) => {
      setResult(data);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.inbox(tenant) }),
        queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) }),
      ]);
      onDone?.();
    },
  });

  function close(next: boolean) {
    if (run.isPending) return;
    onOpenChange(next);
    if (!next) {
      setResult(null);
      setComment("");
    }
  }

  const failures = result?.results.filter((item) => !item.ok) ?? [];

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        {result === null ? (
          <div className="grid min-w-0 gap-4">
            <DialogHeader>
              <DialogTitle>
                {action === "approve_draft" && "검토 없이 "}
                {count}건 {verb}
              </DialogTitle>
              <DialogDescription>{description}</DialogDescription>
            </DialogHeader>
            {approving && (
              <Textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="검토 의견 (선택) — 승인하는 모든 문서에 같은 의견이 남습니다"
                rows={3}
                aria-label="검토 의견"
              />
            )}
            {revisionIds.length > BATCH_LIMIT && (
              <p className="text-xs text-muted-foreground">
                한 번에 {BATCH_LIMIT}건까지 처리합니다. 나머지는 끝난 뒤 다시 실행하세요.
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => close(false)} disabled={run.isPending}>
                취소
              </Button>
              <Button onClick={() => run.mutate()} disabled={run.isPending || count === 0}>
                {run.isPending ? "처리하는 중…" : `${count}건 ${verb}`}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="grid min-w-0 gap-4">
            <DialogHeader>
              <DialogTitle>
                {result.done}건 {verb} 완료
                {result.failed > 0 && `, ${result.failed}건은 하지 못했습니다`}
              </DialogTitle>
              <DialogDescription>
                {result.failed === 0
                  ? "모두 처리했습니다."
                  : "아래 문서는 사유를 해결한 뒤 다시 시도하세요. 나머지는 처리됐습니다."}
              </DialogDescription>
            </DialogHeader>
            {failures.length > 0 ? (
              <ul className="max-h-[50dvh] divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {failures.map((item) => (
                  <li key={item.revision_id} className="flex items-start gap-2 px-3 py-2 text-sm">
                    <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <span className="min-w-0 flex-1">
                      {item.document && (
                        <span className="flex items-center gap-2">
                          <TypeBadge type={item.document.doc_type} />
                          <span className="truncate font-medium">{item.document.title}</span>
                          <DocCode className="hidden shrink-0 sm:inline">{item.document.code}</DocCode>
                        </span>
                      )}
                      <span className="mt-0.5 block text-xs text-muted-foreground">{item.error}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
                <CheckIcon className="size-4" />
                실패한 문서가 없습니다.
              </p>
            )}
            <DialogFooter>
              <Button onClick={() => close(false)}>닫기</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
