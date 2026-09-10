/**
 * Collaboration contract.
 *
 * This file is the single source of truth for the wire schema shared between
 * the client and whatever backend implements it (today: an in-browser mock
 * WebSocket server; later: FastAPI + SQLite over a real WebSocket).
 */

export const BOARD_WIDTH = 6000;
export const BOARD_HEIGHT = 4000;

export type ShapeKind =
  | "box"
  | "database"
  | "queue"
  | "cloud"
  | "loadbalancer"
  | "decision"
  | "junction";

export interface Point {
  x: number;
  y: number;
}

interface ObjectBase {
  id: string;
  /** Objects sharing a groupId move together. */
  groupId?: string | null;
}

export interface ShapeObject extends ObjectBase {
  type: "shape";
  kind: ShapeKind;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

export interface TextObject extends ObjectBase {
  type: "text";
  x: number;
  y: number;
  text: string;
}

export interface DrawObject extends ObjectBase {
  type: "draw";
  /** Absolute board-space points of a freehand stroke. */
  points: Point[];
}

export type ConnectorEnd = { objectId: string } | { point: Point };

export interface ConnectorObject extends ObjectBase {
  type: "connector";
  from: ConnectorEnd;
  to: ConnectorEnd;
  label: string;
}

export type BoardObject = ShapeObject | TextObject | DrawObject | ConnectorObject;

export type BoardDoc = Record<string, BoardObject>;

/* ------------------------------- operations ------------------------------ */

export type BoardOp =
  | { op: "add"; objects: BoardObject[] }
  | { op: "update"; updates: { id: string; patch: Partial<BoardObject> }[] }
  | { op: "delete"; ids: string[] };

/* --------------------------------- events -------------------------------- */

export interface Viewport {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Participant {
  id: string;
  color: string;
  role: "interviewer" | "candidate";
  cursor?: Point | null;
  viewport?: Viewport | null;
}

/** Client -> server. */
export type ClientEvent =
  | { type: "join"; sessionId: string; participant: Participant }
  | { type: "leave"; sessionId: string; participantId: string }
  | { type: "ops"; sessionId: string; from: string; ops: BoardOp[] }
  | { type: "cursor"; sessionId: string; from: string; cursor: Point | null }
  | { type: "viewport"; sessionId: string; from: string; viewport: Viewport };

/** Server -> client. */
export type ServerEvent =
  | { type: "snapshot"; objects: BoardObject[]; participants: Participant[] }
  | { type: "ops"; from: string; ops: BoardOp[] }
  | { type: "presence"; participants: Participant[] };

export interface BackendClient {
  /** Create a new session and return its id (used to build the share link). */
  createSession(): Promise<string>;
  connect(sessionId: string, participant: Participant): Promise<void>;
  disconnect(): void;
  sendOps(ops: BoardOp[]): void;
  sendCursor(cursor: Point | null): void;
  sendViewport(viewport: Viewport): void;
  /** Subscribe to server events. Returns an unsubscribe function. */
  subscribe(handler: (event: ServerEvent) => void): () => void;
}
