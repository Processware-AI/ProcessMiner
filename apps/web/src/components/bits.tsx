import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { DOC_TYPE_STYLE, STATUS_LABEL, STATUS_STYLE } from "@/lib/labels";
import { cn } from "@/lib/utils";

const pill = "inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-xs font-medium";

export function StatusBadge({ status, version }: { status: string; version?: string | null }) {
  return (
    <span className={cn(pill, STATUS_STYLE[status] ?? STATUS_STYLE.superseded)}>
      {STATUS_LABEL[status] ?? status}
      {version && <span className="ml-1 font-mono opacity-80">v{version}</span>}
    </span>
  );
}

export function TypeBadge({ type }: { type: string }) {
  return (
    <span className={cn(pill, "w-10 justify-center font-mono", DOC_TYPE_STYLE[type])}>{type}</span>
  );
}

export function DocCode({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("font-mono text-xs text-muted-foreground", className)}>{children}</span>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground text-pretty">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-border px-6 py-12 text-center">
      {icon && <div className="mb-3 text-muted-foreground [&_svg]:size-7">{icon}</div>}
      <p className="font-medium">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-muted-foreground text-pretty">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      {error.message}
    </div>
  );
}

/** 모바일에서 기기 기본 선택기가 뜨도록 네이티브 select 를 쓴다. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30",
        className,
      )}
      {...props}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

/** 버튼 모양의 링크. */
export function LinkButton({
  href,
  ...props
}: Omit<ComponentProps<typeof Button>, "render" | "nativeButton"> & { href: string }) {
  return <Button nativeButton={false} render={<Link href={href} />} {...props} />;
}
