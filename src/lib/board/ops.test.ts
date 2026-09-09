import { describe, expect, it } from "vitest";
import { applyOps, invertOps, pushHistory, HISTORY_DEPTH, type History } from "./ops";
import type { BoardDoc, BoardObject, BoardOp } from "../collab/types";

const box = (id: string, x = 0, y = 0): BoardObject => ({
  id,
  type: "shape",
  kind: "box",
  x,
  y,
  width: 100,
  height: 60,
  label: id,
});

describe("applyOps", () => {
  it("adds, updates and deletes objects immutably", () => {
    const start: BoardDoc = {};
    const added = applyOps(start, [{ op: "add", objects: [box("a"), box("b")] }]);
    expect(Object.keys(added)).toEqual(["a", "b"]);
    expect(start).toEqual({});

    const moved = applyOps(added, [{ op: "update", updates: [{ id: "a", patch: { x: 50 } }] }]);
    expect((moved["a"] as { x: number }).x).toBe(50);
    expect((added["a"] as { x: number }).x).toBe(0);

    const removed = applyOps(moved, [{ op: "delete", ids: ["b"] }]);
    expect(removed["b"]).toBeUndefined();
    expect(moved["b"]).toBeDefined();
  });

  it("ignores updates to unknown objects", () => {
    const doc = applyOps({}, [{ op: "update", updates: [{ id: "ghost", patch: { x: 1 } }] }]);
    expect(doc).toEqual({});
  });
});

describe("invertOps", () => {
  it("round-trips add / update / delete back to the original document", () => {
    const before = applyOps({}, [{ op: "add", objects: [box("a", 10, 10), box("b")] }]);
    const ops: BoardOp[] = [
      { op: "update", updates: [{ id: "a", patch: { x: 400 } }] },
      { op: "delete", ids: ["b"] },
      { op: "add", objects: [box("c")] },
    ];

    const after = applyOps(before, ops);
    const restored = applyOps(after, invertOps(before, ops));
    expect(restored).toEqual(before);
  });

  it("restores grouping when a group op is undone", () => {
    const before = applyOps({}, [{ op: "add", objects: [box("a"), box("b")] }]);
    const group = [
      { op: "update" as const, updates: [{ id: "a", patch: { groupId: "g1" } }, { id: "b", patch: { groupId: "g1" } }] },
    ];
    const grouped = applyOps(before, group);
    expect(grouped["a"]?.groupId).toBe("g1");
    const ungrouped = applyOps(grouped, invertOps(before, group));
    expect(ungrouped["a"]?.groupId).toBeUndefined();
  });
});

describe("history", () => {
  it("caps depth at 10 and clears the redo stack on new work", () => {
    let history: History = { past: [], future: [{ redo: [], undo: [] }] };
    for (let i = 0; i < 15; i++) {
      history = pushHistory(history, { redo: [{ op: "delete", ids: [String(i)] }], undo: [] });
    }
    expect(history.past).toHaveLength(HISTORY_DEPTH);
    expect(history.future).toHaveLength(0);
    const first = history.past[0]!.redo[0];
    expect(first).toEqual({ op: "delete", ids: ["5"] });
  });
});
