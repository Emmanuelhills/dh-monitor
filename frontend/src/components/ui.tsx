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

export const DEFAULT_PAGE_SIZE = 10;
export const MAX_PAGE_SIZE = 100;

function ArrowIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden focusable="false">
      <path
        d={direction === "left" ? "M10 3 5 8l5 5" : "M6 3l5 5-5 5"}
        fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  );
}

/** Previous/next arrows, page position, and an editable "per page" size (1–100). */
export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  onPageSize?: (size: number) => void;
}) {
  const sizeId = useId();
  const [draft, setDraft] = useState(String(pageSize));
  useEffect(() => setDraft(String(pageSize)), [pageSize]);
  if (total === 0) return null;

  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  const commit = () => {
    const n = Math.round(Number(draft));
    if (!Number.isFinite(n) || n < 1) return setDraft(String(pageSize));
    const size = Math.min(n, MAX_PAGE_SIZE);
    setDraft(String(size));
    if (size !== pageSize) onPageSize?.(size);
  };

  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted small">
        {from}–{to} of {total}
      </span>
      <span className="pager">
        {onPageSize && (
          <span className="per-page">
            <label htmlFor={sizeId} className="small muted">Per page</label>
            <input
              id={sizeId} type="number" inputMode="numeric" min={1} max={MAX_PAGE_SIZE} value={draft}
              onChange={(e) => setDraft(e.target.value)} onBlur={commit}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
            />
          </span>
        )}
        <button className="icon-btn" aria-label="Previous page" title="Previous page"
          disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ArrowIcon direction="left" />
        </button>
        <span className="small muted" aria-live="polite">
          {page} / {pages}
        </span>
        <button className="icon-btn" aria-label="Next page" title="Next page"
          disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <ArrowIcon direction="right" />
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

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden focusable="false" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M4 4l16 16" />}
    </svg>
  );
}

/** Password input with a show/hide toggle. It only reveals what the user typed; saved secrets are never sent to the browser. */
export function PasswordInput(props: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="password-input">
      <input {...props} type={visible ? "text" : "password"} spellCheck={false} autoCapitalize="off" />
      <button type="button" className="reveal" onClick={() => setVisible(!visible)}
        aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible}
        title={visible ? "Hide password" : "Show password"}>
        <EyeIcon open={!visible} />
      </button>
    </span>
  );
}
