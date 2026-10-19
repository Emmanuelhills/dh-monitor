"use client";

import Link from "next/link";
import { useState } from "react";
import { DeliveryBadge } from "@/components/Badges";
import { useToast } from "@/components/Toast";
import { Empty, ErrorAlert, Loading, Pagination } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDate, formatDateTime, intervalLabel } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import type { NotificationEvent, Page } from "@/lib/types";

const PAGE_SIZE = 25;

export default function NotificationsPage() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [recordType, setRecordType] = useState("");
  const [page, setPage] = useState(1);
  const list = useAsync(
    () => api.get<Page<NotificationEvent>>("/notifications", {
      delivery_status: status, record_type: recordType, page, page_size: PAGE_SIZE,
    }),
    [status, recordType, page],
  );

  async function retry(id: string) {
    try {
      await api.post(`/notifications/${id}/retry`);
      toast("success", "Reminder re-queued.");
      list.reload();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Notification history</h1>
          <p>Every reminder and test email. &quot;Accepted by SES&quot; means Amazon SES took the message; inbox delivery is not confirmed.</p>
        </div>
      </div>
      <section className="card">
        <div className="toolbar">
          <label className="sr-only" htmlFor="n-status">Delivery status</label>
          <select id="n-status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">Any status</option>
            <option value="queued">Queued</option>
            <option value="sent">Accepted by SES</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <label className="sr-only" htmlFor="n-type">Record type</label>
          <select id="n-type" value={recordType} onChange={(e) => { setRecordType(e.target.value); setPage(1); }}>
            <option value="">Domains & hosting</option>
            <option value="domain">Domains</option>
            <option value="hosting">Hosting accounts</option>
          </select>
          <button className="btn small" onClick={list.reload}>Refresh</button>
        </div>
        {list.error && <div className="card-body"><ErrorAlert message={list.error} onRetry={list.reload} /></div>}
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.items.length === 0 && (
          <Empty title="No notifications yet">Reminders appear here once records approach their expiration dates.</Empty>
        )}
        {list.data && list.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data responsive">
              <thead>
                <tr><th>Record</th><th>Reminder</th><th>Recipient</th><th>Status</th><th>Attempts</th><th>Created</th><th /></tr>
              </thead>
              <tbody>
                {list.data.items.map((n) => {
                  const href = n.domain_id ? `/domains/${n.domain_id}` : n.hosting_account_id ? `/hosting/${n.hosting_account_id}` : null;
                  return (
                    <tr key={n.id}>
                      <td className="name" data-label="Record">
                        {n.is_test ? <span className="muted">Test email</span> : href ? <Link href={href}>{n.record_name}</Link> : n.record_name}
                        {n.expiration_date_at_send && <div className="small muted">Expires {formatDate(n.expiration_date_at_send)}</div>}
                      </td>
                      <td data-label="Reminder">{intervalLabel(n.reminder_interval)}</td>
                      <td data-label="Recipient">{n.recipient}</td>
                      <td data-label="Status">
                        <DeliveryBadge status={n.delivery_status} />
                        {n.last_error && <div className="small muted" style={{ maxWidth: 320 }}>{n.last_error}</div>}
                        {n.delivery_status === "queued" && n.next_attempt_at && (
                          <div className="small muted">Next attempt {formatDateTime(n.next_attempt_at)}</div>
                        )}
                      </td>
                      <td data-label="Attempts">{n.attempt_count}</td>
                      <td data-label="Created" className="nowrap">
                        {formatDateTime(n.created_at)}
                        {n.sent_at && <div className="small muted">Accepted {formatDateTime(n.sent_at)}</div>}
                      </td>
                      <td>
                        {n.delivery_status === "failed" && !n.is_test && (
                          <button className="btn small" onClick={() => retry(n.id)}>Retry</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {list.data && <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />}
      </section>
    </>
  );
}
