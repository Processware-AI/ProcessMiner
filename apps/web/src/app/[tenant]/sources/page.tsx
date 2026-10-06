"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRightIcon, FileUpIcon, ScrollTextIcon } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { EmptyState, ErrorState, Field, PageHeader } from "@/components/bits";
import { RunProgress, SourceStatusBadge } from "@/components/sources/source-bits";
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
import { type Source, uploadSource } from "@/lib/api";
import { keys, useSources, useTenant } from "@/lib/queries";
import { routes } from "@/lib/routes";

/** 원문 목록: 표준·법규 문서를 올리고 요건 도출 상태를 본다. */
export default function SourcesPage() {
  const { tenant } = useParams<{ tenant: string }>();
  const tenantQuery = useTenant(tenant);
  const sources = useSources(tenant);
  const [uploading, setUploading] = useState(false);
  const canManage = tenantQuery.data?.actions.includes("source.manage") ?? false;

  return (
    <div className="space-y-5">
      <PageHeader
        title="원문과 요건"
        description="표준·법규 원문을 올리면 조항별 요건을 뽑아 줍니다. 확정한 요건은 프로세스 문서의 근거가 됩니다."
        actions={
          canManage && (
            <Button onClick={() => setUploading(true)}>
              <FileUpIcon />
              원문 올리기
            </Button>
          )
        }
      />

      {sources.isPending && <Skeleton className="h-24" />}
      {sources.error && <ErrorState error={sources.error} />}
      {sources.data?.length === 0 && (
        <EmptyState
          icon={<ScrollTextIcon />}
          title="아직 올린 원문이 없습니다"
          description="조항 번호가 있는 표준·법규 PDF 를 올리세요. 원문은 이 회사 안에서만 보관하고 다른 회사와 공유하지 않습니다."
          action={
            canManage && (
              <Button onClick={() => setUploading(true)}>
                <FileUpIcon />
                원문 올리기
              </Button>
            )
          }
        />
      )}

      <ul className="space-y-2">
        {sources.data?.map((source) => (
          <li key={source.id}>
            <SourceCard tenant={tenant} source={source} />
          </li>
        ))}
      </ul>

      <Dialog open={uploading} onOpenChange={setUploading}>
        <DialogContent>
          {uploading && <UploadForm tenant={tenant} onDone={() => setUploading(false)} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SourceCard({ tenant, source }: { tenant: string; source: Source }) {
  const { requirements } = source;
  const live = requirements.proposed + requirements.confirmed;
  return (
    <Link
      href={routes.source(tenant, source.id)}
      className="group block rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:border-ring/60"
    >
      <div className="flex items-center gap-3">
        <ScrollTextIcon className="size-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{source.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            <span className="font-mono">{source.code}</span>
            {source.edition && ` · ${source.edition}`} · {source.page_count}쪽 · 조항{" "}
            {source.clause_count}개
            {live > 0 && ` · 요건 ${live}건`}
            {requirements.unverified > 0 && ` · 인용 미확인 ${requirements.unverified}건`}
          </p>
        </div>
        <SourceStatusBadge status={source.status} />
        <ChevronRightIcon className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
      {source.run && (source.run.status === "queued" || source.run.status === "running") && (
        <div className="mt-3">
          <RunProgress run={source.run} compact />
        </div>
      )}
    </Link>
  );
}

function UploadForm({ tenant, onDone }: { tenant: string; onDone: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [edition, setEdition] = useState("");

  const upload = useMutation({
    mutationFn: () => uploadSource(tenant, { file: file!, title: title.trim(), code, edition }),
    onSuccess: async (source) => {
      await queryClient.invalidateQueries({ queryKey: keys.sources(tenant) });
      onDone();
      router.push(routes.source(tenant, source.id));
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (file) upload.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>원문 올리기</DialogTitle>
        <DialogDescription>
          PDF 를 올리면 바로 본문을 읽어 조항으로 나눕니다. 스캔 이미지로 된 PDF 는 아직 읽지
          못합니다.
        </DialogDescription>
      </DialogHeader>
      <Field label="파일">
        <Input
          type="file"
          accept="application/pdf,.pdf"
          required
          onChange={(event) => {
            const picked = event.target.files?.[0] ?? null;
            setFile(picked);
            // 제목을 비워 뒀으면 파일 이름으로 채워 준다.
            if (picked && !title) setTitle(picked.name.replace(/\.pdf$/i, ""));
          }}
        />
      </Field>
      <Field label="제목">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={300}
          placeholder="의료기기 소프트웨어 — 소프트웨어 수명주기 프로세스"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="약칭" hint="요건 번호 앞에 붙습니다. 영문 대문자·숫자.">
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            required
            pattern="[A-Z0-9][A-Z0-9._\-]{1,31}"
            placeholder="IEC62304"
            className="font-mono"
          />
        </Field>
        <Field label="판 (선택)">
          <Input
            value={edition}
            onChange={(e) => setEdition(e.target.value)}
            maxLength={100}
            placeholder="Ed 1.1 (2015)"
          />
        </Field>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={!file || upload.isPending}>
          {upload.isPending ? "읽는 중…" : "올리고 조항 분석"}
        </Button>
      </DialogFooter>
    </form>
  );
}
