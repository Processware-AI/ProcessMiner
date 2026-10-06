import { LoaderCircleIcon } from "lucide-react";

import type { Run } from "@/lib/api";
import { SOURCE_STATUS_LABEL, SOURCE_STATUS_STYLE } from "@/lib/labels";
import { cn } from "@/lib/utils";

export function SourceStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-xs font-medium",
        SOURCE_STATUS_STYLE[status] ?? SOURCE_STATUS_STYLE.extracted,
      )}
    >
      {SOURCE_STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** 요건 도출 작업의 진행 상황. */
export function RunProgress({ run, compact = false }: { run: Run; compact?: boolean }) {
  const progress = run.progress as { done?: number; failed?: number; total?: number };
  const total = progress.total ?? 0;
  const finished = (progress.done ?? 0) + (progress.failed ?? 0);
  const ratio = total > 0 ? finished / total : 0;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <LoaderCircleIcon className="size-4 animate-spin text-primary" />
        <span>
          {run.status === "queued" || total === 0
            ? "요건 도출을 준비하고 있습니다"
            : `요건 도출 중 — ${total}개 절 가운데 ${finished}개 완료`}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={finished}
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-500"
          style={{ width: `${Math.max(ratio * 100, 3)}%` }}
        />
      </div>
      {!compact && run.events.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {run.events.slice(-5).map((event, index) => (
            <li key={index}>{event}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
