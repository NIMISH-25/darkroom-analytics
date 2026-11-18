"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { DEMO_PASS, DEMO_USER, login } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      router.replace("/overview");
    } catch {
      setError("Sign in failed. Check the username and password.");
    } finally {
      setBusy(false);
    }
  }

  const inputCls = "h-9 w-full border border-border bg-transparent px-3 text-sm outline-none focus:border-foreground";

  return (
    <form onSubmit={submit} className="flex w-[420px] flex-col gap-4 border border-border p-8">
      <h1 className="text-xl font-semibold tracking-tight">Darkroom Analytics</h1>
      <p className="text-sm text-muted-foreground">
        This environment runs on pre-loaded synthetic demo data for Northlight&apos;s 5 TikTok Shop brands. Use the demo session below to explore the workspace.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        Username
        <input className={inputCls} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Password
        <input className={inputCls} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      </label>
      <p className="text-sm text-muted-foreground">
        Demo login: <span className="font-mono">{DEMO_USER}</span> / <span className="font-mono">{DEMO_PASS}</span>
      </p>
      {error && <div className="text-sm text-rose-500">{error}</div>}
      <Button type="submit" size="lg" disabled={busy}>{busy ? "Signing in..." : "Sign In"}</Button>
    </form>
  );
}
