"use client";

import { useMutation, useQueries } from "@tanstack/react-query";
import { PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Field, NativeSelect, TypeBadge } from "@/components/bits";
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
import { api, type Plan, unwrap } from "@/lib/api";
import { basisRequirementsQuery } from "@/lib/queries";
import { cn } from "@/lib/utils";

type DocType = "POL" | "PRO" | "WI";

/** 편집 중인 문서 하나. 템플릿은 지침에 딸린 이름 목록으로 다룬다. */
type Draft = {
  id: string;
  type: DocType;
  parentId: string | null;
  title: string;
  purpose: string;
  note: string;
  requirements: string[];
  templates: string[];
};

const CHILD: Record<DocType, { type: DocType; label: string; title: string } | null> = {
  POL: { type: "PRO", label: "절차 추가", title: "새 절차" },
  PRO: { type: "WI", label: "지침 추가", title: "새 지침" },
  WI: null,
};
const UNASSIGNED = "__unassigned";
const MAX_TEMPLATES = 3;

function fromPlan(plan: Plan): Draft[] {
  const drafts: Draft[] = [];
  for (const node of plan.nodes) {
    if (node.doc_type === "TMP") {
      drafts.find((d) => d.id === node.parent)?.templates.push(node.title);
    } else {
      drafts.push({
        id: node.path,
        type: node.doc_type as DocType,
        parentId: node.parent,
        title: node.title,
        purpose: node.purpose,
        note: node.integration_note,
        requirements: [...node.requirements],
        templates: [],
      });
    }
  }
  return drafts;
}

/** 상위 문서 다음에 하위 문서가 오는 순서로 편다. */
function ordered(drafts: Draft[]): { draft: Draft; depth: number }[] {
  const rows: { draft: Draft; depth: number }[] = [];
  const walk = (parentId: string | null, depth: number) => {
    for (const draft of drafts.filter((d) => d.parentId === parentId)) {
      rows.push({ draft, depth });
      walk(draft.id, depth + 1);
    }
  };
  walk(null, 0);
  return rows;
}

function toPayload(drafts: Draft[]) {
  const under = (parentId: string | null) => drafts.filter((d) => d.parentId === parentId);
  return {
    policies: under(null).map((policy) => ({
      title: policy.title,
      purpose: policy.purpose,
      requirements: policy.requirements,
      procedures: under(policy.id).map((procedure) => ({
        title: procedure.title,
        purpose: procedure.purpose,
        requirements: procedure.requirements,
        integration_note: procedure.note,
        instructions: under(procedure.id).map((instruction) => ({
          title: instruction.title,
          purpose: instruction.purpose,
          requirements: instruction.requirements,
          integration_note: instruction.note,
          templates: instruction.templates.map((t) => t.trim()).filter(Boolean),
        })),
      })),
    })),
  };
}

/**
 * 설계안을 사람이 고친다: 문서 이름과 구성, 요건이 어느 문서에 배정되는지.
 * 문서를 생성하기 전에만 열 수 있고, 저장하기 전에는 아무것도 바뀌지 않는다.
 */
export function PlanEditorDialog({
  tenant,
  system,
  plan,
  open,
  onOpenChange,
  onSaved,
}: {
  tenant: string;
  system: string;
  plan: Plan;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  return (
    // 고치던 내용을 잃지 않도록 바깥을 눌러서는 닫히지 않게 한다.
    <Dialog open={open} onOpenChange={onOpenChange} disablePointerDismissal>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-5xl">
        {open && (
          <PlanEditor
            tenant={tenant}
            system={system}
            plan={plan}
            onClose={() => onOpenChange(false)}
            onSaved={onSaved}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function PlanEditor({
  tenant,
  system,
  plan,
  onClose,
  onSaved,
}: {
  tenant: string;
  system: string;
  plan: Plan;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState(() => fromPlan(plan));
  const [selected, setSelected] = useState<string>(() => plan.nodes[0]?.path ?? UNASSIGNED);
  const [nextId, setNextId] = useState(1);

  // 요건의 요약과, 이 설계안이 배정해야 하는 요건 전체(제외한 요건은 뺀다).
  const results = useQueries({
    queries: plan.sources.map((source) => basisRequirementsQuery(tenant, system, source.id)),
  });
  const loading = results.some((result) => result.isPending);
  const summaries = new Map<string, string>();
  plan.sources.forEach((source, index) => {
    for (const requirement of results[index]?.data ?? []) {
      if (!requirement.excluded) summaries.set(`${source.code} ${requirement.code}`, requirement.summary);
    }
  });
  const assigned = new Set(drafts.flatMap((d) => d.requirements));
  const unassigned = loading ? plan.uncovered : [...summaries.keys()].filter((code) => !assigned.has(code));

  const rows = useMemo(() => ordered(drafts), [drafts]);
  const current = drafts.find((d) => d.id === selected);
  const blank = drafts.some((d) => !d.title.trim());

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/api/t/{tenant_slug}/systems/{system_slug}/plans/{plan_id}", {
          params: { path: { tenant_slug: tenant, system_slug: system, plan_id: plan.id } },
          body: toPayload(drafts),
        }),
      ),
    onSuccess: async () => {
      toast.success("설계안을 저장했습니다.");
      await onSaved();
      onClose();
    },
  });

  function update(id: string, patch: Partial<Draft>) {
    setDrafts((list) => list.map((d) => (d.id === id ? { ...d, ...patch } : d)));
  }

  function add(type: DocType, parentId: string | null, title: string) {
    const id = `new-${nextId}`;
    setNextId(nextId + 1);
    setDrafts((list) => [
      ...list,
      { id, type, parentId, title, purpose: "", note: "", requirements: [], templates: [] },
    ]);
    setSelected(id);
  }

  /** 문서와 그 아래 문서를 모두 지운다. 배정돼 있던 요건은 미배정이 된다. */
  function remove(id: string) {
    const doomed = new Set([id]);
    for (const { draft } of rows) if (draft.parentId && doomed.has(draft.parentId)) doomed.add(draft.id);
    const parent = drafts.find((d) => d.id === id)?.parentId;
    setDrafts((list) => list.filter((d) => !doomed.has(d.id)));
    setSelected(parent ?? drafts.find((d) => !doomed.has(d.id))?.id ?? UNASSIGNED);
  }

  function move(code: string, targetId: string) {
    setDrafts((list) =>
      list.map((d) => {
        const without = d.requirements.filter((c) => c !== code);
        return { ...d, requirements: d.id === targetId ? [...without, code] : without };
      }),
    );
  }

  const targets = rows.map(({ draft, depth }) => ({
    id: draft.id,
    label: `${"　".repeat(depth)}[${draft.type}] ${draft.title || "(제목 없음)"}`,
  }));

  return (
    <div className="grid min-w-0 gap-4">
      <DialogHeader>
        <DialogTitle>설계안 고치기</DialogTitle>
        <DialogDescription>
          문서의 이름과 구성, 요건이 어느 문서에 배정되는지를 바꿉니다. 저장하기 전에는 아무것도
          바뀌지 않습니다. 모든 요건이 문서에 배정돼야 문서를 생성할 수 있습니다.
        </DialogDescription>
      </DialogHeader>

      <div className="grid min-w-0 gap-4 md:h-[60dvh] md:grid-cols-[19rem_minmax(0,1fr)]">
        {/* 문서 구성 */}
        <div className="flex min-h-0 flex-col rounded-lg border border-border">
          <ul className="max-h-56 min-h-0 flex-1 overflow-y-auto p-1 md:max-h-none">
            {(unassigned.length > 0 || selected === UNASSIGNED) && (
              <li>
                <button
                  type="button"
                  onClick={() => setSelected(UNASSIGNED)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-amber-700 dark:text-amber-300",
                    selected === UNASSIGNED ? "bg-amber-500/15" : "hover:bg-muted",
                  )}
                >
                  <span className="min-w-0 flex-1 font-medium">배정되지 않은 요건</span>
                  <span className="text-xs">{unassigned.length}</span>
                </button>
              </li>
            )}
            {rows.map(({ draft, depth }) => (
              <li key={draft.id}>
                <button
                  type="button"
                  onClick={() => setSelected(draft.id)}
                  aria-current={selected === draft.id}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-sm",
                    selected === draft.id ? "bg-primary/10" : "hover:bg-muted",
                  )}
                  style={{ paddingLeft: `${0.5 + depth * 0.875}rem` }}
                >
                  <TypeBadge type={draft.type} />
                  <span className={cn("min-w-0 flex-1 truncate", !draft.title.trim() && "text-destructive")}>
                    {draft.title.trim() || "(제목 없음)"}
                  </span>
                  {draft.requirements.length > 0 && (
                    <span className="text-xs text-muted-foreground">{draft.requirements.length}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-border p-1.5">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start"
              onClick={() => add("POL", null, "새 정책")}
            >
              <PlusIcon />
              정책 추가
            </Button>
          </div>
        </div>

        {/* 고른 문서 */}
        <div className="min-h-0 min-w-0 overflow-y-auto md:pr-1">
          {selected === UNASSIGNED || !current ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground text-pretty">
                {unassigned.length > 0
                  ? "아래 요건은 어느 문서에도 배정되지 않았습니다. 이행할 문서를 골라 배정하세요."
                  : "모든 요건이 문서에 배정돼 있습니다."}
              </p>
              <RequirementList
                codes={unassigned}
                summaries={summaries}
                loading={loading}
                targets={targets}
                placeholder="배정할 문서"
                onMove={move}
              />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <TypeBadge type={current.type} />
                <span className="flex-1" />
                {CHILD[current.type] && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => add(CHILD[current.type]!.type, current.id, CHILD[current.type]!.title)}
                  >
                    <PlusIcon />
                    {CHILD[current.type]!.label}
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => remove(current.id)}>
                  <Trash2Icon />
                  {rows.some((r) => r.draft.parentId === current.id) ? "하위 문서와 함께 삭제" : "삭제"}
                </Button>
              </div>

              <Field label="제목">
                <Input
                  value={current.title}
                  onChange={(event) => update(current.id, { title: event.target.value })}
                  maxLength={200}
                  aria-invalid={!current.title.trim()}
                />
              </Field>
              <Field label="다루는 범위" hint="문서를 쓸 때 모델에 전달됩니다.">
                <Textarea
                  value={current.purpose}
                  onChange={(event) => update(current.id, { purpose: event.target.value })}
                  rows={2}
                  maxLength={1000}
                />
              </Field>
              {current.type !== "POL" && (plan.sources.length > 1 || current.note) && (
                <Field
                  label="통합 방향"
                  hint="여러 표준의 요건이 이 문서에서 어떻게 맞물리는지. 문서를 쓸 때 모델에 전달됩니다."
                >
                  <Textarea
                    value={current.note}
                    onChange={(event) => update(current.id, { note: event.target.value })}
                    rows={2}
                    maxLength={1000}
                  />
                </Field>
              )}

              {current.type === "WI" && (
                <div className="grid gap-1.5 text-sm">
                  <span className="font-medium">기록 양식 (템플릿)</span>
                  {current.templates.map((template, index) => (
                    <div key={index} className="flex gap-2">
                      <Input
                        value={template}
                        onChange={(event) =>
                          update(current.id, {
                            templates: current.templates.map((t, i) => (i === index ? event.target.value : t)),
                          })
                        }
                        maxLength={200}
                        aria-label={`기록 양식 ${index + 1}`}
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="기록 양식 삭제"
                        onClick={() =>
                          update(current.id, { templates: current.templates.filter((_, i) => i !== index) })
                        }
                      >
                        <XIcon />
                      </Button>
                    </div>
                  ))}
                  {current.templates.length < MAX_TEMPLATES && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="justify-self-start"
                      onClick={() => update(current.id, { templates: [...current.templates, ""] })}
                    >
                      <PlusIcon />
                      양식 추가
                    </Button>
                  )}
                </div>
              )}

              <div className="grid gap-1.5 text-sm">
                <span className="font-medium">배정된 요건 {current.requirements.length}건</span>
                <RequirementList
                  codes={current.requirements}
                  summaries={summaries}
                  loading={loading}
                  targets={targets.filter((t) => t.id !== current.id)}
                  placeholder="다른 문서로 옮기기"
                  onMove={move}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <DialogFooter className="items-center">
        <span
          className={cn(
            "min-w-0 flex-1 text-sm text-pretty",
            blank || unassigned.length > 0 ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground",
          )}
        >
          {blank
            ? "제목이 빈 문서가 있습니다."
            : unassigned.length > 0
              ? `배정되지 않은 요건이 ${unassigned.length}건 있습니다. 저장은 되지만 문서를 생성하려면 모두 배정해야 합니다.`
              : "모든 요건이 배정돼 있습니다."}
        </span>
        <Button variant="outline" onClick={onClose} disabled={save.isPending}>
          취소
        </Button>
        <Button
          onClick={() => save.mutate()}
          disabled={save.isPending || blank || loading || !drafts.some((d) => d.type === "POL")}
        >
          저장
        </Button>
      </DialogFooter>
    </div>
  );
}

function RequirementList({
  codes,
  summaries,
  loading,
  targets,
  placeholder,
  onMove,
}: {
  codes: string[];
  summaries: Map<string, string>;
  loading: boolean;
  targets: { id: string; label: string }[];
  placeholder: string;
  onMove: (code: string, targetId: string) => void;
}) {
  if (codes.length === 0) {
    return <p className="text-sm text-muted-foreground">배정된 요건이 없습니다.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {codes.map((code) => (
        <li key={code} className="flex flex-wrap items-start gap-x-3 gap-y-1.5 px-3 py-2 text-sm">
          <div className="min-w-0 flex-1 basis-64 leading-6">
            <span className="mr-1.5 font-mono text-xs text-muted-foreground">{code}</span>
            {loading ? <Skeleton className="inline-block h-3 w-40 align-middle" /> : summaries.get(code)}
          </div>
          <NativeSelect
            value=""
            onChange={(event) => event.target.value && onMove(code, event.target.value)}
            aria-label={`${code} ${placeholder}`}
            className="w-44 shrink-0"
          >
            <option value="">{placeholder}</option>
            {targets.map((target) => (
              <option key={target.id} value={target.id}>
                {target.label}
              </option>
            ))}
          </NativeSelect>
        </li>
      ))}
    </ul>
  );
}
