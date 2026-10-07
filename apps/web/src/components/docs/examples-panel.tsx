"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenTextIcon, LoaderCircleIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, unwrap } from "@/lib/api";
import { keys, useExamples } from "@/lib/queries";

/** 작성예시가 없는 양식이 있으면 알려주고, AI 로 한꺼번에 만든다. */
export function ExamplesPanel({
  tenant,
  system,
  canCreate,
}: {
  tenant: string;
  system: string;
  canCreate: boolean;
}) {
  const queryClient = useQueryClient();
  const state = useExamples(tenant, system);
  const [confirming, setConfirming] = useState(false);
  const run = state.data?.run;
  const busy = run?.status === "queued" || run?.status === "running";
  const missing = state.data?.missing ?? [];
  const progress = run?.progress as { done?: number; failed?: number; total?: number } | undefined;

  // 예시가 하나 만들어질 때마다 문서 목록에 나타나게 한다.
  const signature = `${run?.id}:${run?.status}:${progress?.done ?? 0}`;
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: keys.documents(tenant, system) });
  }, [queryClient, tenant, system, signature]);

  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/examples", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
        }),
      ),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: keys.examples(tenant, system) });
    },
  });

  if (!busy && (missing.length === 0 || !canCreate) && run?.status !== "failed") return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-sky-500/25 bg-sky-500/6 px-4 py-2.5">
      <p className="min-w-0 flex-1 basis-64 text-sm text-pretty">
        {busy ? (
          <>
            <LoaderCircleIcon className="mr-1.5 inline size-4 animate-spin align-[-3px] text-sky-600" />
            작성예시를 만들고 있습니다
            {progress?.total
              ? ` — ${progress.total}건 가운데 ${(progress.done ?? 0) + (progress.failed ?? 0)}건 처리`
              : ""}
          </>
        ) : run?.status === "failed" && missing.length > 0 ? (
          `작성예시를 만들지 못했습니다: ${run.error}`
        ) : (
          <>
            <BookOpenTextIcon className="mr-1.5 inline size-4 align-[-3px] text-sky-600" />
            양식 {missing.length}건에 작성예시가 없습니다. 작성예시는 실무자가 양식을 처음 채울 때 보는
            교육용 샘플입니다.
          </>
        )}
      </p>
      {canCreate && !busy && missing.length > 0 && (
        <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
          <BookOpenTextIcon />
          AI 로 작성예시 만들기
        </Button>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>작성예시 만들기</DialogTitle>
            <DialogDescription>
              작성예시가 없는 양식 {missing.length}건마다, 그 양식을 쓰는 지침과 요건에 맞춰 가상의
              예시값·작성 요령·유의사항·잘못된 작성 사례를 AI 가 씁니다. 작성예시는 양식과 같은 지침
              아래에 초안으로 만들어지고, 실제 기록으로는 쓸 수 없습니다. 양식과 지침 내용이 AI 모델로
              전송됩니다. 양식 하나에 30초~1분쯤 걸립니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              취소
            </Button>
            <Button disabled={start.isPending} onClick={() => start.mutate()}>
              {missing.length}건 만들기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
