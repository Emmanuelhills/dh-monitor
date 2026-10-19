"use client";

import { useState } from "react";
import { Badge } from "@/components/Badges";
import { useToast } from "@/components/Toast";
import { ConfirmButton, Empty, ErrorAlert, Field, Loading } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Registrar } from "@/lib/types";

interface Values {
  name: string;
  website: string;
  notes: string;
  for_domains: boolean;
  for_hosting: boolean;
}

const EMPTY: Values = { name: "", website: "", notes: "", for_domains: true, for_hosting: false };

function RegistrarForm({ registrar, onDone, onCancel }: {
  registrar?: Registrar;
  onDone: () => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [v, setV] = useState<Values>(
    registrar
      ? { name: registrar.name, website: registrar.website ?? "", notes: registrar.notes ?? "",
          for_domains: registrar.for_domains, for_hosting: registrar.for_hosting }
      : EMPTY,
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idp = registrar ? `r-${registrar.id}` : "r-new";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!v.name.trim()) next.name = "Enter a name.";
    if (!v.for_domains && !v.for_hosting) next.kind = "Tick domain names, hosting, or both.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    setFormError(null);
    const body = { name: v.name.trim(), website: v.website.trim() || null, notes: v.notes.trim() || null,
      for_domains: v.for_domains, for_hosting: v.for_hosting };
    try {
      if (registrar) await api.patch(`/registrars/${registrar.id}`, body);
      else await api.post("/registrars", body);
      toast("success", registrar ? "Registrar saved." : `${body.name} added.`);
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
        <Field label="Name" htmlFor={`${idp}-name`} error={errors.name}>
          <input id={`${idp}-name`} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} autoFocus />
        </Field>
        <Field label="Website (optional)" htmlFor={`${idp}-web`} error={errors.website} hint="e.g. namecheap.com">
          <input id={`${idp}-web`} value={v.website} onChange={(e) => setV({ ...v, website: e.target.value })} />
        </Field>
      </div>
      <fieldset>
        <legend>Provides</legend>
        <label className="checkbox">
          <input type="checkbox" checked={v.for_domains} onChange={(e) => setV({ ...v, for_domains: e.target.checked })} />
          <span>Domain names: can be selected as a domain&apos;s registrar</span>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={v.for_hosting} onChange={(e) => setV({ ...v, for_hosting: e.target.checked })} />
          <span>Hosting: can be selected as a hosting plan&apos;s company</span>
        </label>
        {errors.kind && <span className="small" style={{ color: "var(--danger-fg)" }} role="alert">{errors.kind}</span>}
      </fieldset>
      <Field label="Notes (optional)" htmlFor={`${idp}-notes`}>
        <textarea id={`${idp}-notes`} value={v.notes} maxLength={10000} onChange={(e) => setV({ ...v, notes: e.target.value })} />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} {registrar ? "Save registrar" : "Add registrar"}
        </button>
      </div>
    </form>
  );
}

export default function RegistrarsPage() {
  const toast = useToast();
  const [kind, setKind] = useState<"" | "domain" | "hosting">("");
  const list = useAsync(() => api.get<Registrar[]>("/registrars", { kind }), [kind]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  async function remove(r: Registrar) {
    try {
      await api.del(`/registrars/${r.id}`);
      toast("success", `${r.name} removed.`);
      list.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Registrars</h1>
          <p>Companies you buy domain names and hosting from. Select them on each domain or hosting plan.</p>
        </div>
        <button className="btn primary" onClick={() => { setAdding(true); setEditing(null); }}>Add registrar</button>
      </div>

      {adding && (
        <section className="card section">
          <div className="card-header"><h2>New registrar</h2></div>
          <RegistrarForm onCancel={() => setAdding(false)} onDone={() => { setAdding(false); list.reload(); }} />
        </section>
      )}

      <section className="card section">
        <div className="toolbar">
          <label className="sr-only" htmlFor="reg-kind">Show</label>
          <select id="reg-kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="">All registrars</option>
            <option value="domain">Domain registrars</option>
            <option value="hosting">Hosting providers</option>
          </select>
        </div>
        {list.error && <div className="card-body"><ErrorAlert message={list.error} onRetry={list.reload} /></div>}
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.length === 0 && (
          <Empty title="No registrars yet">Add the companies you buy domains and hosting from.</Empty>
        )}
        {list.data && list.data.length > 0 && (
          <div className="table-wrap">
            <table className="data responsive">
              <thead>
                <tr><th>Name</th><th>Provides</th><th>Domains</th><th>Hosting plans</th><th /></tr>
              </thead>
              <tbody>
                {list.data.map((r) =>
                  editing === r.id ? (
                    <tr key={r.id}>
                      <td colSpan={5} style={{ padding: 0 }}>
                        <RegistrarForm registrar={r} onCancel={() => setEditing(null)} onDone={() => { setEditing(null); list.reload(); }} />
                      </td>
                    </tr>
                  ) : (
                    <tr key={r.id}>
                      <td className="name" data-label="Name">
                        {r.name}
                        {r.website && (
                          <span className="sub"><a href={r.website} target="_blank" rel="noopener noreferrer">{r.website.replace(/^https?:\/\//, "")}</a></span>
                        )}
                      </td>
                      <td data-label="Provides">
                        <div className="badges">
                          {r.for_domains && <Badge tone="info">Domain names</Badge>}
                          {r.for_hosting && <Badge tone="ok">Hosting</Badge>}
                        </div>
                      </td>
                      <td data-label="Domains">{r.for_domains ? r.domain_count : <span className="muted">—</span>}</td>
                      <td data-label="Hosting plans">{r.for_hosting ? r.hosting_count : <span className="muted">—</span>}</td>
                      <td>
                        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                          <button className="btn small" onClick={() => { setEditing(r.id); setAdding(false); }}>Edit</button>
                          <ConfirmButton className="btn small danger" label="Delete" title={`Delete ${r.name}?`} confirmLabel="Delete"
                            message={
                              r.domain_count || r.hosting_count
                                ? `${r.domain_count} domain(s) and ${r.hosting_count} hosting plan(s) will no longer be linked to it. They are not deleted, and hosting plans keep the company name as text.`
                                : "This registrar isn't used by any domain or hosting plan."
                            }
                            onConfirm={() => remove(r)} />
                        </div>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
