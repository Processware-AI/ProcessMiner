"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlertIcon, EllipsisIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { toast } from "sonner";

import { Field, NativeSelect } from "@/components/bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type OrgUnit, type System, unwrap } from "@/lib/api";
import { keys, useOrgUnits, useSystem } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** 조직 트리를 상위부터 펼치고 깊이를 붙인다. */
export function orgTree(units: OrgUnit[]): { unit: OrgUnit; depth: number }[] {
  const byParent = new Map<string | null, OrgUnit[]>();
  for (const unit of units) {
    const key = unit.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), unit]);
  }
  const out: { unit: OrgUnit; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const unit of byParent.get(parent) ?? []) {
      out.push({ unit, depth });
      walk(unit.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** 체계에 대해 열 수 있는 대화상자. parent 가 있는 create 는 하위(조직 변형) 체계를 만든다. */
export type SystemDialogState =
  | { kind: "create"; parent?: System }
  | { kind: "rename"; system: System }
  | { kind: "delete"; system: System };

export function SystemDialog({
  tenant,
  state,
  onClose,
  onDeleted,
}: {
  tenant: string;
  state: SystemDialogState | null;
  onClose: () => void;
  onDeleted?: (system: System) => void;
}) {
  return (
    <Dialog open={state !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {state?.kind === "create" && (
          <NewSystemForm tenant={tenant} parent={state.parent} onDone={onClose} />
        )}
        {state?.kind === "rename" && (
          <RenameSystemForm tenant={tenant} system={state.system} onDone={onClose} />
        )}
        {state?.kind === "delete" && (
          <DeleteSystemForm
            tenant={tenant}
            system={state.system}
            onCancel={onClose}
            onDone={() => {
              onClose();
              onDeleted?.(state.system);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** 체계 한 줄 옆의 '더 보기' 메뉴. 할 수 있는 일이 없으면 그리지 않는다. */
export function SystemMenu({
  system,
  canCreate,
  canManage,
  onAction,
  className,
}: {
  system: System;
  canCreate: boolean;
  canManage: boolean;
  onAction: (state: SystemDialogState) => void;
  className?: string;
}) {
  if (!canCreate && !canManage) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`${system.name} 관리`}
            className={cn("text-muted-foreground", className)}
          />
        }
      >
        <EllipsisIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-44">
        {canManage && (
          <DropdownMenuItem onClick={() => onAction({ kind: "rename", system })}>
            <PencilIcon />
            이름 바꾸기
          </DropdownMenuItem>
        )}
        {canCreate && (
          <DropdownMenuItem onClick={() => onAction({ kind: "create", parent: system })}>
            <PlusIcon />
            하위 체계 추가
          </DropdownMenuItem>
        )}
        {canManage && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onClick={() => onAction({ kind: "delete", system })}
            >
              <Trash2Icon />
              삭제
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NewSystemForm({
  tenant,
  parent,
  onDone,
}: {
  tenant: string;
  parent?: System;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const unitsQuery = useOrgUnits(tenant);
  const units = useMemo(() => orgTree(unitsQuery.data ?? []), [unitsQuery.data]);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  // 기준선 체계는 보통 회사 전체에 적용하므로 최상위 조직을 먼저 고른다.
  const [orgUnitId, setOrgUnitId] = useState("");
  const chosenUnit = orgUnitId || (parent ? "" : (units[0]?.unit.id ?? ""));

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems", {
          params: { path: { tenant_slug: tenant } },
          body: {
            name: name.trim(),
            slug,
            description: description.trim(),
            org_unit_id: chosenUnit,
            parent_system_id: parent?.id ?? null,
          },
        }),
      ),
    onSuccess: async (system) => {
      await queryClient.invalidateQueries({ queryKey: keys.systems(tenant) });
      toast.success(`체계를 만들었습니다: ${system.name}`);
      onDone();
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>{parent ? "조직 변형 체계" : "새 체계"}</DialogTitle>
        <DialogDescription>
          {parent
            ? `상위 체계: ${parent.name}. 이 체계를 바탕으로 하는 조직별 체계를 만듭니다. 문서 번호는 상위 체계와 겹치지 않게 매겨집니다.`
            : "회사 전체에 적용할 기준선 체계를 만듭니다."}
        </DialogDescription>
      </DialogHeader>
      <Field label="이름">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoFocus
          placeholder={parent ? "개발본부 체계" : "통합경영체계"}
        />
      </Field>
      <Field label="주소" hint="영문 소문자·숫자·하이픈. 웹 주소에 쓰이고, 만든 뒤에는 바꿀 수 없습니다.">
        <Input
          value={slug}
          onChange={(e) => setSlug(e.target.value.toLowerCase())}
          required
          pattern="[a-z0-9][a-z0-9-]{1,62}"
          placeholder={parent ? "dev" : "ims"}
          className="font-mono"
        />
      </Field>
      <Field label="적용 조직">
        <NativeSelect value={chosenUnit} onChange={(e) => setOrgUnitId(e.target.value)} required>
          <option value="" disabled>
            조직 선택
          </option>
          {units.map(({ unit, depth }) => (
            <option key={unit.id} value={unit.id}>
              {"  ".repeat(depth)}
              {unit.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="설명 (선택)">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={create.isPending}>
          만들기
        </Button>
      </DialogFooter>
    </form>
  );
}

function RenameSystemForm({
  tenant,
  system,
  onDone,
}: {
  tenant: string;
  system: System;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(system.name);
  const [description, setDescription] = useState(system.description);

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/t/{tenant_slug}/systems/{system_slug}", {
          params: { path: { tenant_slug: tenant, system_slug: system.slug } },
          body: { name: name.trim(), description: description.trim() },
        }),
      ),
    onSuccess: async () => {
      // 체계 목록과 상세(키가 목록 아래에 있다)를 함께 새로 읽는다.
      await queryClient.invalidateQueries({ queryKey: keys.systems(tenant) });
      toast.success("체계 이름을 바꿨습니다.");
      onDone();
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    rename.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>체계 이름 바꾸기</DialogTitle>
        <DialogDescription>
          주소(<span className="font-mono">{system.slug}</span>)는 그대로 둡니다. 문서 번호와
          링크는 바뀌지 않습니다.
        </DialogDescription>
      </DialogHeader>
      <Field label="이름">
        <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      </Field>
      <Field label="설명 (선택)">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={rename.isPending || !name.trim()}>
          저장
        </Button>
      </DialogFooter>
    </form>
  );
}

function DeleteSystemForm({
  tenant,
  system,
  onCancel,
  onDone,
}: {
  tenant: string;
  system: System;
  onCancel: () => void;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const detail = useSystem(tenant, system.slug);
  const blockers = detail.data?.delete_blockers ?? [];

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/systems/{system_slug}", {
          params: { path: { tenant_slug: tenant, system_slug: system.slug } },
        }),
      ),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: keys.system(tenant, system.slug) });
      await queryClient.invalidateQueries({ queryKey: keys.systems(tenant) });
      toast.success(`체계를 삭제했습니다: ${system.name}`);
      onDone();
    },
  });

  return (
    <div className="grid gap-4">
      <DialogHeader>
        <DialogTitle>체계 삭제: {system.name}</DialogTitle>
        <DialogDescription>
          빈 체계만 삭제할 수 있습니다. 근거로 고른 원문, 설계안, 이 체계에 준 역할도 함께
          지워집니다. 감사 기록에는 남습니다.
        </DialogDescription>
      </DialogHeader>
      {detail.isPending && <Skeleton className="h-16" />}
      {blockers.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-2.5 text-sm">
          <p className="flex items-center gap-1.5 font-medium">
            <CircleAlertIcon className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
            아직 남아 있는 것이 있어 삭제할 수 없습니다.
          </p>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-muted-foreground">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-muted-foreground">
            문서는 문서 목록에서 골라 다른 체계로 옮기거나 삭제할 수 있습니다.
          </p>
        </div>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          취소
        </Button>
        <Button
          variant="destructive"
          onClick={() => remove.mutate()}
          disabled={remove.isPending || detail.isPending || blockers.length > 0}
        >
          삭제
        </Button>
      </DialogFooter>
    </div>
  );
}
