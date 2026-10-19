import type { SummaryCounts } from "@/lib/types";

type Counts = Pick<SummaryCounts, "total" | "active" | "inactive" | "expiring_30_days" | "expired">;

/** The four headline cards for one record type: Total, Active / Inactive, Expiring ≤ 30 days, Expired. */
export function SummaryCards({ counts }: { counts: Counts }) {
  return (
    <div className="stats stats-4">
      <div className="card stat ok"><div className="value">{counts.total}</div><div className="label">Total</div></div>
      <div className="card stat">
        <div className="value">{counts.active}<span className="value-sep">/</span>{counts.inactive}</div>
        <div className="label">Active / Inactive</div>
      </div>
      <div className={`card stat${counts.expiring_30_days ? " warn" : ""}`}>
        <div className="value">{counts.expiring_30_days}</div><div className="label">Expiring ≤ 30 days</div>
      </div>
      <div className={`card stat${counts.expired ? " danger" : ""}`}>
        <div className="value">{counts.expired}</div><div className="label">Expired</div>
      </div>
    </div>
  );
}
