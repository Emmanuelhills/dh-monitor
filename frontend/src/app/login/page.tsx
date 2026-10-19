"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function safeNext(): string {
  if (typeof window === "undefined") return "/dashboard";
  const next = new URLSearchParams(window.location.search).get("next") || "/dashboard";
  // Only same-site relative paths.
  return next.startsWith("/") && !next.startsWith("//") && next !== "/login" && next !== "/" ? next : "/dashboard";
}

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace(safeNext());
  }, [loading, user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace(safeNext());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <form className="card-body form" onSubmit={submit} noValidate>
          <div>
            <div className="brand-mark" style={{ marginBottom: 18 }}>Domain Monitor</div>
            <h1>Welcome back</h1>
            <p className="muted" style={{ margin: "6px 0 0" }}>Sign in to manage domains, hosting and reminders.</p>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="username" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button className="btn primary" type="submit" disabled={busy || !email || !password}>
            {busy && <span className="spinner" aria-hidden />} Sign in
          </button>
          <a className="small" href="/" style={{ textAlign: "center" }}>View the public overview</a>
        </form>
      </div>
    </div>
  );
}
