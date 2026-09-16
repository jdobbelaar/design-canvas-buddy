import { describe, expect, it } from "vitest";
import {
  boundsOf,
  connectorGeometry,
  distanceToSegment,
  expandSelection,
  pointInRect,
  rectsIntersect,
  translatePatch,
  unionRects,
} from "./geometry";
import { applyOps } from "./ops";
import type { BoardDoc, BoardObject } from "../collab/types";

const box = (id: string, x: number, y: number): BoardObject => ({
  id,
  type: "shape",
  kind: "box",
  x,
  y,
  width: 100,
  height: 100,
  label: id,
});

const doc: BoardDoc = applyOps({}, [
  {
    op: "add",
    objects: [
      box("a", 0, 0),
      box("b", 400, 0),
      {
        id: "c",
        type: "connector",
        from: { objectId: "a" },
        to: { objectId: "b" },
        label: "HTTPS",
      },
      {
        id: "d",
        type: "draw",
        points: [
          { x: 10, y: 20 },
          { x: 60, y: 90 },
        ],
      },
      { id: "t", type: "text", x: 5, y: 5, text: "hello" },
    ],
  },
]);

describe("boundsOf", () => {
  it("measures shapes, strokes and text", () => {
    expect(boundsOf(doc["a"]!, doc)).toEqual({ x: 0, y: 0, width: 100, height: 100 });
    expect(boundsOf(doc["d"]!, doc)).toEqual({ x: 10, y: 20, width: 50, height: 70 });
    const text = boundsOf(doc["t"]!, doc)!;
    expect(text.width).toBeGreaterThan(40);
    expect(text.height).toBeGreaterThan(0);
  });
});

describe("connectors", () => {
  it("attaches to shape edges rather than centers", () => {
    const { start, end } = connectorGeometry(
      doc["a"]!.type === "connector" ? doc["a"]!.from : { objectId: "a" },
      { objectId: "b" },
      doc,
    );
    expect(start.x).toBeCloseTo(100);
    expect(end.x).toBeCloseTo(400);
    expect(start.y).toBeCloseTo(50);
  });

  it("re-routes when the attached shape moves", () => {
    const before = connectorGeometry({ objectId: "a" }, { objectId: "b" }, doc);
    const moved = applyOps(doc, [
      { op: "update", updates: [{ id: "b", patch: { x: 400, y: 600 } }] },
    ]);
    const after = connectorGeometry({ objectId: "a" }, { objectId: "b" }, moved);
    expect(after.end).not.toEqual(before.end);
    expect(after.end.y).toBeGreaterThan(before.end.y);
  });

  it("falls back to free points when a shape is deleted", () => {
    const pruned = applyOps(doc, [{ op: "delete", ids: ["b"] }]);
    const { end } = connectorGeometry({ objectId: "a" }, { objectId: "b" }, pruned);
    expect(end).toEqual({ x: 0, y: 0 });
  });

  it("hugs a cloud shape's actual rendered outline, not its bounding box", () => {
    const cloud = applyOps(doc, [
      {
        op: "update",
        updates: [{ id: "b", patch: { kind: "cloud", x: 0, y: 0, width: 100, height: 100 } }],
      },
    ]);

    // Approaching from directly above (a cardinal angle): an ellipse or
    // rectangle inscribed in the box both land exactly on the box's top
    // edge (y=0). The cloud's outline sits well below that.
    const fromAbove = connectorGeometry({ point: { x: 50, y: -1000 } }, { objectId: "b" }, cloud);
    expect(fromAbove.end.y).toBeGreaterThan(5);
    expect(fromAbove.end.y).toBeLessThan(50);

    // Approaching from the diagonal: a rectangle clip lands exactly on the
    // box corner (100,100); the cloud's outline doesn't reach the corner.
    const fromCorner = connectorGeometry({ point: { x: 1000, y: 1000 } }, { objectId: "b" }, cloud);
    const distToCorner = Math.hypot(fromCorner.end.x - 100, fromCorner.end.y - 100);
    expect(distToCorner).toBeGreaterThan(10);
    expect(fromCorner.end.x).toBeGreaterThan(50);
    expect(fromCorner.end.x).toBeLessThan(100);
    expect(fromCorner.end.y).toBeGreaterThan(50);
    expect(fromCorner.end.y).toBeLessThan(100);
  });

  it("hugs a decision (diamond) shape's angled edge, not its bounding box corner", () => {
    const withDecision = applyOps(doc, [
      { op: "update", updates: [{ id: "b", patch: { kind: "decision", x: 0, y: 0 } }] },
    ]);
    const { end } = connectorGeometry(
      { point: { x: 1000, y: 1000 } },
      { objectId: "b" },
      withDecision,
    );
    // Diamond boundary at a 45-degree approach is even further inset than
    // the ellipse case above: |dx|/hw + |dy|/hh = 1 with dx = dy.
    expect(end.x).toBeCloseTo(75);
    expect(end.y).toBeCloseTo(75);
  });
});

describe("selection helpers", () => {
  it("unions rects and detects intersection/containment", () => {
    expect(
      unionRects([
        { x: 0, y: 0, width: 10, height: 10 },
        { x: 20, y: 5, width: 10, height: 10 },
      ]),
    ).toEqual({
      x: 0,
      y: 0,
      width: 30,
      height: 15,
    });
    expect(
      rectsIntersect({ x: 0, y: 0, width: 10, height: 10 }, { x: 5, y: 5, width: 10, height: 10 }),
    ).toBe(true);
    expect(
      rectsIntersect({ x: 0, y: 0, width: 10, height: 10 }, { x: 50, y: 0, width: 10, height: 10 }),
    ).toBe(false);
    expect(pointInRect({ x: 3, y: 3 }, { x: 0, y: 0, width: 10, height: 10 })).toBe(true);
  });

  it("expands a selection to whole groups", () => {
    const grouped = applyOps(doc, [
      {
        op: "update",
        updates: [
          { id: "a", patch: { groupId: "g" } },
          { id: "t", patch: { groupId: "g" } },
        ],
      },
    ]);
    expect(expandSelection(["a"], grouped).sort()).toEqual(["a", "t"]);
    expect(expandSelection(["b"], grouped)).toEqual(["b"]);
  });

  it("measures distance to a segment for connector hit-testing", () => {
    expect(distanceToSegment({ x: 5, y: 5 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBe(5);
  });
});

describe("translatePatch", () => {
  it("moves shapes, strokes and free connector ends", () => {
    expect(translatePatch(doc["a"]!, 10, -5)).toEqual({ x: 10, y: -5 });
    expect(translatePatch(doc["d"]!, 1, 1)).toEqual({
      points: [
        { x: 11, y: 21 },
        { x: 61, y: 91 },
      ],
    });
    const free: BoardObject = {
      id: "f",
      type: "connector",
      from: { point: { x: 0, y: 0 } },
      to: { objectId: "a" },
      label: "",
    };
    expect(translatePatch(free, 5, 5)).toEqual({
      from: { point: { x: 5, y: 5 } },
      to: { objectId: "a" },
    });
  });
});
