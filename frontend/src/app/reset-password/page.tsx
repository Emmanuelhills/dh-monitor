"use client";

import { useEffect, useState } from "react";
import { Loading, PasswordInput } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

type Status = "checking" | "ready" | "invalid" | "done";

export default function ResetPasswordPage() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<Status>("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(t);
    if (!t) return setStatus("invalid");
    api.post<{ valid: boolean }>("/auth/reset-password/check", { token: t })
      .then((r) => setStatus(r.valid ? "ready" : "invalid"))
      .catch(() => setStatus("invalid"));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 12) return setError("Use at least 12 characters.");
    if (password !== confirm) return setError("The passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/reset-password", { token, new_password: password });
      window.history.replaceState(null, "", "/reset-password"); // drop the used token from the address bar
      setStatus("done");
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
            <h1>Choose a new password</h1>
          </div>
          {status === "checking" && <Loading label="Checking your link…" />}
          {status === "invalid" && (
            <>
              <div className="alert error" role="alert">
                This reset link is invalid, has already been used, or has expired.
              </div>
              <a className="btn primary" href="/forgot-password">Send a new link</a>
            </>
          )}
          {status === "done" && (
            <>
              <div className="alert success" role="status">
                Your password has been changed. You&apos;ve been signed out everywhere else.
              </div>
              <a className="btn primary" href="/login">Sign in</a>
            </>
          )}
          {status === "ready" && (
            <>
              {error && <div className="alert error" role="alert">{error}</div>}
              <div className="field">
                <label htmlFor="new-password">New password</label>
                <PasswordInput id="new-password" autoComplete="new-password" value={password} autoFocus
                  onChange={(e) => setPassword(e.target.value)} />
                <span className="hint">At least 12 characters.</span>
              </div>
              <div className="field">
                <label htmlFor="confirm-password">Repeat new password</label>
                <PasswordInput id="confirm-password" autoComplete="new-password" value={confirm}
                  onChange={(e) => setConfirm(e.target.value)} />
              </div>
              <button className="btn primary" type="submit" disabled={busy || !password || !confirm}>
                {busy && <span className="spinner" aria-hidden />} Save new password
              </button>
            </>
          )}
          {status !== "done" && <a className="small" href="/login" style={{ textAlign: "center" }}>Back to sign in</a>}
        </form>
      </div>
    </div>
  );
}
