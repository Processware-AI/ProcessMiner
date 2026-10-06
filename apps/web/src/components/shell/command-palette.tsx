"use client";

import {
  HistoryIcon,
  InboxIcon,
  LibraryIcon,
  MoonIcon,
  NetworkIcon,
  ScrollTextIcon,
  SettingsIcon,
  SunIcon,
  UsersIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect } from "react";

import { TypeBadge } from "@/components/bits";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import type { System } from "@/lib/api";
import { useDocuments } from "@/lib/queries";
import { routes } from "@/lib/routes";

export function CommandPalette({
  open,
  onOpenChange,
  tenant,
  system,
  systems,
  canManage,
  canReadAudit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: string;
  system: string | undefined;
  systems: System[];
  canManage: boolean;
  canReadAudit: boolean;
}) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  // 문서 검색은 보고 있는 체계(없으면 첫 체계)를 대상으로 한다.
  const searchSystem = system ?? systems[0]?.slug;
  const documents = useDocuments(tenant, open ? searchSystem : undefined);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  function go(href: string) {
    onOpenChange(false);
    router.push(href);
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="검색 또는 이동"
      description="문서 번호나 제목, 화면 이름으로 찾습니다."
      className="sm:max-w-xl"
    >
      <CommandInput placeholder="문서 번호·제목 또는 화면 이름" />
      <CommandList>
        <CommandEmpty>일치하는 항목이 없습니다.</CommandEmpty>

        {searchSystem && (documents.data?.length ?? 0) > 0 && (
          <CommandGroup heading="문서">
            {documents.data!.map((doc) => (
              <CommandItem
                key={doc.id}
                value={`${doc.code} ${doc.title}`}
                onSelect={() => go(routes.document(tenant, searchSystem, doc.id))}
              >
                <TypeBadge type={doc.doc_type} />
                <span className="min-w-0 flex-1 truncate">{doc.title}</span>
                <CommandShortcut className="font-mono">{doc.code}</CommandShortcut>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        <CommandGroup heading="이동">
          <CommandItem value="받은 일 홈" onSelect={() => go(routes.home(tenant))}>
            <InboxIcon />
            받은 일
          </CommandItem>
          {systems.map((s) => (
            <CommandItem
              key={s.id}
              value={`체계 ${s.name} ${s.slug}`}
              onSelect={() => go(routes.library(tenant, s.slug))}
            >
              <LibraryIcon />
              {s.name}
            </CommandItem>
          ))}
          <CommandItem value="원문 요건 표준 법규" onSelect={() => go(routes.sources(tenant))}>
            <ScrollTextIcon />
            원문과 요건
          </CommandItem>
          <CommandItem value="조직 체계 관리" onSelect={() => go(routes.org(tenant))}>
            <NetworkIcon />
            조직·체계
          </CommandItem>
          <CommandItem value="구성원 권한" onSelect={() => go(routes.members(tenant))}>
            <UsersIcon />
            구성원
          </CommandItem>
          {canReadAudit && (
            <CommandItem value="감사 기록 이력" onSelect={() => go(routes.audit(tenant))}>
              <HistoryIcon />
              감사 기록
            </CommandItem>
          )}
          {canManage && (
            <CommandItem value="설정" onSelect={() => go(routes.settings(tenant))}>
              <SettingsIcon />
              설정
            </CommandItem>
          )}
        </CommandGroup>

        <CommandGroup heading="화면">
          <CommandItem
            value="테마 밝게 어둡게 전환"
            onSelect={() => {
              setTheme(resolvedTheme === "dark" ? "light" : "dark");
              onOpenChange(false);
            }}
          >
            {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
            {resolvedTheme === "dark" ? "밝은 화면으로" : "어두운 화면으로"}
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
