"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ServiceBadge, UsageBadge } from "@/components/Badges";
import { DomainForm } from "@/components/DomainForm";
import { RecordHistory } from "@/components/History";
import { MonitoringPanel, RunCheckButton } from "@/components/RecordPanels";
import { useToast } from "@/components/Toast";
import { ConfirmButton, ErrorAlert, Loading } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { Domain } from "@/lib/types";

export default function DomainDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const domain = useAsync(() => api.get<Domain>(`/domains/${id}`), [id, refreshKey]);
  const refresh = () => setRefreshKey((k) => k + 1);

  if (domain.error) return <ErrorAlert message={domain.error} onRetry={domain.reload} />;
  if (!domain.data) return <Loading />;
  const d = domain.data;
  const archived = !!d.archived_at;

  async function archive() {
    try {
      await api.del(`/domains/${d.id}`);
      toast("success", `${d.display_name} archived.`);
      refresh();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  async function restore() {
    try {
      await api.post(`/domains/${d.id}/restore`);
      toast("success", `${d.display_name} restored.`);
      refresh();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  async function destroy() {
    try {
      await api.del(`/domains/${d.id}`, { permanent: true });
      toast("success", `${d.display_name} deleted.`);
      router.replace("/domains");
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="small"><Link href="/domains">← Domains</Link></div>
          <h1>{d.display_name}</h1>
          <div className="badges" style={{ marginTop: 6 }}>
            <UsageBadge status={d.usage_status} prefix="Usage" />
            <ServiceBadge status={d.service_status} prefix="Registration" />
            {archived && <span className="badge neutral">Archived {formatDate(d.archived_at!.slice(0, 10))}</span>}
          </div>
        </div>
        {!editing && (
          <div className="btn-row">
            {!archived && (
              <>
                <RunCheckButton path={`/domains/${d.id}`} record={d} onUpdated={refresh} />
                <button className="btn primary" onClick={() => setEditing(true)}>Edit</button>
                <ConfirmButton label="Archive" title={`Archive ${d.display_name}?`} confirmLabel="Archive"
                  message="The domain leaves the active lists, checks stop and queued reminders are cancelled. Its hosting account is not affected. You can restore it later."
                  onConfirm={archive} />
              </>
            )}
            {archived && (
              <>
                <button className="btn primary" onClick={restore}>Restore</button>
                <ConfirmButton label="Delete permanently" title={`Delete ${d.display_name} permanently?`}
                  confirmLabel="Delete permanently"
                  message="This removes the domain and its monitoring and reminder history. Its hosting account is not affected. This cannot be undone."
                  onConfirm={destroy} />
              </>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <div className="card section">
          <div className="card-header"><h2>Edit domain</h2></div>
          <div className="card-body">
            <DomainForm domain={d} onCancel={() => setEditing(false)}
              onSaved={(saved) => { domain.setData(saved); setEditing(false); setRefreshKey((k) => k + 1); toast("success", "Domain saved."); }} />
          </div>
        </div>
      ) : (
        <div className="grid grid-2 section">
          <div className="card">
            <div className="card-header"><h2>Registration</h2></div>
            <div className="card-body">
              <dl className="props">
                <dt>Domain</dt>
                <dd>{d.display_name}{d.display_name !== d.normalized_domain_name && <span className="muted small"> ({d.normalized_domain_name})</span>}</dd>
                <dt>Hosting account</dt>
                <dd>{d.hosting_account ? <Link href={`/hosting/${d.hosting_account.id}`}>{d.hosting_account.name}</Link> : <span className="muted">Unassigned</span>}
                  {d.hosting_account && <span className="muted small"> · {d.hosting_account.provider_name}</span>}</dd>
                <dt>Registrar</dt>
                <dd>{d.registrar ? d.registrar.name : <span className="muted">Not set</span>}</dd>
                <dt>Registry reports</dt>
                <dd>{d.registrar_name ?? <span className="muted">Not checked yet</span>}</dd>
                <dt>Registered on</dt>
                <dd>{formatDate(d.registration_date)}</dd>
                <dt>Registry status codes</dt>
                <dd>{d.registry_statuses.length ? d.registry_statuses.map((s) => <code key={s} style={{ marginRight: 4 }}>{s}</code>) : "—"}</dd>
                <dt>Usage</dt>
                <dd><UsageBadge status={d.usage_status} /></dd>
                <dt>Notes</dt>
                <dd style={{ whiteSpace: "pre-wrap" }}>{d.notes || <span className="muted">No notes</span>}</dd>
                <dt>Added</dt>
                <dd>{formatDateTime(d.created_at)}</dd>
              </dl>
            </div>
          </div>
          <MonitoringPanel record={d} />
        </div>
      )}

      <RecordHistory basePath={`/domains/${d.id}`} refreshKey={refreshKey} />
    </>
  );
}
