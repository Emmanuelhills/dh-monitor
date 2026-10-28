"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAsync, useDebounced } from "@/lib/hooks";
import type { Domain, Hosting, Page, Registrar } from "@/lib/types";
import { BulkBar, SelectAllHeader, SelectCell, useSelection, type BulkAction } from "./BulkSelect";
import { ExpirationBadge, ExpiryDot, MonitoringBadge, ServiceBadge, UsageBadge } from "./Badges";
import { DEFAULT_PAGE_SIZE, Empty, ErrorAlert, Loading, Pagination, SortHeader, useSessionState } from "./ui";

interface Filters {
  search: string;
  hosting: string; // "" | "unassigned" | id
  registrar: string; // "" | "none" | id
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
  hosting: "",
  registrar: "",
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

/** Domain list. `compact` renders a narrow three-column version for side-by-side layouts. */
export function DomainTable({ title = "Domains", storageKey = "domain-filters", compact = false }: {
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

  const hostingOptions = useAsync(
    () => api.get<Page<Hosting>>("/hosting-accounts", { page_size: 100 }).then((p) => p.items),
    [],
  );
  const registrars = useAsync(() => api.get<Registrar[]>("/registrars", { kind: "domain" }), []);
  const providers = useAsync(() => (compact ? Promise.resolve([]) : api.get<string[]>("/hosting-accounts/providers")), [compact]);

  const list = useAsync(
    () =>
      api.get<Page<Domain>>("/domains", {
        search,
        hosting_account_id: filters.hosting,
        registrar_id: filters.registrar,
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
    [search, filters.hosting, filters.registrar, filters.provider, filters.usage, filters.service, filters.monitoring,
      filters.expiration, filters.archived, filters.sort, filters.order, page, pageSize],
  );

  const selection = useSelection(
    list.data?.items.map((d) => d.id) ?? [],
    JSON.stringify([search, filters, page, pageSize]),
  );
  const selectable = !compact;
  const bulkActions: BulkAction[] = filters.archived
    ? [{
        label: "Delete permanently", title: `Delete ${selection.count} domain(s) permanently?`, path: "/domains/bulk-delete",
        permanent: true, done: "deleted", noun: ["domain", "domains"],
        message: "This removes the selected domains and their monitoring and reminder history. Their hosting accounts are not affected. This cannot be undone.",
      }]
    : [{
        label: "Archive selected", title: `Archive ${selection.count} domain(s)?`, path: "/domains/bulk-delete",
        permanent: false, done: "archived", noun: ["domain", "domains"],
        message: "The selected domains leave the active lists, checks stop and queued reminders are cancelled. Their hosting accounts are not affected. You can restore them from the Archived view.",
      }];

  const filtered = JSON.stringify({ ...filters, sort: "", order: "", pageSize: 0 }) !== JSON.stringify({ ...DEFAULTS, sort: "", order: "", pageSize: 0 });
  const onSort = (sort: string, order: "asc" | "desc") => update({ sort, order });
  const id = (suffix: string) => `${storageKey}-${suffix}`;

  return (
    <section className="card section" aria-labelledby={id("title")}>
      <div className="card-header">
        <h2 id={id("title")}>
          {title} {list.data && <span className="muted small">({list.data.total})</span>}
        </h2>
        <Link className="btn primary small" href="/domains/new">
          Add domain
        </Link>
      </div>
      <div className="toolbar" role="search">
        <label className="sr-only" htmlFor={id("search")}>Search domains</label>
        <input id={id("search")} className="grow" type="search" placeholder="Search domains, registrars, hosting…"
          value={filters.search} onChange={(e) => update({ search: e.target.value })} />
        <label className="sr-only" htmlFor={id("hosting")}>Hosting account</label>
        <select id={id("hosting")} value={filters.hosting} onChange={(e) => update({ hosting: e.target.value })}>
          <option value="">All hosting</option>
          <option value="unassigned">Unassigned</option>
          {hostingOptions.data?.map((h) => (
            <option key={h.id} value={h.id}>{h.name}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor={id("registrar")}>Registrar</label>
        <select id={id("registrar")} value={filters.registrar} onChange={(e) => update({ registrar: e.target.value })}>
          <option value="">All registrars</option>
          <option value="none">No registrar set</option>
          {registrars.data?.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        {!compact && (
          <>
            <label className="sr-only" htmlFor={id("provider")}>Hosting company</label>
            <select id={id("provider")} value={filters.provider} onChange={(e) => update({ provider: e.target.value })}>
              <option value="">All providers</option>
              {providers.data?.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </>
        )}
        <label className="sr-only" htmlFor={id("usage")}>Usage status</label>
        <select id={id("usage")} value={filters.usage} onChange={(e) => update({ usage: e.target.value })}>
          <option value="">Any usage</option>
          <option value="active">Usage: Active</option>
          <option value="inactive">Usage: Inactive</option>
        </select>
        {!compact && (
          <>
            <label className="sr-only" htmlFor={id("service")}>Registration status</label>
            <select id={id("service")} value={filters.service} onChange={(e) => update({ service: e.target.value })}>
              <option value="">Any registration status</option>
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
        <Empty title={filtered ? "No domains match these filters" : "No domains yet"}>
          {filtered ? "Try clearing some filters." : <Link href="/domains/new">Add your first domain</Link>}
        </Empty>
      )}
      {selectable && <BulkBar selection={selection} actions={bulkActions} onDone={() => (page === 1 ? list.reload() : setPage(1))} />}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap" aria-busy={list.loading}>
          <table className="data responsive">
            <thead>
              <tr>
                {selectable && <SelectAllHeader selection={selection} label="Select all domains on this page" />}
                <SortHeader label="Domain" field="name" sort={filters.sort} order={filters.order} onSort={onSort} />
                {!compact && <th>Hosting account</th>}
                {!compact && <th>Registrar</th>}
                <SortHeader label="Expiration" field="expiration_date" sort={filters.sort} order={filters.order} onSort={onSort} />
                {compact ? <th>Status</th> : (
                  <>
                    <th>Usage</th>
                    <th>Registration</th>
                    <th>Monitoring</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((d) => (
                <tr key={d.id} className={selection.has(d.id) ? "selected" : undefined}>
                  {selectable && <SelectCell selection={selection} id={d.id} label={`Select ${d.display_name}`} />}
                  <td className="name" data-label="Domain">
                    <span className="name-cell">
                      <ExpiryDot expiration={d.expiration} />
                      <span>
                        <Link href={`/domains/${d.id}`}>{d.display_name}</Link>
                        {compact && (
                          <span className="sub">
                            {d.hosting_account ? d.hosting_account.name : "Unassigned"}
                            {d.registrar && ` · ${d.registrar.name}`}
                          </span>
                        )}
                      </span>
                    </span>
                  </td>
                  {!compact && (
                    <td data-label="Hosting">
                      {d.hosting_account ? (
                        <Link href={`/hosting/${d.hosting_account.id}`}>{d.hosting_account.name}</Link>
                      ) : (
                        <span className="muted">Unassigned</span>
                      )}
                    </td>
                  )}
                  {!compact && (
                    <td data-label="Registrar">{d.registrar ? d.registrar.name : <span className="muted">—</span>}</td>
                  )}
                  <td data-label="Expiration">
                    <div className="badges"><ExpirationBadge expiration={d.expiration} /></div>
                    <div className="small muted">
                      {formatDate(d.expiration_date)}
                      {d.expiration_date && d.expiration_source === "manual" && " · manual"}
                    </div>
                  </td>
                  {compact ? (
                    <td data-label="Status">
                      <div className="badges stack">
                        <UsageBadge status={d.usage_status} />
                        <ServiceBadge status={d.service_status} />
                      </div>
                    </td>
                  ) : (
                    <>
                      <td data-label="Usage"><UsageBadge status={d.usage_status} /></td>
                      <td data-label="Registration"><ServiceBadge status={d.service_status} /></td>
                      <td data-label="Monitoring"><MonitoringBadge status={d.monitoring_status} stale={d.is_stale} /></td>
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
