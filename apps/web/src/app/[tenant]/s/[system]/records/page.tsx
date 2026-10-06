"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeftIcon, FileUpIcon, LoaderCircleIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { DocCode, EmptyState, ErrorState } from "@/components/bits";
import { ARTIFACT_STATE, RecordCountsNote } from "@/components/records/record-bits";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Artifact, uploadArtifact } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/labels";
import { keys, useArtifacts, useRecords, useSystem, useTenant } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.xlsx,.pptx,.hwpx,.txt,.md";

/** 기록: 기존 산출물을 올려 표준 양식의 기록으로 정리하고, 발행한 기록을 본다. */
export default function RecordsPage() {
  const { tenant, system } = useParams<{ tenant: string; system: string }>();
  const queryClient = useQueryClient();
  const tenantQuery = useTenant(tenant);
  const systemQuery = useSystem(tenant, system);
  const artifacts = useArtifacts(tenant, system);
  const records = useRecords(tenant, system);
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<string | null>(null);

  const canManage = systemQuery.data?.actions.includes("record.manage") ?? false;
  const aiEnabled = tenantQuery.data?.artifact_ai ?? false;
  const pending = (artifacts.data ?? []).filter((a) => a.state !== "published");

  async function upload(files: FileList | null) {
    if (!files) return;
    let done = 0;
    for (const file of Array.from(files)) {
      setUploading(file.name);
      try {
        await uploadArtifact(tenant, system, file);
        done += 1;
      } catch (error) {
        toast.error(`${file.name}: ${error instanceof Error ? error.message : "올리지 못했습니다."}`);
      }
    }
    setUploading(null);
    if (input.current) input.current.value = "";
    if (done > 0) toast.success(`${done}건을 올렸습니다.`);
    await queryClient.invalidateQueries({ queryKey: keys.recordsAll(tenant) });
  }

  return (
    <div className="space-y-8">
      <div>
        <Link
          href={routes.library(tenant, system)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeftIcon className="size-4" />
          {systemQuery.data?.name ?? "체계"}
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">기록</h1>
        <p className="mt-1 text-sm text-muted-foreground text-pretty">
          이미 갖고 있는 산출물을 올리면 이 체계의 기록 양식에 맞춰 정리합니다. 원본 파일은 그대로
          보관하고, 기록의 값마다 원본의 어디에서 왔는지 남깁니다. 원본에 없는 항목은 비워 두고
          사람이 보완합니다.
        </p>
      </div>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="text-sm font-semibold">정리할 산출물</h2>
          {pending.length > 0 && <span className="text-sm text-muted-foreground">{pending.length}</span>}
          {canManage && (
            <>
              <input
                ref={input}
                type="file"
                multiple
                accept={ACCEPT}
                className="sr-only"
                aria-label="산출물 파일"
                onChange={(event) => void upload(event.target.files)}
              />
              <Button
                className="ml-auto"
                disabled={uploading !== null}
                onClick={() => input.current?.click()}
              >
                {uploading ? <LoaderCircleIcon className="animate-spin" /> : <FileUpIcon />}
                {uploading ? `올리는 중 — ${uploading}` : "산출물 올리기"}
              </Button>
            </>
          )}
        </div>

        {tenantQuery.data && !aiEnabled && (
          <p className="rounded-xl border border-border bg-muted/50 px-4 py-2.5 text-sm text-pretty">
            산출물의 AI 처리가 꺼져 있어, 올린 산출물의 양식을 직접 고르고 항목을 직접 채워야
            합니다.{" "}
            {tenantQuery.data.actions.includes("tenant.manage") ? (
              <Link href={routes.settings(tenant)} className="font-medium underline underline-offset-4">
                설정에서 켜기
              </Link>
            ) : (
              "회사 관리자가 설정에서 켤 수 있습니다."
            )}
          </p>
        )}

        {artifacts.isPending && <Skeleton className="h-24" />}
        {artifacts.error && <ErrorState error={artifacts.error} />}
        {artifacts.data && pending.length === 0 && (
          <EmptyState
            icon={<FileUpIcon />}
            title="정리할 산출물이 없습니다"
            description="PDF, DOCX, XLSX, PPTX, HWPX, TXT 파일을 올릴 수 있습니다. 스캔한 이미지는 아직 읽지 못합니다."
          />
        )}
        {pending.length > 0 && (
          <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
            {pending.map((artifact) => (
              <li key={artifact.id}>
                <ArtifactRow tenant={tenant} system={system} artifact={artifact} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">발행한 기록</h2>
          {records.data && <span className="text-sm text-muted-foreground">{records.data.length}</span>}
        </div>
        {records.isPending && <Skeleton className="h-16" />}
        {records.error && <ErrorState error={records.error} />}
        {records.data?.length === 0 && (
          <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            아직 발행한 기록이 없습니다.
          </p>
        )}
        {(records.data?.length ?? 0) > 0 && (
          <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
            {records.data!.map((record) => (
              <li key={record.id}>
                <Link
                  href={record.artifact_id ? routes.artifact(tenant, system, record.artifact_id) : "#"}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-muted/50 sm:px-4"
                >
                  <span className="min-w-0 flex-1 basis-56">
                    <span className="block truncate text-sm font-medium">{record.title}</span>
                    <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <DocCode>{record.code}</DocCode>
                      <span>{record.template.title}</span>
                      {record.performed_on && <span>수행 {formatDate(record.performed_on)}</span>}
                    </span>
                  </span>
                  {record.legacy && (
                    <span
                      className="inline-flex h-5 items-center rounded-md bg-muted px-1.5 text-xs text-muted-foreground"
                      title="표준 양식이 생기기 전의 산출물에서 옮긴 기록입니다"
                    >
                      기존 산출물
                    </span>
                  )}
                  <RecordCountsNote counts={record.counts} />
                  <span className="hidden w-24 shrink-0 text-right text-xs text-muted-foreground md:block">
                    {record.published_at && formatRelative(record.published_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ArtifactRow({ tenant, system, artifact }: { tenant: string; system: string; artifact: Artifact }) {
  const state = ARTIFACT_STATE[artifact.state] ?? ARTIFACT_STATE.needs_template;
  return (
    <Link
      href={routes.artifact(tenant, system, artifact.id)}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-muted/50 sm:px-4"
    >
      <span className="inline-flex h-5 w-12 shrink-0 items-center justify-center rounded-md bg-muted font-mono text-xs uppercase text-muted-foreground">
        {artifact.kind}
      </span>
      <span className="min-w-0 flex-1 basis-56">
        <span className="block truncate text-sm font-medium">{artifact.title || artifact.filename}</span>
        <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span className="truncate">{artifact.filename}</span>
          {artifact.template && (
            <span>
              → {artifact.template.title}
              {artifact.match_confidence !== null && ` (일치도 ${artifact.match_confidence})`}
            </span>
          )}
        </span>
      </span>
      {artifact.record && <RecordCountsNote counts={artifact.record.counts} />}
      <span className={cn("inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-xs font-medium", state.style)}>
        {artifact.state === "processing" && <LoaderCircleIcon className="size-3 animate-spin" />}
        {state.label}
      </span>
      <span className="hidden w-20 shrink-0 text-right text-xs text-muted-foreground md:block">
        {formatRelative(artifact.created_at)}
      </span>
    </Link>
  );
}
