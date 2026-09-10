import type { BoardDoc, BoardObject, ConnectorEnd, Point } from "../collab/types";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const TEXT_CHAR_WIDTH = 8.4;
const TEXT_LINE_HEIGHT = 22;

/** Axis-aligned bounding box of a single object, in board space. */
export function boundsOf(object: BoardObject, doc: BoardDoc): Rect | null {
  switch (object.type) {
    case "shape":
      return { x: object.x, y: object.y, width: object.width, height: object.height };
    case "text": {
      const lines = object.text.split("\n");
      const longest = lines.reduce((m, l) => Math.max(m, l.length), 1);
      return {
        x: object.x,
        y: object.y,
        width: Math.max(40, longest * TEXT_CHAR_WIDTH + 12),
        height: lines.length * TEXT_LINE_HEIGHT + 8,
      };
    }
    case "draw": {
      if (!object.points.length) return null;
      const xs = object.points.map((p) => p.x);
      const ys = object.points.map((p) => p.y);
      const x = Math.min(...xs);
      const y = Math.min(...ys);
      return { x, y, width: Math.max(1, Math.max(...xs) - x), height: Math.max(1, Math.max(...ys) - y) };
    }
    case "connector": {
      const a = endPoint(object.from, doc);
      const b = endPoint(object.to, doc);
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      return { x, y, width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y) };
    }
  }
}

export function unionRects(rects: Rect[]): Rect | null {
  if (!rects.length) return null;
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  const right = Math.max(...rects.map((r) => r.x + r.width));
  const bottom = Math.max(...rects.map((r) => r.y + r.height));
  return { x, y, width: right - x, height: bottom - y };
}

export function rectsIntersect(a: Rect, b: Rect): boolean {
  return !(a.x + a.width < b.x || b.x + b.width < a.x || a.y + a.height < b.y || b.y + b.height < a.y);
}

export function pointInRect(p: Point, r: Rect): boolean {
  return p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;
}

function centerOf(rect: Rect): Point {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

/** Resolve a connector endpoint to a concrete board-space point. */
export function endPoint(end: ConnectorEnd, doc: BoardDoc): Point {
  if ("point" in end) return end.point;
  const target = doc[end.objectId];
  if (!target) return { x: 0, y: 0 };
  const rect = boundsOf(target, doc);
  return rect ? centerOf(rect) : { x: 0, y: 0 };
}

/**
 * Where a line from `from` towards `to` exits the rectangle around `to`'s
 * owner. This is what makes attached connectors re-route when shapes move.
 */
export function edgeIntersection(rect: Rect, from: Point): Point {
  const c = centerOf(rect);
  const dx = from.x - c.x;
  const dy = from.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = rect.width / 2;
  const hh = rect.height / 2;
  const scale = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6));
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

/** Final rendered [start, end] of a connector, clipped to attached shapes. */
export function connectorGeometry(
  from: ConnectorEnd,
  to: ConnectorEnd,
  doc: BoardDoc,
): { start: Point; end: Point } {
  let start = endPoint(from, doc);
  let end = endPoint(to, doc);

  if ("objectId" in from) {
    const o = doc[from.objectId];
    const r = o && boundsOf(o, doc);
    if (r) start = edgeIntersection(r, end);
  }
  if ("objectId" in to) {
    const o = doc[to.objectId];
    const r = o && boundsOf(o, doc);
    if (r) end = edgeIntersection(r, start);
  }
  return { start, end };
}

/** Distance from a point to a segment — used for connector hit-testing. */
export function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/** Translate an object by (dx, dy), returning the patch to apply. */
export function translatePatch(object: BoardObject, dx: number, dy: number): Partial<BoardObject> {
  if (object.type === "draw") {
    return { points: object.points.map((p) => ({ x: p.x + dx, y: p.y + dy })) } as Partial<BoardObject>;
  }
  if (object.type === "connector") {
    const move = (end: ConnectorEnd): ConnectorEnd =>
      "point" in end ? { point: { x: end.point.x + dx, y: end.point.y + dy } } : end;
    return { from: move(object.from), to: move(object.to) } as Partial<BoardObject>;
  }
  return { x: object.x + dx, y: object.y + dy } as Partial<BoardObject>;
}

/** Expand a selection to include every member of any touched group. */
export function expandSelection(ids: string[], doc: BoardDoc): string[] {
  const groups = new Set(ids.map((id) => doc[id]?.groupId).filter(Boolean) as string[]);
  const result = new Set(ids);
  if (groups.size) {
    for (const object of Object.values(doc)) {
      if (object.groupId && groups.has(object.groupId)) result.add(object.id);
    }
  }
  return [...result];
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
