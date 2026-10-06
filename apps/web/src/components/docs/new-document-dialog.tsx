"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { DocCode, Field, NativeSelect } from "@/components/bits";
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
import { api, unwrap } from "@/lib/api";
import { keys, useDocTypes, useScopeCodes } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

export type NewDocumentParent = { id: string; code: string; title: string; doc_type: string };

export function NewDocumentDialog({
  tenant,
  system,
  parent,
  open,
  onOpenChange,
}: {
  tenant: string;
  system: string;
  /** 없으면 최상위 문서(정책서·참고자료)를 만든다. */
  parent?: NewDocumentParent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* 열릴 때마다 입력값이 초기화되도록 내용은 열려 있을 때만 그린다. */}
        {open && (
          <NewDocumentForm
            tenant={tenant}
            system={system}
            parent={parent}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function NewDocumentForm({
  tenant,
  system,
  parent,
  onDone,
}: {
  tenant: string;
  system: string;
  parent?: NewDocumentParent;
  onDone: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const docTypes = useDocTypes();
  const scopeCodes = useScopeCodes(tenant);

  const options = (docTypes.data ?? []).filter((t) =>
    parent ? t.parent_type === parent.doc_type : t.parent_type === null,
  );
  const [chosenType, setChosenType] = useState<string | null>(null);
  const docType = chosenType ?? options[0]?.code ?? "";
  const [title, setTitle] = useState("");
  const [scopeCode, setScopeCode] = useState("");
  const needsScope = docType === "POL";

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/t/{tenant_slug}/systems/{system_slug}/documents", {
          params: { path: { tenant_slug: tenant, system_slug: system } },
          body: {
            doc_type: docType,
            title: title.trim(),
            parent_id: parent?.id ?? null,
            scope_code: needsScope ? scopeCode : null,
          },
        }),
      ),
    onSuccess: async (detail) => {
      await queryClient.invalidateQueries({ queryKey: keys.docsAll(tenant) });
      onDone();
      router.push(routes.document(tenant, system, detail.document.id));
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>{parent ? "하위 문서 추가" : "새 문서"}</DialogTitle>
        <DialogDescription>
          {parent ? (
            <>
              <DocCode>{parent.code}</DocCode> {parent.title} 아래에 만듭니다. 번호는 자동으로
              매겨집니다.
            </>
          ) : (
            "최상위 문서를 만듭니다. 번호는 자동으로 매겨집니다."
          )}
        </DialogDescription>
      </DialogHeader>

      {options.length > 1 && (
        <div className="grid gap-1.5 text-sm">
          <span className="font-medium">유형</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {options.map((option) => (
              <button
                key={option.code}
                type="button"
                onClick={() => setChosenType(option.code)}
                aria-pressed={docType === option.code}
                className={cn(
                  "rounded-lg border px-3 py-2 text-left transition-colors",
                  docType === option.code
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/50",
                )}
              >
                <span className="block font-medium">{option.name}</span>
                <span className="block text-xs text-muted-foreground">{option.description}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <Field label="제목">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          autoFocus
          maxLength={300}
          placeholder={options.find((o) => o.code === docType)?.name}
        />
      </Field>

      {needsScope && (
        <Field label="영역" hint="문서 번호에 들어갑니다. 예: POL-QMS-01">
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
      )}

      <DialogFooter>
        <Button type="submit" disabled={create.isPending || !docType}>
          만들고 작성 시작
        </Button>
      </DialogFooter>
    </form>
  );
}
