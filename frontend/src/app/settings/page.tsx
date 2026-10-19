"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { ErrorAlert, Field, Loading } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { GeneralSettings } from "@/lib/types";

function timezones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
}

function PasswordForm() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next.length < 12) return setError("Use at least 12 characters.");
    if (next !== confirm) return setError("The new passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      setCurrent(""); setNext(""); setConfirm("");
      toast("success", "Password changed. Other sessions were signed out.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="Current password" htmlFor="pw-current">
          <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password" htmlFor="pw-new" hint="At least 12 characters.">
          <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="Repeat new password" htmlFor="pw-confirm">
          <input id="pw-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn primary" type="submit" disabled={busy || !current || !next}>Change password</button>
      </div>
    </form>
  );
}

export default function GeneralSettingsPage() {
  const toast = useToast();
  const loaded = useAsync(() => api.get<GeneralSettings>("/settings"), []);
  const [s, setS] = useState<GeneralSettings | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (loaded.data) setS(loaded.data); }, [loaded.data]);

  if (loaded.error) return <ErrorAlert message={loaded.error} onRetry={loaded.reload} />;
  if (!s) return <Loading />;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      setS(await api.patch<GeneralSettings>("/settings", s));
      toast("success", "Settings saved.");
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      toast("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const num = (k: keyof GeneralSettings) => (e: React.ChangeEvent<HTMLInputElement>) => setS({ ...s, [k]: Number(e.target.value) });

  return (
    <>
      <div className="page-header">
        <div>
          <h1>General settings</h1>
          <p>Timezone and monitoring frequency for background jobs.</p>
        </div>
      </div>
      <form className="card section" onSubmit={save} noValidate>
        <div className="card-header"><h2>Application</h2></div>
        <div className="card-body form">
          <div className="form-grid">
            <Field label="Timezone" htmlFor="tz" error={errors.timezone}
              hint="Decides which calendar day it is for countdowns and reminders.">
              <select id="tz" value={s.timezone} onChange={(e) => setS({ ...s, timezone: e.target.value })}>
                {Array.from(new Set(["UTC", ...timezones()])).map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </select>
            </Field>
            <Field label="Domain check interval (hours)" htmlFor="dci" error={errors.domain_check_interval_hours}>
              <input id="dci" type="number" min={1} max={720} value={s.domain_check_interval_hours} onChange={num("domain_check_interval_hours")} />
            </Field>
            <Field label="Hosting check interval (hours)" htmlFor="hci" error={errors.hosting_check_interval_hours}>
              <input id="hci" type="number" min={1} max={720} value={s.hosting_check_interval_hours} onChange={num("hosting_check_interval_hours")} />
            </Field>
            <Field label="Mark stale after (hours)" htmlFor="stale" error={errors.stale_after_hours}
              hint="Records without a successful check for this long are flagged.">
              <input id="stale" type="number" min={1} max={2160} value={s.stale_after_hours} onChange={num("stale_after_hours")} />
            </Field>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={s.public_page_enabled}
              onChange={(e) => setS({ ...s, public_page_enabled: e.target.checked })} />
            <span>
              <strong>Public overview page</strong>: anyone who can open this site sees the domain and hosting list
              (names, hosting, expiration dates, statuses) at <a href="/" target="_blank">the home page</a> without signing in.
              Notes, admin URLs and history stay private.
            </span>
          </label>
          <div className="form-actions">
            <button className="btn primary" type="submit" disabled={busy}>Save settings</button>
          </div>
        </div>
      </form>
      <section className="card section">
        <div className="card-header"><h2>Your password</h2></div>
        <div className="card-body"><PasswordForm /></div>
      </section>
    </>
  );
}
