import type {
  BackendClient,
  BoardOp,
  ClientEvent,
  Participant,
  Point,
  ServerEvent,
  Viewport,
} from "./types";

/**
 * Real WebSocket transport, talking to the FastAPI backend in `backend/`.
 *
 * Speaks the same ClientEvent/ServerEvent schema as MockBackendClient (see
 * openapi.yaml), so it is a drop-in replacement for it.
 */

function httpBaseUrl(): string {
  const configured = import.meta.env.VITE_BACKEND_URL;
  return (configured ?? "http://localhost:8000").replace(/\/+$/, "");
}

function wsBaseUrl(): string {
  return httpBaseUrl().replace(/^http/, "ws");
}

export class WebSocketBackendClient implements BackendClient {
  private socket: WebSocket | null = null;
  private handlers = new Set<(event: ServerEvent) => void>();
  private me: Participant | null = null;
  private sessionId = "";
  /**
   * Set by disconnect() so a close mid-handshake (e.g. React StrictMode's
   * dev-only mount/cleanup/remount) doesn't get reported as a connection
   * failure — it's an intentional abort, not an error.
   */
  private closedIntentionally = false;

  async createSession(): Promise<string> {
    const res = await fetch(`${httpBaseUrl()}/sessions`, { method: "POST" });
    if (!res.ok) {
      throw new Error(`Failed to create session: ${res.status} ${res.statusText}`);
    }
    const body = (await res.json()) as { sessionId: string };
    return body.sessionId;
  }

  connect(sessionId: string, participant: Participant): Promise<void> {
    this.sessionId = sessionId;
    this.me = participant;
    this.closedIntentionally = false;

    return new Promise((resolve, reject) => {
      const socket = new WebSocket(`${wsBaseUrl()}/ws/${sessionId}`);
      this.socket = socket;

      socket.addEventListener("open", () => {
        this.send({ type: "join", sessionId, participant });
        resolve();
      });

      socket.addEventListener("message", (event) => {
        const data = JSON.parse(event.data as string) as ServerEvent;
        this.emit(data);
      });

      socket.addEventListener("error", () => {
        if (this.closedIntentionally) return;
        reject(new Error("WebSocket connection failed"));
      });

      socket.addEventListener("close", () => {
        if (this.socket === socket) this.socket = null;
      });
    });
  }

  disconnect(): void {
    this.closedIntentionally = true;
    if (this.socket?.readyState === WebSocket.OPEN && this.me) {
      this.send({ type: "leave", sessionId: this.sessionId, participantId: this.me.id });
    }
    this.socket?.close();
    this.socket = null;
  }

  sendOps(ops: BoardOp[]): void {
    if (!this.me) return;
    this.send({ type: "ops", sessionId: this.sessionId, from: this.me.id, ops });
  }

  sendCursor(cursor: Point | null): void {
    if (!this.me) return;
    this.send({ type: "cursor", sessionId: this.sessionId, from: this.me.id, cursor });
  }

  sendViewport(viewport: Viewport): void {
    if (!this.me) return;
    this.send({ type: "viewport", sessionId: this.sessionId, from: this.me.id, viewport });
  }

  subscribe(handler: (event: ServerEvent) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  private send(event: ClientEvent): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(event));
    }
  }

  private emit(event: ServerEvent): void {
    for (const handler of this.handlers) handler(event);
  }
}
