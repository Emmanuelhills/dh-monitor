"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "./Toast";
import { ConfirmButton } from "./ui";
import { api, errorMessage } from "@/lib/api";

/** Row selection for bulk actions. Selection is cleared whenever `resetKey` changes (page, filters). */
export function useSelection(pageIds: string[], resetKey: string) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(new Set()), [resetKey]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const onPage = pageIds.filter((id) => selected.has(id)).length;
  const allOnPage = pageIds.length > 0 && onPage === pageIds.length;
  const toggleAll = () => setSelected(allOnPage ? new Set() : new Set(pageIds));
  const clear = () => setSelected(new Set());

  return {
    ids: [...selected],
    count: selected.size,
    has: (id: string) => selected.has(id),
    toggle,
    toggleAll,
    clear,
    all: allOnPage,
    some: onPage > 0 && !allOnPage,
  };
}

export type Selection = ReturnType<typeof useSelection>;

/** Header checkbox: selects every row on the current page; shows a dash when only some are selected. */
export function SelectAllHeader({ selection, label }: { selection: Selection; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = selection.some;
  }, [selection.some]);
  return (
    <th className="select-col">
      <input ref={ref} type="checkbox" aria-label={label} checked={selection.all} onChange={selection.toggleAll} />
    </th>
  );
}

export function SelectCell({ selection, id, label }: { selection: Selection; id: string; label: string }) {
  return (
    <td className="select-col" data-label="Select">
      <input type="checkbox" aria-label={label} checked={selection.has(id)} onChange={() => selection.toggle(id)} />
    </td>
  );
}

export interface BulkAction {
  label: string;
  title: string;
  message: React.ReactNode;
  /** Endpoint, e.g. "/domains/bulk-delete". */
  path: string;
  permanent?: boolean;
  /** Past-tense verb for the toast, e.g. "archived". */
  done: string;
  noun: [singular: string, plural: string];
}

/** "N selected · actions · Clear" bar shown above a table while rows are selected. */
export function BulkBar({ selection, actions, onDone }: {
  selection: Selection;
  actions: BulkAction[];
  onDone: () => void;
}) {
  const toast = useToast();
  if (selection.count === 0) return null;

  const run = (action: BulkAction) => async () => {
    try {
      const body: { ids: string[]; permanent?: boolean } = { ids: selection.ids };
      if (action.permanent !== undefined) body.permanent = action.permanent;
      const result = await api.post<{ deleted: number }>(action.path, body);
      const [one, many] = action.noun;
      toast("success", `${result.deleted} ${result.deleted === 1 ? one : many} ${action.done}.`);
      selection.clear();
      onDone();
    } catch (err) {
      toast("error", errorMessage(err));
    }
  };

  return (
    <div className="bulk-bar" role="region" aria-label="Bulk actions">
      <strong>{selection.count} selected</strong>
      <div className="btn-row">
        {actions.map((a) => (
          <ConfirmButton key={a.label} className="btn small danger" label={a.label} title={a.title}
            confirmLabel={a.label} message={a.message} onConfirm={run(a)} />
        ))}
        {!selection.all && <button type="button" className="btn small" onClick={selection.toggleAll}>Select page</button>}
        <button type="button" className="btn small" onClick={selection.clear}>Clear</button>
      </div>
    </div>
  );
}
