"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDateTime, relativeTime, sourceLabels } from "@/lib/format";
import type { CheckQueued, RecordBase } from "@/lib/types";
import { ExpirationBadge, MonitoringBadge, RenewalBadge } from "./Badges";
import { useToast } from "./Toast";

/** Expiration + renewal + monitoring facts, shared by domain and hosting detail views. */
export function MonitoringPanel({ record, children }: { record: RecordBase; children?: React.ReactNode }) {
  const verified = record.expiration_source !== "manual" && record.expiration_verified_at;
  return (
    <div className="card">
      <div className="card-header"><h2>Expiration & monitoring</h2></div>
      <div className="card-body">
        <dl className="props">
          <dt>Expiration date</dt>
          <dd>
            <strong>{formatDate(record.expiration_date)}</strong>{" "}
            <ExpirationBadge expiration={record.expiration} />
            <div className="small muted">
              {record.expiration_date
                ? verified
                  ? `${sourceLabels[record.expiration_source]} on ${formatDateTime(record.expiration_verified_at)}`
                  : "Entered manually. Not verified."
                : "Unknown. Enter it manually or run a check."}
            </div>
          </dd>
          <dt>Renewal</dt>
          <dd>
            <RenewalBadge status={record.renewal_status} />
            {record.renewal_status === "renewed" && record.renewal_confirmed_for_date && (
              <span className="small muted"> Period ending {formatDate(record.renewal_confirmed_for_date)}</span>
            )}
          </dd>
          <dt>Status source</dt>
          <dd>{sourceLabels[record.service_status_source]}</dd>
          <dt>Monitoring</dt>
          <dd><MonitoringBadge status={record.monitoring_status} stale={record.is_stale} /></dd>
          <dt>Last attempt</dt>
          <dd>{record.last_checked_at ? `${formatDateTime(record.last_checked_at)} (${relativeTime(record.last_checked_at)})` : "Never"}</dd>
          <dt>Last successful check</dt>
          <dd>{record.last_successful_check_at ? `${formatDateTime(record.last_successful_check_at)} (${relativeTime(record.last_successful_check_at)})` : "Never"}</dd>
          <dt>Next scheduled check</dt>
          <dd>{record.next_check_at ? formatDateTime(record.next_check_at) : record.auto_check_enabled ? "Not scheduled" : "Automatic checks off"}</dd>
          {record.last_check_error && (
            <>
              <dt>Last problem</dt>
              <dd style={{ color: "var(--urgent-fg)" }}>{record.last_check_error}</dd>
            </>
          )}
          <dt>Reminders</dt>
          <dd>{record.notifications_enabled ? "On" : "Off for this record"}</dd>
          {children}
        </dl>
      </div>
    </div>
  );
}

/** Queue an on-demand check and poll the record until the check finishes. */
export function RunCheckButton({ path, record, onUpdated, disabled }: {
  path: string;
  record: RecordBase;
  onUpdated: () => void;
  disabled?: boolean;
}) {
  const toast = useToast();
  const [waiting, setWaiting] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function run() {
    try {
      const res = await api.post<CheckQueued>(`${path}/check`);
      if (res.status === "not_supported") {
        toast("info", res.message);
        return;
      }
      if (res.status === "completed") {
        // Serverless hosting runs the check during the request.
        toast(res.message.includes("failure") ? "error" : "success", res.message);
        onUpdated();
        return;
      }
      toast("info", res.message);
      setWaiting(true);
      const startedAfter = record.last_checked_at;
      let polls = 0;
      timer.current = setInterval(async () => {
        polls += 1;
        try {
          const latest = await api.get<RecordBase>(path);
          if (latest.last_checked_at && latest.last_checked_at !== startedAfter) {
            clearInterval(timer.current!);
            setWaiting(false);
            toast(latest.monitoring_status === "failed" ? "error" : "success",
              latest.monitoring_status === "failed" ? `Check failed: ${latest.last_check_error ?? "see history"}` : "Check finished.");
            onUpdated();
          }
        } catch {
          // keep polling
        }
        if (polls >= 30 && timer.current) {
          clearInterval(timer.current);
          setWaiting(false);
          toast("info", "The check is still queued. Results will appear in the history when the worker runs it.");
        }
      }, 3000);
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <button className="btn" onClick={run} disabled={waiting || disabled}>
      {waiting && <span className="spinner" aria-hidden />} {waiting ? "Checking…" : "Run check now"}
    </button>
  );
}
