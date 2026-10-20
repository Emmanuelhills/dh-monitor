"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ExpirationBadge, ExpiryDot, ServiceBadge, UsageBadge } from "@/components/Badges";
import { SummaryCards } from "@/components/SummaryCards";
import { DEFAULT_PAGE_SIZE, Empty, ErrorAlert, Loading, Pagination } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime } from "@/lib/format";
import type { Expiration, ServiceStatus, UsageStatus } from "@/lib/types";

interface PublicDomain {
  id: string;
  domain_name: string;
  hosting_account: string | null;
  hosting_provider: string | null;
  expiration_date: string | null;
  expiration: Expiration;
  expiration_verified: boolean;
  usage_status: UsageStatus;
  service_status: ServiceStatus;
}

interface PublicHosting {
  id: string;
  name: string;
  provider_name: string;
  domain_count: number;
  expiration_date: string | null;
  expiration: Expiration;
  expiration_verified: boolean;
  usage_status: UsageStatus;
  service_status: ServiceStatus;
}

interface Overview {
  today: string;
  timezone: string;
  domains: PublicDomain[];
  hosting: PublicHosting[];
}

type Window = "" | "overdue" | "30" | "unknown";
type Sort = "name" | "expiration";

const REFRESH_MS = 5 * 60 * 1000;

function matchesWindow(e: Expiration, w: Window): boolean {
  if (!w) return true;
  if (w === "unknown") return e.days_remaining === null;
  if (w === "overdue") return e.days_remaining !== null && e.days_remaining < 0;
  return e.days_remaining !== null && e.days_remaining >= 0 && e.days_remaining <= 30;
}

function byExpiration(a: { expiration_date: string | null }, b: { expiration_date: string | null }) {
  if (a.expiration_date === b.expiration_date) return 0;
  if (!a.expiration_date) return 1; // unknown dates last
  if (!b.expiration_date) return -1;
  return a.expiration_date < b.expiration_date ? -1 : 1;
}

function summarize(rows: { usage_status: UsageStatus; service_status: ServiceStatus; expiration: Expiration }[]) {
  return {
    total: rows.length,
    active: rows.filter((r) => r.usage_status === "active").length,
    inactive: rows.filter((r) => r.usage_status === "inactive").length,
    expiring_30_days: rows.filter((r) => matchesWindow(r.expiration, "30")).length,
    expired: rows.filter((r) => r.service_status === "expired").length,
  };
}

function DateCell({ date, verified }: { date: string | null; verified: boolean }) {
  return (
    <div className="small muted">
      {formatDate(date)}
      {date && (verified ? " · verified" : " · manual")}
    </div>
  );
}

export default function PublicOverviewPage() {
  const { user } = useAuth();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loadedAt, setLoadedAt] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [usage, setUsage] = useState("");
  const [window_, setWindow] = useState<Window>("");
  const [sort, setSort] = useState<Sort>("name");
  const [domainPage, setDomainPage] = useState(1);
  const [domainSize, setDomainSize] = useState(DEFAULT_PAGE_SIZE);
  const [hostingPage, setHostingPage] = useState(1);
  const [hostingSize, setHostingSize] = useState(DEFAULT_PAGE_SIZE);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .get<Overview>("/public/overview")
        .then((o) => {
          if (cancelled) return;
          setData(o);
          setError(null);
          setLoadedAt(new Date().toISOString());
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof ApiError && err.code === "public_page_disabled") setDisabled(true);
          else setError(err instanceof Error ? err.message : "Could not load the overview.");
        });
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const term = search.trim().toLowerCase();

  const domains = useMemo(() => {
    if (!data) return [];
    const rows = data.domains.filter(
      (d) =>
        (!term || d.domain_name.toLowerCase().includes(term) || (d.hosting_account ?? "").toLowerCase().includes(term)) &&
        (!usage || d.usage_status === usage) &&
        matchesWindow(d.expiration, window_),
    );
    return sort === "expiration" ? [...rows].sort(byExpiration) : rows;
  }, [data, term, usage, window_, sort]);

  const hosting = useMemo(() => {
    if (!data) return [];
    const rows = data.hosting.filter(
      (h) =>
        (!term || h.name.toLowerCase().includes(term) || h.provider_name.toLowerCase().includes(term)) &&
        (!usage || h.usage_status === usage) &&
        matchesWindow(h.expiration, window_),
    );
    return sort === "expiration" ? [...rows].sort(byExpiration) : rows;
  }, [data, term, usage, window_, sort]);

  // Back to the first page whenever the search, filters or sort change.
  useEffect(() => { setDomainPage(1); setHostingPage(1); }, [term, usage, window_, sort]);
  const pagedDomains = domains.slice((domainPage - 1) * domainSize, domainPage * domainSize);
  const pagedHosting = hosting.slice((hostingPage - 1) * hostingSize, hostingPage * hostingSize);

  const domainCounts = useMemo(() => summarize(data?.domains ?? []), [data]);
  const hostingCounts = useMemo(() => summarize(data?.hosting ?? []), [data]);

  const filtered = !!(term || usage || window_);

  return (
    <div className="public-page">
      <nav className="topbar" aria-label="Site">
        <span className="brand-mark">Domain Monitor</span>
        <Link className={user ? "btn primary small" : "btn small"} href={user ? "/dashboard" : "/login"}>
          {user ? "Open admin dashboard" : "Admin sign in"}
        </Link>
      </nav>

      <header className="hero">
        <div className="eyebrow">Domain &amp; Hosting Overview</div>
        <h1>
          Every domain and hosting plan, <span className="accent">at a glance</span>.
        </h1>
        <p>
          Read-only list of our domains and hosting accounts.
          {data && <> Today is {formatDate(data.today)} ({data.timezone}).</>}
        </p>
        <div className="hero-points">
          <span>Expiration countdowns</span>
          <span>Hosting assignments</span>
          <span>Usage &amp; status</span>
        </div>
      </header>

      {disabled && (
        <div className="card"><Empty title="The public overview is turned off">Ask an administrator to enable it, or sign in.</Empty></div>
      )}
      {error && <ErrorAlert message={error} onRetry={() => window.location.reload()} />}
      {!data && !error && !disabled && <Loading />}

      {data && (
        <>
          <div className="card section">
            <div className="toolbar" role="search" style={{ borderBottom: "none" }}>
              <label className="sr-only" htmlFor="pub-search">Search</label>
              <input id="pub-search" className="grow" type="search" placeholder="Search domains, hosting or companies…"
                value={search} onChange={(e) => setSearch(e.target.value)} />
              <label className="sr-only" htmlFor="pub-usage">Usage</label>
              <select id="pub-usage" value={usage} onChange={(e) => setUsage(e.target.value)}>
                <option value="">Any usage</option>
                <option value="active">Usage: Active</option>
                <option value="inactive">Usage: Inactive</option>
              </select>
              <label className="sr-only" htmlFor="pub-window">Expiration</label>
              <select id="pub-window" value={window_} onChange={(e) => setWindow(e.target.value as Window)}>
                <option value="">Any expiration</option>
                <option value="30">Within 30 days</option>
                <option value="overdue">Overdue</option>
                <option value="unknown">Unknown date</option>
              </select>
              <label className="sr-only" htmlFor="pub-sort">Sort</label>
              <select id="pub-sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="name">Sort: A–Z</option>
                <option value="expiration">Sort: Expiring first</option>
              </select>
            </div>
          </div>

          {/* Domains first (left), hosting plans second (right). */}
          <div className="columns section">
            <div className="column">
              <h2 className="column-title">Domains</h2>
              <SummaryCards counts={domainCounts} />
              <section className="card" aria-labelledby="pub-domains">
                <div className="card-header"><h2 id="pub-domains">Domain list <span className="muted small">({domains.length})</span></h2></div>
                {domains.length === 0 ? (
                  <Empty title={filtered ? "No domains match" : "No domains yet"} />
                ) : (
                  <div className="table-wrap">
                    <table className="data responsive">
                      <thead><tr><th>Domain</th><th>Expiration</th><th>Status</th></tr></thead>
                      <tbody>
                        {pagedDomains.map((d) => (
                          <tr key={d.id}>
                            <td className="name" data-label="Domain">
                              <span className="name-cell">
                                <ExpiryDot expiration={d.expiration} />
                                <span>
                                  {d.domain_name}
                                  <span className="sub">{d.hosting_account ? `${d.hosting_account} · ${d.hosting_provider}` : "Unassigned"}</span>
                                </span>
                              </span>
                            </td>
                            <td data-label="Expiration">
                              <ExpirationBadge expiration={d.expiration} />
                              <DateCell date={d.expiration_date} verified={d.expiration_verified} />
                            </td>
                            <td data-label="Status">
                              <div className="badges stack">
                                <UsageBadge status={d.usage_status} />
                                <ServiceBadge status={d.service_status} />
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <Pagination page={domainPage} pageSize={domainSize} total={domains.length} onPage={setDomainPage}
                  onPageSize={(n) => { setDomainSize(n); setDomainPage(1); }} />
              </section>
            </div>

            <div className="column">
              <h2 className="column-title">Hosting plans</h2>
              <SummaryCards counts={hostingCounts} />
              <section className="card" aria-labelledby="pub-hosting">
                <div className="card-header"><h2 id="pub-hosting">Hosting list <span className="muted small">({hosting.length})</span></h2></div>
                {hosting.length === 0 ? (
                  <Empty title={filtered ? "No hosting plans match" : "No hosting plans yet"} />
                ) : (
                  <div className="table-wrap">
                    <table className="data responsive">
                      <thead><tr><th>Hosting plan</th><th>Expiration</th><th>Status</th></tr></thead>
                      <tbody>
                        {pagedHosting.map((h) => (
                          <tr key={h.id}>
                            <td className="name" data-label="Hosting plan">
                              <span className="name-cell">
                                <ExpiryDot expiration={h.expiration} />
                                <span>
                                  {h.name}
                                  <span className="sub">{h.provider_name} · {h.domain_count} domain{h.domain_count === 1 ? "" : "s"}</span>
                                </span>
                              </span>
                            </td>
                            <td data-label="Expiration">
                              <ExpirationBadge expiration={h.expiration} />
                              <DateCell date={h.expiration_date} verified={h.expiration_verified} />
                            </td>
                            <td data-label="Status">
                              <div className="badges stack">
                                <UsageBadge status={h.usage_status} />
                                <ServiceBadge status={h.service_status} />
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <Pagination page={hostingPage} pageSize={hostingSize} total={hosting.length} onPage={setHostingPage}
                  onPageSize={(n) => { setHostingSize(n); setHostingPage(1); }} />
              </section>
            </div>
          </div>

          {loadedAt && <p className="small muted">Updated {formatDateTime(loadedAt)} · refreshes every 5 minutes.</p>}
        </>
      )}
    </div>
  );
}
