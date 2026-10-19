"use client";

import { useEffect, useId, useRef, useState } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden /> {label}
    </div>
  );
}

export function ErrorAlert({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert error" role="alert">
      {message}{" "}
      {onRetry && (
        <button className="btn link" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted small">
        {from}–{to} of {total}
      </span>
      <span className="btn-row">
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span className="small muted" style={{ alignSelf: "center" }}>
          Page {page} of {pages}
        </span>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </span>
    </nav>
  );
}

export function SortHeader({
  label,
  field,
  sort,
  order,
  onSort,
}: {
  label: string;
  field: string;
  sort: string;
  order: "asc" | "desc";
  onSort: (field: string, order: "asc" | "desc") => void;
}) {
  const active = sort === field;
  const next = active && order === "asc" ? "desc" : "asc";
  return (
    <th aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button className="sort-btn" aria-sort={active ? undefined : "none"} onClick={() => onSort(field, next)}>
        {label}
        <span className="arrow" aria-hidden>
          {active ? (order === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

/** Confirmation dialog for destructive actions. */
export function ConfirmButton({
  label,
  title,
  message,
  confirmLabel,
  onConfirm,
  className = "btn danger",
  danger = true,
}: {
  label: string;
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void> | void;
  className?: string;
  danger?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const titleId = useId();
  return (
    <>
      <button type="button" className={className} onClick={() => ref.current?.showModal()}>
        {label}
      </button>
      <dialog ref={ref} className="modal" aria-labelledby={titleId}>
        <div className="modal-body">
          <h2 id={titleId}>{title}</h2>
          <div>{message}</div>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={() => ref.current?.close()} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? "btn danger solid" : "btn primary"}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                ref.current?.close();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? <span className="spinner" aria-hidden /> : null} {confirmLabel}
          </button>
        </div>
      </dialog>
    </>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="field" aria-invalid={error ? true : undefined}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && (
        <span className="hint" id={`${htmlFor}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={`${htmlFor}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Persist a small UI preference (filters, sort) in sessionStorage. */
export function useSessionState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw) setValue({ ...initial, ...JSON.parse(raw) });
    } catch {
      // storage unavailable: keep defaults
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const update = (next: T) => {
    setValue(next);
    try {
      sessionStorage.setItem(key, JSON.stringify(next));
    } catch {
      // ignore
    }
  };
  return [value, update];
}
