"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, EyeIcon, LoaderCircleIcon, PencilIcon, SendIcon, TriangleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/bits";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SectionCitations } from "@/components/docs/revision-view";
import {
  api,
  ApiError,
  type Revision,
  type RevisionRequirement,
  type SectionSpec,
  unwrap,
} from "@/lib/api";
import { CHANGE_KIND_LABEL } from "@/lib/labels";
import { keys } from "@/lib/queries";
import { cn } from "@/lib/utils";

type Draft = {
  title: string;
  bodies: Record<string, string>;
  changeSummary: string;
  changeKind: string;
};

type SaveState = "saved" | "dirty" | "saving" | "error";

const AUTOSAVE_DELAY_MS = 1200;

/**
 * 초안 편집기. 입력을 멈추면 자동 저장한다.
 * 편집 중인 내용이 서버 응답으로 덮이지 않도록, 화면 상태는 처음 한 번만 서버 값으로 채운다.
 * (부모가 key={revision.id} 로 개정판이 바뀔 때 새로 만든다.)
 */
export function RevisionEditor({
  tenant,
  revision,
  schema,
  isFirstRevision,
  canSubmit,
  citations = [],
  onSubmitted,
}: {
  tenant: string;
  revision: Revision;
  schema: SectionSpec[];
  isFirstRevision: boolean;
  canSubmit: boolean;
  /** 섹션별 근거 요건(표준에서 생성한 문서). 본문을 고쳐도 근거 링크는 그대로 남는다. */
  citations?: RevisionRequirement[];
  onSubmitted: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => ({
    title: revision.title,
    bodies: Object.fromEntries(revision.sections.map((s) => [s.key, s.body_md])),
    changeSummary: revision.change_summary,
    changeKind: revision.change_kind,
  }));
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [version, setVersion] = useState(revision.version);
  const [previewing, setPreviewing] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  const latest = useRef(draft);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);
  const dirty = useRef(false);

  const save = useCallback(async (): Promise<void> => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    // 저장이 진행 중이면 끝난 뒤, 그 사이 바뀐 내용이 있으면 한 번 더 저장한다.
    if (inFlight.current) await inFlight.current.catch(() => undefined);
    if (!dirty.current) return;

    dirty.current = false;
    setSaveState("saving");
    const snapshot = latest.current;
    const request = unwrap(
      api.PATCH("/api/t/{tenant_slug}/revisions/{revision_id}", {
        params: { path: { tenant_slug: tenant, revision_id: revision.id } },
        body: {
          title: snapshot.title.trim() || revision.title,
          sections: schema.map((s) => ({
            key: s.key,
            title: s.title,
            body_md: snapshot.bodies[s.key] ?? "",
          })),
          change_summary: snapshot.changeSummary,
          ...(isFirstRevision ? {} : { change_kind: snapshot.changeKind as "minor" | "major" }),
        },
      }),
    ).then(
      (saved) => {
        setVersion(saved.version);
        setSaveState(dirty.current ? "dirty" : "saved");
      },
      (error: unknown) => {
        dirty.current = true;
        setSaveState("error");
        throw error;
      },
    );
    inFlight.current = request.finally(() => {
      inFlight.current = null;
    });
    await inFlight.current;
  }, [tenant, revision.id, revision.title, schema, isFirstRevision]);

  function update(patch: Partial<Draft>) {
    const next = { ...latest.current, ...patch };
    latest.current = next;
    setDraft(next);
    dirty.current = true;
    setSaveState("dirty");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      save().catch(() => undefined);
    }, AUTOSAVE_DELAY_MS);
  }

  // 화면을 떠날 때 남은 변경을 저장하고, 목록·상세 캐시를 새로 받게 한다.
  useEffect(() => {
    return () => {
      save()
        .catch(() => undefined)
        .finally(() => queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) }));
    };
  }, [save, queryClient, tenant]);

  // 저장되지 않은 변경이 있으면 창을 닫기 전에 한 번 확인한다.
  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (dirty.current || inFlight.current) event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // Ctrl/⌘+S 로 바로 저장
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "s" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        save().catch(() => undefined);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [save]);

  async function submit() {
    setSubmitting(true);
    try {
      await save();
      await unwrap(
        api.POST("/api/t/{tenant_slug}/revisions/{revision_id}/submit", {
          params: { path: { tenant_slug: tenant, revision_id: revision.id } },
        }),
      );
      toast.success("검토를 요청했습니다.");
      onSubmitted();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "검토를 요청하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  function togglePreview(key: string) {
    setPreviewing((previous) => {
      const next = new Set(previous);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  const missing = schema.filter((s) => s.required && !(draft.bodies[s.key] ?? "").trim());

  return (
    <div className="space-y-3">
      <div className="grid gap-3 rounded-xl border border-border bg-card px-4 py-4 sm:px-5">
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">제목</span>
          <Input
            value={draft.title}
            onChange={(e) => update({ title: e.target.value })}
            maxLength={300}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-[11rem_1fr]">
          {!isFirstRevision && (
            <label className="grid content-start gap-1.5 text-sm">
              <span className="font-medium">개정 구분</span>
              <NativeSelect
                value={draft.changeKind}
                onChange={(e) => update({ changeKind: e.target.value })}
              >
                <option value="minor">{CHANGE_KIND_LABEL.minor}</option>
                <option value="major">{CHANGE_KIND_LABEL.major}</option>
              </NativeSelect>
              <span className="text-xs text-muted-foreground">승인되면 v{version}</span>
            </label>
          )}
          <label className={cn("grid gap-1.5 text-sm", isFirstRevision && "sm:col-span-2")}>
            <span className="font-medium">변경 요약</span>
            <Textarea
              value={draft.changeSummary}
              onChange={(e) => update({ changeSummary: e.target.value })}
              placeholder="무엇을 왜 바꿨는지 적습니다. 검토자와 개정 이력에 보입니다."
              className="min-h-9"
            />
          </label>
        </div>
      </div>

      {schema.map((spec, index) => {
        const body = draft.bodies[spec.key] ?? "";
        const preview = previewing.has(spec.key);
        return (
          <section
            key={spec.key}
            id={`section-${spec.key}`}
            className="scroll-mt-20 rounded-xl border border-border bg-card px-4 py-4 sm:px-5"
          >
            <div className="mb-2 flex items-center gap-2">
              <h2 className="flex min-w-0 flex-1 items-baseline gap-2 text-base font-semibold">
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  {index + 1}
                </span>
                <span className="truncate">{spec.title}</span>
                {spec.required && (
                  <span className="text-xs font-normal text-muted-foreground">필수</span>
                )}
              </h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => togglePreview(spec.key)}
                aria-pressed={preview}
              >
                {preview ? <PencilIcon /> : <EyeIcon />}
                {preview ? "편집" : "미리보기"}
              </Button>
            </div>
            {spec.hint && <p className="mb-2 text-xs text-muted-foreground">{spec.hint}</p>}
            {preview ? (
              body.trim() ? (
                <Markdown>{body}</Markdown>
              ) : (
                <p className="text-sm text-muted-foreground">내용 없음</p>
              )
            ) : (
              <Textarea
                value={body}
                onChange={(e) => update({ bodies: { ...latest.current.bodies, [spec.key]: e.target.value } })}
                aria-label={spec.title}
                spellCheck={false}
                className="min-h-24 text-[0.9375rem] leading-7"
              />
            )}
            <SectionCitations citations={citations.filter((c) => c.section_key === spec.key)} />
          </section>
        );
      })}

      <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border bg-background/95 px-3 py-2 shadow-lg backdrop-blur md:bottom-4">
        <SaveIndicator state={saveState} onRetry={() => save().catch(() => undefined)} />
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {missing.length > 0 && `비어 있는 필수 섹션: ${missing.map((s) => s.title).join(", ")}`}
        </span>
        {canSubmit && (
          <Button onClick={submit} disabled={submitting || missing.length > 0}>
            <SendIcon />
            검토 요청
          </Button>
        )}
      </div>
    </div>
  );
}

function SaveIndicator({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  if (state === "error") {
    return (
      <button
        type="button"
        onClick={onRetry}
        className="flex items-center gap-1.5 text-sm text-destructive"
      >
        <TriangleAlertIcon className="size-4" />
        저장하지 못했습니다 · 다시 시도
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-sm text-muted-foreground" aria-live="polite">
      {state === "saved" ? (
        <CheckIcon className="size-4 text-emerald-600 dark:text-emerald-400" />
      ) : (
        <LoaderCircleIcon className={cn("size-4", state === "saving" && "animate-spin")} />
      )}
      {state === "saved" ? "저장됨" : state === "saving" ? "저장 중…" : "변경 있음"}
    </span>
  );
}
