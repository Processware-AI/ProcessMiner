"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArchiveIcon, ArchiveRestoreIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { Field } from "@/components/bits";
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
import { api, type Tenant, unwrap } from "@/lib/api";
import { formatDate } from "@/lib/labels";
import { keys } from "@/lib/queries";

function useRefreshTenant(slug: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      // 보관 여부에 따라 회사 안의 모든 화면에서 할 수 있는 일이 달라진다.
      queryClient.invalidateQueries({ queryKey: keys.tenant(slug) }),
      queryClient.invalidateQueries({ queryKey: keys.me }),
    ]);
}

/** 운영 중인 회사의 설정 화면 아래쪽: 보관. */
export function ArchiveSection({ tenant }: { tenant: Tenant }) {
  const refresh = useRefreshTenant(tenant.slug);
  const [open, setOpen] = useState(false);
  const archive = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/archive", {
          params: { path: { tenant_slug: tenant.slug } },
        }),
      ),
    onSuccess: async () => {
      setOpen(false);
      await refresh();
      toast.success("회사를 보관했습니다.");
    },
  });

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <h2 className="font-medium">회사 보관</h2>
      <p className="mt-1 text-sm text-muted-foreground text-pretty">
        더 쓰지 않는 회사를 보관합니다. 문서와 기록은 그대로 남고 읽기만 가능해지며, 관리자가 아닌
        구성원에게는 보이지 않습니다. 언제든 복원할 수 있습니다.
      </p>
      <Button variant="outline" className="mt-3" onClick={() => setOpen(true)}>
        <ArchiveIcon />
        회사 보관
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>회사를 보관할까요?</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{tenant.name}</span> — 보관하면 누구도 문서를 만들거나 고칠 수 없고, 진행 중인 검토도 멈춥니다. 데이터는
              지워지지 않으며 복원하면 그대로 이어서 쓸 수 있습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              취소
            </Button>
            <Button onClick={() => archive.mutate()} disabled={archive.isPending}>
              보관
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

/** 보관된 회사의 설정 화면: 복원, 그리고 권한이 있으면 완전 삭제. */
export function ArchivedSection({ tenant }: { tenant: Tenant }) {
  const refresh = useRefreshTenant(tenant.slug);
  const [purging, setPurging] = useState(false);
  const canRestore = tenant.actions.includes("tenant.restore");
  const canDelete = tenant.actions.includes("tenant.delete");

  const restore = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/restore", {
          params: { path: { tenant_slug: tenant.slug } },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      toast.success("회사를 복원했습니다.");
    },
  });

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-medium">보관된 회사입니다</h2>
        <p className="mt-1 text-sm text-muted-foreground text-pretty">
          {formatDate(tenant.archived_at)} 에 보관됐습니다. 문서와 기록은 읽을 수만 있습니다.
          복원하면 구성원이 다시 들어와 이어서 쓸 수 있습니다.
        </p>
        {canRestore && (
          <Button className="mt-3" onClick={() => restore.mutate()} disabled={restore.isPending}>
            <ArchiveRestoreIcon />
            회사 복원
          </Button>
        )}
      </section>

      <section className="rounded-xl border border-destructive/30 bg-card p-5">
        <h2 className="font-medium">완전 삭제</h2>
        <p className="mt-1 text-sm text-muted-foreground text-pretty">
          회사의 문서, 개정 이력, 감사 기록, 조직과 체계를 모두 지웁니다. 이 회사에만 속한 구성원의
          계정도 함께 지워집니다. 되돌릴 수 없고, 지웠다는 사실(누가, 언제)만 남습니다.
        </p>
        {canDelete ? (
          <Button variant="destructive" className="mt-3" onClick={() => setPurging(true)}>
            <Trash2Icon />
            완전 삭제
          </Button>
        ) : (
          <p className="mt-3 text-sm">완전 삭제는 플랫폼 관리자만 할 수 있습니다.</p>
        )}
      </section>

      <Dialog open={purging} onOpenChange={setPurging}>
        <DialogContent>
          {purging && <PurgeForm tenant={tenant} onCancel={() => setPurging(false)} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PurgeForm({ tenant, onCancel }: { tenant: Tenant; onCancel: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState("");

  const purge = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/purge", {
          params: { path: { tenant_slug: tenant.slug } },
          body: { confirm_slug: confirm },
        }),
      ),
    onSuccess: (result) => {
      // 이 회사에 대해 들고 있던 데이터는 모두 무효다.
      queryClient.clear();
      toast.success(`회사를 삭제했습니다: ${result.name}`);
      router.replace("/");
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    purge.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>회사 완전 삭제</DialogTitle>
        <DialogDescription>
          <span className="font-medium text-foreground">{tenant.name}</span> 의 모든 문서와 기록이
          사라지고 되돌릴 수 없습니다. 계속하려면 아래에 회사 주소를 그대로 입력하세요:{" "}
          <span className="font-mono font-medium text-foreground">{tenant.slug}</span>
        </DialogDescription>
      </DialogHeader>
      <Field label="회사 주소">
        <Input
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
        />
      </Field>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          취소
        </Button>
        <Button
          type="submit"
          variant="destructive"
          disabled={confirm !== tenant.slug || purge.isPending}
        >
          완전 삭제
        </Button>
      </DialogFooter>
    </form>
  );
}
