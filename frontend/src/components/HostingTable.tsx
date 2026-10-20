"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAsync, useDebounced } from "@/lib/hooks";
import type { Hosting, Page } from "@/lib/types";
import { ExpirationBadge, ExpiryDot, MonitoringBadge, ServiceBadge, UsageBadge } from "./Badges";
import { DEFAULT_PAGE_SIZE, Empty, ErrorAlert, Loading, Pagination, SortHeader, useSessionState } from "./ui";

interface Filters {
  search: string;
  provider: string;
  usage: string;
  service: string;
  monitoring: string;
  expiration: string;
  sort: string;
  order: "asc" | "desc";
  archived: boolean;
  pageSize: number;
}

const DEFAULTS: Filters = {
  search: "",
  provider: "",
  usage: "",
  service: "",
  monitoring: "",
  expiration: "",
  sort: "name",
  order: "asc",
  archived: false,
  pageSize: DEFAULT_PAGE_SIZE,
};

/** Hosting list. `compact` renders a narrow three-column version for side-by-side layouts. */
export function HostingTable({ title = "Hosting accounts", storageKey = "hosting-filters", compact = false }: {
  title?: string;
  storageKey?: string;
  compact?: boolean;
}) {
  const [filters, setFilters] = useSessionState<Filters>(storageKey, DEFAULTS);
  const [page, setPage] = useState(1);
  const pageSize = filters.pageSize || DEFAULT_PAGE_SIZE;
  const search = useDebounced(filters.search);
  const update = (patch: Partial<Filters>) => {
    setFilters({ ...filters, ...patch });
    setPage(1);
  };

  const providers = useAsync(() => api.get<string[]>("/hosting-accounts/providers"), []);
  const list = useAsync(
    () =>
      api.get<Page<Hosting>>("/hosting-accounts", {
        search,
        provider_name: filters.provider,
        usage_status: filters.usage,
        service_status: filters.service,
        monitoring_status: filters.monitoring,
        expiration: filters.expiration,
        archived_only: filters.archived || undefined,
        sort: filters.sort,
        order: filters.order,
        page,
        page_size: pageSize,
      }),
    [search, filters.provider, filters.usage, filters.service, filters.monitoring, filters.expiration,
      filters.archived, filters.sort, filters.order, page, pageSize],
  );
  const filtered = JSON.stringify({ ...filters, sort: "", order: "", pageSize: 0 }) !== JSON.stringify({ ...DEFAULTS, sort: "", order: "", pageSize: 0 });
  const onSort = (sort: string, order: "asc" | "desc") => update({ sort, order });
  const id = (suffix: string) => `${storageKey}-${suffix}`;

  return (
    <section className="card section" aria-labelledby={id("title")}>
      <div className="card-header">
        <h2 id={id("title")}>
          {title} {list.data && <span className="muted small">({list.data.total})</span>}
        </h2>
        <Link className="btn primary small" href="/hosting/new">
          Add hosting
        </Link>
      </div>
      <div className="toolbar" role="search">
        <label className="sr-only" htmlFor={id("search")}>Search hosting accounts</label>
        <input id={id("search")} className="grow" type="search" placeholder="Search name or company…"
          value={filters.search} onChange={(e) => update({ search: e.target.value })} />
        <label className="sr-only" htmlFor={id("provider")}>Hosting company</label>
        <select id={id("provider")} value={filters.provider} onChange={(e) => update({ provider: e.target.value })}>
          <option value="">All companies</option>
          {providers.data?.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor={id("usage")}>Usage status</label>
        <select id={id("usage")} value={filters.usage} onChange={(e) => update({ usage: e.target.value })}>
          <option value="">Any usage</option>
          <option value="active">Usage: Active</option>
          <option value="inactive">Usage: Inactive</option>
        </select>
        {!compact && (
          <>
            <label className="sr-only" htmlFor={id("service")}>Service status</label>
            <select id={id("service")} value={filters.service} onChange={(e) => update({ service: e.target.value })}>
              <option value="">Any service status</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
              <option value="expired">Expired</option>
              <option value="unknown">Unknown</option>
            </select>
            <label className="sr-only" htmlFor={id("monitoring")}>Monitoring status</label>
            <select id={id("monitoring")} value={filters.monitoring} onChange={(e) => update({ monitoring: e.target.value })}>
              <option value="">Any monitoring</option>
              <option value="current">Current</option>
              <option value="due">Check due</option>
              <option value="partial">Partial</option>
              <option value="failed">Failed</option>
              <option value="manual">Manual</option>
            </select>
          </>
        )}
        <label className="sr-only" htmlFor={id("exp")}>Expiration window</label>
        <select id={id("exp")} value={filters.expiration} onChange={(e) => update({ expiration: e.target.value })}>
          <option value="">Any expiration</option>
          <option value="overdue">Overdue</option>
          <option value="within_7">Within 7 days</option>
          <option value="within_30">Within 30 days</option>
          <option value="beyond_30">More than 30 days</option>
          <option value="unknown">Unknown date</option>
        </select>
        {!compact && (
          <label className="checkbox small">
            <input type="checkbox" checked={filters.archived} onChange={(e) => update({ archived: e.target.checked })} />
            Archived
          </label>
        )}
        {filtered && (
          <button className="btn small" onClick={() => update({ ...DEFAULTS, sort: filters.sort, order: filters.order, pageSize: filters.pageSize })}>
            Clear filters
          </button>
        )}
      </div>

      {list.error && <div className="card-body"><ErrorAlert message={list.error} onRetry={list.reload} /></div>}
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.items.length === 0 && (
        <Empty title={filtered ? "No hosting accounts match these filters" : "No hosting accounts yet"}>
          {filtered ? "Try clearing some filters." : <Link href="/hosting/new">Add a hosting account</Link>}
        </Empty>
      )}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap" aria-busy={list.loading}>
          <table className="data responsive">
            <thead>
              <tr>
                <SortHeader label="Hosting plan" field="name" sort={filters.sort} order={filters.order} onSort={onSort} />
                {!compact && <SortHeader label="Company" field="provider_name" sort={filters.sort} order={filters.order} onSort={onSort} />}
                {!compact && <SortHeader label="Domains" field="domain_count" sort={filters.sort} order={filters.order} onSort={onSort} />}
                <SortHeader label="Expiration" field="expiration_date" sort={filters.sort} order={filters.order} onSort={onSort} />
                {compact ? <th>Status</th> : (
                  <>
                    <th>Usage</th>
                    <th>Service</th>
                    <th>Monitoring</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((h) => (
                <tr key={h.id}>
                  <td className="name" data-label="Hosting plan">
                    <span className="name-cell">
                      <ExpiryDot expiration={h.expiration} />
                      <span>
                        <Link href={`/hosting/${h.id}`}>{h.name}</Link>
                        {compact && (
                          <span className="sub">
                            {h.provider_name} · {h.domain_count} domain{h.domain_count === 1 ? "" : "s"}
                          </span>
                        )}
                      </span>
                    </span>
                  </td>
                  {!compact && <td data-label="Company">{h.provider_name}</td>}
                  {!compact && <td data-label="Domains">{h.domain_count}</td>}
                  <td data-label="Expiration">
                    <div className="badges"><ExpirationBadge expiration={h.expiration} /></div>
                    <div className="small muted">
                      {formatDate(h.expiration_date)}
                      {h.expiration_date && h.expiration_source === "manual" && " · manual"}
                    </div>
                  </td>
                  {compact ? (
                    <td data-label="Status">
                      <div className="badges stack">
                        <UsageBadge status={h.usage_status} />
                        <ServiceBadge status={h.service_status} />
                      </div>
                    </td>
                  ) : (
                    <>
                      <td data-label="Usage"><UsageBadge status={h.usage_status} /></td>
                      <td data-label="Service"><ServiceBadge status={h.service_status} /></td>
                      <td data-label="Monitoring"><MonitoringBadge status={h.monitoring_status} stale={h.is_stale} /></td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.data && <Pagination page={page} pageSize={pageSize} total={list.data.total} onPage={setPage}
        onPageSize={(size) => update({ pageSize: size })} />}
    </section>
  );
}
