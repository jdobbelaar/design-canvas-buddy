import { beforeEach, describe, expect, it, vi } from "vitest";
import { MockBackendClient, type Channel } from "./mock-backend";
import type { ClientEvent, Participant, ServerEvent } from "./types";

/** In-memory stand-in for BroadcastChannel so two clients can talk in a test. */
class TestBus {
  private listeners = new Map<string, Set<(e: ClientEvent) => void>>();
  private senders = new WeakMap<object, string>();

  channel = (name: string): Channel => {
    const key = {};
    const handlers = new Set<(e: ClientEvent) => void>();
    this.senders.set(key, name);
    return {
      post: (event) => {
        for (const [n, set] of this.listeners) {
          if (n !== name) continue;
          for (const handler of set) if (!handlers.has(handler)) handler(event);
        }
      },
      onMessage: (handler) => {
        handlers.add(handler);
        const set = this.listeners.get(name) ?? new Set();
        set.add(handler);
        this.listeners.set(name, set);
        return () => set.delete(handler);
      },
      close: () => {
        for (const handler of handlers) this.listeners.get(name)?.delete(handler);
      },
    };
  };
}

const participant = (id: string, role: Participant["role"]): Participant => ({
  id,
  role,
  color: role === "interviewer" ? "#2f6df6" : "#e0603a",
});

describe("MockBackendClient", () => {
  let bus: TestBus;
  let a: MockBackendClient;
  let b: MockBackendClient;
  let eventsA: ServerEvent[];
  let eventsB: ServerEvent[];

  beforeEach(async () => {
    bus = new TestBus();
    a = new MockBackendClient(bus.channel);
    b = new MockBackendClient(bus.channel);
    eventsA = [];
    eventsB = [];
    a.subscribe((e) => eventsA.push(e));
    b.subscribe((e) => eventsB.push(e));
    await a.connect("s1", participant("a", "interviewer"));
    await b.connect("s1", participant("b", "candidate"));
  });

  it("creates unique session ids", async () => {
    const ids = await Promise.all([a.createSession(), a.createSession()]);
    expect(ids[0]).not.toEqual(ids[1]);
    expect(ids[0]).toMatch(/^\w+$/);
  });

  it("announces presence to both peers on join", () => {
    const presenceA = eventsA.filter((e) => e.type === "presence").at(-1);
    const presenceB = eventsB.filter((e) => e.type === "presence").at(-1);
    expect(presenceA && presenceA.type === "presence" && presenceA.participants.map((p) => p.id)).toEqual(["b"]);
    expect(presenceB && presenceB.type === "presence" && presenceB.participants.map((p) => p.id)).toEqual(["a"]);
  });

  it("relays ops to the peer but never echoes them back to the sender", () => {
    a.sendOps([{ op: "add", objects: [{ id: "o1", type: "text", x: 0, y: 0, text: "hi" }] }]);
    const opsForB = eventsB.filter((e) => e.type === "ops");
    expect(opsForB).toHaveLength(1);
    expect(eventsA.filter((e) => e.type === "ops")).toHaveLength(0);
  });

  it("sends the current board to a late joiner", async () => {
    a.sendOps([{ op: "add", objects: [{ id: "o1", type: "text", x: 0, y: 0, text: "hi" }] }]);
    const c = new MockBackendClient(bus.channel);
    const eventsC: ServerEvent[] = [];
    c.subscribe((e) => eventsC.push(e));
    await c.connect("s1", participant("c", "candidate"));

    const received = eventsC.filter((e) => e.type === "ops").flatMap((e) => (e.type === "ops" ? e.ops : []));
    const added = received.flatMap((op) => (op.op === "add" ? op.objects.map((o) => o.id) : []));
    expect(added).toContain("o1");
  });

  it("tracks peer cursors and viewports in presence", () => {
    b.sendCursor({ x: 120, y: 240 });
    b.sendViewport({ x: 0, y: 0, width: 800, height: 600 });
    const latest = eventsA.filter((e) => e.type === "presence").at(-1);
    const peer = latest?.type === "presence" ? latest.participants[0] : undefined;
    expect(peer?.cursor).toEqual({ x: 120, y: 240 });
    expect(peer?.viewport?.width).toBe(800);
  });

  it("ignores traffic from other sessions", async () => {
    const other = new MockBackendClient(bus.channel);
    await other.connect("s2", participant("z", "candidate"));
    const before = eventsA.length;
    other.sendOps([{ op: "delete", ids: ["o1"] }]);
    expect(eventsA.length).toBe(before);
  });

  it("removes a peer from presence on disconnect", () => {
    b.disconnect();
    const latest = eventsA.filter((e) => e.type === "presence").at(-1);
    expect(latest?.type === "presence" && latest.participants).toEqual([]);
  });

  it("does nothing when sending before connecting", () => {
    const lonely = new MockBackendClient(bus.channel);
    expect(() => lonely.sendOps([{ op: "delete", ids: ["x"] }])).not.toThrow();
  });
});

describe("swappability", () => {
  it("satisfies the BackendClient contract surface", () => {
    const client = new MockBackendClient();
    for (const method of ["createSession", "connect", "disconnect", "sendOps", "sendCursor", "sendViewport", "subscribe"]) {
      expect(typeof (client as unknown as Record<string, unknown>)[method]).toBe("function");
    }
    vi.restoreAllMocks();
  });
});
