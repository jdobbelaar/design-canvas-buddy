import type { BoardDoc, BoardObject, ConnectorEnd, Point, ShapeKind } from "../collab/types";

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
      return {
        x,
        y,
        width: Math.max(1, Math.max(...xs) - x),
        height: Math.max(1, Math.max(...ys) - y),
      };
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
  return !(
    a.x + a.width < b.x ||
    b.x + b.width < a.x ||
    a.y + a.height < b.y ||
    b.y + b.height < a.y
  );
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
function rectEdgeIntersection(rect: Rect, from: Point): Point {
  const c = centerOf(rect);
  const dx = from.x - c.x;
  const dy = from.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = rect.width / 2;
  const hh = rect.height / 2;
  const scale = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6));
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

/** Where a line from `from` exits the ellipse inscribed in `rect`. */
function ellipseEdgeIntersection(rect: Rect, from: Point): Point {
  const c = centerOf(rect);
  const dx = from.x - c.x;
  const dy = from.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = rect.width / 2 || 1e-6;
  const hh = rect.height / 2 || 1e-6;
  const scale = 1 / Math.hypot(dx / hw, dy / hh);
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

/*
 * The cloud shape is a lumpy, off-center blob (see cloudPathD below) — not
 * an ellipse. An ellipse inscribed in its bounding box coincides with the
 * box edge along the cardinal axes (same as a plain rectangle) and still
 * cuts through empty space on the diagonals, so cardinal-angle connectors
 * saw no improvement at all from ellipseEdgeIntersection. Instead, flatten
 * the exact path used for rendering into a polygon and ray-cast against
 * that, the same shape the user actually sees.
 */

interface ArcSegment {
  rx: number;
  ry: number;
  to: Point;
}

/** The cloud shape's outline as a start point + a sequence of elliptical
 * arcs (all with x-axis-rotation 0, large-arc-flag 0, sweep-flag 1) — the
 * single source of truth ShapeView.tsx's rendered `d` string is built from
 * too, via cloudPathD, so the two can never drift apart. */
function cloudArcs(rect: Rect): { start: Point; segments: ArcSegment[] } {
  const { x, y, width: w, height: h } = rect;
  const start = { x: x + w * 0.22, y: y + h * 0.82 };
  const p1 = { x: start.x - h * 0.03, y: start.y - h * 0.46 };
  const p2 = { x: p1.x + w * 0.26, y: p1.y - h * 0.26 };
  const p3 = { x: p2.x + w * 0.42, y: p2.y + h * 0.08 };
  const p4 = { x: p3.x + w * 0.08, y: p3.y + h * 0.64 };
  return {
    start,
    segments: [
      { rx: h * 0.24, ry: h * 0.24, to: p1 },
      { rx: h * 0.28, ry: h * 0.28, to: p2 },
      { rx: h * 0.3, ry: h * 0.3, to: p3 },
      { rx: h * 0.24, ry: h * 0.24, to: p4 },
    ],
  };
}

/** SVG path `d` for the cloud shape — shared with geometry so the visible
 * outline and the connector-clipping outline can never drift apart. */
export function cloudPathD(rect: Rect): string {
  const { start, segments } = cloudArcs(rect);
  const arcs = segments.map((s) => `A ${s.rx} ${s.ry} 0 0 1 ${s.to.x} ${s.to.y}`).join(" ");
  return `M ${start.x} ${start.y} ${arcs} Z`;
}

/** Endpoint-to-center parameterization of one SVG elliptical arc (see the
 * SVG spec's arc implementation notes), specialized for x-axis-rotation 0. */
function arcCenterParams(p0: Point, rx: number, ry: number, sweep: boolean, p1: Point) {
  const x1p = (p0.x - p1.x) / 2;
  const y1p = (p0.y - p1.y) / 2;

  let rxAbs = Math.abs(rx) || 1e-6;
  let ryAbs = Math.abs(ry) || 1e-6;
  const lambda = (x1p * x1p) / (rxAbs * rxAbs) + (y1p * y1p) / (ryAbs * ryAbs);
  if (lambda > 1) {
    const s = Math.sqrt(lambda);
    rxAbs *= s;
    ryAbs *= s;
  }

  // Per the SVG spec: sign is +1 when largeArc !== sweep, else -1. This
  // shape's arcs are always largeArc=false, which simplifies that to:
  const sign = sweep ? 1 : -1;
  const num = Math.max(
    0,
    rxAbs * rxAbs * ryAbs * ryAbs - rxAbs * rxAbs * y1p * y1p - ryAbs * ryAbs * x1p * x1p,
  );
  const den = rxAbs * rxAbs * y1p * y1p + ryAbs * ryAbs * x1p * x1p;
  const co = den === 0 ? 0 : sign * Math.sqrt(num / den);

  const cxp = (co * (rxAbs * y1p)) / ryAbs;
  const cyp = (-co * (ryAbs * x1p)) / rxAbs;
  const cx = cxp + (p0.x + p1.x) / 2;
  const cy = cyp + (p0.y + p1.y) / 2;

  const vectorAngle = (ux: number, uy: number, vx: number, vy: number) => {
    const len = Math.hypot(ux, uy) * Math.hypot(vx, vy) || 1e-9;
    const dot = Math.max(-1, Math.min(1, (ux * vx + uy * vy) / len));
    const a = Math.acos(dot);
    return ux * vy - uy * vx < 0 ? -a : a;
  };

  const theta1 = vectorAngle(1, 0, (x1p - cxp) / rxAbs, (y1p - cyp) / ryAbs);
  let dTheta = vectorAngle(
    (x1p - cxp) / rxAbs,
    (y1p - cyp) / ryAbs,
    (-x1p - cxp) / rxAbs,
    (-y1p - cyp) / ryAbs,
  );
  if (!sweep && dTheta > 0) dTheta -= 2 * Math.PI;
  if (sweep && dTheta < 0) dTheta += 2 * Math.PI;

  return { cx, cy, rx: rxAbs, ry: ryAbs, theta1, dTheta };
}

/** Sample points along one elliptical arc, from just after p0 through p1. */
function sampleArc(
  p0: Point,
  rx: number,
  ry: number,
  sweep: boolean,
  p1: Point,
  segments: number,
): Point[] {
  const { cx, cy, rx: rxC, ry: ryC, theta1, dTheta } = arcCenterParams(p0, rx, ry, sweep, p1);
  const points: Point[] = [];
  for (let i = 1; i <= segments; i++) {
    const theta = theta1 + (dTheta * i) / segments;
    points.push({ x: cx + rxC * Math.cos(theta), y: cy + ryC * Math.sin(theta) });
  }
  return points;
}

/** Flatten the cloud outline into a closed polygon, in board space. */
function cloudPolygon(rect: Rect, segmentsPerArc = 16): Point[] {
  const { start, segments } = cloudArcs(rect);
  const points: Point[] = [start];
  let prev = start;
  for (const seg of segments) {
    points.push(...sampleArc(prev, seg.rx, seg.ry, true, seg.to, segmentsPerArc));
    prev = seg.to;
  }
  return points;
}

function cross(ax: number, ay: number, bx: number, by: number): number {
  return ax * by - ay * bx;
}

/** Where a ray from `origin` towards `towards` first exits `polygon`. */
function polygonRayIntersection(polygon: Point[], origin: Point, towards: Point): Point {
  const dx = towards.x - origin.x;
  const dy = towards.y - origin.y;
  if (dx === 0 && dy === 0) return origin;

  let nearest = Infinity;
  for (let i = 0; i < polygon.length; i++) {
    const a = polygon[i]!;
    const b = polygon[(i + 1) % polygon.length]!;
    const sx = b.x - a.x;
    const sy = b.y - a.y;
    const denom = cross(dx, dy, sx, sy);
    if (Math.abs(denom) < 1e-9) continue;
    const ax = a.x - origin.x;
    const ay = a.y - origin.y;
    const t = cross(ax, ay, sx, sy) / denom;
    const u = cross(ax, ay, dx, dy) / denom;
    if (t >= 0 && u >= 0 && u <= 1 && t < nearest) nearest = t;
  }
  if (!Number.isFinite(nearest)) return origin;
  return { x: origin.x + dx * nearest, y: origin.y + dy * nearest };
}

/** Where a line from `from` exits the cloud shape's actual rendered outline. */
function cloudEdgeIntersection(rect: Rect, from: Point): Point {
  const polygon = cloudPolygon(rect);
  // Ray from the polygon's own centroid, not the bounding box's geometric
  // center, since the cloud shape sits off-center within its box.
  const origin = polygon.reduce(
    (acc, p) => ({ x: acc.x + p.x / polygon.length, y: acc.y + p.y / polygon.length }),
    { x: 0, y: 0 },
  );
  return polygonRayIntersection(polygon, origin, from);
}

/** Where a line from `from` exits the diamond inscribed in `rect`. */
function diamondEdgeIntersection(rect: Rect, from: Point): Point {
  const c = centerOf(rect);
  const dx = from.x - c.x;
  const dy = from.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = rect.width / 2 || 1e-6;
  const hh = rect.height / 2 || 1e-6;
  const scale = 1 / (Math.abs(dx) / hw + Math.abs(dy) / hh);
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

/**
 * Connector endpoints should hug a shape's actual rendered silhouette, not
 * its bounding box — a rectangle formula overshoots round/pointed shapes
 * (cloud, junction, decision), leaving the arrowhead either floating well
 * off the visible edge or, at steep angles, landing back inside the shape
 * and disappearing under it.
 */
export function edgeIntersection(rect: Rect, from: Point, kind?: ShapeKind): Point {
  if (kind === "cloud") return cloudEdgeIntersection(rect, from);
  if (kind === "junction") return ellipseEdgeIntersection(rect, from);
  if (kind === "decision") return diamondEdgeIntersection(rect, from);
  return rectEdgeIntersection(rect, from);
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
    if (r) start = edgeIntersection(r, end, o?.type === "shape" ? o.kind : undefined);
  }
  if ("objectId" in to) {
    const o = doc[to.objectId];
    const r = o && boundsOf(o, doc);
    if (r) end = edgeIntersection(r, start, o?.type === "shape" ? o.kind : undefined);
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
    return {
      points: object.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
    } as Partial<BoardObject>;
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
