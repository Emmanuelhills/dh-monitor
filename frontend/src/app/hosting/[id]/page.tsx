"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ExpirationBadge, MonitoringBadge, ServiceBadge, UsageBadge } from "@/components/Badges";
import { RecordHistory } from "@/components/History";
import { HostingForm } from "@/components/HostingForm";
import { MonitoringPanel, RunCheckButton } from "@/components/RecordPanels";
import { useToast } from "@/components/Toast";
import { ConfirmButton, Empty, ErrorAlert, Loading } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { HostingDetail } from "@/lib/types";

export default function HostingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const hosting = useAsync(() => api.get<HostingDetail>(`/hosting-accounts/${id}`), [id, refreshKey]);
  const refresh = () => setRefreshKey((k) => k + 1);

  if (hosting.error) return <ErrorAlert message={hosting.error} onRetry={hosting.reload} />;
  if (!hosting.data) return <Loading />;
  const h = hosting.data;
  const archived = !!h.archived_at;

  const act = (fn: () => Promise<unknown>, done: string, after?: () => void) => async () => {
    try {
      await fn();
      toast("success", done);
      (after ?? refresh)();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  };

  const domainNote = h.domain_count
    ? ` Its ${h.domain_count} domain${h.domain_count === 1 ? "" : "s"} will not be deleted.`
    : "";

  return (
    <>
      <div className="page-header">
        <div>
          <div className="small"><Link href="/hosting">← Hosting accounts</Link></div>
          <h1>{h.name}</h1>
          <div className="badges" style={{ marginTop: 6 }}>
            <UsageBadge status={h.usage_status} prefix="Usage" />
            <ServiceBadge status={h.service_status} prefix="Service" />
            {archived && <span className="badge neutral">Archived</span>}
          </div>
        </div>
        {!editing && (
          <div className="btn-row">
            {!archived && (
              <>
                <RunCheckButton path={`/hosting-accounts/${h.id}`} record={h} onUpdated={refresh} />
                <button className="btn primary" onClick={() => setEditing(true)}>Edit</button>
                <ConfirmButton label="Archive" title={`Archive ${h.name}?`} confirmLabel="Archive"
                  message={`Checks stop and queued reminders are cancelled.${domainNote} You can restore it later.`}
                  onConfirm={act(() => api.del(`/hosting-accounts/${h.id}`), `${h.name} archived.`)} />
              </>
            )}
            {archived && (
              <>
                <button className="btn primary"
                  onClick={act(() => api.post(`/hosting-accounts/${h.id}/restore`), `${h.name} restored.`)}>Restore</button>
                <ConfirmButton label="Delete permanently" title={`Delete ${h.name} permanently?`} confirmLabel="Delete permanently"
                  message={`This removes the account and its history. Associated domains are kept and become unassigned.${domainNote}`}
                  onConfirm={act(() => api.del(`/hosting-accounts/${h.id}`, { permanent: true }), `${h.name} deleted.`,
                    () => router.replace("/hosting"))} />
              </>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <div className="card section">
          <div className="card-header"><h2>Edit hosting account</h2></div>
          <div className="card-body">
            <HostingForm hosting={h} onCancel={() => setEditing(false)}
              onSaved={(saved) => { hosting.setData(saved); setEditing(false); refresh(); toast("success", "Hosting account saved."); }} />
          </div>
        </div>
      ) : (
        <div className="grid grid-2 section">
          <div className="card">
            <div className="card-header"><h2>Account</h2></div>
            <div className="card-body">
              <dl className="props">
                <dt>Hosting company</dt>
                <dd>{h.registrar ? <Link href="/registrars">{h.registrar.name}</Link> : <>{h.provider_name} <span className="muted small">(not in registrars)</span></>}</dd>
                <dt>Purchase date</dt>
                <dd>{formatDate(h.purchase_date)}</dd>
                <dt>Integration</dt>
                <dd>{h.integration ? <>{h.integration.name} {h.external_ref && <span className="muted small">· service {h.external_ref}</span>}</> : <span className="muted">None. Maintained manually.</span>}</dd>
                <dt>Admin URL</dt>
                <dd className="muted">{h.has_admin_url ? "Saved (private; open Edit to view)" : "Not set"}</dd>
                <dt>Usage</dt>
                <dd><UsageBadge status={h.usage_status} /></dd>
                <dt>Notes</dt>
                <dd style={{ whiteSpace: "pre-wrap" }}>{h.notes || <span className="muted">No notes</span>}</dd>
                <dt>Added</dt>
                <dd>{formatDateTime(h.created_at)}</dd>
              </dl>
            </div>
          </div>
          <MonitoringPanel record={h} />
        </div>
      )}

      <section className="card section">
        <div className="card-header">
          <h2>Associated domains ({h.domains.length})</h2>
          <span className="small muted">Domains keep their own expiration dates.</span>
        </div>
        {h.domains.length === 0 ? (
          <Empty title="No domains use this hosting account">Assign one from a domain&apos;s edit form.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data responsive">
              <thead>
                <tr><th>Domain</th><th>Expiration</th><th>Usage</th><th>Registration</th><th>Monitoring</th></tr>
              </thead>
              <tbody>
                {h.domains.map((d) => (
                  <tr key={d.id}>
                    <td className="name" data-label="Domain"><Link href={`/domains/${d.id}`}>{d.domain_name}</Link></td>
                    <td data-label="Expiration"><ExpirationBadge expiration={d.expiration} /><div className="small muted">{formatDate(d.expiration_date)}</div></td>
                    <td data-label="Usage"><UsageBadge status={d.usage_status} /></td>
                    <td data-label="Registration"><ServiceBadge status={d.service_status} /></td>
                    <td data-label="Monitoring"><MonitoringBadge status={d.monitoring_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <RecordHistory basePath={`/hosting-accounts/${h.id}`} refreshKey={refreshKey} />
    </>
  );
}
