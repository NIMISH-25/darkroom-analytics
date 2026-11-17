"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AlertTriangle, Activity, LayoutDashboard, LogOut, Stethoscope, Users, Package, Store } from "lucide-react";
import { clearToken, getToken, USE_MOCKS } from "@/lib/api";
import { useMeta } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { HatchDefs } from "./HatchDefs";

const NAV = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/attention", label: "Attention", icon: AlertTriangle },
  { href: "/creators", label: "Creators", icon: Users },
  { href: "/samples", label: "Samples", icon: Package },
  { href: "/diagnostics", label: "Diagnostics", icon: Stethoscope },
  { href: "/health", label: "Data health", icon: Activity },
];

function Sidebar({ path }: { path: string }) {
  const { data: meta } = useMeta();
  const router = useRouter();
  const link = (active: boolean) =>
    cn("flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground", active && "bg-accent text-foreground");
  return (
    <aside className="sticky top-0 flex h-screen w-[250px] shrink-0 flex-col border-r border-border">
      <div className="border-b border-border px-3 py-3 text-sm font-semibold tracking-tight">Darkroom</div>
      <nav className="flex-1 overflow-y-auto py-2">
        <Link href="/overview" className={link(path === "/overview")}><LayoutDashboard className="h-3.5 w-3.5" />Overview</Link>
        <div className="mt-3 flex items-center gap-2 px-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground"><Store className="h-3 w-3" />Brands</div>
        {meta?.brands.map((b) => (
          <Link key={b.brand_id} href={`/brands/${b.brand_id}`} className={link(path === `/brands/${b.brand_id}`)}>
            <span className="w-3.5" />{b.name}
          </Link>
        ))}
        <div className="mt-3 px-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground">Portfolio</div>
        {NAV.slice(1).map((n) => (
          <Link key={n.href} href={n.href} className={link(path === n.href)}><n.icon className="h-3.5 w-3.5" />{n.label}</Link>
        ))}
      </nav>
      <div className="space-y-2 border-t border-border p-3 text-xs text-muted-foreground">
        <div className="font-mono tabular-nums tracking-tight">rev {meta?.data_revision ?? "UNAVAILABLE"}</div>
        {USE_MOCKS && <div className="font-mono uppercase text-amber-500">mock data</div>}
        <Button variant="outline" size="sm" className="w-full" onClick={() => { clearToken(); router.replace("/login"); }}>
          <LogOut className="h-4 w-4" />Logout
        </Button>
      </div>
    </aside>
  );
}

function TopBar() {
  const router = useRouter();
  const { data: meta } = useMeta();
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-8 text-sm">
      <span className="font-mono tabular-nums tracking-tight text-muted-foreground">
        as of {meta?.default_cutoff ?? "UNAVAILABLE"} · rev {meta?.data_revision ?? "UNAVAILABLE"}
      </span>
      <Button variant="outline" onClick={() => { clearToken(); router.replace("/login"); }}>
        <LogOut className="h-4 w-4" />Logout
      </Button>
    </header>
  );
}

/** Sidebar + content frame with auth guard. `/login` renders bare. Defines the #missing-data-hatch SVG pattern once. */
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const isLogin = path === "/login";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isLogin && !getToken()) router.replace("/login");
    else setReady(true);
  }, [isLogin, router, path]);

  if (isLogin) return <main className="flex min-h-screen items-start justify-center pt-24">{children}</main>;
  if (!ready) return null;
  return (
    <div className="flex min-h-screen">
      <HatchDefs />
      <Sidebar path={path} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-w-0 flex-1 p-8">{children}</main>
      </div>
    </div>
  );
}
