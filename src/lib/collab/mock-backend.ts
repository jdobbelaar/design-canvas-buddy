import type {
  BackendClient,
  BoardOp,
  ClientEvent,
  Participant,
  Point,
  ServerEvent,
  Viewport,
} from "./types";
import { applyOps } from "../board/ops";
import type { BoardDoc } from "./types";

/**
 * Mock WebSocket transport.
 *
 * Speaks the exact ClientEvent/ServerEvent schema a real FastAPI WebSocket
 * backend will speak, so swapping this class out requires no UI changes.
 * Messages travel over a BroadcastChannel, so two browser tabs on the same
 * session id collaborate for real.
 */

export interface Channel {
  post(event: ClientEvent): void;
  onMessage(handler: (event: ClientEvent) => void): () => void;
  close(): void;
}

export function createBroadcastChannel(name: string): Channel {
  if (typeof BroadcastChannel === "undefined") {
    const handlers = new Set<(e: ClientEvent) => void>();
    return {
      post: () => {},
      onMessage: (h) => {
        handlers.add(h);
        return () => handlers.delete(h);
      },
      close: () => handlers.clear(),
    };
  }
  const channel = new BroadcastChannel(name);
  return {
    post: (event) => channel.postMessage(event),
    onMessage: (handler) => {
      const listener = (e: MessageEvent) => handler(e.data as ClientEvent);
      channel.addEventListener("message", listener);
      return () => channel.removeEventListener("message", listener);
    },
    close: () => channel.close(),
  };
}

export const PARTICIPANT_COLORS = ["#2f6df6", "#e0603a", "#1f9d76", "#a855f7"];

export function newId(prefix = "id"): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export class MockBackendClient implements BackendClient {
  private channel: Channel | null = null;
  private handlers = new Set<(event: ServerEvent) => void>();
  private peers = new Map<string, Participant>();
  private me: Participant | null = null;
  private sessionId = "";
  /** Local mirror of the doc, so this peer can answer snapshot requests. */
  private doc: BoardDoc = {};
  private unsubscribe: (() => void) | null = null;

  constructor(private makeChannel: (name: string) => Channel = createBroadcastChannel) {}

  async createSession(): Promise<string> {
    return newId("s").slice(2);
  }

  async connect(sessionId: string, participant: Participant): Promise<void> {
    this.sessionId = sessionId;
    this.me = participant;
    this.channel = this.makeChannel(`sdi-session-${sessionId}`);
    this.unsubscribe = this.channel.onMessage((event) => this.handleIncoming(event));
    this.channel.post({ type: "join", sessionId, participant });
    this.emitPresence();
  }

  disconnect(): void {
    if (this.channel && this.me) {
      this.channel.post({ type: "leave", sessionId: this.sessionId, participantId: this.me.id });
    }
    this.unsubscribe?.();
    this.channel?.close();
    this.channel = null;
    this.peers.clear();
  }

  /** Keep the local mirror in sync with ops the app applied itself. */
  trackLocalOps(ops: BoardOp[]): void {
    this.doc = applyOps(this.doc, ops);
  }

  sendOps(ops: BoardOp[]): void {
    if (!this.me) return;
    this.trackLocalOps(ops);
    this.channel?.post({ type: "ops", sessionId: this.sessionId, from: this.me.id, ops });
  }

  sendCursor(cursor: Point | null): void {
    if (!this.me) return;
    this.channel?.post({ type: "cursor", sessionId: this.sessionId, from: this.me.id, cursor });
  }

  sendViewport(viewport: Viewport): void {
    if (!this.me) return;
    this.channel?.post({ type: "viewport", sessionId: this.sessionId, from: this.me.id, viewport });
  }

  subscribe(handler: (event: ServerEvent) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  private emit(event: ServerEvent) {
    for (const handler of this.handlers) handler(event);
  }

  private emitPresence() {
    this.emit({ type: "presence", participants: [...this.peers.values()] });
  }

  private handleIncoming(event: ClientEvent) {
    if (event.sessionId !== this.sessionId) return;
    const myId = this.me?.id;

    switch (event.type) {
      case "join": {
        if (event.participant.id === myId) return;
        const alreadyKnown = this.peers.has(event.participant.id);
        this.peers.set(event.participant.id, event.participant);
        this.emitPresence();
        // Answer the newcomer once with everything we know.
        if (this.me && !alreadyKnown) {
          this.channel?.post({ type: "join", sessionId: this.sessionId, participant: this.me });
          const objects = Object.values(this.doc);
          if (objects.length) {
            this.channel?.post({
              type: "ops",
              sessionId: this.sessionId,
              from: this.me.id,
              ops: [{ op: "add", objects }],
            });
          }
        }
        break;
      }
      case "leave": {
        this.peers.delete(event.participantId);
        this.emitPresence();
        break;
      }
      case "ops": {
        if (event.from === myId) return;
        this.doc = applyOps(this.doc, event.ops);
        this.emit({ type: "ops", from: event.from, ops: event.ops });
        break;
      }
      case "cursor": {
        const peer = this.peers.get(event.from);
        if (!peer) return;
        this.peers.set(event.from, { ...peer, cursor: event.cursor });
        this.emitPresence();
        break;
      }
      case "viewport": {
        const peer = this.peers.get(event.from);
        if (!peer) return;
        this.peers.set(event.from, { ...peer, viewport: event.viewport });
        this.emitPresence();
        break;
      }
    }
  }
}

/** The app talks to this. Swap the implementation to go live. */
export const backend: BackendClient & { trackLocalOps?: (ops: BoardOp[]) => void } =
  new MockBackendClient();
