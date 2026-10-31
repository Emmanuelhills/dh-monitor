"use client";

import { useState } from "react";
import { api, errorMessage } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/forgot-password", { email: email.trim() });
      setSent(true);
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
            <h1>Reset your password</h1>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              Enter your sign-in email and we&apos;ll send you a link to choose a new password.
            </p>
          </div>
          {sent ? (
            <div className="alert success" role="status">
              If <strong>{email.trim()}</strong> belongs to an administrator, a reset link is on its way. It works once
              and expires in 1 hour. Check your spam folder if it doesn&apos;t arrive in a few minutes.
            </div>
          ) : (
            <>
              {error && <div className="alert error" role="alert">{error}</div>}
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="username" required value={email} autoFocus
                  onChange={(e) => setEmail(e.target.value)} />
              </div>
              <button className="btn primary" type="submit" disabled={busy || !email.trim()}>
                {busy && <span className="spinner" aria-hidden />} Send reset link
              </button>
            </>
          )}
          <a className="small" href="/login" style={{ textAlign: "center" }}>Back to sign in</a>
        </form>
      </div>
    </div>
  );
}
