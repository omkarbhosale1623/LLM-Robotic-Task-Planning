"use client";

import { Cpu, LogIn, UserPlus } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useAuth } from "@/components/AuthProvider";

/**
 * Login gate: renders the email/password sign-in / sign-up form when there is no
 * Supabase session, and only renders the app UI (`children`) once authenticated.
 *
 * When Supabase is not configured (no NEXT_PUBLIC_SUPABASE_* env), it shows a
 * clear setup note instead of a broken form.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { session, loading, configured, signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }

  if (session) {
    return <>{children}</>;
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      if (mode === "signin") {
        await signIn(email, password);
      } else {
        await signUp(email, password);
        setInfo("Account created. Check your email to confirm, then sign in.");
        setMode("signin");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-2 px-6 pt-6 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <Cpu className="h-6 w-6" />
          </div>
          <h1 className="text-lg font-semibold text-slate-100">
            LLM Robotic Task Planner
          </h1>
          <p className="text-xs text-slate-400">
            Sign in to plan and execute robot tasks.
          </p>
        </div>

        {!configured ? (
          <div className="px-6 py-6 text-sm text-warn">
            Supabase is not configured. Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
            <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in <code>.env.local</code> to
            enable login.
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-3 px-6 py-6">
            <div>
              <label className="mb-1 block text-xs text-slate-400">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm text-slate-100 focus:border-accent/60 focus:outline-none"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-sm text-slate-100 focus:border-accent/60 focus:outline-none"
                placeholder="••••••••"
              />
            </div>

            {error && <p className="text-xs text-bad">{error}</p>}
            {info && <p className="text-xs text-ok">{info}</p>}

            <Button type="submit" disabled={busy} className="w-full">
              {mode === "signin" ? (
                <>
                  <LogIn className="h-4 w-4" /> Sign in
                </>
              ) : (
                <>
                  <UserPlus className="h-4 w-4" /> Create account
                </>
              )}
            </Button>

            <button
              type="button"
              onClick={() => {
                setMode(mode === "signin" ? "signup" : "signin");
                setError(null);
                setInfo(null);
              }}
              className="w-full text-center text-xs text-slate-400 hover:text-slate-200"
            >
              {mode === "signin"
                ? "Need an account? Sign up"
                : "Already have an account? Sign in"}
            </button>
          </form>
        )}
      </Card>
    </div>
  );
}
