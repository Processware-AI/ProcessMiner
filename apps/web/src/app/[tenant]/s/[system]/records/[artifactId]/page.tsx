"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, ChevronLeftIcon, LoaderCircleIcon, SparklesIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { DocCode, ErrorState, Field, NativeSelect } from "@/components/bits";
import { ARTIFACT_STATE } from "@/components/records/record-bits";
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
import {
  api,
  type ArtifactDetail,
  type ProcessRecord,
  type RecordField,
  type RecordTemplate,
  unwrap,
} from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/labels";
import { keys, useArtifact, useRecord, useRecordTemplates } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/** 산출물 한 건을 기록으로 정리한다: 양식을 정하고, 원본과 나란히 보며 항목을 확인·보완하고, 발행한다. */
export default function ArtifactPage() {
  const { tenant, system, artifactId } = useParams<{
    tenant: string;
    system: string;
    artifactId: string;
  }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const artifact = useArtifact(tenant, artifactId);
  const record = useRecord(tenant, artifact.data?.record?.id ?? null);
  const templates = useRecordTemplates(tenant, system);
  // 기록의 항목을 누르면 그 값이 나온 원본 자리를 보여준다.
  const [focus, setFocus] = useState<{ location: string; quote: string } | null>(null);

  // 처리가 끝나면 기록(초안)이 새로 만들어지거나 바뀌므로 다시 받아온다.
  const runSignature = `${artifact.data?.run?.id}:${artifact.data?.run?.status}`;
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["t", tenant, "records", "record"] });
  }, [queryClient, tenant, runSignature]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: keys.recordsAll(tenant) });
  }
  const path = { tenant_slug: tenant, artifact_id: artifactId };
  const match = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/t/{tenant_slug}/artifacts/{artifact_id}/match", { params: { path } })),
    onSuccess: refresh,
  });
  const setTemplate = useMutation({
    mutationFn: (documentId: string) =>
      unwrap(
        api.PUT("/api/t/{tenant_slug}/artifacts/{artifact_id}/template", {
          params: { path },
          body: { document_id: documentId },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE("/api/t/{tenant_slug}/artifacts/{artifact_id}", { params: { path } })),
    onSuccess: async () => {
      toast.success("산출물을 지웠습니다.");
      router.replace(routes.records(tenant, system));
      await refresh();
    },
  });

  if (artifact.error) return <ErrorState error={artifact.error} />;
  if (!artifact.data) return <Skeleton className="h-64" />;
  const data = artifact.data;
  const can = (action: string) => data.actions.includes(action);
  const state = ARTIFACT_STATE[data.state] ?? ARTIFACT_STATE.needs_template;
  const busy = data.state === "processing";

  return (
    <div className="space-y-5">
      <div>
        <Link
          href={routes.records(tenant, system)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeftIcon className="size-4" />
          기록
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="min-w-0">
            <p className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className={cn("inline-flex h-5 items-center gap-1 rounded-md px-1.5 font-medium", state.style)}>
                {busy && <LoaderCircleIcon className="size-3 animate-spin" />}
                {state.label}
              </span>
              {record.data?.code && <DocCode>{record.data.code}</DocCode>}
              <span className="truncate">{data.filename}</span>
              <span>{Math.max(1, Math.round(data.size_bytes / 1024))}KB</span>
            </p>
            <h1 className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">
              {record.data?.title || data.title || data.filename}
            </h1>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {can("match") && !data.record && (
              <Button variant="outline" disabled={match.isPending} onClick={() => match.mutate()}>
                <SparklesIcon />
                AI 로 양식 찾기
              </Button>
            )}
            {can("delete") && (
              <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
                <Trash2Icon />
                삭제
              </Button>
            )}
          </div>
        </div>
      </div>

      {busy && data.run && (
        <div className="space-y-1.5 rounded-xl border border-border bg-card px-4 py-3">
          <p className="flex items-center gap-2 text-sm">
            <LoaderCircleIcon className="size-4 animate-spin text-primary" />
            {data.run.progress.step === "normalize" || data.template
              ? "원본에서 항목 값을 옮기고 있습니다"
              : "어느 양식의 기록인지 찾고 있습니다"}
          </p>
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {data.run.events.slice(-3).map((event, index) => (
              <li key={index}>{event}</li>
            ))}
          </ul>
        </div>
      )}
      {!busy && data.run?.status === "failed" && (
        <Note tone="error">처리하지 못했습니다: {data.run.error}</Note>
      )}

      {data.state !== "published" && !busy && (
        <TemplatePicker
          key={data.template?.id ?? "none"}
          artifact={data}
          templates={templates.data ?? []}
          canSet={can("set_template")}
          pending={setTemplate.isPending}
          onSet={(id) => setTemplate.mutate(id)}
        />
      )}

      <div className={cn("grid gap-4", record.data && "lg:grid-cols-2")}>
        <Original segments={data.segments} focus={focus} narrow={Boolean(record.data)} />
        {record.data && (
          <RecordForm
            key={`${record.data.id}:${record.data.created_at}:${record.data.fields.length}:${runSignature}`}
            tenant={tenant}
            record={record.data}
            onFocus={setFocus}
            onChanged={refresh}
          />
        )}
      </div>
    </div>
  );
}

function Note({ tone, children }: { tone: "info" | "warn" | "error"; children: ReactNode }) {
  const styles = {
    info: "border-border bg-muted/50",
    warn: "border-amber-500/30 bg-amber-500/8",
    error: "border-destructive/30 bg-destructive/5 text-destructive",
  };
  return <p className={cn("rounded-xl border px-4 py-2.5 text-sm text-pretty", styles[tone])}>{children}</p>;
}

// ── 양식 ─────────────────────────────────────────────────────────────────────

function TemplatePicker({
  artifact,
  templates,
  canSet,
  pending,
  onSet,
}: {
  artifact: ArtifactDetail;
  templates: RecordTemplate[];
  canSet: boolean;
  pending: boolean;
  onSet: (documentId: string) => void;
}) {
  const [picked, setPicked] = useState(artifact.template?.id ?? "");
  const proposal = artifact.candidates.find((c) => c.document.id === artifact.template?.id);
  const chosen = templates.find((t) => t.document.id === picked);
  const confirmed = artifact.match_state === "confirmed" && artifact.record;
  const unchanged = picked === artifact.template?.id && Boolean(artifact.record);

  return (
    <section className="space-y-3 rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-sm font-semibold">기록 양식</h2>
        <span className="text-xs text-muted-foreground">이 산출물이 어느 양식의 기록인지 정합니다</span>
      </div>

      {artifact.state === "needs_confirm" && proposal && (
        <Note tone="warn">
          AI 제안: <b className="font-medium">{proposal.document.title}</b> (일치도 {proposal.confidence})
          — {proposal.reason} 일치도가 높지 않아 확인이 필요합니다.
        </Note>
      )}
      {artifact.state === "needs_template" && artifact.run?.status === "succeeded" && (
        <Note tone="info">알맞은 양식을 찾지 못했습니다. 아래에서 직접 고르세요.</Note>
      )}

      {artifact.candidates.length > 0 && (
        <ul className="space-y-1.5">
          {artifact.candidates.map((candidate) => (
            <li key={candidate.document.id}>
              <button
                type="button"
                disabled={!canSet}
                onClick={() => setPicked(candidate.document.id)}
                className={cn(
                  "flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border px-3 py-2 text-left text-sm",
                  picked === candidate.document.id
                    ? "border-primary/50 bg-primary/5"
                    : "border-border hover:bg-muted/50",
                )}
              >
                <span className="font-medium">{candidate.document.title}</span>
                <DocCode>{candidate.document.code}</DocCode>
                <span className="text-xs text-muted-foreground tabular-nums">일치도 {candidate.confidence}</span>
                <span className="basis-full text-xs text-muted-foreground">{candidate.reason}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {canSet && (
        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect
            value={picked}
            onChange={(event) => setPicked(event.target.value)}
            aria-label="기록 양식"
            className="min-w-0 flex-1 basis-64"
          >
            <option value="">양식 선택</option>
            {templates.map((template) => (
              <option key={template.document.id} value={template.document.id}>
                {template.document.title} · {template.instruction} ({template.document.code})
              </option>
            ))}
          </NativeSelect>
          <Button disabled={!picked || pending || unchanged} onClick={() => onSet(picked)}>
            {confirmed ? "이 양식으로 다시 옮기기" : "이 양식으로 정하기"}
          </Button>
        </div>
      )}
      {templates.length === 0 && (
        <p className="text-sm text-muted-foreground">
          이 체계에 기록 양식(템플릿)이 없습니다. 먼저 템플릿 문서를 만드세요.
        </p>
      )}
      {chosen && !chosen.approved && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          아직 승인되지 않은 양식입니다(v{chosen.version} 작성 중). 기록에는 이 판의 항목이 그대로
          고정됩니다.
        </p>
      )}
    </section>
  );
}

// ── 원본 ─────────────────────────────────────────────────────────────────────

function Original({
  segments,
  focus,
  narrow,
}: {
  segments: ArtifactDetail["segments"];
  focus: { location: string; quote: string } | null;
  narrow: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focus) return;
    container.current
      ?.querySelector(`[data-loc="${CSS.escape(focus.location)}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  return (
    <section
      className={cn(
        "flex min-w-0 flex-col rounded-xl border border-border bg-card",
        narrow && "max-h-96 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)]",
      )}
    >
      <h2 className="border-b border-border px-4 py-2.5 text-sm font-semibold">
        원본 <span className="font-normal text-muted-foreground">· 올린 파일에서 읽은 내용</span>
      </h2>
      <div ref={container} className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        {segments.map((segment, index) => {
          const active = focus?.location === segment.loc;
          return (
            <div
              key={index}
              data-loc={segment.loc}
              className={cn("rounded-lg px-2 py-1.5", active && "bg-amber-500/12 ring-1 ring-amber-500/40")}
            >
              <span className="font-mono text-[11px] text-muted-foreground">{segment.loc}</span>
              <p className="text-sm leading-6 break-words whitespace-pre-wrap">
                {active ? <Highlighted text={segment.text} quote={focus.quote} /> : segment.text}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Highlighted({ text, quote }: { text: string; quote: string }) {
  const at = quote ? text.indexOf(quote) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded bg-amber-400/50 px-0.5 text-foreground">{quote}</mark>
      {text.slice(at + quote.length)}
    </>
  );
}

// ── 기록 ─────────────────────────────────────────────────────────────────────

const SOURCE_CHIP = {
  original: { label: "원본", style: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" },
  check: { label: "확인 필요", style: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  confirmed: { label: "원본 · 사람 확인", style: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" },
  human: { label: "사람 입력", style: "bg-sky-500/12 text-sky-700 dark:text-sky-300" },
  empty: { label: "비어 있음", style: "bg-muted text-muted-foreground" },
};

function chipOf(field: RecordField) {
  if (field.source === "empty") return SOURCE_CHIP.empty;
  if (field.source === "human") return SOURCE_CHIP.human;
  if (field.needs_check) return SOURCE_CHIP.check;
  return field.verified ? SOURCE_CHIP.original : SOURCE_CHIP.confirmed;
}

function RecordForm({
  tenant,
  record,
  onFocus,
  onChanged,
}: {
  tenant: string;
  record: ProcessRecord;
  onFocus: (focus: { location: string; quote: string }) => void;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const canEdit = record.actions.includes("edit");
  const [title, setTitle] = useState(record.title);
  const [performedOn, setPerformedOn] = useState(record.performed_on ?? "");
  const [confirming, setConfirming] = useState(false);
  const path = { tenant_slug: tenant, record_id: record.id };

  const save = useMutation({
    mutationFn: (body: {
      title?: string;
      performed_on?: string | null;
      fields?: { name: string; value: string }[];
      confirm?: string[];
    }) =>
      unwrap(
        api.PATCH("/api/t/{tenant_slug}/records/{record_id}", {
          params: { path },
          body: { fields: [], confirm: [], ...body },
        }),
      ),
    onSuccess: async (updated) => {
      queryClient.setQueryData(keys.record(tenant, record.id), updated);
      await onChanged();
    },
  });
  const publish = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/t/{tenant_slug}/records/{record_id}/publish", { params: { path } })),
    onSuccess: async (published) => {
      setConfirming(false);
      queryClient.setQueryData(keys.record(tenant, record.id), published);
      toast.success(`${published.code} 로 발행했습니다.`);
      await onChanged();
    },
  });

  const { counts } = record;
  return (
    <section className="min-w-0 space-y-3">
      <div className="space-y-3 rounded-xl border border-border bg-card px-4 py-3">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{record.template.title}</span>
          <DocCode>{record.template.code}</DocCode>
          <span>양식 v{record.template_version}</span>
          {!record.template_approved && <span className="text-amber-700 dark:text-amber-300">승인 전 양식</span>}
          {record.generated_by && <span>· AI 가 원본에서 옮김</span>}
        </p>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_11rem]">
          <Field label="기록 제목">
            <Input
              value={title}
              disabled={!canEdit}
              maxLength={300}
              onChange={(event) => setTitle(event.target.value)}
              onBlur={() => title.trim() !== record.title && save.mutate({ title })}
            />
          </Field>
          <Field label="수행한 날" hint="원본의 업무를 한 날">
            <Input
              type="date"
              value={performedOn}
              disabled={!canEdit}
              onChange={(event) => setPerformedOn(event.target.value)}
              onBlur={() =>
                performedOn !== (record.performed_on ?? "") &&
                save.mutate({ performed_on: performedOn || null })
              }
            />
          </Field>
        </div>
      </div>

      <ul className="space-y-2">
        {record.fields.map((field) => (
          <li key={field.name}>
            <FieldCard
              field={field}
              canEdit={canEdit}
              pending={save.isPending}
              onFocus={onFocus}
              onSave={(value) => save.mutate({ fields: [{ name: field.name, value }] })}
              onConfirm={() => save.mutate({ confirm: [field.name] })}
            />
          </li>
        ))}
      </ul>

      <div className="sticky bottom-20 z-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-sm backdrop-blur md:bottom-4">
        {record.status === "published" ? (
          <p className="flex min-w-0 flex-1 items-center gap-2 text-sm">
            <CheckIcon className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span className="min-w-0">
              <span className="font-mono">{record.code}</span> ·{" "}
              {record.published_at && formatDateTime(record.published_at)} {record.published_by?.name}{" "}
              발행. 발행한 기록은 바뀌지 않습니다.
            </span>
          </p>
        ) : (
          <>
            <p className="min-w-0 flex-1 basis-56 text-sm text-pretty">
              항목 {counts.total}개
              {counts.unverified > 0 && (
                <span className="text-amber-700 dark:text-amber-300"> · 확인 필요 {counts.unverified}</span>
              )}
              {counts.empty > 0 && <span className="text-muted-foreground"> · 빈 항목 {counts.empty}</span>}
              {counts.unverified > 0 && (
                <span className="block text-xs text-muted-foreground">
                  원본에서 찾지 못한 값은 원본을 보고 확인하거나 고쳐야 발행할 수 있습니다.
                </span>
              )}
            </p>
            {canEdit && (
              <Button disabled={!record.actions.includes("publish")} onClick={() => setConfirming(true)}>
                기록으로 발행
              </Button>
            )}
          </>
        )}
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>기록으로 발행</DialogTitle>
            <DialogDescription>
              발행하면 기록 번호가 발급되고, 이후에는 내용을 바꿀 수 없습니다.
              {counts.empty > 0 && ` 빈 항목 ${counts.empty}개는 빈 채로 남습니다(원본에 없는 내용).`}
              {!record.template_approved &&
                " 이 기록은 아직 승인되지 않은 양식을 기준으로 합니다."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              취소
            </Button>
            <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
              발행
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function FieldCard({
  field,
  canEdit,
  pending,
  onFocus,
  onSave,
  onConfirm,
}: {
  field: RecordField;
  canEdit: boolean;
  pending: boolean;
  onFocus: (focus: { location: string; quote: string }) => void;
  onSave: (value: string) => void;
  onConfirm: () => void;
}) {
  const [value, setValue] = useState(field.value);
  const [seen, setSeen] = useState(field.value);
  // 저장하거나 다시 옮긴 뒤 서버의 값이 바뀌면 입력란도 따라간다.
  if (seen !== field.value) {
    setSeen(field.value);
    setValue(field.value);
  }
  const chip = chipOf(field);

  return (
    <div
      className={cn(
        "space-y-1.5 rounded-xl border bg-card px-3 py-2.5",
        field.needs_check
          ? "border-amber-500/40"
          : field.source === "empty"
            ? "border-dashed border-border"
            : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 text-sm font-medium">{field.name}</span>
        <span className={cn("inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium", chip.style)}>
          {chip.label}
        </span>
      </div>
      {canEdit ? (
        <Textarea
          value={value}
          rows={Math.min(6, Math.max(1, Math.ceil(value.length / 44)))}
          aria-label={field.name}
          placeholder="원본에 없는 항목입니다. 알고 있는 내용을 적거나 비워 두세요."
          onChange={(event) => setValue(event.target.value)}
          onBlur={() => value.trim() !== field.value && onSave(value)}
        />
      ) : (
        <p className="text-sm leading-6 break-words whitespace-pre-wrap">
          {field.value || <span className="text-muted-foreground">—</span>}
        </p>
      )}
      {field.quote && field.source === "artifact" && (
        <button
          type="button"
          onClick={() => onFocus({ location: field.location, quote: field.quote })}
          className="block w-full text-left text-xs text-muted-foreground hover:text-foreground"
          title="원본에서 이 자리 보기"
        >
          <span className="font-mono">{field.location || "위치 모름"}</span> · “{field.quote}”
        </button>
      )}
      {field.needs_check && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-amber-700 dark:text-amber-300">
          <span className="min-w-0 flex-1 basis-48 text-pretty">
            이 구절을 원본에서 찾지 못했습니다. 원본을 보고 값이 맞는지 확인하거나 고치세요.
          </span>
          {canEdit && (
            <Button size="sm" variant="outline" disabled={pending} onClick={onConfirm}>
              원본과 맞음
            </Button>
          )}
        </div>
      )}
      {field.source === "human" && field.filled_by && (
        <p className="text-xs text-muted-foreground">
          {field.filled_by.name} 입력{field.filled_at && ` · ${formatRelative(field.filled_at)}`}
          {field.original_value && ` · 원본에서 옮겼던 값: ${field.original_value}`}
        </p>
      )}
      {field.confirmed_by && field.source === "artifact" && (
        <p className="text-xs text-muted-foreground">{field.confirmed_by.name} 확인</p>
      )}
    </div>
  );
}
