import type { DataSource, DeliveryStatus, MonitoringStatus, RenewalStatus, ServiceStatus, UsageStatus } from "./types";

const dateFmt = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Date-only values (YYYY-MM-DD) are calendar dates: format without timezone shifting. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.split("-").map(Number);
  return dateFmt.format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return dateTimeFmt.format(new Date(value));
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  const abs = Math.abs(diff);
  const units: [number, string][] = [
    [86400000, "day"],
    [3600000, "hour"],
    [60000, "minute"],
  ];
  for (const [ms, unit] of units) {
    if (abs >= ms) {
      const n = Math.round(abs / ms);
      return diff >= 0 ? `${n} ${unit}${n === 1 ? "" : "s"} ago` : `in ${n} ${unit}${n === 1 ? "" : "s"}`;
    }
  }
  return "just now";
}

export const usageLabels: Record<UsageStatus, string> = { active: "Active", inactive: "Inactive" };

export const serviceLabels: Record<ServiceStatus, string> = {
  active: "Active",
  suspended: "Suspended",
  expired: "Expired",
  unknown: "Unknown",
};

export const renewalLabels: Record<RenewalStatus, string> = {
  unknown: "Unknown",
  renewed: "Renewed",
  not_renewed: "Not renewed",
};

export const monitoringLabels: Record<MonitoringStatus, string> = {
  current: "Current",
  due: "Check due",
  partial: "Partial",
  failed: "Failed",
  manual: "Manual",
};

export const sourceLabels: Record<DataSource, string> = {
  manual: "Entered manually",
  rdap: "Verified via RDAP",
  whois: "Verified via WHOIS",
  provider: "Verified via provider",
};

export const deliveryLabels: Record<DeliveryStatus, string> = {
  queued: "Queued",
  sending: "Sending",
  sent: "Accepted by SES",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function intervalLabel(key: string): string {
  if (key === "test") return "Test email";
  if (key === "due_today") return "Expiration day";
  const before = key.match(/^(\d+)_days$/);
  if (before) return `${before[1]} day${before[1] === "1" ? "" : "s"} before`;
  const after = key.match(/^overdue_day_(\d+)$/);
  if (after) return `${after[1]} day${after[1] === "1" ? "" : "s"} overdue`;
  return key;
}

export function fieldLabel(field: string): string {
  return field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
