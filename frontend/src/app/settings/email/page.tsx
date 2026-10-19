"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { ErrorAlert, Field, Loading } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { NotificationSettings, SesChecks, TestEmailResult } from "@/lib/types";

const REGIONS = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1", "eu-west-1", "eu-west-2", "eu-west-3",
  "eu-central-1", "eu-north-1", "eu-south-1", "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
  "ap-northeast-2", "ap-northeast-3", "sa-east-1", "me-south-1", "af-south-1", "il-central-1",
];

function ChecksView({ checks }: { checks: SesChecks }) {
  const row = (label: string, value: boolean | null) => (
    <>
      <dt>{label}</dt>
      <dd>{value === null ? <span className="muted">Not checked</span> : value ? "✓ Yes" : <strong style={{ color: "var(--danger-fg)" }}>✗ No</strong>}</dd>
    </>
  );
  return (
    <>
      <dl className="props">
        {row("Credentials work", checks.credentials)}
        {row("Sending enabled", checks.sending_enabled)}
        {row("Production access (out of sandbox)", checks.production_access)}
        {row("Sender identity verified", checks.sender_verified)}
        {checks.quota && (
          <>
            <dt>Quota</dt>
            <dd>{checks.quota.sent_last_24_hours} of {checks.quota.max_24_hour_send} sent in 24 h · {checks.quota.max_send_rate}/s</dd>
          </>
        )}
      </dl>
      {checks.problems.length > 0 && (
        <div className="alert warn" style={{ marginTop: 12 }}>
          <ul>{checks.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
    </>
  );
}

export default function EmailSettingsPage() {
  const toast = useToast();
  const loaded = useAsync(() => api.get<NotificationSettings>("/notifications/settings"), []);
  const [s, setS] = useState<NotificationSettings | null>(null);
  const [recipientInput, setRecipientInput] = useState("");
  const [days, setDays] = useState("");
  const [keyId, setKeyId] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestEmailResult | null>(null);

  useEffect(() => {
    if (loaded.data) {
      setS(loaded.data);
      setDays(loaded.data.reminder_days_before.join(", "));
    }
  }, [loaded.data]);

  if (loaded.error) return <ErrorAlert message={loaded.error} onRetry={loaded.reload} />;
  if (!s) return <Loading />;

  const set = <K extends keyof NotificationSettings>(k: K, v: NotificationSettings[K]) => setS({ ...s, [k]: v });

  function addRecipient() {
    const value = recipientInput.trim().toLowerCase();
    if (!value) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setErrors({ ...errors, recipients: "Enter a valid email address." });
      return;
    }
    if (!s!.notification_recipients.includes(value)) set("notification_recipients", [...s!.notification_recipients, value]);
    setRecipientInput("");
    setErrors({ ...errors, recipients: "" });
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const parsedDays = days.split(/[\s,]+/).filter(Boolean).map(Number);
    if (parsedDays.some((d) => !Number.isInteger(d) || d < 1 || d > 365)) {
      setErrors({ reminder_days_before: "Use whole numbers between 1 and 365, separated by commas." });
      return;
    }
    const body: Record<string, unknown> = {
      notifications_enabled: s!.notifications_enabled,
      notification_recipients: s!.notification_recipients,
      reminder_days_before: parsedDays,
      remind_on_expiration_day: s!.remind_on_expiration_day,
      overdue_reminder_days: s!.overdue_reminder_days,
      remind_suspended: s!.remind_suspended,
      ses_region: s!.ses_region || null,
      ses_sender: s!.ses_sender || null,
      ses_configuration_set: s!.ses_configuration_set || null,
      ses_auth_method: s!.ses_auth_method,
    };
    if (s!.ses_auth_method === "access_keys" && (keyId || secretKey)) {
      body.ses_credentials = { access_key_id: keyId.trim(), secret_access_key: secretKey.trim(), session_token: sessionToken.trim() || null };
    }
    setBusy(true);
    setErrors({});
    try {
      const saved = await api.patch<NotificationSettings>("/notifications/settings", body);
      setS(saved);
      setDays(saved.reminder_days_before.join(", "));
      setKeyId(""); setSecretKey(""); setSessionToken("");
      toast("success", "Email settings saved.");
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      toast("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function clearKeys() {
    try {
      const saved = await api.patch<NotificationSettings>("/notifications/settings", { clear_ses_credentials: true, ses_auth_method: "default_chain" });
      setS(saved);
      toast("success", "Stored AWS keys removed.");
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  async function runTest(sendEmail: boolean) {
    setTesting(true);
    setResult(null);
    try {
      const res = sendEmail
        ? await api.post<TestEmailResult>("/notifications/test", { recipient: testTo.trim() || null })
        : await api.post<TestEmailResult>("/notifications/validate");
      setResult(res);
      toast(res.ok ? "success" : "error", res.message);
      loaded.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    } finally {
      setTesting(false);
    }
  }

  const lastChecks = (result?.checks ?? (s.ses_last_validation as SesChecks)) as SesChecks | undefined;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Email notifications (Amazon SES)</h1>
          <p>Reminders go to every recipient for both Active and Inactive records.</p>
        </div>
      </div>

      <form className="form" onSubmit={save} noValidate>
        <section className="card">
          <div className="card-header"><h2>Reminders</h2></div>
          <div className="card-body form">
            <label className="checkbox">
              <input type="checkbox" checked={s.notifications_enabled} onChange={(e) => set("notifications_enabled", e.target.checked)} />
              <span><strong>Send expiration reminders</strong></span>
            </label>
            <div className="field">
              <label htmlFor="recipient">Recipients</label>
              <div className="chips" aria-live="polite">
                {s.notification_recipients.length === 0 && <span className="muted small">No recipients yet</span>}
                {s.notification_recipients.map((r) => (
                  <span className="chip" key={r}>
                    {r}
                    <button type="button" aria-label={`Remove ${r}`}
                      onClick={() => set("notification_recipients", s.notification_recipients.filter((x) => x !== r))}>×</button>
                  </span>
                ))}
              </div>
              <div className="btn-row">
                <input id="recipient" type="email" placeholder="name@example.com" value={recipientInput}
                  onChange={(e) => setRecipientInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRecipient(); } }} />
                <button type="button" className="btn" onClick={addRecipient}>Add</button>
              </div>
              {(errors.recipients || errors.notification_recipients) && (
                <span className="error" role="alert">{errors.recipients || errors.notification_recipients}</span>
              )}
            </div>
            <div className="form-grid">
              <Field label="Days before expiration" htmlFor="days" error={errors.reminder_days_before}
                hint="Comma-separated. Default: 30, 14, 7, 3, 1">
                <input id="days" value={days} onChange={(e) => setDays(e.target.value)} />
              </Field>
              <Field label="Daily reminders after expiration" htmlFor="overdue" error={errors.overdue_reminder_days}
                hint="Number of days to keep reminding once overdue (0 to 60).">
                <input id="overdue" type="number" min={0} max={60} value={s.overdue_reminder_days}
                  onChange={(e) => set("overdue_reminder_days", Number(e.target.value))} />
              </Field>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={s.remind_on_expiration_day} onChange={(e) => set("remind_on_expiration_day", e.target.checked)} />
              <span>Remind on the expiration date</span>
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={s.remind_suspended} onChange={(e) => set("remind_suspended", e.target.checked)} />
              <span>Remind for suspended records</span>
            </label>
          </div>
        </section>

        <section className="card">
          <div className="card-header"><h2>Amazon SES</h2></div>
          <div className="card-body form">
            <div className="form-grid">
              <Field label="AWS region" htmlFor="region" error={errors.ses_region}>
                <select id="region" value={s.ses_region ?? ""} onChange={(e) => set("ses_region", e.target.value || null)}>
                  <option value="">Select a region</option>
                  {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </Field>
              <Field label="Verified sender address" htmlFor="sender" error={errors.ses_sender}
                hint="Must be a verified SES identity (address or its domain).">
                <input id="sender" type="email" value={s.ses_sender ?? ""} onChange={(e) => set("ses_sender", e.target.value)} />
              </Field>
              <Field label="Configuration set (optional)" htmlFor="cset" error={errors.ses_configuration_set}
                hint="For delivery, bounce and complaint event tracking.">
                <input id="cset" value={s.ses_configuration_set ?? ""} onChange={(e) => set("ses_configuration_set", e.target.value)} />
              </Field>
            </div>
            <fieldset>
              <legend>Authentication</legend>
              <label className="checkbox">
                <input type="radio" name="auth" checked={s.ses_auth_method === "default_chain"}
                  onChange={() => set("ses_auth_method", "default_chain")} />
                <span><strong>IAM role / default credential chain (recommended).</strong> Uses the role or environment
                  credentials of the server running the worker. No keys are stored.</span>
              </label>
              <label className="checkbox">
                <input type="radio" name="auth" checked={s.ses_auth_method === "access_keys"}
                  onChange={() => set("ses_auth_method", "access_keys")} />
                <span><strong>Access keys.</strong> Stored encrypted and never shown again after saving.</span>
              </label>
              {s.ses_auth_method === "access_keys" && (
                <div className="form-grid" style={{ marginTop: 12 }}>
                  <Field label="Access key ID" htmlFor="akid" error={errors["ses_credentials.access_key_id"]}
                    hint={s.ses_credentials_set ? "Keys are saved. Enter new ones only to replace them." : undefined}>
                    <input id="akid" autoComplete="off" value={keyId} onChange={(e) => setKeyId(e.target.value)}
                      placeholder={s.ses_credentials_set ? "••••••••••••" : ""} />
                  </Field>
                  <Field label="Secret access key" htmlFor="sak" error={errors["ses_credentials.secret_access_key"]}>
                    <input id="sak" type="password" autoComplete="new-password" value={secretKey}
                      onChange={(e) => setSecretKey(e.target.value)} placeholder={s.ses_credentials_set ? "••••••••••••" : ""} />
                  </Field>
                  <Field label="Session token (temporary credentials only)" htmlFor="stok">
                    <input id="stok" type="password" autoComplete="off" value={sessionToken} onChange={(e) => setSessionToken(e.target.value)} />
                  </Field>
                </div>
              )}
              {s.ses_credentials_set && (
                <div style={{ marginTop: 8 }}>
                  <button type="button" className="btn small danger" onClick={clearKeys}>Remove stored keys</button>
                </div>
              )}
            </fieldset>
          </div>
        </section>

        <div className="form-actions">
          <button type="submit" className="btn primary" disabled={busy}>
            {busy && <span className="spinner" aria-hidden />} Save settings
          </button>
        </div>
      </form>

      <section className="card section" style={{ marginTop: 24 }}>
        <div className="card-header">
          <h2>Test the configuration</h2>
          {s.ses_last_validated_at && <span className="small muted">Last checked {formatDateTime(s.ses_last_validated_at)}</span>}
        </div>
        <div className="card-body form">
          <p className="muted" style={{ margin: 0 }}>Save your changes first. A test email only goes to the address you enter, or to the first recipient.</p>
          <div className="btn-row">
            <label className="sr-only" htmlFor="test-to">Test recipient</label>
            <input id="test-to" type="email" placeholder={s.notification_recipients[0] ?? "test@example.com"} value={testTo}
              onChange={(e) => setTestTo(e.target.value)} />
            <button className="btn" onClick={() => runTest(false)} disabled={testing}>Validate only</button>
            <button className="btn primary" onClick={() => runTest(true)} disabled={testing}>
              {testing && <span className="spinner" aria-hidden />} Send test email
            </button>
          </div>
          {result && <div className={`alert ${result.ok ? "success" : "error"}`} role="status">{result.message}</div>}
          {lastChecks && "problems" in lastChecks && <ChecksView checks={lastChecks} />}
        </div>
      </section>
    </>
  );
}
