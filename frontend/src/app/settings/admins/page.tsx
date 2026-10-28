"use client";

import { useState } from "react";
import { useToast } from "@/components/Toast";
import { ConfirmButton, ErrorAlert, Field, Loading, PasswordInput } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, relativeTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { Admin } from "@/lib/types";

function AddAdminForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!email.trim()) next.email = "Enter an email address.";
    if (password.length < 12) next.password = "Use at least 12 characters.";
    else if (password !== confirm) next.confirm = "The passwords do not match.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    setFormError(null);
    try {
      await api.post("/users", { email: email.trim(), password });
      toast("success", `${email.trim()} can now sign in.`);
      onDone();
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form card-body" onSubmit={submit} noValidate>
      {formError && <div className="alert error" role="alert">{formError}</div>}
      <div className="form-grid">
        <Field label="Email" htmlFor="adm-email" error={errors.email}>
          <input id="adm-email" type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </Field>
        <Field label="Password" htmlFor="adm-pw" error={errors.password}
          hint="At least 12 characters. Share it with them privately; they can change it under Settings → General.">
          <PasswordInput id="adm-pw" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Repeat password" htmlFor="adm-pw2" error={errors.confirm}>
          <PasswordInput id="adm-pw2" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} Add administrator
        </button>
      </div>
    </form>
  );
}

export default function AdminsPage() {
  const toast = useToast();
  const { user } = useAuth();
  const list = useAsync(() => api.get<Admin[]>("/users"), []);
  const [adding, setAdding] = useState(false);

  async function remove(a: Admin) {
    try {
      await api.del(`/users/${a.id}`);
      toast("success", `${a.email} removed.`);
      list.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Administrators</h1>
          <p>People who can sign in and manage domains, hosting and settings.</p>
        </div>
        {!adding && <button className="btn primary" onClick={() => setAdding(true)}>Add administrator</button>}
      </div>

      {adding && (
        <section className="card section">
          <div className="card-header"><h2>New administrator</h2></div>
          <AddAdminForm onCancel={() => setAdding(false)} onDone={() => { setAdding(false); list.reload(); }} />
        </section>
      )}

      <section className="card section">
        {list.error && <div className="card-body"><ErrorAlert message={list.error} onRetry={list.reload} /></div>}
        {list.loading && !list.data && <Loading />}
        {list.data && (
          <div className="table-wrap">
            <table className="data responsive">
              <thead>
                <tr><th>Email</th><th>Added</th><th>Last sign-in</th><th /></tr>
              </thead>
              <tbody>
                {list.data.map((a) => (
                  <tr key={a.id}>
                    <td className="name" data-label="Email">
                      {a.email}
                      {a.id === user?.id && <span className="sub">You</span>}
                    </td>
                    <td data-label="Added">{formatDate(a.created_at.slice(0, 10))}</td>
                    <td data-label="Last sign-in">{a.last_login_at ? relativeTime(a.last_login_at) : <span className="muted">Never</span>}</td>
                    <td>
                      {a.id !== user?.id && (
                        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                          <ConfirmButton className="btn small danger" label="Remove" title={`Remove ${a.email}?`}
                            confirmLabel="Remove" onConfirm={() => remove(a)}
                            message="They will be signed out and can no longer sign in. Their past actions stay in the audit log." />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
