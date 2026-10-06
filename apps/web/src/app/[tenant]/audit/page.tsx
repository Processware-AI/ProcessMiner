"use client";

import { ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";
import { useParams } from "next/navigation";

import { ErrorState, PageHeader } from "@/components/bits";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuditEntry } from "@/lib/api";
import { AUDIT_ACTION_LABEL, formatDateTime } from "@/lib/labels";
import { useAuditLog, useTenant } from "@/lib/queries";

/** 기록에 딸린 값 중 사람이 알아볼 만한 것만 한 줄로 보여준다. */
function summarize(entry: AuditEntry): string {
  const data = entry.data as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of ["code", "name", "email", "slug"]) {
    if (typeof data[key] === "string") {
      parts.push(data[key] as string);
      break;
    }
  }
  if (typeof data.title === "string") parts.push(data.title);
  if (typeof data.version === "string") parts.push(`v${data.version}`);
  if (typeof data.comment === "string" && data.comment) parts.push(`“${data.comment}”`);
  return parts.join(" · ");
}

/** 감사 기록: 누가 언제 무엇을 했는지. 고칠 수 없고, 변조되면 표시된다. */
export default function AuditPage() {
  const { tenant } = useParams<{ tenant: string }>();
  const tenantQuery = useTenant(tenant);
  const allowed = tenantQuery.data?.actions.includes("audit_log.read") ?? false;
  const log = useAuditLog(tenant, allowed);

  return (
    <div className="space-y-5">
      <PageHeader
        title="감사 기록"
        description="회사 안에서 일어난 변경을 시간순으로 남깁니다. 기록은 추가만 되고, 앞 기록과 이어진 지문으로 변조 여부를 확인합니다."
      />

      {tenantQuery.data && !allowed && (
        <p className="text-sm text-muted-foreground">감사 기록은 관리자만 볼 수 있습니다.</p>
      )}
      {allowed && log.isPending && <Skeleton className="h-48" />}
      {log.error && <ErrorState error={log.error} />}

      {log.data && (
        <>
          {log.data.chain_intact ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/8 px-4 py-2.5 text-sm">
              <ShieldCheckIcon className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              기록이 온전합니다. 전체 기록의 지문을 다시 계산해 확인했습니다.
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/8 px-4 py-2.5 text-sm text-destructive">
              <ShieldAlertIcon className="size-4 shrink-0" />
              기록 #{log.data.broken_at} 부터 지문이 맞지 않습니다. 기록이 변조됐을 수 있습니다.
            </div>
          )}

          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full min-w-xl text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2 font-medium">시각</th>
                  <th className="px-4 py-2 font-medium">사람</th>
                  <th className="px-4 py-2 font-medium">행위</th>
                  <th className="px-4 py-2 font-medium">대상</th>
                </tr>
              </thead>
              <tbody>
                {log.data.entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-2 whitespace-nowrap text-muted-foreground">
                      {formatDateTime(entry.at)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">{entry.actor?.name ?? "—"}</td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      {AUDIT_ACTION_LABEL[entry.action] ?? entry.action}
                    </td>
                    <td className="max-w-80 truncate px-4 py-2 text-muted-foreground">
                      {summarize(entry)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">최근 {log.data.entries.length}건을 보여줍니다.</p>
        </>
      )}
    </div>
  );
}
