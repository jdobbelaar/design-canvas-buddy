import type { BoardDoc, BoardObject, BoardOp } from "../collab/types";

/** Apply ops immutably to a board document. */
export function applyOps(doc: BoardDoc, ops: BoardOp[]): BoardDoc {
  let next = doc;
  const clone = () => (next === doc ? { ...doc } : next);

  for (const op of ops) {
    if (op.op === "add") {
      next = clone();
      for (const object of op.objects) next[object.id] = object;
    } else if (op.op === "update") {
      next = clone();
      for (const { id, patch } of op.updates) {
        const existing = next[id];
        if (!existing) continue;
        next[id] = { ...existing, ...patch } as BoardObject;
      }
    } else {
      next = clone();
      for (const id of op.ids) delete next[id];
    }
  }
  return next;
}

/**
 * Build the ops that reverse `ops` against the document as it looked *before*
 * they were applied. Used for per-participant local undo.
 */
export function invertOps(before: BoardDoc, ops: BoardOp[]): BoardOp[] {
  const inverse: BoardOp[] = [];
  let doc = before;

  for (const op of ops) {
    if (op.op === "add") {
      inverse.unshift({ op: "delete", ids: op.objects.map((o) => o.id) });
    } else if (op.op === "update") {
      const updates = op.updates
        .filter((u) => doc[u.id])
        .map((u) => {
          const prev = doc[u.id] as unknown as Record<string, unknown>;
          const patch: Record<string, unknown> = {};
          for (const key of Object.keys(u.patch)) patch[key] = prev[key];
          return { id: u.id, patch: patch as Partial<BoardObject> };
        });
      if (updates.length) inverse.unshift({ op: "update", updates });
    } else {
      const objects = op.ids.map((id) => doc[id]).filter(Boolean) as BoardObject[];
      if (objects.length) inverse.unshift({ op: "add", objects });
    }
    doc = applyOps(doc, [op]);
  }
  return inverse;
}

export const HISTORY_DEPTH = 10;

export interface HistoryEntry {
  redo: BoardOp[];
  undo: BoardOp[];
}

export interface History {
  past: HistoryEntry[];
  future: HistoryEntry[];
}

export const emptyHistory: History = { past: [], future: [] };

export function pushHistory(history: History, entry: HistoryEntry): History {
  const past = [...history.past, entry].slice(-HISTORY_DEPTH);
  return { past, future: [] };
}
