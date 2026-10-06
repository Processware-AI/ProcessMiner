"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRightIcon, Building2Icon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { EmptyState, ErrorState, Field } from "@/components/bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api";
import { TENANT_ROLE_LABEL } from "@/lib/labels";
import { keys, useMe } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/** 회사 선택 화면. */
export default function TenantsPage() {
  const me = useMe();

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 sm:py-16">
      <div className="mb-8 flex items-center gap-2.5">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/icon.svg" alt="" className="size-8 rounded-lg" />
        <span className="text-lg font-semibold tracking-tight">ProcessMiner</span>
      </div>

      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">회사</h1>
          {me.data && (
            <p className="mt-1 text-sm text-muted-foreground">
              {me.data.user.name} 님이 참여 중인 회사입니다.
            </p>
          )}
        </div>
        {me.data?.can_create_tenant && <NewTenantDialog />}
      </div>

      {me.isPending && <Skeleton className="h-16" />}
      {me.error && <ErrorState error={me.error} />}
      {me.data?.tenants.length === 0 && (
        <EmptyState
          icon={<Building2Icon />}
          title="참여 중인 회사가 없습니다"
          description={
            me.data.can_create_tenant
              ? "회사를 만들어 조직과 프로세스 체계를 구성하세요."
              : "회사 관리자에게 초대를 요청하세요."
          }
        />
      )}
      <ul className="space-y-2">
        {[...(me.data?.tenants ?? [])]
          .sort((a, b) => Number(Boolean(a.archived_at)) - Number(Boolean(b.archived_at)))
          .map((tenant) => (
          <li key={tenant.id}>
            <Link
              href={routes.home(tenant.slug)}
              className={cn(
                "group flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:border-ring/60",
                tenant.archived_at && "bg-transparent opacity-70",
              )}
            >
              <span
                className={cn(
                  "grid size-9 shrink-0 place-content-center rounded-lg bg-primary font-semibold text-primary-foreground",
                  tenant.archived_at && "bg-muted text-muted-foreground",
                )}
              >
                {tenant.name.slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{tenant.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {tenant.tenant_role
                    ? (TENANT_ROLE_LABEL[tenant.tenant_role] ?? tenant.tenant_role)
                    : "플랫폼 관리자"}
                </span>
              </span>
              {tenant.archived_at && (
                <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
                  보관됨
                </span>
              )}
              <ArrowRightIcon className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NewTenantDialog() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/tenants", { body: { name: name.trim(), slug } })),
    onSuccess: async (tenant) => {
      await queryClient.invalidateQueries({ queryKey: keys.me });
      router.push(routes.org(tenant.slug));
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <PlusIcon />새 회사
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>새 회사</DialogTitle>
            <DialogDescription>
              회사마다 조직, 체계, 문서가 서로 분리되어 관리됩니다.
            </DialogDescription>
          </DialogHeader>
          <Field label="회사 이름">
            <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </Field>
          <Field label="주소" hint="영문 소문자·숫자·하이픈. 웹 주소에 쓰이며 나중에 바꿀 수 없습니다.">
            <Input
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              required
              pattern="[a-z0-9][a-z0-9-]{1,62}"
              placeholder="acme"
              className="font-mono"
            />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
