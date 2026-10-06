"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { LinkButton } from "@/components/bits";
import { api, ApiError, unwrap } from "@/lib/api";

export default function VerifyPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}

function Verify() {
  const params = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const token = params.get("token");
  const [failure, setFailure] = useState<string | null>(null);
  const error = token ? failure : "로그인 링크가 올바르지 않습니다.";
  const started = useRef(false);

  useEffect(() => {
    // 토큰은 한 번만 쓸 수 있으므로 개발 모드의 이중 실행에서도 한 번만 보낸다.
    if (started.current || !token) return;
    started.current = true;

    const next = params.get("next");
    unwrap(api.POST("/api/auth/verify", { body: { token } }))
      .then(() => {
        queryClient.clear();
        // 외부 주소로 보내지 않도록 사이트 안의 경로만 허용한다.
        router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
      })
      .catch((e: unknown) =>
        setFailure(e instanceof ApiError ? e.message : "로그인하지 못했습니다."),
      );
  }, [token, params, router, queryClient]);

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      {error ? (
        <div className="w-full max-w-sm space-y-4 text-center">
          <p className="font-medium">{error}</p>
          <LinkButton href="/login">로그인 링크 다시 받기</LinkButton>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">로그인하는 중…</p>
      )}
    </div>
  );
}
