"use client";

import { useState } from "react";
import { useToast } from "@/components/Toast";
import { ConfirmButton, Empty, ErrorAlert, Field, Loading, PasswordInput } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { AdapterInfo, Integration } from "@/lib/types";

function configToStrings(config: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(config).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]),
  );
}

function IntegrationEditor({ adapter, integration, onDone, onCancel }: {
  adapter: AdapterInfo;
  integration?: Integration;
  onDone: () => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(integration?.name ?? adapter.label);
  const [enabled, setEnabled] = useState(integration?.enabled ?? true);
  const [config, setConfig] = useState<Record<string, string>>(configToStrings(integration?.config ?? {}));
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const cleanConfig = Object.fromEntries(Object.entries(config).filter(([, v]) => v.trim() !== ""));
    const cleanSecrets = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v !== ""));
    try {
      if (integration) {
        await api.patch(`/integrations/${integration.id}`, {
          name, enabled, config: cleanConfig, ...(Object.keys(cleanSecrets).length ? { secrets: cleanSecrets } : {}),
        });
      } else {
        await api.post("/integrations", { name, adapter: adapter.key, enabled, config: cleanConfig, secrets: cleanSecrets });
      }
      toast("success", "Integration saved.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form card-body" onSubmit={submit} noValidate>
      {error && <div className="alert error" role="alert">{error}</div>}
      <p className="muted" style={{ margin: 0 }}>
        {adapter.description} Authentication: {adapter.auth_method}. Retrieves: {adapter.supported_fields.join(", ")}.
      </p>
      <div className="form-grid">
        <Field label="Name" htmlFor="int-name">
          <input id="int-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        {adapter.config_fields.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? "" : " (optional)"}`} htmlFor={`cfg-${f.key}`} hint={f.help}>
            <input id={`cfg-${f.key}`} value={config[f.key] ?? ""} onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} />
          </Field>
        ))}
        {adapter.secret_fields.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? "" : " (optional)"}`} htmlFor={`sec-${f.key}`}
            hint={integration?.secret_set ? "Saved and hidden. Enter a value only to replace it." : f.help}>
            <PasswordInput id={`sec-${f.key}`} autoComplete="new-password" value={secrets[f.key] ?? ""}
              placeholder={integration?.secret_set ? "••••••••" : ""}
              onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })} />
          </Field>
        ))}
      </div>
      <label className="checkbox">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span>Enabled. Disabling switches linked hosting accounts to manual maintenance.</span>
      </label>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>Save integration</button>
      </div>
    </form>
  );
}

export default function IntegrationsPage() {
  const toast = useToast();
  const adapters = useAsync(() => api.get<AdapterInfo[]>("/integrations/adapters"), []);
  const list = useAsync(() => api.get<Integration[]>("/integrations"), []);
  const [creating, setCreating] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  if (adapters.error || list.error) return <ErrorAlert message={(adapters.error || list.error)!} onRetry={() => { adapters.reload(); list.reload(); }} />;
  if (!adapters.data || !list.data) return <Loading />;
  const adapterFor = (key: string) => adapters.data!.find((a) => a.key === key);

  async function test(i: Integration) {
    try {
      const res = await api.post<{ ok: boolean; message: string }>(`/integrations/${i.id}/test`);
      toast(res.ok ? "success" : "error", res.message);
      list.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  async function remove(i: Integration) {
    try {
      await api.del(`/integrations/${i.id}`);
      toast("success", `${i.name} removed.`);
      list.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Provider integrations</h1>
          <p>Authorized APIs that let the monitor read hosting expiration dates and status. Accounts without one are maintained manually.</p>
        </div>
      </div>

      <section className="card section">
        <div className="card-header">
          <h2>Configured integrations</h2>
          <div className="btn-row">
            {adapters.data.map((a) => (
              <button key={a.key} className="btn" onClick={() => { setCreating(a.key); setEditing(null); }}>Add {a.label}</button>
            ))}
          </div>
        </div>
        {creating && adapterFor(creating) && (
          <IntegrationEditor adapter={adapterFor(creating)!} onCancel={() => setCreating(null)}
            onDone={() => { setCreating(null); list.reload(); }} />
        )}
        {list.data.length === 0 && !creating && (
          <Empty title="No integrations">Hosting accounts are maintained manually until you add one.</Empty>
        )}
        <ul className="timeline">
          {list.data.map((i) => (
            <li key={i.id}>
              {editing === i.id && adapterFor(i.adapter) ? (
                <IntegrationEditor adapter={adapterFor(i.adapter)!} integration={i} onCancel={() => setEditing(null)}
                  onDone={() => { setEditing(null); list.reload(); }} />
              ) : (
                <div className="meta" style={{ justifyContent: "space-between" }}>
                  <div>
                    <strong>{i.name}</strong> <span className="muted small">· {adapterFor(i.adapter)?.label ?? i.adapter}</span>
                    {!i.enabled && <span className="badge neutral" style={{ marginLeft: 6 }}>Disabled</span>}
                    <div className="small muted">
                      {i.hosting_account_count} hosting account{i.hosting_account_count === 1 ? "" : "s"} ·{" "}
                      {i.secret_set ? "credentials saved" : "no credentials saved"}
                      {i.last_tested_at && <> · last test {formatDateTime(i.last_tested_at)}: {i.last_test_ok ? "OK" : "failed"}{i.last_test_message ? ` (${i.last_test_message})` : ""}</>}
                    </div>
                  </div>
                  <div className="btn-row">
                    <button className="btn small" onClick={() => test(i)}>Test connection</button>
                    <button className="btn small" onClick={() => { setEditing(i.id); setCreating(null); }}>Edit</button>
                    <ConfirmButton className="btn small danger" label="Remove" title={`Remove ${i.name}?`} confirmLabel="Remove"
                      message="Linked hosting accounts keep their saved data and switch to manual maintenance. Stored credentials are deleted."
                      onConfirm={() => remove(i)} />
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
