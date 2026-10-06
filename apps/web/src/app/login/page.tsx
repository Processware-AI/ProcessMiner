"use client";

import { useMutation } from "@tanstack/react-query";
import { MailCheckIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { Field } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, unwrap } from "@/lib/api";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const request = useMutation({
    mutationFn: (email: string) =>
      unwrap(api.POST("/api/auth/request-link", { body: { email } })),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    request.mutate(email.trim());
  }

  // 개발 설정에서는 메일 대신 링크가 응답에 담겨 온다.
  const devLink = request.data?.dev_link
    ? new URL(request.data.dev_link).pathname +
      new URL(request.data.dev_link).search +
      (next ? `&next=${encodeURIComponent(next)}` : "")
    : null;

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icon.svg" alt="" className="size-8 rounded-lg" />
          <span className="text-lg font-semibold tracking-tight">ProcessMiner</span>
        </div>

        {request.isSuccess ? (
          <div className="space-y-4">
            <MailCheckIcon className="size-8 text-primary" />
            <div>
              <h1 className="text-xl font-semibold tracking-tight">메일을 확인하세요</h1>
              <p className="mt-1.5 text-sm text-muted-foreground text-pretty">
                등록된 주소라면 <span className="font-medium text-foreground">{email}</span> 로
                로그인 링크를 보냈습니다. 링크는 15분 동안 한 번만 쓸 수 있습니다.
              </p>
            </div>
            {devLink && (
              <div className="rounded-lg border border-dashed border-border p-3">
                <p className="mb-2 text-xs text-muted-foreground">
                  개발 설정이라 메일을 보내지 않았습니다.
                </p>
                <Button className="w-full" onClick={() => window.location.assign(devLink)}>
                  바로 로그인
                </Button>
              </div>
            )}
            <Button variant="ghost" className="w-full" onClick={() => request.reset()}>
              다른 주소로 다시 받기
            </Button>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">로그인</h1>
              <p className="mt-1.5 text-sm text-muted-foreground">
                이메일로 로그인 링크를 보내 드립니다.
              </p>
            </div>
            <Field label="이메일">
              <Input
                type="email"
                inputMode="email"
                autoComplete="email"
                autoFocus
                required
                placeholder="name@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            <Button type="submit" className="w-full" disabled={request.isPending}>
              {request.isPending ? "보내는 중…" : "로그인 링크 받기"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
