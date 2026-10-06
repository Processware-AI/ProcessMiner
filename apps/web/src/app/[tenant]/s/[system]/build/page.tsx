"use client";

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  ChevronLeftIcon,
  CircleAlertIcon,
  LayersIcon,
  LoaderCircleIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, Field, LinkButton, NativeSelect, TypeBadge } from "@/components/bits";
import { PlanEditorDialog } from "@/components/plans/plan-editor";
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
import { api, type BasisItem, type BasisRequirement, type Plan, type PlanNode, unwrap } from "@/lib/api";
import { formatDate, OBLIGATION_LABEL, OBLIGATION_STYLE } from "@/lib/labels";
import {
  basisRequirementsQuery,
  keys,
  useBasis,
  useBasisRequirements,
  usePlans,
  useScopeCodes,
  useSystem,
} from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

const isBusy = (plan: Plan) => plan.run?.status === "queued" || plan.run?.status === "running";

/** 표준에서 문서 만들기: 근거 원문 선택 → 적용요건 승인 → 구조 설계 → 문서 생성. */
export default function BuildPage() {
  const { tenant, system } = useParams<{ tenant: string; system: string }>();
  const queryClient = useQueryClient();
  const systemQuery = useSystem(tenant, system);
  const basis = useBasis(tenant, system);
  const plans = usePlans(tenant, system);

  // 설계안의 상태가 바뀌면 근거 쪽에서 할 수 있는 일도 달라지고, 문서가 생기면 목록도 바뀐다.
  const planSignature = (plans.data ?? []).map((p) => `${p.id}:${p.status}:${p.run?.status}`).join();
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: keys.basis(tenant, system) });
    void queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) });
  }, [queryClient, tenant, system, planSignature]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["t", tenant, "build", system] });
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
        <h1 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
          표준에서 문서 만들기
        </h1>
        <p className="mt-1 text-sm text-muted-foreground text-pretty">
          확정한 요건 가운데 이 체계에 적용할 것을 정해 승인하면, 그 요건을 근거로 문서 구조를
          설계하고 초안을 생성합니다. 생성된 문서는 초안이며 사람의 검토와 승인을 거쳐야 기준이
          됩니다.
        </p>
      </div>

      <section className="space-y-3">
        <StepHeading number={1} title="근거와 적용요건" />
        {basis.isPending && <Skeleton className="h-24" />}
        {basis.error && <ErrorState error={basis.error} />}
        {basis.data && (
          <BasisSection
            tenant={tenant}
            system={system}
            basis={basis.data}
            onChanged={refresh}
          />
        )}
      </section>

      <section className="space-y-3">
        <StepHeading number={2} title="문서 구조와 생성" />
        {plans.isPending && <Skeleton className="h-24" />}
        {plans.error && <ErrorState error={plans.error} />}
        {plans.data?.length === 0 && (
          <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            적용요건을 승인한 뒤 위에서 “문서 구조 설계”를 시작하면 설계안이 여기에 나타납니다.
            표준을 여러 개 승인하면 하나의 문서 체계로 통합해 설계할 수 있습니다.
          </p>
        )}
        {plans.data?.map((plan) => (
          <PlanCard key={plan.id} tenant={tenant} system={system} plan={plan} onChanged={refresh} />
        ))}
      </section>
    </div>
  );
}

function StepHeading({ number, title }: { number: number; title: string }) {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold">
      <span className="grid size-5 place-content-center rounded-full bg-primary text-[11px] text-primary-foreground">
        {number}
      </span>
      {title}
    </h2>
  );
}

// ── 1. 근거 ──────────────────────────────────────────────────────────────────

function BasisSection({
  tenant,
  system,
  basis,
  onChanged,
}: {
  tenant: string;
  system: string;
  basis: NonNullable<ReturnType<typeof useBasis>["data"]>;
  onChanged: () => Promise<void>;
}) {
  const [picked, setPicked] = useState("");
  const [reviewing, setReviewing] = useState<BasisItem | null>(null);
  const [designing, setDesigning] = useState(false);
  const path = { tenant_slug: tenant, system_slug: system };

  const attach = useMutation({
    mutationFn: (sourceId: string) =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/basis", {
          params: { path },
          body: { source_id: sourceId },
        }),
      ),
    onSuccess: async () => {
      setPicked("");
      await onChanged();
    },
  });
  const act = useMutation({
    mutationFn: ({ sourceId, action }: { sourceId: string; action: "approve" | "reopen" | "detach" }) => {
      const params = { path: { ...path, source_id: sourceId } };
      if (action === "detach") {
        return unwrap(
          api.DELETE("/api/t/{tenant_slug}/systems/{system_slug}/basis/{source_id}", { params }),
        );
      }
      return unwrap(
        action === "approve"
          ? api.POST("/api/t/{tenant_slug}/systems/{system_slug}/basis/{source_id}/approve", { params })
          : api.POST("/api/t/{tenant_slug}/systems/{system_slug}/basis/{source_id}/reopen", { params }),
      );
    },
    onSuccess: onChanged,
  });

  const canAttach = basis.actions.includes("attach");
  // 승인됐고 아직 설계안에 쓰이지 않은 근거. 여럿이면 한 설계안으로 통합할 수 있다.
  const designable = basis.items.filter((item) => item.actions.includes("design"));

  return (
    <div className="space-y-3">
      {basis.items.length === 0 && basis.available.length === 0 && (
        <EmptyState
          title="근거로 삼을 원문이 없습니다"
          description="먼저 표준·법규 원문을 올려 요건을 도출하고 확정하세요."
          action={<LinkButton href={routes.sources(tenant)}>원문과 요건으로</LinkButton>}
        />
      )}

      {basis.items.map((item) => {
        const applicable = item.total - item.excluded;
        const can = (action: string) => item.actions.includes(action);
        return (
          <div key={item.source.id} className="rounded-xl border border-border bg-card px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{item.source.title}</p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-mono">{item.source.code}</span>
                  {item.source.edition && ` · ${item.source.edition}`} · 적용 {applicable}건
                  {item.excluded > 0 && ` · 제외 ${item.excluded}건`}
                </p>
              </div>
              {item.approved_at ? (
                <span className="flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
                  <CheckIcon className="size-3.5" />
                  {formatDate(item.approved_at)} {item.approved_by?.name} 승인
                </span>
              ) : (
                <span className="text-xs text-amber-700 dark:text-amber-300">승인 전</span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setReviewing(item)}>
                {can("review") ? "적용요건 검토" : "적용요건 보기"}
              </Button>
              {can("approve") && (
                <Button
                  size="sm"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ sourceId: item.source.id, action: "approve" })}
                >
                  <ShieldCheckIcon />
                  적용요건 승인
                </Button>
              )}
              {can("reopen") && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ sourceId: item.source.id, action: "reopen" })}
                >
                  승인 취소
                </Button>
              )}
              {can("detach") && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ sourceId: item.source.id, action: "detach" })}
                >
                  근거에서 빼기
                </Button>
              )}
            </div>
          </div>
        );
      })}

      {designable.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
          <p className="min-w-0 flex-1 basis-60 text-sm text-pretty">
            {designable.length > 1
              ? `승인한 표준 ${designable.length}개(${designable.map((item) => item.source.code).join(", ")})를 하나의 문서 체계로 통합해 설계할 수 있습니다.`
              : `${designable[0].source.code} 적용요건으로 문서 구조를 설계할 수 있습니다.`}
          </p>
          <Button size="sm" onClick={() => setDesigning(true)}>
            <SparklesIcon />
            문서 구조 설계
          </Button>
        </div>
      )}

      {canAttach && basis.available.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            className="max-w-sm"
            aria-label="근거로 추가할 원문"
          >
            <option value="">근거로 추가할 원문 선택</option>
            {basis.available.map((source) => (
              <option key={source.id} value={source.id}>
                {source.code} · {source.title}
              </option>
            ))}
          </NativeSelect>
          <Button
            variant="outline"
            disabled={!picked || attach.isPending}
            onClick={() => attach.mutate(picked)}
          >
            근거로 추가
          </Button>
        </div>
      )}

      <Dialog open={reviewing !== null} onOpenChange={(open) => !open && setReviewing(null)}>
        <DialogContent className="sm:max-w-3xl">
          {reviewing && (
            <RequirementReview
              tenant={tenant}
              system={system}
              item={reviewing}
              onChanged={onChanged}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={designing} onOpenChange={setDesigning}>
        <DialogContent className="sm:max-w-lg">
          {designing && (
            <DesignForm
              tenant={tenant}
              system={system}
              candidates={designable}
              onDone={async () => {
                setDesigning(false);
                await onChanged();
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RequirementReview({
  tenant,
  system,
  item,
  onChanged,
}: {
  tenant: string;
  system: string;
  item: BasisItem;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const requirements = useBasisRequirements(tenant, system, item.source.id);
  const editable = item.actions.includes("review");
  const [excluding, setExcluding] = useState<{ id: string; reason: string } | null>(null);

  const setExclusion = useMutation({
    mutationFn: (input: { id: string; excluded: boolean; reason: string }) =>
      unwrap(
        api.PUT(
          "/api/t/{tenant_slug}/systems/{system_slug}/basis/{source_id}/requirements/{requirement_id}",
          {
            params: {
              path: {
                tenant_slug: tenant,
                system_slug: system,
                source_id: item.source.id,
                requirement_id: input.id,
              },
            },
            body: { excluded: input.excluded, reason: input.reason },
          },
        ),
      ),
    onSuccess: async () => {
      setExcluding(null);
      await queryClient.invalidateQueries({
        queryKey: keys.basisRequirements(tenant, system, item.source.id),
      });
      await onChanged();
    },
  });

  const rows = requirements.data ?? [];
  const excluded = rows.filter((r) => r.excluded).length;

  return (
    <div className="grid gap-3">
      <DialogHeader>
        <DialogTitle>적용요건 {editable ? "검토" : ""}</DialogTitle>
        <DialogDescription>
          {item.source.title} — 확정한 요건 {rows.length}건 가운데 {rows.length - excluded}건을
          적용합니다.
          {editable && " 이 체계에 해당하지 않는 요건은 사유를 적어 제외하세요."}
        </DialogDescription>
      </DialogHeader>
      {requirements.isPending && <Skeleton className="h-48" />}
      {requirements.error && <ErrorState error={requirements.error} />}
      <ul className="max-h-[60dvh] divide-y divide-border overflow-y-auto rounded-lg border border-border">
        {rows.map((row) => (
          <RequirementRow
            key={row.id}
            row={row}
            editable={editable}
            pending={setExclusion.isPending}
            excluding={excluding?.id === row.id ? excluding.reason : null}
            onStartExclude={() => setExcluding({ id: row.id, reason: "" })}
            onReason={(reason) => setExcluding({ id: row.id, reason })}
            onCancel={() => setExcluding(null)}
            onExclude={() =>
              setExclusion.mutate({ id: row.id, excluded: true, reason: excluding?.reason ?? "" })
            }
            onRestore={() => setExclusion.mutate({ id: row.id, excluded: false, reason: "" })}
          />
        ))}
      </ul>
    </div>
  );
}

function RequirementRow({
  row,
  editable,
  pending,
  excluding,
  onStartExclude,
  onReason,
  onCancel,
  onExclude,
  onRestore,
}: {
  row: BasisRequirement;
  editable: boolean;
  pending: boolean;
  excluding: string | null;
  onStartExclude: () => void;
  onReason: (reason: string) => void;
  onCancel: () => void;
  onExclude: () => void;
  onRestore: () => void;
}) {
  return (
    <li className={cn("px-3 py-2.5 text-sm", row.excluded && "bg-muted/40")}>
      <div className="flex items-start gap-2">
        <div className={cn("min-w-0 flex-1", row.excluded && "opacity-60")}>
          <p className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-xs text-muted-foreground">{row.code}</span>
            <span
              className={cn(
                "inline-flex h-5 items-center rounded-md px-1.5 text-xs font-medium",
                OBLIGATION_STYLE[row.obligation],
              )}
            >
              {OBLIGATION_LABEL[row.obligation]}
            </span>
            {row.applicability && (
              <span className="text-xs text-muted-foreground">{row.applicability}</span>
            )}
          </p>
          <p className="mt-1 leading-6">{row.summary}</p>
          {row.excluded && <p className="mt-1 text-xs">제외 사유: {row.reason}</p>}
        </div>
        {editable &&
          excluding === null &&
          (row.excluded ? (
            <Button variant="ghost" size="sm" disabled={pending} onClick={onRestore}>
              다시 적용
            </Button>
          ) : (
            <Button variant="ghost" size="sm" onClick={onStartExclude}>
              제외
            </Button>
          ))}
      </div>
      {excluding !== null && (
        <form
          className="mt-2 flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onExclude();
          }}
        >
          <Input
            value={excluding}
            onChange={(e) => onReason(e.target.value)}
            placeholder="적용하지 않는 사유 (심사에서 설명해야 합니다)"
            required
            autoFocus
            className="min-w-48 flex-1"
          />
          <Button type="submit" size="sm" disabled={pending || !excluding.trim()}>
            제외
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            취소
          </Button>
        </form>
      )}
    </li>
  );
}

function DesignForm({
  tenant,
  system,
  candidates,
  onDone,
}: {
  tenant: string;
  system: string;
  candidates: BasisItem[];
  onDone: () => Promise<void>;
}) {
  const scopeCodes = useScopeCodes(tenant);
  const [scopeCode, setScopeCode] = useState("");
  const [picked, setPicked] = useState(() => candidates.map((item) => item.source.id));
  const chosen = candidates.filter((item) => picked.includes(item.source.id));
  const total = chosen.reduce((sum, item) => sum + item.total - item.excluded, 0);
  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/plans", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
          body: { source_ids: chosen.map((item) => item.source.id), scope_code: scopeCode },
        }),
      ),
    onSuccess: onDone,
  });

  function toggle(sourceId: string) {
    setPicked((current) =>
      current.includes(sourceId) ? current.filter((id) => id !== sourceId) : [...current, sourceId],
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid min-w-0 gap-4">
      <DialogHeader>
        <DialogTitle>문서 구조 설계</DialogTitle>
        <DialogDescription>
          {chosen.length > 1
            ? `표준 ${chosen.length}개의 적용요건 ${total}건을 하나의 문서 체계(정책·절차·지침·템플릿)로 통합한 설계안을 만듭니다. 같은 활동에 관한 요건은 표준이 달라도 같은 문서에 배정해, 지침 하나로 여러 표준을 함께 이행하게 합니다.`
            : `적용요건 ${total}건을 정책·절차·지침·템플릿으로 묶은 설계안을 만듭니다.`}{" "}
          몇 분 걸리고, 요건 내용이 AI 모델로 전송됩니다. 설계안을 본 뒤에 문서 생성 여부를
          정합니다.
        </DialogDescription>
      </DialogHeader>
      {candidates.length > 1 && (
        <fieldset className="grid min-w-0 gap-2">
          <legend className="mb-1 text-sm font-medium">함께 설계할 표준</legend>
          {candidates.map((item) => (
            <label
              key={item.source.id}
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-border px-3 py-2 text-sm has-checked:border-primary/50 has-checked:bg-primary/5"
            >
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={picked.includes(item.source.id)}
                onChange={() => toggle(item.source.id)}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.source.title}</span>
                <span className="text-xs text-muted-foreground">
                  <span className="font-mono">{item.source.code}</span> · 적용{" "}
                  {item.total - item.excluded}건
                </span>
              </span>
            </label>
          ))}
          <p className="text-xs text-muted-foreground text-pretty">
            함께 고른 표준은 한 설계안으로 묶입니다. 따로 설계하면 표준마다 별도의 문서가
            만들어지고, 나중에 합칠 수 없습니다.
          </p>
        </fieldset>
      )}
      <Field label="영역" hint="생성되는 문서 번호에 들어갑니다. 예: POL-MDSW-01">
        <NativeSelect value={scopeCode} onChange={(e) => setScopeCode(e.target.value)} required>
          <option value="" disabled>
            영역 선택
          </option>
          {(scopeCodes.data ?? []).map((scope) => (
            <option key={scope.code} value={scope.code}>
              {scope.code} · {scope.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={!scopeCode || chosen.length === 0 || start.isPending}>
          {chosen.length > 1 ? `표준 ${chosen.length}개 통합 설계 시작` : "설계 시작"}
        </Button>
      </DialogFooter>
    </form>
  );
}

// ── 2. 설계안과 문서 생성 ────────────────────────────────────────────────────

const PLAN_STATUS: Record<string, { label: string; style: string }> = {
  designing: { label: "설계 중", style: "bg-sky-500/12 text-sky-700 dark:text-sky-300" },
  proposed: { label: "검토 대기", style: "bg-amber-500/12 text-amber-700 dark:text-amber-300" },
  writing: { label: "문서 생성 중", style: "bg-sky-500/12 text-sky-700 dark:text-sky-300" },
  partial: { label: "일부 생성", style: "bg-amber-500/12 text-amber-700 dark:text-amber-300" },
  done: { label: "생성 완료", style: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" },
  failed: { label: "설계 실패", style: "bg-destructive/10 text-destructive" },
};

function PlanCard({
  tenant,
  system,
  plan,
  onChanged,
}: {
  tenant: string;
  system: string;
  plan: Plan;
  onChanged: () => Promise<void>;
}) {
  const busy = isBusy(plan);
  const status = PLAN_STATUS[plan.status] ?? PLAN_STATUS.proposed;
  const canWrite = plan.actions.includes("write");
  const path = { tenant_slug: tenant, system_slug: system, plan_id: plan.id };

  const write = useMutation({
    mutationFn: (policies: string[] | null) =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/plans/{plan_id}/write", {
          params: { path },
          body: { policies },
        }),
      ),
    onSuccess: async () => {
      toast.success("문서 생성을 시작했습니다.");
      await onChanged();
    },
  });
  const discard = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/systems/{system_slug}/plans/{plan_id}", {
          params: { path },
        }),
      ),
    onSuccess: onChanged,
  });

  const policies = useMemo(() => plan.nodes.filter((n) => n.doc_type === "POL"), [plan.nodes]);
  const counts = useMemo(() => {
    const by = (type: string) => plan.nodes.filter((n) => n.doc_type === type).length;
    return { POL: by("POL"), PRO: by("PRO"), WI: by("WI"), TMP: by("TMP") };
  }, [plan.nodes]);
  const done = plan.nodes.filter((n) => n.status === "done").length;
  const failed = plan.nodes.filter((n) => n.status === "failed").length;
  const pending = plan.nodes.length - done;
  const progress = plan.run?.progress as { done?: number; failed?: number; total?: number } | undefined;
  const multi = plan.sources.length > 1;
  const shared = plan.nodes.filter((n) => Object.keys(n.by_standard).length > 1);
  const [comparing, setComparing] = useState(false);
  const [editing, setEditing] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            <span className="font-mono text-sm text-muted-foreground">
              {plan.sources.map((source) => source.code).join(" + ")}
            </span>
            {multi ? "통합 문서 구조 설계안" : "문서 구조 설계안"}
            <span className={cn("inline-flex h-5 items-center rounded-md px-1.5 text-xs", status.style)}>
              {status.label}
            </span>
          </p>
          {plan.nodes.length > 0 && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              정책 {counts.POL} · 절차 {counts.PRO} · 지침 {counts.WI} · 템플릿 {counts.TMP} · 적용요건{" "}
              {plan.applicable_count}건
              {multi &&
                ` (${Object.entries(plan.applicable_by_standard)
                  .map(([standard, count]) => `${standard} ${count}`)
                  .join(" · ")})`}{" "}
              · 영역 <span className="font-mono">{plan.scope_code}</span>
              {done > 0 && ` · 생성 ${done}/${plan.nodes.length}`}
            </p>
          )}
        </div>
        {plan.actions.includes("edit") && (
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            설계안 고치기
          </Button>
        )}
        {plan.actions.includes("discard") && (
          <Button variant="ghost" size="sm" disabled={discard.isPending} onClick={() => discard.mutate()}>
            설계안 버리기
          </Button>
        )}
        {canWrite && (
          <Button disabled={write.isPending} onClick={() => write.mutate(null)}>
            <SparklesIcon />
            {done > 0 ? `남은 문서 ${pending}건 생성` : `문서 ${pending}건 모두 생성`}
          </Button>
        )}
      </div>

      {busy && plan.run && (
        <div className="space-y-2 border-b border-border px-4 py-3">
          <p className="flex items-center gap-2 text-sm">
            <LoaderCircleIcon className="size-4 animate-spin text-primary" />
            {plan.status === "designing"
              ? "문서 구조를 설계하고 있습니다"
              : progress?.total
                ? `문서를 작성하고 있습니다 — ${progress.total}건 가운데 ${(progress.done ?? 0) + (progress.failed ?? 0)}건 완료`
                : "문서 작성을 준비하고 있습니다"}
          </p>
          {plan.status === "writing" && (progress?.total ?? 0) > 0 && (
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-500"
                style={{
                  width: `${Math.max((((progress?.done ?? 0) + (progress?.failed ?? 0)) / (progress?.total ?? 1)) * 100, 3)}%`,
                }}
              />
            </div>
          )}
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {plan.run.events.slice(-4).map((event, index) => (
              <li key={index}>{event}</li>
            ))}
          </ul>
        </div>
      )}

      {!busy && plan.run?.status === "failed" && (
        <Note tone="error">작업이 실패했습니다: {plan.run.error}</Note>
      )}
      {plan.uncovered.length > 0 && (
        <Note tone="warn">
          어느 문서에도 배정되지 않은 적용요건이 {plan.uncovered.length}건 있습니다(
          {plan.uncovered.slice(0, 8).join(", ")}
          {plan.uncovered.length > 8 && " …"}). 모든 요건이 배정돼야 문서를 생성할 수 있습니다.
          “설계안 고치기”에서 문서에 배정하거나, 설계안을 버리고 다시 설계하세요.
        </Note>
      )}
      {!busy && failed > 0 && (
        <Note tone="warn">
          생성하지 못한 문서가 {failed}건 있습니다. 근거 검사를 통과하지 못했거나 상위 문서가 없어
          건너뛴 문서입니다. 다시 생성하면 남은 문서만 처리합니다.
        </Note>
      )}
      {plan.status === "proposed" && plan.uncovered.length === 0 && !busy && (
        <Note tone="info">
          설계안을 확인하고, 맞지 않는 곳은 “설계안 고치기”로 바로잡으세요. 문서 생성을
          시작한 뒤에는 고칠 수 없습니다. 문서 생성은 문서 한 건마다 모델을 호출하므로 {plan.nodes.length}건이면
          10~20분 걸립니다. 정책 하나씩 나눠서 생성할 수도 있습니다.
        </Note>
      )}

      {multi && plan.nodes.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-violet-500/8 px-4 py-2.5">
          <p className="min-w-0 flex-1 basis-60 text-sm text-pretty">
            <LayersIcon className="mr-1.5 inline size-4 align-[-3px] text-violet-600 dark:text-violet-300" />
            여러 표준의 요건을 함께 이행하는 문서가 {shared.length}건입니다. 이 문서들에서 표준 간
            요건이 맞게 대응됐는지 확인하세요.
          </p>
          {shared.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setComparing(true)}>
              표준 간 대응 보기
            </Button>
          )}
        </div>
      )}

      {policies.map((policy) => (
        <PolicyTree
          key={policy.path}
          tenant={tenant}
          system={system}
          policy={policy}
          nodes={plan.nodes}
          multi={multi}
          canWrite={canWrite && !write.isPending}
          onWrite={() => write.mutate([policy.path])}
        />
      ))}

      <PlanEditorDialog
        tenant={tenant}
        system={system}
        plan={plan}
        open={editing}
        onOpenChange={setEditing}
        onSaved={onChanged}
      />

      <Dialog open={comparing} onOpenChange={setComparing}>
        <DialogContent className="sm:max-w-4xl">
          {comparing && <Correspondence tenant={tenant} system={system} plan={plan} nodes={shared} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** 여러 표준의 요건을 함께 이행하는 문서별로, 어느 표준의 어느 요건이 묶였는지 나란히 보여준다. */
function Correspondence({
  tenant,
  system,
  plan,
  nodes,
}: {
  tenant: string;
  system: string;
  plan: Plan;
  nodes: PlanNode[];
}) {
  const results = useQueries({
    queries: plan.sources.map((source) => basisRequirementsQuery(tenant, system, source.id)),
  });
  const summaries = new Map<string, string>();
  plan.sources.forEach((source, index) => {
    for (const requirement of results[index]?.data ?? []) {
      summaries.set(`${source.code} ${requirement.code}`, requirement.summary);
    }
  });
  const loading = results.some((result) => result.isPending);

  return (
    <div className="grid gap-3">
      <DialogHeader>
        <DialogTitle>표준 간 요건 대응</DialogTitle>
        <DialogDescription>
          문서 {nodes.length}건이 {plan.sources.map((source) => source.code).join(", ")}의 요건을
          함께 이행합니다. 같은 문서에 묶인 요건이 실제로 같은 활동에 관한 것인지 확인하고, 맞지
          않으면 설계안을 버리고 다시 설계하세요.
        </DialogDescription>
      </DialogHeader>
      <ul className="max-h-[65dvh] space-y-3 overflow-y-auto pr-1">
        {nodes.map((node) => (
          <li key={node.path} className="rounded-lg border border-border">
            <div className="border-b border-border px-3 py-2">
              <p className="flex items-center gap-2 text-sm font-medium">
                <TypeBadge type={node.doc_type} />
                {node.title}
              </p>
              {node.integration_note && (
                <p className="mt-1 text-sm text-muted-foreground text-pretty">
                  {node.integration_note}
                </p>
              )}
            </div>
            <div className="grid gap-px bg-border sm:grid-cols-2">
              {Object.entries(node.by_standard).map(([standard, codes]) => (
                <div key={standard} className="bg-card px-3 py-2">
                  <p className="font-mono text-xs font-medium">
                    {standard} · {codes.length}건
                  </p>
                  <ul className="mt-1.5 space-y-1.5">
                    {codes.map((code) => (
                      <li key={code} className="text-sm leading-5">
                        <span className="mr-1.5 font-mono text-xs text-muted-foreground">{code}</span>
                        {loading ? (
                          <Skeleton className="inline-block h-3 w-40 align-middle" />
                        ) : (
                          summaries.get(`${standard} ${code}`)
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Note({ tone, children }: { tone: "info" | "warn" | "error"; children: ReactNode }) {
  const styles = {
    info: "bg-sky-500/8",
    warn: "bg-amber-500/10",
    error: "bg-destructive/8 text-destructive",
  };
  return (
    <p className={cn("border-b border-border px-4 py-2.5 text-sm text-pretty", styles[tone])}>
      {children}
    </p>
  );
}

function PolicyTree({
  tenant,
  system,
  policy,
  nodes,
  multi,
  canWrite,
  onWrite,
}: {
  tenant: string;
  system: string;
  policy: PlanNode;
  nodes: PlanNode[];
  multi: boolean;
  canWrite: boolean;
  onWrite: () => void;
}) {
  const subtree = nodes.filter((n) => n.path === policy.path || n.path.startsWith(`${policy.path}.`));
  const pending = subtree.filter((n) => n.status !== "done").length;
  return (
    <div className="border-b border-border last:border-b-0">
      <ul>
        {subtree.map((node) => (
          <li
            key={node.path}
            className="flex items-center gap-2 py-1.5 pr-4 text-sm"
            style={{ paddingLeft: `${1 + (node.path.split(".").length - 1) * 1.125}rem` }}
          >
            <TypeBadge type={node.doc_type} />
            <span className="min-w-0 flex-1">
              {node.document_id ? (
                <Link
                  href={routes.document(tenant, system, node.document_id)}
                  className="font-medium hover:underline"
                >
                  {node.title}
                </Link>
              ) : (
                <span className={cn(node.doc_type !== "TMP" && "font-medium")}>{node.title}</span>
              )}
              {Object.keys(node.by_standard).length > 1 && (
                <span
                  className="ml-2 inline-flex h-5 items-center rounded-md bg-violet-500/12 px-1.5 text-xs text-violet-700 dark:text-violet-300"
                  title={node.integration_note || "여러 표준의 요건을 함께 이행합니다"}
                >
                  통합
                </span>
              )}
              {node.purpose && (
                <span className="ml-2 hidden text-xs text-muted-foreground lg:inline">
                  {node.purpose}
                </span>
              )}
              {node.status === "failed" && (
                <span className="block text-xs text-amber-700 dark:text-amber-300">{node.error}</span>
              )}
            </span>
            {node.requirements.length > 0 && (
              <span
                className="shrink-0 text-xs text-muted-foreground"
                title={node.requirements.join(", ")}
              >
                {multi ? (
                  <>
                    <span className="sm:hidden">요건 {node.requirements.length}</span>
                    <span className="hidden sm:inline">
                      {Object.entries(node.by_standard)
                        .map(([standard, codes]) => `${standard} ${codes.length}`)
                        .join(" · ")}
                    </span>
                  </>
                ) : (
                  `요건 ${node.requirements.length}`
                )}
              </span>
            )}
            {node.status === "done" && (
              <CheckIcon className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="생성됨" />
            )}
            {node.status === "failed" && (
              <CircleAlertIcon className="size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-label="실패" />
            )}
            {node.path === policy.path && canWrite && pending > 0 && (
              <Button variant="outline" size="sm" onClick={onWrite}>
                이 정책만 생성 ({pending}건)
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
