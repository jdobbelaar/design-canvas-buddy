import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowRight, Database, Share2, Users } from "lucide-react";
import { useState } from "react";
import { MockBackendClient } from "@/lib/collab/mock-backend";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Whiteboard for System Design Interviews | Draftbench" },
      {
        name: "description",
        content:
          "Run remote system design interviews on a shared canvas. Create a session, share the link, and diagram services, databases and queues together in real time.",
      },
      { property: "og:title", content: "Whiteboard for System Design Interviews | Draftbench" },
      {
        property: "og:description",
        content:
          "A shared, real-time canvas built for interviewing system design candidates — no accounts, just a link.",
      },
    ],
  }),
  component: Landing,
});

function Landing() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [joinId, setJoinId] = useState("");

  const startSession = async () => {
    setBusy(true);
    const sessionId = await new MockBackendClient().createSession();
    void navigate({ to: "/session/$sessionId", params: { sessionId }, search: { host: 1 } });
  };

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
        <p className="font-display text-sm uppercase tracking-[0.22em] text-muted-foreground">
          Draftbench
        </p>
        <h1 className="mt-4 max-w-3xl text-5xl leading-[1.05] text-foreground sm:text-6xl">
          A shared canvas for system design interviews.
        </h1>
        <p className="mt-6 max-w-xl text-lg text-muted-foreground">
          Create a session, send the link to your candidate, and sketch architectures together —
          services, databases, queues, connectors and freehand notes, live on both screens.
        </p>

        <div className="mt-10 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={startSession}
            className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            Start a session
            <ArrowRight className="h-4 w-4" />
          </button>

          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const sessionId = joinId.trim().split("/").pop();
              if (sessionId) void navigate({ to: "/session/$sessionId", params: { sessionId }, search: { host: undefined } });
            }}
          >
            <input
              value={joinId}
              onChange={(e) => setJoinId(e.target.value)}
              placeholder="Paste a session link"
              aria-label="Session link or id"
              className="w-56 rounded-full border border-border bg-card px-4 py-3 text-sm outline-none focus:border-primary"
            />
            <button
              type="submit"
              className="rounded-full border border-border px-5 py-3 text-sm font-medium transition-colors hover:bg-secondary"
            >
              Join
            </button>
          </form>
        </div>

        <dl className="mt-16 grid gap-8 sm:grid-cols-3">
          {[
            { icon: Users, title: "No accounts", body: "Access is link-based. Both sides edit equally." },
            { icon: Database, title: "Design toolkit", body: "Services, databases, queues, load balancers, decisions." },
            { icon: Share2, title: "Live everything", body: "Cursors, viewports and edits sync as you talk." },
          ].map(({ icon: Icon, title, body }) => (
            <div key={title}>
              <Icon className="h-5 w-5 text-primary" />
              <dt className="mt-3 font-display text-base text-foreground">{title}</dt>
              <dd className="mt-1 text-sm text-muted-foreground">{body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </main>
  );
}
