"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PlusIcon, XIcon } from "lucide-react";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { ErrorState, Field, NativeSelect, PageHeader } from "@/components/bits";
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
import { api, type Member, type RoleGrant, type System, unwrap } from "@/lib/api";
import { SYSTEM_ROLE_HINT, SYSTEM_ROLE_LABEL, TENANT_ROLE_LABEL } from "@/lib/labels";
import { keys, useMembers, useSystems, useTenant } from "@/lib/queries";

type TenantRole = "tenant_admin" | "member";

/** 구성원과 역할 관리. */
export default function MembersPage() {
  const { tenant } = useParams<{ tenant: string }>();
  const tenantQuery = useTenant(tenant);
  const members = useMembers(tenant);
  const systems = useSystems(tenant);
  const canManage = tenantQuery.data?.actions.includes("member.manage") ?? false;
  const [dialog, setDialog] = useState<{ member?: Member } | null>(null);

  const systemName = new Map((systems.data ?? []).map((s) => [s.id, s.name]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="구성원"
        description="관리자는 회사 안의 모든 일을 할 수 있습니다. 구성원은 읽기만 가능하며, 역할을 받으면 그 범위에서 문서를 작성하거나 검토합니다."
        actions={
          canManage && (
            <Button onClick={() => setDialog({})}>
              <PlusIcon />
              구성원 추가
            </Button>
          )
        }
      />

      {members.isPending && <Skeleton className="h-32" />}
      {members.error && <ErrorState error={members.error} />}
      {members.data && (
        <ul className="overflow-hidden rounded-xl border border-border bg-card">
          {members.data.map((member) => (
            <li
              key={member.user.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-3 last:border-b-0"
            >
              <div className="min-w-48 flex-1">
                <p className="truncate text-sm font-medium">{member.user.name}</p>
                <p className="truncate text-xs text-muted-foreground">{member.user.email}</p>
              </div>
              <div className="flex flex-1 flex-wrap items-center gap-1.5">
                <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium">
                  {TENANT_ROLE_LABEL[member.tenant_role] ?? member.tenant_role}
                </span>
                {member.roles.map((grant) => (
                  <span
                    key={`${grant.role}:${grant.system_id ?? ""}`}
                    className="rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary"
                  >
                    {SYSTEM_ROLE_LABEL[grant.role]}
                    <span className="opacity-70">
                      {" · "}
                      {grant.system_id ? (systemName.get(grant.system_id) ?? "체계") : "회사 전체"}
                    </span>
                  </span>
                ))}
              </div>
              {canManage && (
                <Button variant="ghost" size="sm" onClick={() => setDialog({ member })}>
                  권한 변경
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent className="sm:max-w-md">
          {dialog && (
            <MemberForm
              tenant={tenant}
              member={dialog.member}
              systems={systems.data ?? []}
              onDone={() => setDialog(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MemberForm({
  tenant,
  member,
  systems,
  onDone,
}: {
  tenant: string;
  member?: Member;
  systems: System[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [tenantRole, setTenantRole] = useState<TenantRole>(
    (member?.tenant_role as TenantRole) ?? "member",
  );
  const [roles, setRoles] = useState<RoleGrant[]>(member?.roles ?? []);

  const save = useMutation({
    mutationFn: () =>
      member
        ? unwrap(
            api.PATCH("/api/t/{tenant_slug}/members/{user_id}", {
              params: { path: { tenant_slug: tenant, user_id: member.user.id } },
              body: { tenant_role: tenantRole, roles },
            }),
          )
        : unwrap(
            api.POST("/api/t/{tenant_slug}/members", {
              params: { path: { tenant_slug: tenant } },
              body: { email: email.trim(), name: name.trim(), tenant_role: tenantRole, roles },
            }),
          ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.members(tenant) });
      onDone();
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  function setGrant(index: number, patch: Partial<RoleGrant>) {
    setRoles((previous) => previous.map((g, i) => (i === index ? { ...g, ...patch } : g)));
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>{member ? `${member.user.name} 권한` : "구성원 추가"}</DialogTitle>
        <DialogDescription>
          {member
            ? member.user.email
            : "추가된 사람은 이 이메일로 로그인 링크를 받아 들어올 수 있습니다."}
        </DialogDescription>
      </DialogHeader>

      {!member && (
        <>
          <Field label="이메일">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </Field>
          <Field label="이름">
            <Input value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
        </>
      )}

      <Field label="회사 내 권한">
        <NativeSelect
          value={tenantRole}
          onChange={(e) => setTenantRole(e.target.value as TenantRole)}
        >
          <option value="member">구성원 — 읽기, 그리고 아래 역할의 범위</option>
          <option value="tenant_admin">관리자 — 회사 안의 모든 일</option>
        </NativeSelect>
      </Field>

      {tenantRole === "member" && (
        <div className="grid gap-2 text-sm">
          <span className="font-medium">역할</span>
          {roles.length === 0 && (
            <p className="text-xs text-muted-foreground">역할이 없으면 문서를 읽기만 할 수 있습니다.</p>
          )}
          {roles.map((grant, index) => (
            <div key={index} className="grid grid-cols-[1fr_1fr_auto] items-start gap-2">
              <div>
                <NativeSelect
                  value={grant.role}
                  onChange={(e) => setGrant(index, { role: e.target.value as RoleGrant["role"] })}
                  aria-label="역할"
                >
                  {Object.entries(SYSTEM_ROLE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
                <p className="mt-1 text-xs text-muted-foreground">{SYSTEM_ROLE_HINT[grant.role]}</p>
              </div>
              <NativeSelect
                value={grant.system_id ?? ""}
                onChange={(e) => setGrant(index, { system_id: e.target.value || null })}
                aria-label="적용 범위"
              >
                <option value="">회사 전체</option>
                {systems.map((system) => (
                  <option key={system.id} value={system.id}>
                    {system.name}
                  </option>
                ))}
              </NativeSelect>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="역할 제거"
                onClick={() => setRoles((previous) => previous.filter((_, i) => i !== index))}
              >
                <XIcon />
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-fit"
            onClick={() =>
              setRoles((previous) => [...previous, { role: "process_owner", system_id: null }])
            }
          >
            <PlusIcon />
            역할 추가
          </Button>
        </div>
      )}

      <DialogFooter>
        <Button type="submit" disabled={save.isPending}>
          {member ? "저장" : "추가"}
        </Button>
      </DialogFooter>
    </form>
  );
}
