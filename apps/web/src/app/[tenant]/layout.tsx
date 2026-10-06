import { AppShell } from "@/components/shell/app-shell";

export default function TenantLayout({ children }: LayoutProps<"/[tenant]">) {
  return <AppShell>{children}</AppShell>;
}
