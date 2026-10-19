"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Domain, Hosting, Page, Registrar } from "@/lib/types";
import { Field } from "./ui";

interface Values {
  domain_name: string;
  hosting_account_id: string;
  expiration_date: string;
  registration_date: string;
  registrar_id: string;
  usage_status: string;
  service_status: string;
  renewal_status: string;
  auto_check_enabled: boolean;
  notifications_enabled: boolean;
  notes: string;
}

function initialValues(d?: Domain): Values {
  return {
    domain_name: d?.domain_name ?? "",
    hosting_account_id: d?.hosting_account?.id ?? "",
    expiration_date: d?.expiration_date ?? "",
    registration_date: d?.registration_date ?? "",
    registrar_id: d?.registrar?.id ?? "",
    usage_status: d?.usage_status ?? "active",
    service_status: d?.service_status ?? "unknown",
    renewal_status: d?.renewal_status ?? "unknown",
    auto_check_enabled: d?.auto_check_enabled ?? true,
    notifications_enabled: d?.notifications_enabled ?? true,
    notes: d?.notes ?? "",
  };
}

function toPayload(v: Values): Record<string, unknown> {
  return {
    domain_name: v.domain_name.trim(),
    hosting_account_id: v.hosting_account_id || null,
    expiration_date: v.expiration_date || null,
    registration_date: v.registration_date || null,
    registrar_id: v.registrar_id || null,
    usage_status: v.usage_status,
    service_status: v.service_status,
    renewal_status: v.renewal_status,
    auto_check_enabled: v.auto_check_enabled,
    notifications_enabled: v.notifications_enabled,
    notes: v.notes.trim() || null,
  };
}

export function DomainForm({ domain, onSaved, onCancel }: {
  domain?: Domain;
  onSaved: (d: Domain) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<Values>(() => initialValues(domain));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hosting = useAsync(() => api.get<Page<Hosting>>("/hosting-accounts", { page_size: 100 }).then((p) => p.items), []);
  const registrars = useAsync(() => api.get<Registrar[]>("/registrars", { kind: "domain" }), []);

  const set = <K extends keyof Values>(key: K, value: Values[K]) => setValues((v) => ({ ...v, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!values.domain_name.trim()) nextErrors.domain_name = "Enter a domain name.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setBusy(true);
    setFormError(null);
    try {
      const payload = toPayload(values);
      let saved: Domain;
      if (domain) {
        const original = toPayload(initialValues(domain));
        const changed = Object.fromEntries(
          Object.entries(payload).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(original[k])),
        );
        saved = Object.keys(changed).length ? await api.patch<Domain>(`/domains/${domain.id}`, changed) : domain;
      } else {
        saved = await api.post<Domain>("/domains", payload);
      }
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const describedBy = (id: string) => (errors[id] ? `${id}-error` : `${id}-hint`);

  return (
    <form className="form" onSubmit={submit} noValidate>
      {formError && <div className="alert error" role="alert">{formError}</div>}
      <div className="form-grid">
        <Field label="Domain name" htmlFor="domain_name" error={errors.domain_name}
          hint="For example example.com. It is normalized automatically.">
          <input id="domain_name" required value={values.domain_name} aria-describedby={describedBy("domain_name")}
            onChange={(e) => set("domain_name", e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Hosting account" htmlFor="hosting_account_id" error={errors.hosting_account_id}
          hint="Optional. A domain can stay unassigned.">
          <select id="hosting_account_id" value={values.hosting_account_id}
            onChange={(e) => set("hosting_account_id", e.target.value)}>
            <option value="">Unassigned</option>
            {hosting.data?.map((h) => (
              <option key={h.id} value={h.id}>{h.name} ({h.provider_name})</option>
            ))}
          </select>
        </Field>
        <Field label="Expiration date" htmlFor="expiration_date" error={errors.expiration_date}
          hint="Leave empty if unknown. Automatic checks can fill it in.">
          <input id="expiration_date" type="date" value={values.expiration_date}
            onChange={(e) => set("expiration_date", e.target.value)} />
        </Field>
        <Field label="Registration date" htmlFor="registration_date" error={errors.registration_date}>
          <input id="registration_date" type="date" value={values.registration_date}
            onChange={(e) => set("registration_date", e.target.value)} />
        </Field>
        <Field label="Registrar" htmlFor="registrar_id" error={errors.registrar_id}
          hint={registrars.data && registrars.data.length === 0
            ? <>No domain registrars yet. <Link href="/registrars">Add one</Link>.</>
            : <>Where the domain is registered. <Link href="/registrars">Manage registrars</Link></>}>
          <select id="registrar_id" value={values.registrar_id} onChange={(e) => set("registrar_id", e.target.value)}>
            <option value="">Not set</option>
            {registrars.data?.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Usage status" htmlFor="usage_status" hint="Is a product or website using this domain?">
          <select id="usage_status" value={values.usage_status} onChange={(e) => set("usage_status", e.target.value)}>
            <option value="active">Active: in use</option>
            <option value="inactive">Inactive: not in use</option>
          </select>
        </Field>
        <Field label="Registration status" htmlFor="service_status"
          hint="Mark suspended or expired only when confirmed.">
          <select id="service_status" value={values.service_status} onChange={(e) => set("service_status", e.target.value)}>
            <option value="unknown">Unknown</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="expired">Expired</option>
          </select>
        </Field>
        <Field label="Renewal status" htmlFor="renewal_status"
          hint="Confirming a renewal stops reminders for the current date.">
          <select id="renewal_status" value={values.renewal_status} onChange={(e) => set("renewal_status", e.target.value)}>
            <option value="unknown">Unknown</option>
            <option value="renewed">Renewed</option>
            <option value="not_renewed">Not renewed</option>
          </select>
        </Field>
      </div>
      <fieldset>
        <legend>Monitoring & reminders</legend>
        <label className="checkbox">
          <input type="checkbox" checked={values.auto_check_enabled} onChange={(e) => set("auto_check_enabled", e.target.checked)} />
          <span>Check registration data automatically (RDAP, with WHOIS fallback)</span>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={values.notifications_enabled}
            onChange={(e) => set("notifications_enabled", e.target.checked)} />
          <span>Send expiration reminders for this domain</span>
        </label>
      </fieldset>
      <Field label="Notes" htmlFor="notes" error={errors.notes}>
        <textarea id="notes" value={values.notes} maxLength={10000} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} {domain ? "Save changes" : "Add domain"}
        </button>
      </div>
    </form>
  );
}
