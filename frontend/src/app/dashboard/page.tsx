"use client";

import Link from "next/link";
import { ExpirationBadge, ServiceBadge, UsageBadge } from "@/components/Badges";
import { DomainTable } from "@/components/DomainTable";
import { HostingTable } from "@/components/HostingTable";
import { SummaryCards } from "@/components/SummaryCards";
import { ErrorAlert, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { Dashboard } from "@/lib/types";

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export default function DashboardPage() {
  const dash = useAsync(() => api.get<Dashboard>("/dashboard"), []);
  const d = dash.data;

  // Things that need attention but have no headline card.
  const attention: string[] = [];
  if (d) {
    const overdue = d.domains.overdue + d.hosting.overdue;
    const failed = d.domains.monitoring_failed + d.hosting.monitoring_failed + d.domains.stale + d.hosting.stale;
    const suspended = d.domains.suspended + d.hosting.suspended;
    const unknown = d.domains.unknown_expiration + d.hosting.unknown_expiration;
    if (overdue) attention.push(`${plural(overdue, "record")} past the expiration date with no confirmed renewal.`);
    if (suspended) attention.push(`${plural(suspended, "record")} suspended.`);
    if (failed) attention.push(`${plural(failed, "record")} with failed or stale checks.`);
    if (unknown) attention.push(`${plural(unknown, "record")} without an expiration date.`);
  }
  const warnings = [...(d?.warnings ?? []), ...attention];

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          {d && <p>Today is {formatDate(d.today)} ({d.timezone})</p>}
        </div>
      </div>

      {dash.error && <ErrorAlert message={dash.error} onRetry={dash.reload} />}
      {dash.loading && !d && <Loading />}
      {warnings.length > 0 && (
        <div className="alert warn" role="status">
          <ul>{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          {d && !d.notifications_enabled && <Link href="/settings/email">Open email settings</Link>}
        </div>
      )}

      {d && (
        <section className="card section">
          <div className="card-header">
            <h2>Upcoming and overdue expirations (next 30 days)</h2>
            <span className="small muted">
              Reminders in the last 7 days: {d.notifications_last_7_days.sent} accepted, {d.notifications_last_7_days.failed} failed
            </span>
          </div>
          {d.upcoming.length === 0 ? (
            <div className="empty">Nothing expires in the next 30 days.</div>
          ) : (
            <div className="table-wrap">
              <table className="data responsive">
                <thead>
                  <tr><th>Name</th><th>Type</th><th>Expiration</th><th>Usage</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {d.upcoming.map((u) => (
                    <tr key={`${u.record_type}-${u.id}`}>
                      <td className="name" data-label="Name">
                        <Link href={`/${u.record_type === "domain" ? "domains" : "hosting"}/${u.id}`}>{u.name}</Link>
                        <span className="sub">{u.context}</span>
                      </td>
                      <td data-label="Type">{u.record_type === "domain" ? "Domain" : "Hosting"}</td>
                      <td data-label="Expiration">
                        <ExpirationBadge expiration={u.expiration} />
                        <div className="small muted">{formatDate(u.expiration_date)}</div>
                      </td>
                      <td data-label="Usage"><UsageBadge status={u.usage_status} /></td>
                      <td data-label="Status"><ServiceBadge status={u.service_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Domains first (left), hosting plans second (right). */}
      <div className="columns">
        <div className="column">
          <h2 className="column-title"><Link href="/domains">Domains</Link></h2>
          {d && <SummaryCards counts={d.domains} />}
          <DomainTable title="Domain list" storageKey="dash-domains" compact />
        </div>
        <div className="column">
          <h2 className="column-title"><Link href="/hosting">Hosting plans</Link></h2>
          {d && <SummaryCards counts={d.hosting} />}
          <HostingTable title="Hosting list" storageKey="dash-hosting" compact />
        </div>
      </div>

    </>
  );
}
