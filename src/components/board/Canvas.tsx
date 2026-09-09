import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BOARD_HEIGHT,
  BOARD_WIDTH,
  type BoardDoc,
  type BoardObject,
  type BoardOp,
  type Point,
} from "@/lib/collab/types";
import {
  boundsOf,
  clamp,
  connectorGeometry,
  distanceToSegment,
  expandSelection,
  pointInRect,
  rectsIntersect,
  translatePatch,
  unionRects,
  type Rect,
} from "@/lib/board/geometry";
import { createConnector, createShape, createStroke, createText } from "@/lib/board/factory";
import { newId } from "@/lib/collab/mock-backend";
import type { BoardSession } from "@/lib/board/useBoardSession";
import { ShapeView } from "./ShapeView";
import { Toolbar, type Tool } from "./Toolbar";
import { Minimap } from "./Minimap";

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2.5;

type Gesture =
  | { mode: "pan"; originClient: Point; originView: Point }
  | { mode: "marquee"; origin: Point }
  | { mode: "move"; last: Point; ids: string[] }
  | { mode: "resize"; ids: string[]; start: Rect; origin: Point }
  | { mode: "pen" }
  | { mode: "connector"; fromId: string };

interface Props {
  session: BoardSession;
}

export function Canvas({ session }: Props) {
  const { doc, peers, me, commit, applyLive, beginInteraction, endInteraction } = session;

  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [view, setView] = useState({ x: 2400, y: 1600, zoom: 1 });
  const [tool, setTool] = useState<Tool>("select");
  const [selection, setSelection] = useState<string[]>([]);
  const [marquee, setMarquee] = useState<Rect | null>(null);
  const [stroke, setStroke] = useState<Point[] | null>(null);
  const [pendingLink, setPendingLink] = useState<{ fromId: string; to: Point } | null>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const gestureRef = useRef<Gesture | null>(null);

  const viewport = useMemo(
    () => ({ x: view.x, y: view.y, width: size.width / view.zoom, height: size.height / view.zoom }),
    [view, size],
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    session.publishViewport(viewport);
  }, [viewport, session]);

  const toBoard = useCallback(
    (clientX: number, clientY: number): Point => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return {
        x: view.x + (clientX - rect.left) / view.zoom,
        y: view.y + (clientY - rect.top) / view.zoom,
      };
    },
    [view],
  );

  const objects = useMemo(() => Object.values(doc), [doc]);

  const selectionBounds = useMemo(() => {
    const rects = selection.map((id) => doc[id] && boundsOf(doc[id]!, doc)).filter(Boolean) as Rect[];
    return unionRects(rects);
  }, [selection, doc]);

  const hitTest = useCallback(
    (point: Point): BoardObject | null => {
      for (let i = objects.length - 1; i >= 0; i--) {
        const object = objects[i]!;
        if (object.type === "connector") {
          const { start, end } = connectorGeometry(object.from, object.to, doc);
          if (distanceToSegment(point, start, end) < 8) return object;
          continue;
        }
        if (object.type === "draw") {
          for (let p = 1; p < object.points.length; p++) {
            if (distanceToSegment(point, object.points[p - 1]!, object.points[p]!) < 8) return object;
          }
          continue;
        }
        const bounds = boundsOf(object, doc);
        if (bounds && pointInRect(point, bounds)) return object;
      }
      return null;
    },
    [objects, doc],
  );

  const centerOn = useCallback(
    (center: Point) => {
      setView((v) => ({
        ...v,
        x: clamp(center.x - size.width / v.zoom / 2, 0, BOARD_WIDTH - size.width / v.zoom),
        y: clamp(center.y - size.height / v.zoom / 2, 0, BOARD_HEIGHT - size.height / v.zoom),
      }));
    },
    [size],
  );

  /* ------------------------------- mutations ------------------------------ */

  const deleteSelection = useCallback(() => {
    if (!selection.length) return;
    const ids = expandSelection(selection, doc);
    const orphanConnectors = objects
      .filter(
        (o) =>
          o.type === "connector" &&
          (("objectId" in o.from && ids.includes(o.from.objectId)) ||
            ("objectId" in o.to && ids.includes(o.to.objectId))),
      )
      .map((o) => o.id);
    commit([{ op: "delete", ids: [...new Set([...ids, ...orphanConnectors])] }]);
    setSelection([]);
  }, [selection, doc, objects, commit]);

  const groupSelection = useCallback(() => {
    const ids = expandSelection(selection, doc);
    if (ids.length < 2) return;
    const groupId = newId("g");
    commit([{ op: "update", updates: ids.map((id) => ({ id, patch: { groupId } })) }]);
  }, [selection, doc, commit]);

  const ungroupSelection = useCallback(() => {
    const ids = expandSelection(selection, doc).filter((id) => doc[id]?.groupId);
    if (!ids.length) return;
    commit([{ op: "update", updates: ids.map((id) => ({ id, patch: { groupId: null } })) }]);
  }, [selection, doc, commit]);

  const canGroup = expandSelection(selection, doc).length > 1;
  const canUngroup = expandSelection(selection, doc).some((id) => doc[id]?.groupId);

  /* ------------------------------- keyboard ------------------------------- */

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      const meta = event.metaKey || event.ctrlKey;

      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        event.shiftKey ? session.redo() : session.undo();
        return;
      }
      if (meta && event.key.toLowerCase() === "g") {
        event.preventDefault();
        event.shiftKey ? ungroupSelection() : groupSelection();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
        return;
      }
      if (event.key === "Escape") {
        setSelection([]);
        setPendingLink(null);
        setTool("select");
        return;
      }
      const hotkeys: Record<string, Tool> = { v: "select", p: "pen", t: "text", c: "connector" };
      const next = hotkeys[event.key.toLowerCase()];
      if (next && !meta) setTool(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [session, deleteSelection, groupSelection, ungroupSelection]);

  /* ------------------------------- pointers ------------------------------- */

  const onPointerDown = (event: React.PointerEvent) => {
    if (editing) setEditing(null);
    (event.target as Element).setPointerCapture?.(event.pointerId);
    const point = toBoard(event.clientX, event.clientY);

    if (event.button === 1 || event.altKey || event.shiftKey === false && tool === "select" && event.button === 2) {
      gestureRef.current = { mode: "pan", originClient: { x: event.clientX, y: event.clientY }, originView: { x: view.x, y: view.y } };
      return;
    }

    if (tool === "pen") {
      gestureRef.current = { mode: "pen" };
      setStroke([point]);
      return;
    }

    if (tool === "text") {
      const object = createText(point);
      commit([{ op: "add", objects: [object] }]);
      setSelection([object.id]);
      setEditing({ id: object.id, value: (object as { text: string }).text });
      setTool("select");
      return;
    }

    if (tool === "connector") {
      const hit = hitTest(point);
      if (!hit || hit.type === "connector") return;
      if (!pendingLink) {
        setPendingLink({ fromId: hit.id, to: point });
        gestureRef.current = { mode: "connector", fromId: hit.id };
      }
      return;
    }

    if (tool !== "select") {
      const object = createShape(tool, point);
      commit([{ op: "add", objects: [object] }]);
      setSelection([object.id]);
      setTool("select");
      return;
    }

    // select tool
    const handle = (event.target as HTMLElement).dataset?.["handle"];
    if (handle && selectionBounds) {
      const ids = expandSelection(selection, doc);
      beginInteraction(ids);
      gestureRef.current = { mode: "resize", ids, start: selectionBounds, origin: point };
      return;
    }

    const hit = hitTest(point);
    if (!hit) {
      if (!event.shiftKey) setSelection([]);
      gestureRef.current = { mode: "marquee", origin: point };
      setMarquee({ x: point.x, y: point.y, width: 0, height: 0 });
      return;
    }

    const hitIds = expandSelection([hit.id], doc);
    const nextSelection = event.shiftKey
      ? selection.includes(hit.id)
        ? selection.filter((id) => !hitIds.includes(id))
        : [...selection, ...hitIds]
      : selection.includes(hit.id)
        ? selection
        : hitIds;
    setSelection(nextSelection);
    const movingIds = expandSelection(nextSelection, doc);
    beginInteraction(movingIds);
    gestureRef.current = { mode: "move", last: point, ids: movingIds };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const point = toBoard(event.clientX, event.clientY);
    session.publishCursor(point);
    const gesture = gestureRef.current;
    if (!gesture) return;

    if (gesture.mode === "pan") {
      setView((v) => ({
        ...v,
        x: clamp(gesture.originView.x - (event.clientX - gesture.originClient.x) / v.zoom, 0, BOARD_WIDTH - size.width / v.zoom),
        y: clamp(gesture.originView.y - (event.clientY - gesture.originClient.y) / v.zoom, 0, BOARD_HEIGHT - size.height / v.zoom),
      }));
      return;
    }

    if (gesture.mode === "pen") {
      setStroke((points) => (points ? [...points, point] : [point]));
      return;
    }

    if (gesture.mode === "connector") {
      setPendingLink((link) => (link ? { ...link, to: point } : link));
      return;
    }

    if (gesture.mode === "marquee") {
      setMarquee({
        x: Math.min(gesture.origin.x, point.x),
        y: Math.min(gesture.origin.y, point.y),
        width: Math.abs(point.x - gesture.origin.x),
        height: Math.abs(point.y - gesture.origin.y),
      });
      return;
    }

    if (gesture.mode === "move") {
      const dx = point.x - gesture.last.x;
      const dy = point.y - gesture.last.y;
      gesture.last = point;
      const updates = gesture.ids
        .map((id) => doc[id])
        .filter(Boolean)
        .map((object) => ({ id: object!.id, patch: translatePatch(object!, dx, dy) }));
      if (updates.length) applyLive([{ op: "update", updates }]);
      return;
    }

    if (gesture.mode === "resize") {
      const scaleX = Math.max(0.1, (point.x - gesture.start.x) / Math.max(1, gesture.start.width));
      const scaleY = Math.max(0.1, (point.y - gesture.start.y) / Math.max(1, gesture.start.height));
      const updates: { id: string; patch: Partial<BoardObject> }[] = [];
      for (const id of gesture.ids) {
        const object = doc[id];
        if (!object) continue;
        const map = (p: Point) => ({
          x: gesture.start.x + (p.x - gesture.start.x) * scaleX,
          y: gesture.start.y + (p.y - gesture.start.y) * scaleY,
        });
        if (object.type === "shape") {
          const topLeft = map({ x: object.x, y: object.y });
          updates.push({
            id,
            patch: {
              ...topLeft,
              width: Math.max(30, object.width * scaleX),
              height: Math.max(30, object.height * scaleY),
            } as Partial<BoardObject>,
          });
        } else if (object.type === "text") {
          updates.push({ id, patch: map({ x: object.x, y: object.y }) as Partial<BoardObject> });
        } else if (object.type === "draw") {
          updates.push({ id, patch: { points: object.points.map(map) } as Partial<BoardObject> });
        }
      }
      if (updates.length) {
        // Resize is relative to the pre-gesture geometry, so re-anchor each frame.
        applyLive([{ op: "update", updates }]);
        gestureRef.current = { ...gesture, start: { ...gesture.start } };
      }
    }
  };

  const onPointerUp = () => {
    const gesture = gestureRef.current;
    gestureRef.current = null;

    if (gesture?.mode === "move" || gesture?.mode === "resize") {
      endInteraction();
    }

    if (gesture?.mode === "pen" && stroke && stroke.length > 1) {
      commit([{ op: "add", objects: [createStroke(stroke)] }]);
    }
    if (gesture?.mode === "pen") setStroke(null);

    if (gesture?.mode === "marquee" && marquee) {
      const hits = objects
        .filter((object) => {
          const bounds = boundsOf(object, doc);
          return bounds && rectsIntersect(bounds, marquee);
        })
        .map((object) => object.id);
      setSelection(expandSelection(hits, doc));
      setMarquee(null);
    }
  };

  const finishConnector = (targetId: string) => {
    if (!pendingLink || pendingLink.fromId === targetId) return;
    const connector = createConnector(pendingLink.fromId, targetId);
    commit([{ op: "add", objects: [connector] }]);
    setPendingLink(null);
    setTool("select");
  };

  const onDoubleClick = (event: React.MouseEvent) => {
    const hit = hitTest(toBoard(event.clientX, event.clientY));
    if (!hit) return;
    if (hit.type === "shape") setEditing({ id: hit.id, value: hit.label });
    else if (hit.type === "text") setEditing({ id: hit.id, value: hit.text });
    else if (hit.type === "connector") setEditing({ id: hit.id, value: hit.label });
  };

  const commitEdit = () => {
    if (!editing) return;
    const object = doc[editing.id];
    if (object) {
      const key = object.type === "text" ? "text" : "label";
      const ops: BoardOp[] = [{ op: "update", updates: [{ id: editing.id, patch: { [key]: editing.value } as Partial<BoardObject> }] }];
      commit(ops);
    }
    setEditing(null);
  };

  const onWheel = (event: React.WheelEvent) => {
    if (!event.ctrlKey && !event.metaKey) {
      setView((v) => ({
        ...v,
        x: clamp(v.x + event.deltaX / v.zoom, 0, BOARD_WIDTH - size.width / v.zoom),
        y: clamp(v.y + event.deltaY / v.zoom, 0, BOARD_HEIGHT - size.height / v.zoom),
      }));
      return;
    }
    setView((v) => {
      const zoom = clamp(v.zoom * (event.deltaY < 0 ? 1.08 : 0.93), MIN_ZOOM, MAX_ZOOM);
      return { ...v, zoom };
    });
  };

  const editingScreen = editing && doc[editing.id] ? boundsOf(doc[editing.id]!, doc) : null;

  return (
    <div className="relative h-full w-full overflow-hidden bg-board-surface">
      <div
        ref={containerRef}
        className="h-full w-full touch-none"
        style={{ cursor: tool === "select" ? "default" : "crosshair" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => session.publishCursor(null)}
        onDoubleClick={onDoubleClick}
        onWheel={onWheel}
        onContextMenu={(e) => e.preventDefault()}
      >
        <svg
          width={size.width}
          height={size.height}
          viewBox={`${view.x} ${view.y} ${size.width / view.zoom} ${size.height / view.zoom}`}
          role="application"
          aria-label="System design canvas"
        >
          <defs>
            <pattern id="grid" width={40} height={40} patternUnits="userSpaceOnUse">
              <circle cx={1} cy={1} r={1} fill="var(--board-grid)" />
            </pattern>
            <marker id="arrow" viewBox="0 0 10 10" refX={9} refY={5} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--ink)" />
            </marker>
          </defs>
          <rect x={0} y={0} width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="url(#grid)" />

          {/* connectors below shapes */}
          {objects
            .filter((o) => o.type === "connector")
            .map((object) => {
              const connector = object as Extract<BoardObject, { type: "connector" }>;
              const { start, end } = connectorGeometry(connector.from, connector.to, doc);
              return (
                <g key={connector.id}>
                  <line
                    x1={start.x}
                    y1={start.y}
                    x2={end.x}
                    y2={end.y}
                    stroke="var(--ink)"
                    strokeWidth={1.6}
                    markerEnd="url(#arrow)"
                  />
                  {connector.label ? (
                    <text
                      x={(start.x + end.x) / 2}
                      y={(start.y + end.y) / 2 - 8}
                      textAnchor="middle"
                      fontSize={13}
                      fill="var(--ink-soft)"
                      style={{ userSelect: "none" }}
                    >
                      {connector.label}
                    </text>
                  ) : null}
                </g>
              );
            })}

          {objects
            .filter((o) => o.type !== "connector")
            .map((object) => {
              if (object.type === "shape") {
                return (
                  <g
                    key={object.id}
                    onPointerUp={() => tool === "connector" && finishConnector(object.id)}
                  >
                    <ShapeView shape={object} />
                  </g>
                );
              }
              if (object.type === "text") {
                return (
                  <text
                    key={object.id}
                    x={object.x + 6}
                    y={object.y + 20}
                    fontSize={16}
                    fill="var(--ink)"
                    style={{ userSelect: "none" }}
                  >
                    {object.text}
                  </text>
                );
              }
              return (
                <polyline
                  key={object.id}
                  points={object.points.map((p) => `${p.x},${p.y}`).join(" ")}
                  fill="none"
                  stroke="var(--ink)"
                  strokeWidth={2.4}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              );
            })}

          {stroke && stroke.length > 1 ? (
            <polyline
              points={stroke.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none"
              stroke="var(--ink)"
              strokeWidth={2.4}
              strokeLinecap="round"
            />
          ) : null}

          {pendingLink && doc[pendingLink.fromId] ? (
            <line
              x1={connectorGeometry({ objectId: pendingLink.fromId }, { point: pendingLink.to }, doc).start.x}
              y1={connectorGeometry({ objectId: pendingLink.fromId }, { point: pendingLink.to }, doc).start.y}
              x2={pendingLink.to.x}
              y2={pendingLink.to.y}
              stroke="var(--selection)"
              strokeWidth={1.6}
              strokeDasharray="6 5"
            />
          ) : null}

          {marquee ? (
            <rect
              {...marquee}
              fill="var(--selection)"
              fillOpacity={0.08}
              stroke="var(--selection)"
              strokeWidth={1 / view.zoom}
            />
          ) : null}

          {selectionBounds ? (
            <g>
              <rect
                x={selectionBounds.x - 6}
                y={selectionBounds.y - 6}
                width={selectionBounds.width + 12}
                height={selectionBounds.height + 12}
                fill="none"
                stroke="var(--selection)"
                strokeWidth={1.5 / view.zoom}
                strokeDasharray="5 4"
              />
              <rect
                data-handle="se"
                x={selectionBounds.x + selectionBounds.width + 1}
                y={selectionBounds.y + selectionBounds.height + 1}
                width={10 / view.zoom}
                height={10 / view.zoom}
                fill="var(--selection)"
                style={{ cursor: "nwse-resize" }}
              />
            </g>
          ) : null}

          {peers.map((peer) =>
            peer.cursor ? (
              <g key={peer.id} pointerEvents="none">
                <path
                  d={`M ${peer.cursor.x} ${peer.cursor.y} l 0 18 l 5 -5 l 4 8 l 4 -2 l -4 -8 l 7 -1 Z`}
                  fill={peer.color}
                />
              </g>
            ) : null,
          )}
        </svg>
      </div>

      {editing && editingScreen ? (
        <input
          autoFocus
          value={editing.value}
          onChange={(e) => setEditing({ ...editing, value: e.target.value })}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitEdit();
            if (e.key === "Escape") setEditing(null);
          }}
          className="absolute z-20 rounded-md border border-selection bg-card px-2 py-1 text-sm text-foreground outline-none"
          style={{
            left: (editingScreen.x - view.x) * view.zoom,
            top: (editingScreen.y - view.y) * view.zoom + (editingScreen.height * view.zoom) / 2 - 16,
            width: Math.max(120, editingScreen.width * view.zoom),
          }}
        />
      ) : null}

      <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center">
        <div className="pointer-events-auto">
          <Toolbar
            tool={tool}
            onToolChange={(next) => {
              setTool(next);
              setPendingLink(null);
            }}
            selectionCount={selection.length}
            canGroup={canGroup}
            canUngroup={canUngroup}
            onGroup={groupSelection}
            onUngroup={ungroupSelection}
            onDelete={deleteSelection}
            onUndo={session.undo}
            onRedo={session.redo}
            canUndo={session.canUndo}
            canRedo={session.canRedo}
          />
        </div>
      </div>

      <div className="absolute bottom-4 right-4">
        <Minimap doc={doc} viewport={viewport} me={me} peers={peers} onNavigate={centerOn} />
      </div>

      <div className="board-panel absolute bottom-4 left-4 flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground">
        <span>{Math.round(view.zoom * 100)}%</span>
        <span className="h-3 w-px bg-border" />
        <button type="button" className="hover:text-foreground" onClick={() => setView((v) => ({ ...v, zoom: clamp(v.zoom * 0.9, MIN_ZOOM, MAX_ZOOM) }))}>
          −
        </button>
        <button type="button" className="hover:text-foreground" onClick={() => setView((v) => ({ ...v, zoom: clamp(v.zoom * 1.1, MIN_ZOOM, MAX_ZOOM) }))}>
          +
        </button>
        <span className="h-3 w-px bg-border" />
        <span>Alt-drag to pan · Ctrl-scroll to zoom</span>
      </div>
    </div>
  );
}
