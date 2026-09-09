import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BoardDoc, BoardObject, BoardOp, Participant, Point, Viewport } from "../collab/types";
import { MockBackendClient, PARTICIPANT_COLORS, newId } from "../collab/mock-backend";
import { applyOps, emptyHistory, invertOps, pushHistory, type History } from "./ops";

export interface BoardSession {
  doc: BoardDoc;
  peers: Participant[];
  me: Participant;
  /** Apply ops locally, record them in local undo history, and broadcast. */
  commit: (ops: BoardOp[]) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Start a live drag: remembers the pre-drag state of the given objects. */
  beginInteraction: (ids: string[]) => void;
  /** Broadcast intermediate drag state without polluting undo history. */
  applyLive: (ops: BoardOp[]) => void;
  /** Close a live drag, recording a single undo step for the whole gesture. */
  endInteraction: () => void;
  publishCursor: (cursor: Point | null) => void;
  publishViewport: (viewport: Viewport) => void;
}

export function useBoardSession(sessionId: string, role: "interviewer" | "candidate"): BoardSession {
  const me = useMemo<Participant>(
    () => ({
      id: newId("p"),
      role,
      color: PARTICIPANT_COLORS[role === "interviewer" ? 0 : 1]!,
    }),
    [role],
  );

  const clientRef = useRef<MockBackendClient | null>(null);
  const [doc, setDoc] = useState<BoardDoc>({});
  const docRef = useRef<BoardDoc>({});
  const [peers, setPeers] = useState<Participant[]>([]);
  const [history, setHistory] = useState<History>(emptyHistory);

  const setDocBoth = useCallback((next: BoardDoc) => {
    docRef.current = next;
    setDoc(next);
  }, []);

  useEffect(() => {
    const client = new MockBackendClient();
    clientRef.current = client;
    const off = client.subscribe((event) => {
      if (event.type === "ops") {
        setDocBoth(applyOps(docRef.current, event.ops));
      } else if (event.type === "presence") {
        setPeers(event.participants);
      } else if (event.type === "snapshot") {
        setDocBoth(applyOps({}, [{ op: "add", objects: event.objects }]));
        setPeers(event.participants);
      }
    });
    void client.connect(sessionId, me);
    return () => {
      off();
      client.disconnect();
      clientRef.current = null;
    };
  }, [sessionId, me, setDocBoth]);

  const commit = useCallback(
    (ops: BoardOp[]) => {
      if (!ops.length) return;
      const before = docRef.current;
      const undoOps = invertOps(before, ops);
      setDocBoth(applyOps(before, ops));
      setHistory((h) => pushHistory(h, { redo: ops, undo: undoOps }));
      clientRef.current?.sendOps(ops);
    },
    [setDocBoth],
  );

  const applyWithoutHistory = useCallback(
    (ops: BoardOp[]) => {
      setDocBoth(applyOps(docRef.current, ops));
      clientRef.current?.sendOps(ops);
    },
    [setDocBoth],
  );

  const undo = useCallback(() => {
    setHistory((h) => {
      const entry = h.past[h.past.length - 1];
      if (!entry) return h;
      applyWithoutHistory(entry.undo);
      return { past: h.past.slice(0, -1), future: [entry, ...h.future] };
    });
  }, [applyWithoutHistory]);

  const redo = useCallback(() => {
    setHistory((h) => {
      const entry = h.future[0];
      if (!entry) return h;
      applyWithoutHistory(entry.redo);
      return { past: [...h.past, entry], future: h.future.slice(1) };
    });
  }, [applyWithoutHistory]);

  const interactionRef = useRef<{ before: BoardDoc; ids: string[] } | null>(null);

  const beginInteraction = useCallback((ids: string[]) => {
    interactionRef.current = { before: docRef.current, ids };
  }, []);

  const endInteraction = useCallback(() => {
    const interaction = interactionRef.current;
    interactionRef.current = null;
    if (!interaction) return;
    const undoUpdates: { id: string; patch: Partial<BoardObject> }[] = [];
    const redoUpdates: { id: string; patch: Partial<BoardObject> }[] = [];
    for (const id of interaction.ids) {
      const before = interaction.before[id];
      const after = docRef.current[id];
      if (!before || !after || before === after) continue;
      const patchKeys = (Object.keys(after) as (keyof BoardObject)[]).filter(
        (key) => JSON.stringify(after[key]) !== JSON.stringify(before[key]),
      );
      if (!patchKeys.length) continue;
      const pick = (source: BoardObject) =>
        Object.fromEntries(
          patchKeys.map((key) => [key, (source as unknown as Record<string, unknown>)[key as string]]),
        ) as Partial<BoardObject>;
      undoUpdates.push({ id, patch: pick(before) });
      redoUpdates.push({ id, patch: pick(after) });
    }
    if (!redoUpdates.length) return;
    setHistory((h) =>
      pushHistory(h, {
        redo: [{ op: "update", updates: redoUpdates }],
        undo: [{ op: "update", updates: undoUpdates }],
      }),
    );
  }, []);

  const publishCursor = useCallback((cursor: Point | null) => {
    clientRef.current?.sendCursor(cursor);
  }, []);
  const publishViewport = useCallback((viewport: Viewport) => {
    clientRef.current?.sendViewport(viewport);
  }, []);

  return {
    doc,
    peers,
    me,
    commit,
    undo,
    redo,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    publishCursor,
    publishViewport,
    beginInteraction,
    applyLive: applyWithoutHistory,
    endInteraction,
  };
}
