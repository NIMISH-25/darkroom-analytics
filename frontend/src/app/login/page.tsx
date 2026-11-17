"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { DEMO_PASS, DEMO_USER, login } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function enter() {
    setBusy(true);
    setError(null);
    try {
      await login(DEMO_USER, DEMO_PASS);
      router.replace("/overview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex w-[420px] flex-col gap-4 border border-border p-8">
      <h1 className="text-xl font-semibold tracking-tight">Darkroom Analytics</h1>
      <p className="text-sm text-muted-foreground">
        This environment runs on pre-loaded synthetic demo data for Northlight&apos;s 5 TikTok Shop brands. Use the demo session below to explore the workspace.
      </p>
      {error && <div className="text-sm text-rose-500">{error}</div>}
      <Button size="lg" disabled={busy} onClick={enter}>{busy ? "Entering..." : "Enter Demo Workspace"}</Button>
    </div>
  );
}
