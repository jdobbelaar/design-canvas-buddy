import type { BoardObject, Point, ShapeKind } from "../collab/types";
import { newId } from "../collab/mock-backend";

export const SHAPE_DEFAULTS: Record<ShapeKind, { width: number; height: number; label: string }> = {
  box: { width: 160, height: 90, label: "Service" },
  database: { width: 140, height: 110, label: "Database" },
  queue: { width: 170, height: 80, label: "Queue" },
  cloud: { width: 180, height: 110, label: "External API" },
  loadbalancer: { width: 160, height: 90, label: "Load balancer" },
  decision: { width: 140, height: 120, label: "Decision?" },
  junction: { width: 60, height: 60, label: "" },
};

export function createShape(kind: ShapeKind, at: Point): BoardObject {
  const preset = SHAPE_DEFAULTS[kind];
  return {
    id: newId("o"),
    type: "shape",
    kind,
    x: Math.round(at.x - preset.width / 2),
    y: Math.round(at.y - preset.height / 2),
    width: preset.width,
    height: preset.height,
    label: preset.label,
  };
}

export function createText(at: Point, text = "Note"): BoardObject {
  return { id: newId("o"), type: "text", x: Math.round(at.x), y: Math.round(at.y), text };
}

export function createStroke(points: Point[]): BoardObject {
  return { id: newId("o"), type: "draw", points };
}

export function createConnector(fromId: string, toId: string): BoardObject {
  return { id: newId("o"), type: "connector", from: { objectId: fromId }, to: { objectId: toId }, label: "" };
}
