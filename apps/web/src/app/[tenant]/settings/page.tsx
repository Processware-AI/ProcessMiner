"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { ErrorState, Field, PageHeader } from "@/components/bits";
import { ArchivedSection, ArchiveSection } from "@/components/tenant-lifecycle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Tenant, unwrap } from "@/lib/api";
import { keys, useTenant } from "@/lib/queries";

export default function SettingsPage() {
  const { tenant } = useParams<{ tenant: string }>();
  const tenantQuery = useTenant(tenant);

  return (
    <div className="max-w-xl space-y-5">
      <PageHeader title="설정" />
      {tenantQuery.isPending && <Skeleton className="h-40" />}
      {tenantQuery.error && <ErrorState error={tenantQuery.error} />}
      {tenantQuery.data && <SettingsBody tenant={tenantQuery.data} />}
    </div>
  );
}

function SettingsBody({ tenant }: { tenant: Tenant }) {
  // 보관된 회사에서는 설정을 바꿀 수 없고, 복원하거나 지우는 일만 남는다.
  if (tenant.archived_at) return <ArchivedSection tenant={tenant} />;
  if (!tenant.actions.includes("tenant.manage")) {
    return <p className="text-sm text-muted-foreground">설정은 관리자만 바꿀 수 있습니다.</p>;
  }
  return (
    <>
      <SettingsForm key={tenant.id} tenant={tenant} />
      {tenant.actions.includes("tenant.archive") && <ArchiveSection tenant={tenant} />}
    </>
  );
}

function SettingsForm({ tenant }: { tenant: Tenant }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(tenant.name);
  const [fourEyes, setFourEyes] = useState(tenant.four_eyes);
  const [artifactAi, setArtifactAi] = useState(tenant.artifact_ai);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/t/{tenant_slug}", {
          params: { path: { tenant_slug: tenant.slug } },
          body: { name: name.trim(), four_eyes: fourEyes, artifact_ai: artifactAi },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.tenant(tenant.slug) }),
        queryClient.invalidateQueries({ queryKey: keys.me }),
      ]);
      toast.success("저장했습니다.");
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-5 rounded-xl border border-border bg-card p-5">
      <Field label="회사 이름">
        <Input value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <label className="flex items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={fourEyes}
          onChange={(e) => setFourEyes(e.target.checked)}
          className="mt-0.5 size-4 accent-primary"
        />
        <span>
          <span className="block font-medium">작성자와 검토자 분리</span>
          <span className="block text-muted-foreground">
            작성자가 자기 개정판을 승인하거나 반려할 수 없게 합니다. 끄면 한 사람이 작성과 승인을
            모두 할 수 있어, 심사에서 문서 통제의 약점으로 지적될 수 있습니다.
          </span>
        </span>
      </label>
      <label className="flex items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={artifactAi}
          onChange={(e) => setArtifactAi(e.target.checked)}
          className="mt-0.5 size-4 accent-primary"
        />
        <span>
          <span className="block font-medium">산출물의 AI 처리에 동의</span>
          <span className="block text-muted-foreground">
            회사의 기존 산출물을 표준 양식의 기록으로 옮길 때, 산출물의 내용을 외부 AI 모델로
            보내 어느 양식에 해당하는지 찾고 항목 값을 뽑습니다. 꺼 두면 산출물은 이 시스템에만
            보관되고, 양식 선택과 항목 입력을 사람이 직접 합니다. 고객이나 제3자의 정보가 든
            문서라면 계약상 외부 전송이 허용되는지 먼저 확인하세요.
          </span>
        </span>
      </label>
      <div>
        <Button type="submit" disabled={save.isPending}>
          저장
        </Button>
      </div>
    </form>
  );
}
