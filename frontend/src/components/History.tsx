"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { displayValue, fieldLabel, formatDateTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { AuditEvent, MonitoringCheck, Page } from "@/lib/types";
import { CheckResultBadge } from "./Badges";
import { Empty, ErrorAlert, Loading, Pagination } from "./ui";

const HIDDEN_OBSERVED = new Set(["missing_fields"]);

function CheckItem({ check }: { check: MonitoringCheck }) {
  const changes = Object.entries(check.changes ?? {});
  const conflicts = Object.entries(check.conflicts ?? {});
  const missing = (check.observed_data?.missing_fields as string[] | undefined) ?? [];
  const observed = Object.entries(check.observed_data ?? {}).filter(([k]) => !HIDDEN_OBSERVED.has(k));
  return (
    <li>
      <div className="meta">
        <CheckResultBadge result={check.result} />
        <strong>{check.source}</strong>
        <span className="muted small">{formatDateTime(check.checked_at)}</span>
        {check.duration_ms != null && <span className="muted small">{check.duration_ms} ms</span>}
      </div>
      {check.error_message && (
        <div className="small" style={{ marginTop: 6 }}>
          <code>{check.error_code}</code> {check.error_message}. Saved values were kept.
        </div>
      )}
      {changes.length > 0 && (
        <div className="kv">
          <strong>Updated:</strong>
          {changes.map(([field, c]) => (
            <span key={field}>{fieldLabel(field)}: {displayValue(c.from)} → {displayValue(c.to)}</span>
          ))}
        </div>
      )}
      {conflicts.length > 0 && (
        <div className="kv" style={{ color: "var(--urgent-fg)" }}>
          <strong>Not applied (conflict):</strong>
          {conflicts.map(([field, c]) => (
            <span key={field}>
              {fieldLabel(field)}: saved {displayValue(c.saved)}, source reported {displayValue(c.observed)}. {c.reason}
            </span>
          ))}
        </div>
      )}
      {missing.length > 0 && <div className="kv">Not returned by source: {missing.map(fieldLabel).join(", ")}</div>}
      {observed.length > 0 && (
        <details className="kv">
          <summary>Observed data</summary>
          {observed.map(([k, v]) => (
            <span key={k}>{fieldLabel(k)}: <code>{displayValue(v)}</code></span>
          ))}
        </details>
      )}
    </li>
  );
}

const ACTION_LABELS: Record<string, string> = {
  domain_created: "Created",
  domain_updated: "Updated",
  domain_archived: "Archived",
  domain_restored: "Restored",
  hosting_created: "Created",
  hosting_updated: "Updated",
  hosting_archived: "Archived",
  hosting_restored: "Restored",
  check_requested: "Check requested",
  admin_url_viewed: "Admin URL viewed",
  status_auto_expired: "Marked expired",
};

function AuditItem({ event }: { event: AuditEvent }) {
  const changes = Object.entries((event.details?.changes as Record<string, { from: unknown; to: unknown }>) ?? {});
  return (
    <li>
      <div className="meta">
        <strong>{ACTION_LABELS[event.action] ?? fieldLabel(event.action)}</strong>
        <span className="muted small">by {event.actor} · {formatDateTime(event.created_at)}</span>
      </div>
      {changes.length > 0 && (
        <div className="kv">
          {changes.map(([field, c]) => (
            <span key={field}>{fieldLabel(field)}: {displayValue(c.from)} → {displayValue(c.to)}</span>
          ))}
        </div>
      )}
      {typeof event.details?.reason === "string" && <div className="kv">{event.details.reason}</div>}
    </li>
  );
}

/** Recent checks as bars, oldest left / newest right. */
function CheckBars({ basePath, refreshKey }: { basePath: string; refreshKey: number }) {
  const recent = useAsync(() => api.get<Page<MonitoringCheck>>(`${basePath}/checks`, { page: 1, page_size: 40 }), [basePath, refreshKey]);
  const items = [...(recent.data?.items ?? [])].reverse();
  if (!items.length) return null;
  const ok = items.filter((c) => c.result === "success").length;
  return (
    <div className="card-body" style={{ borderBottom: "1px solid var(--border-soft)" }}>
      <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <span className="small muted">{items.length === 1 ? "Last check" : `Last ${items.length} checks`}</span>
        <span className="small"><strong className="accent">{Math.round((ok / items.length) * 100)}%</strong> <span className="muted">successful</span></span>
      </div>
      <div className="check-bars" role="img" aria-label={`${ok} of ${items.length} recent checks succeeded`}>
        {items.map((c) => (
          <span key={c.id} className={c.result === "success" ? "ok" : c.result === "partial" ? "warn" : "danger"}
            title={`${formatDateTime(c.checked_at)} · ${c.result}${c.error_message ? ` · ${c.error_message}` : ""}`} />
        ))}
      </div>
    </div>
  );
}

export function RecordHistory({ basePath, refreshKey }: { basePath: string; refreshKey: number }) {
  const [tab, setTab] = useState<"checks" | "changes">("checks");
  const [page, setPage] = useState(1);
  const checks = useAsync(
    () => (tab === "checks" ? api.get<Page<MonitoringCheck>>(`${basePath}/checks`, { page, page_size: 10 }) : Promise.resolve(null)),
    [basePath, tab, page, refreshKey],
  );
  const changes = useAsync(
    () => (tab === "changes" ? api.get<Page<AuditEvent>>(`${basePath}/changes`, { page, page_size: 10 }) : Promise.resolve(null)),
    [basePath, tab, page, refreshKey],
  );
  const current = tab === "checks" ? checks : changes;

  return (
    <section className="card section">
      <CheckBars basePath={basePath} refreshKey={refreshKey} />
      <div className="tabs" role="tablist">
        <button className="tab" role="tab" aria-selected={tab === "checks"} onClick={() => { setTab("checks"); setPage(1); }}>
          Monitoring history
        </button>
        <button className="tab" role="tab" aria-selected={tab === "changes"} onClick={() => { setTab("changes"); setPage(1); }}>
          Change log
        </button>
      </div>
      {current.error && <div className="card-body"><ErrorAlert message={current.error} onRetry={current.reload} /></div>}
      {current.loading && !current.data && <Loading />}
      {tab === "checks" && checks.data && (
        checks.data.items.length === 0 ? (
          <Empty title="No checks yet">Automatic checks run in the background. You can also run one now.</Empty>
        ) : (
          <>
            <ul className="timeline">{checks.data.items.map((c) => <CheckItem key={c.id} check={c} />)}</ul>
            <Pagination page={page} pageSize={10} total={checks.data.total} onPage={setPage} />
          </>
        )
      )}
      {tab === "changes" && changes.data && (
        changes.data.items.length === 0 ? (
          <Empty title="No changes recorded" />
        ) : (
          <>
            <ul className="timeline">{changes.data.items.map((e) => <AuditItem key={e.id} event={e} />)}</ul>
            <Pagination page={page} pageSize={10} total={changes.data.total} onPage={setPage} />
          </>
        )
      )}
    </section>
  );
}
