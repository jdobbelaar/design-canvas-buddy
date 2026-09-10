import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useBoardSession } from "./useBoardSession";
import type { BoardObject } from "../collab/types";

const box = (id: string): BoardObject => ({
  id,
  type: "shape",
  kind: "box",
  x: 0,
  y: 0,
  width: 100,
  height: 60,
  label: id,
});

describe("useBoardSession", () => {
  it("commits ops and undoes/redoes them locally", () => {
    const { result } = renderHook(() => useBoardSession("s-test", "interviewer"));

    act(() => result.current.commit([{ op: "add", objects: [box("a")] }]));
    expect(result.current.doc["a"]).toBeDefined();
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.doc["a"]).toBeUndefined();
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(result.current.doc["a"]).toBeDefined();
  });

  it("records a whole drag gesture as a single undo step", () => {
    const { result } = renderHook(() => useBoardSession("s-drag", "candidate"));
    act(() => result.current.commit([{ op: "add", objects: [box("a")] }]));

    act(() => {
      result.current.beginInteraction(["a"]);
      result.current.applyLive([{ op: "update", updates: [{ id: "a", patch: { x: 20 } }] }]);
      result.current.applyLive([{ op: "update", updates: [{ id: "a", patch: { x: 90 } }] }]);
      result.current.endInteraction();
    });
    expect((result.current.doc["a"] as { x: number }).x).toBe(90);

    act(() => result.current.undo());
    expect((result.current.doc["a"] as { x: number }).x).toBe(0);
    expect(result.current.doc["a"]).toBeDefined();
  });

  it("keeps at most ten undo steps", () => {
    const { result } = renderHook(() => useBoardSession("s-depth", "interviewer"));
    for (let i = 0; i < 12; i++) {
      act(() => result.current.commit([{ op: "add", objects: [box(`o${i}`)] }]));
    }
    for (let i = 0; i < 10; i++) act(() => result.current.undo());
    expect(result.current.canUndo).toBe(false);
    // The two oldest additions fall out of history and stay on the board.
    expect(result.current.doc["o0"]).toBeDefined();
    expect(result.current.doc["o11"]).toBeUndefined();
  });

  it("assigns distinct cursor colors per role", () => {
    const host = renderHook(() => useBoardSession("s-color", "interviewer"));
    const guest = renderHook(() => useBoardSession("s-color", "candidate"));
    expect(host.result.current.me.color).not.toBe(guest.result.current.me.color);
  });
});
