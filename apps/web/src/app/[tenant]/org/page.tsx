"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LibraryIcon, PlusIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { EmptyState, ErrorState, Field, NativeSelect, PageHeader } from "@/components/bits";
import { systemTree } from "@/components/shell/app-shell";
import { orgTree, SystemDialog, type SystemDialogState, SystemMenu } from "@/components/systems/system-dialogs";
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
import { api, type OrgUnit, unwrap } from "@/lib/api";
import { ORG_KIND_LABEL } from "@/lib/labels";
import { keys, useOrgUnits, useSystems, useTenant } from "@/lib/queries";
import { routes } from "@/lib/routes";

/** 조직 트리와 프로세스 체계 관리. */
export default function OrgPage() {
  const { tenant } = useParams<{ tenant: string }>();
  const tenantQuery = useTenant(tenant);
  const units = useOrgUnits(tenant);
  const systems = useSystems(tenant);
  const queryClient = useQueryClient();

  const canManage = tenantQuery.data?.actions.includes("tenant.manage") ?? false;
  const canCreateSystem = tenantQuery.data?.actions.includes("system.create") ?? false;
  const canManageSystem = tenantQuery.data?.actions.includes("system.manage") ?? false;
  const [unitParent, setUnitParent] = useState<OrgUnit | null>(null);
  const [systemDialog, setSystemDialog] = useState<SystemDialogState | null>(null);

  const tree = useMemo(() => orgTree(units.data ?? []), [units.data]);
  const unitName = useMemo(
    () => new Map((units.data ?? []).map((u) => [u.id, u.name])),
    [units.data],
  );

  const removeUnit = useMutation({
    mutationFn: (unitId: string) =>
      unwrap(
        api.DELETE("/api/t/{tenant_slug}/org-units/{unit_id}", {
          params: { path: { tenant_slug: tenant, unit_id: unitId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.orgUnits(tenant) }),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        title="조직·체계"
        description="조직 트리를 만들고, 조직마다 프로세스 체계를 둡니다. 하위 체계는 상위 체계를 바탕으로 합니다."
      />

      <section>
        <h2 className="mb-2 text-sm font-semibold">조직</h2>
        {units.isPending && <Skeleton className="h-24" />}
        {units.error && <ErrorState error={units.error} />}
        <ul className="overflow-hidden rounded-xl border border-border bg-card">
          {tree.map(({ unit, depth }) => (
            <li
              key={unit.id}
              className="group flex items-center gap-2 border-b border-border py-2 pr-2 last:border-b-0"
              style={{ paddingLeft: `${0.875 + depth * 1.25}rem` }}
            >
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{unit.name}</span>
              <span className="text-xs text-muted-foreground">
                {ORG_KIND_LABEL[unit.kind] ?? unit.kind}
              </span>
              {canManage && (
                <>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`${unit.name} 아래에 조직 추가`}
                    onClick={() => setUnitParent(unit)}
                  >
                    <PlusIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`${unit.name} 삭제`}
                    disabled={unit.parent_id === null || removeUnit.isPending}
                    onClick={() => removeUnit.mutate(unit.id)}
                    className={unit.parent_id === null ? "invisible" : undefined}
                  >
                    <Trash2Icon />
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">체계</h2>
          {canCreateSystem && (
            <Button size="sm" onClick={() => setSystemDialog({ kind: "create" })}>
              <PlusIcon />새 체계
            </Button>
          )}
        </div>
        {systems.isPending && <Skeleton className="h-16" />}
        {systems.data?.length === 0 && (
          <EmptyState
            icon={<LibraryIcon />}
            title="아직 체계가 없습니다"
            description="먼저 회사 전체에 적용할 기준선 체계를 만드세요."
          />
        )}
        {(systems.data?.length ?? 0) > 0 && (
          <ul className="overflow-hidden rounded-xl border border-border bg-card">
            {systemTree(systems.data ?? []).map(({ system, depth }) => (
              <li
                key={system.id}
                className="flex items-center gap-3 border-b border-border py-2.5 pr-2 last:border-b-0"
                style={{ paddingLeft: `${0.875 + depth * 1.25}rem` }}
              >
                <Link
                  href={routes.library(tenant, system.slug)}
                  className="min-w-0 flex-1 hover:underline"
                >
                  <span className="block truncate text-sm font-medium">{system.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {unitName.get(system.org_unit_id)} · {depth === 0 ? "기준선" : "조직 변형"} ·{" "}
                    <span className="font-mono">{system.slug}</span>
                  </span>
                </Link>
                {canCreateSystem && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSystemDialog({ kind: "create", parent: system })}
                  >
                    <PlusIcon />
                    변형 추가
                  </Button>
                )}
                <SystemMenu
                  system={system}
                  canCreate={false}
                  canManage={canManageSystem}
                  onAction={setSystemDialog}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog open={unitParent !== null} onOpenChange={(open) => !open && setUnitParent(null)}>
        <DialogContent>
          {unitParent && (
            <NewUnitForm tenant={tenant} parent={unitParent} onDone={() => setUnitParent(null)} />
          )}
        </DialogContent>
      </Dialog>

      <SystemDialog
        tenant={tenant}
        state={systemDialog}
        onClose={() => setSystemDialog(null)}
      />
    </div>
  );
}

function NewUnitForm({
  tenant,
  parent,
  onDone,
}: {
  tenant: string;
  parent: OrgUnit;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"division" | "team" | "project">(
    parent.kind === "company" ? "division" : "team",
  );
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/org-units", {
          params: { path: { tenant_slug: tenant } },
          body: { name: name.trim(), kind, parent_id: parent.id },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.orgUnits(tenant) });
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
        <DialogTitle>조직 추가</DialogTitle>
        <DialogDescription>{parent.name} 아래에 추가합니다.</DialogDescription>
      </DialogHeader>
      <Field label="이름">
        <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      </Field>
      <Field label="종류">
        <NativeSelect value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="division">{ORG_KIND_LABEL.division}</option>
          <option value="team">{ORG_KIND_LABEL.team}</option>
          <option value="project">{ORG_KIND_LABEL.project}</option>
        </NativeSelect>
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={create.isPending}>
          추가
        </Button>
      </DialogFooter>
    </form>
  );
}
