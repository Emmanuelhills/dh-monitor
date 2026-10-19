"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { HostingDetail, Integration, Registrar } from "@/lib/types";
import { Field } from "./ui";

const OTHER = "__other__";

interface Values {
  name: string;
  registrar_id: string; // registrar id, OTHER, or ""
  provider_name: string;
  expiration_date: string;
  purchase_date: string;
  usage_status: string;
  service_status: string;
  renewal_status: string;
  integration_id: string;
  external_ref: string;
  auto_check_enabled: boolean;
  notifications_enabled: boolean;
  notes: string;
}

function initialValues(h?: HostingDetail): Values {
  return {
    name: h?.name ?? "",
    registrar_id: h ? (h.registrar?.id ?? OTHER) : "",
    provider_name: h && !h.registrar ? h.provider_name : "",
    expiration_date: h?.expiration_date ?? "",
    purchase_date: h?.purchase_date ?? "",
    usage_status: h?.usage_status ?? "active",
    service_status: h?.service_status ?? "unknown",
    renewal_status: h?.renewal_status ?? "unknown",
    integration_id: h?.integration?.id ?? "",
    external_ref: h?.external_ref ?? "",
    auto_check_enabled: h?.auto_check_enabled ?? true,
    notifications_enabled: h?.notifications_enabled ?? true,
    notes: h?.notes ?? "",
  };
}

function toPayload(v: Values): Record<string, unknown> {
  const other = v.registrar_id === OTHER;
  return {
    name: v.name.trim(),
    registrar_id: other ? null : v.registrar_id || null,
    provider_name: other ? v.provider_name.trim() : null,
    expiration_date: v.expiration_date || null,
    purchase_date: v.purchase_date || null,
    usage_status: v.usage_status,
    service_status: v.service_status,
    renewal_status: v.renewal_status,
    integration_id: v.integration_id || null,
    external_ref: v.external_ref.trim() || null,
    auto_check_enabled: v.auto_check_enabled,
    notifications_enabled: v.notifications_enabled,
    notes: v.notes.trim() || null,
  };
}

/** The admin URL is private: it is loaded only when the administrator explicitly unlocks it. */
function AdminUrlField({ hostingId, value, onChange, hasExisting }: {
  hostingId?: string;
  value: string | null;
  onChange: (v: string | null) => void;
  hasExisting: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unlocked = value !== null;

  async function unlock() {
    if (!hostingId || !hasExisting) {
      onChange("");
      return;
    }
    setLoading(true);
    try {
      const res = await api.get<{ admin_url: string | null }>(`/hosting-accounts/${hostingId}/admin-url`);
      onChange(res.admin_url ?? "");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="field">
      <label htmlFor="admin_url">Admin URL (private)</label>
      {unlocked ? (
        <input id="admin_url" type="url" placeholder="https://" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <div className="btn-row">
          <span className="muted">{hasExisting ? "Saved and hidden" : "Not set"}</span>
          <button type="button" className="btn small" onClick={unlock} disabled={loading}>
            {loading && <span className="spinner" aria-hidden />} {hasExisting ? "Show and edit" : "Add"}
          </button>
        </div>
      )}
      <span className="hint">Never shown in lists, detail views or reminder emails. Viewing it is logged.</span>
      {error && <span className="error" role="alert">{error}</span>}
    </div>
  );
}

export function HostingForm({ hosting, onSaved, onCancel }: {
  hosting?: HostingDetail;
  onSaved: (h: HostingDetail) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<Values>(() => initialValues(hosting));
  const [adminUrl, setAdminUrl] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const integrations = useAsync(() => api.get<Integration[]>("/integrations"), []);
  const registrars = useAsync(() => api.get<Registrar[]>("/registrars", { kind: "hosting" }), []);
  const set = <K extends keyof Values>(key: K, value: Values[K]) => setValues((v) => ({ ...v, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!values.name.trim()) next.name = "Enter a name.";
    if (!values.registrar_id) next.registrar_id = "Choose the hosting company.";
    if (values.registrar_id === OTHER && !values.provider_name.trim()) next.provider_name = "Enter the company name.";
    setErrors(next);
    if (Object.keys(next).length) return;

    setBusy(true);
    setFormError(null);
    try {
      const payload = toPayload(values);
      let body: Record<string, unknown> = payload;
      if (hosting) {
        const original = toPayload(initialValues(hosting));
        body = Object.fromEntries(Object.entries(payload).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(original[k])));
      }
      if (adminUrl !== null) body.admin_url = adminUrl.trim() || null;
      let saved: HostingDetail;
      if (hosting) {
        saved = Object.keys(body).length ? await api.patch<HostingDetail>(`/hosting-accounts/${hosting.id}`, body) : hosting;
      } else {
        saved = await api.post<HostingDetail>("/hosting-accounts", body);
      }
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const selectedIntegration = integrations.data?.find((i) => i.id === values.integration_id);

  return (
    <form className="form" onSubmit={submit} noValidate>
      {formError && <div className="alert error" role="alert">{formError}</div>}
      <div className="form-grid">
        <Field label="Account name" htmlFor="name" error={errors.name} hint="A name you recognise, e.g. Main shared hosting.">
          <input id="name" required value={values.name} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Hosting company" htmlFor="registrar_id" error={errors.registrar_id}
          hint={<>From your <Link href="/registrars">registrars</Link> marked as hosting providers.</>}>
          <select id="registrar_id" value={values.registrar_id} onChange={(e) => set("registrar_id", e.target.value)}>
            <option value="">Choose…</option>
            {registrars.data?.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
            <option value={OTHER}>Other (type a name)</option>
          </select>
        </Field>
        {values.registrar_id === OTHER && (
          <Field label="Company name" htmlFor="provider_name" error={errors.provider_name}
            hint="Tip: add it on the Registrars page to reuse it.">
            <input id="provider_name" value={values.provider_name} onChange={(e) => set("provider_name", e.target.value)} />
          </Field>
        )}
        <Field label="Expiration date" htmlFor="expiration_date" error={errors.expiration_date}
          hint="Subscription end or next renewal date. Leave empty if unknown.">
          <input id="expiration_date" type="date" value={values.expiration_date}
            onChange={(e) => set("expiration_date", e.target.value)} />
        </Field>
        <Field label="Purchase date" htmlFor="purchase_date" error={errors.purchase_date}>
          <input id="purchase_date" type="date" value={values.purchase_date} onChange={(e) => set("purchase_date", e.target.value)} />
        </Field>
        <Field label="Usage status" htmlFor="usage_status" hint="Is a product or website using this hosting plan?">
          <select id="usage_status" value={values.usage_status} onChange={(e) => set("usage_status", e.target.value)}>
            <option value="active">Active: in use</option>
            <option value="inactive">Inactive: not in use</option>
          </select>
        </Field>
        <Field label="Service status" htmlFor="service_status" hint="Mark suspended or expired only when confirmed.">
          <select id="service_status" value={values.service_status} onChange={(e) => set("service_status", e.target.value)}>
            <option value="unknown">Unknown</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="expired">Expired</option>
          </select>
        </Field>
        <Field label="Renewal status" htmlFor="renewal_status" hint="Confirming a renewal stops reminders for the current date.">
          <select id="renewal_status" value={values.renewal_status} onChange={(e) => set("renewal_status", e.target.value)}>
            <option value="unknown">Unknown</option>
            <option value="renewed">Renewed</option>
            <option value="not_renewed">Not renewed</option>
          </select>
        </Field>
        <AdminUrlField hostingId={hosting?.id} value={adminUrl} onChange={setAdminUrl} hasExisting={!!hosting?.has_admin_url} />
      </div>
      <fieldset>
        <legend>Provider integration</legend>
        <div className="form-grid">
          <Field label="Integration" htmlFor="integration_id"
            hint={integrations.data?.length ? "Optional. Without one, this account is maintained manually."
              : "No integrations configured. Add one under Settings → Provider integrations."}>
            <select id="integration_id" value={values.integration_id} onChange={(e) => set("integration_id", e.target.value)}>
              <option value="">None (manual)</option>
              {integrations.data?.map((i) => (
                <option key={i.id} value={i.id}>{i.name}{i.enabled ? "" : " (disabled)"}</option>
              ))}
            </select>
          </Field>
          {values.integration_id && (
            <Field label="Provider service ID" htmlFor="external_ref" error={errors.external_ref}
              hint={selectedIntegration?.adapter === "whmcs" ? "The WHMCS service (product) ID." : "Identifier used in the integration's URL."}>
              <input id="external_ref" value={values.external_ref} onChange={(e) => set("external_ref", e.target.value)} />
            </Field>
          )}
        </div>
        <label className="checkbox" style={{ marginTop: 12 }}>
          <input type="checkbox" checked={values.auto_check_enabled} onChange={(e) => set("auto_check_enabled", e.target.checked)} />
          <span>Check automatically when an integration is assigned</span>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={values.notifications_enabled}
            onChange={(e) => set("notifications_enabled", e.target.checked)} />
          <span>Send expiration reminders for this hosting account</span>
        </label>
      </fieldset>
      <Field label="Notes" htmlFor="notes" error={errors.notes}>
        <textarea id="notes" value={values.notes} maxLength={10000} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} {hosting ? "Save changes" : "Add hosting account"}
        </button>
      </div>
    </form>
  );
}
