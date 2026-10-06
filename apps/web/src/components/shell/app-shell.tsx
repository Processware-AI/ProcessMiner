"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ArchiveIcon,
  Building2Icon,
  CheckIcon,
  ChevronsUpDownIcon,
  FolderTreeIcon,
  HistoryIcon,
  InboxIcon,
  LibraryIcon,
  LogOutIcon,
  MenuIcon,
  MonitorIcon,
  MoonIcon,
  NetworkIcon,
  ScrollTextIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
  UsersIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { type ReactNode, useMemo, useState } from "react";

import { ErrorState, LinkButton } from "@/components/bits";
import { CommandPalette } from "@/components/shell/command-palette";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type System, unwrap } from "@/lib/api";
import { useInbox, useMe, useSystems, useTenant } from "@/lib/queries";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/** 상위 체계 아래에 하위 체계가 오도록 정렬하고 깊이를 붙인다. */
export function systemTree(systems: System[]): { system: System; depth: number }[] {
  const byParent = new Map<string | null, System[]>();
  for (const system of systems) {
    const key = system.parent_system_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), system]);
  }
  const out: { system: System; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const system of byParent.get(parent) ?? []) {
      out.push({ system, depth });
      walk(system.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { tenant, system } = useParams<{ tenant: string; system?: string }>();
  const pathname = usePathname();
  const tenantQuery = useTenant(tenant);
  const systemsQuery = useSystems(tenant);
  const inboxQuery = useInbox(tenant);
  const [menuOpen, setMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const systems = useMemo(() => systemTree(systemsQuery.data ?? []), [systemsQuery.data]);
  const attention = (inboxQuery.data ?? []).filter(
    (item) => item.kind === "to_review" || item.kind === "returned",
  ).length;
  const actions = tenantQuery.data?.actions ?? [];
  // 보관된 회사에서는 설정을 바꿀 수 없지만, 복원·삭제를 하러 설정 화면에는 들어갈 수 있어야 한다.
  const canOpenSettings = ["tenant.manage", "tenant.restore", "tenant.delete"].some((a) =>
    actions.includes(a),
  );
  const archived = Boolean(tenantQuery.data?.archived_at);
  // 모바일 하단 '문서' 는 보고 있던 체계, 없으면 첫 체계로 간다.
  const librarySlug = system ?? systems[0]?.system.slug;

  if (tenantQuery.error) {
    return (
      <div className="mx-auto grid min-h-dvh max-w-md place-content-center gap-4 p-6">
        <ErrorState error={tenantQuery.error} />
        <LinkButton variant="outline" href="/">
          회사 목록으로
        </LinkButton>
      </div>
    );
  }

  const nav = (
    <SidebarNav
      tenant={tenant}
      pathname={pathname}
      systems={systems}
      loading={systemsQuery.isPending}
      attention={attention}
      canManage={canOpenSettings}
      canReadAudit={actions.includes("audit_log.read")}
      onNavigate={() => setMenuOpen(false)}
      onSearch={() => {
        setMenuOpen(false);
        setPaletteOpen(true);
      }}
    />
  );

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
        {nav}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur md:hidden">
          <Button variant="ghost" size="icon" aria-label="메뉴" onClick={() => setMenuOpen(true)}>
            <MenuIcon />
          </Button>
          <span className="min-w-0 flex-1 truncate text-sm font-medium">
            {tenantQuery.data?.name}
          </span>
          <Button variant="ghost" size="icon" aria-label="검색" onClick={() => setPaletteOpen(true)}>
            <SearchIcon />
          </Button>
        </header>

        {archived && (
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm">
            <span className="flex items-center gap-1.5">
              <ArchiveIcon className="size-4 shrink-0" />
              보관된 회사입니다. 읽기만 가능합니다.
            </span>
            {canOpenSettings && pathname !== routes.settings(tenant) && (
              <Link href={routes.settings(tenant)} className="font-medium underline underline-offset-3">
                복원 또는 삭제
              </Link>
            )}
          </div>
        )}

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-5 pb-24 sm:px-6 md:px-8 md:pt-8 md:pb-12">
          {children}
        </main>

        <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-background/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
          <BottomLink
            href={routes.home(tenant)}
            active={pathname === routes.home(tenant)}
            icon={<InboxIcon />}
            label="받은 일"
            badge={attention}
          />
          <BottomLink
            href={librarySlug ? routes.library(tenant, librarySlug) : routes.org(tenant)}
            active={pathname.startsWith(`/${tenant}/s/`)}
            icon={<LibraryIcon />}
            label="문서"
          />
          <BottomButton icon={<SearchIcon />} label="검색" onClick={() => setPaletteOpen(true)} />
          <BottomButton icon={<MenuIcon />} label="메뉴" onClick={() => setMenuOpen(true)} />
        </nav>
      </div>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-72 gap-0 bg-sidebar p-0" showCloseButton={false}>
          <SheetTitle className="sr-only">메뉴</SheetTitle>
          <SheetDescription className="sr-only">화면 이동과 계정 메뉴</SheetDescription>
          {nav}
        </SheetContent>
      </Sheet>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        tenant={tenant}
        system={system}
        systems={systems.map((s) => s.system)}
        canManage={canOpenSettings}
        canReadAudit={actions.includes("audit_log.read")}
      />
    </div>
  );
}

function SidebarNav({
  tenant,
  pathname,
  systems,
  loading,
  attention,
  canManage,
  canReadAudit,
  onNavigate,
  onSearch,
}: {
  tenant: string;
  pathname: string;
  systems: { system: System; depth: number }[];
  loading: boolean;
  attention: number;
  canManage: boolean;
  canReadAudit: boolean;
  onNavigate: () => void;
  onSearch: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="p-2">
        <TenantSwitcher tenant={tenant} />
      </div>
      <div className="px-2 pb-2">
        <button
          type="button"
          onClick={onSearch}
          className="flex h-8 w-full items-center gap-2 rounded-lg border border-sidebar-border bg-background/60 px-2.5 text-sm text-muted-foreground transition-colors hover:bg-background"
        >
          <SearchIcon className="size-4" />
          <span className="flex-1 text-left">검색 또는 이동</span>
          <kbd className="hidden rounded border border-border bg-muted px-1 font-mono text-[10px] md:inline">
            Ctrl K
          </kbd>
        </button>
      </div>

      <nav className="min-h-0 flex-1 space-y-4 overflow-y-auto px-2 py-1">
        <div className="space-y-0.5">
          <NavLink
            href={routes.home(tenant)}
            active={pathname === routes.home(tenant)}
            icon={<InboxIcon />}
            onNavigate={onNavigate}
            badge={attention}
          >
            받은 일
          </NavLink>
        </div>

        <div className="space-y-0.5">
          <NavHeading>체계</NavHeading>
          {loading && <Skeleton className="mx-2 h-7" />}
          {!loading && systems.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">아직 체계가 없습니다.</p>
          )}
          {systems.map(({ system, depth }) => {
            const href = routes.library(tenant, system.slug);
            return (
              <NavLink
                key={system.id}
                href={href}
                active={pathname === href || pathname.startsWith(`${href}/`)}
                icon={depth === 0 ? <LibraryIcon /> : <FolderTreeIcon />}
                onNavigate={onNavigate}
                depth={depth}
              >
                {system.name}
              </NavLink>
            );
          })}
        </div>

        <div className="space-y-0.5">
          <NavHeading>근거</NavHeading>
          <NavLink
            href={routes.sources(tenant)}
            active={pathname.startsWith(routes.sources(tenant))}
            icon={<ScrollTextIcon />}
            onNavigate={onNavigate}
          >
            원문과 요건
          </NavLink>
        </div>

        <div className="space-y-0.5">
          <NavHeading>관리</NavHeading>
          <NavLink
            href={routes.org(tenant)}
            active={pathname === routes.org(tenant)}
            icon={<NetworkIcon />}
            onNavigate={onNavigate}
          >
            조직·체계
          </NavLink>
          <NavLink
            href={routes.members(tenant)}
            active={pathname === routes.members(tenant)}
            icon={<UsersIcon />}
            onNavigate={onNavigate}
          >
            구성원
          </NavLink>
          {canReadAudit && (
            <NavLink
              href={routes.audit(tenant)}
              active={pathname === routes.audit(tenant)}
              icon={<HistoryIcon />}
              onNavigate={onNavigate}
            >
              감사 기록
            </NavLink>
          )}
          {canManage && (
            <NavLink
              href={routes.settings(tenant)}
              active={pathname === routes.settings(tenant)}
              icon={<SettingsIcon />}
              onNavigate={onNavigate}
            >
              설정
            </NavLink>
          )}
        </div>
      </nav>

      <div className="border-t border-sidebar-border p-2">
        <UserMenu />
      </div>
    </div>
  );
}

function NavHeading({ children }: { children: ReactNode }) {
  return <p className="px-2 pb-1 text-xs font-medium text-muted-foreground">{children}</p>;
}

function NavLink({
  href,
  active,
  icon,
  children,
  onNavigate,
  badge = 0,
  depth = 0,
}: {
  href: string;
  active: boolean;
  icon: ReactNode;
  children: ReactNode;
  onNavigate: () => void;
  badge?: number;
  depth?: number;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      style={{ paddingLeft: `${0.5 + depth * 0.875}rem` }}
      className={cn(
        "flex h-8 items-center gap-2 rounded-lg pr-2 text-sm transition-colors [&_svg]:size-4 [&_svg]:shrink-0",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {badge > 0 && (
        <span className="rounded-full bg-primary px-1.5 text-[11px] leading-5 font-medium text-primary-foreground">
          {badge}
        </span>
      )}
    </Link>
  );
}

const bottomItem =
  "relative flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground [&_svg]:size-5";

function BottomLink({
  href,
  active,
  icon,
  label,
  badge = 0,
}: {
  href: string;
  active: boolean;
  icon: ReactNode;
  label: string;
  badge?: number;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(bottomItem, active && "font-medium text-primary")}
    >
      <span className="relative">
        {icon}
        {badge > 0 && (
          <span className="absolute -top-1 -right-2 rounded-full bg-primary px-1 text-[10px] leading-4 font-medium text-primary-foreground">
            {badge}
          </span>
        )}
      </span>
      {label}
    </Link>
  );
}

function BottomButton({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className={bottomItem}>
      {icon}
      {label}
    </button>
  );
}

function TenantSwitcher({ tenant }: { tenant: string }) {
  const me = useMe();
  const current = me.data?.tenants.find((t) => t.slug === tenant);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            className="flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left transition-colors hover:bg-sidebar-accent/60"
          />
        }
      >
        <span className="grid size-6 shrink-0 place-content-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
          {(current?.name ?? tenant).slice(0, 1)}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {current?.name ?? tenant}
        </span>
        <ChevronsUpDownIcon className="size-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="min-w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel>회사</DropdownMenuLabel>
          {(me.data?.tenants ?? []).map((t) => (
            <DropdownMenuItem key={t.id} render={<Link href={routes.home(t.slug)} />}>
              <Building2Icon />
              <span className="min-w-0 flex-1 truncate">{t.name}</span>
              {t.archived_at && <span className="text-xs text-muted-foreground">보관됨</span>}
              {t.slug === tenant && <CheckIcon />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/" />}>전체 회사 보기</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const me = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { theme, setTheme } = useTheme();

  async function logout() {
    await unwrap(api.POST("/api/auth/logout"));
    queryClient.clear();
    router.replace("/login");
  }

  const themes = [
    { value: "light", label: "밝게", icon: <SunIcon /> },
    { value: "dark", label: "어둡게", icon: <MoonIcon /> },
    { value: "system", label: "기기 설정", icon: <MonitorIcon /> },
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            className="flex h-10 w-full items-center gap-2 rounded-lg px-2 text-left transition-colors hover:bg-sidebar-accent/60"
          />
        }
      >
        <span className="grid size-6 shrink-0 place-content-center rounded-full bg-muted text-xs font-medium">
          {me.data?.user.name.slice(0, 1)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm leading-tight font-medium">
            {me.data?.user.name}
          </span>
          <span className="block truncate text-xs leading-tight text-muted-foreground">
            {me.data?.user.email}
          </span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="min-w-52">
        <DropdownMenuGroup>
          <DropdownMenuLabel>화면</DropdownMenuLabel>
          {themes.map((option) => (
            <DropdownMenuItem key={option.value} onClick={() => setTheme(option.value)}>
              {option.icon}
              <span className="flex-1">{option.label}</span>
              {theme === option.value && <CheckIcon />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={logout}>
          <LogOutIcon />
          로그아웃
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
