"use client";

import { useTheme } from "next-themes";
import { useEffect, useId, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/** 문서 본문 표시. 원시 HTML 은 렌더링하지 않는다(react-markdown 기본 동작). */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-doc", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="table-wrap">
              <table>{children}</table>
            </div>
          ),
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children }) => {
            const text = String(children ?? "");
            const language = /language-(\w+)/.exec(className ?? "")?.[1];
            if (language === "mermaid") return <Mermaid chart={text.trim()} />;
            // 여러 줄이면 코드 블록, 아니면 문장 속 코드
            if (language || text.includes("\n")) {
              return (
                <pre>
                  <code>{text.replace(/\n$/, "")}</code>
                </pre>
              );
            }
            return <code>{children}</code>;
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

function Mermaid({ chart }: { chart: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const { resolvedTheme } = useTheme();
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 무거운 라이브러리라 흐름도가 있는 문서에서만 불러온다.
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: resolvedTheme === "dark" ? "dark" : "neutral",
          fontFamily: "inherit",
        });
        const { svg } = await mermaid.render(`mermaid-${id}`, chart);
        if (!cancelled) {
          setSvg(svg);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, id, resolvedTheme]);

  if (failed) {
    return (
      <pre>
        <code>{chart}</code>
      </pre>
    );
  }
  if (svg === null) return <div className="h-32 animate-pulse rounded-lg bg-muted" />;
  return (
    <div
      className="flex justify-center overflow-x-auto rounded-lg border border-border bg-card p-4 [&_svg]:h-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
