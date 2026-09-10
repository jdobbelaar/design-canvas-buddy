import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Canvas } from "@/components/board/Canvas";
import { useBoardSession } from "@/lib/board/useBoardSession";

export const Route = createFileRoute("/session/$sessionId")({
  validateSearch: (search: Record<string, unknown>) => ({
    host: search["host"] === 1 || search["host"] === "1" ? (1 as const) : undefined,
  }),
  head: ({ params }) => ({
    meta: [
      { title: `Interview session ${params.sessionId} | Draftbench` },
      {
        name: "description",
        content: "A live shared canvas for a system design interview session.",
      },
      { property: "og:title", content: "Live system design interview canvas | Draftbench" },
      { property: "og:description", content: "Join the shared canvas and diagram together in real time." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: SessionPage,
});

function SessionPage() {
  const { sessionId } = Route.useParams();
  const { host } = Route.useSearch();
  const session = useBoardSession(sessionId, host ? "interviewer" : "candidate");
  const [copied, setCopied] = useState(false);
  const [shareUrl, setShareUrl] = useState(`/session/${sessionId}`);

  useEffect(() => {
    setShareUrl(`${window.location.origin}/session/${sessionId}`);
  }, [sessionId]);

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <Link to="/" className="font-display text-sm tracking-tight text-foreground">
            Draftbench
          </Link>
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-muted-foreground">
            {host ? "Interviewer" : "Candidate"} · {sessionId}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5" aria-label="Participants">
            <span
              className="h-2.5 w-2.5 rounded-full ring-2 ring-background"
              style={{ backgroundColor: session.me.color }}
              title="You"
            />
            {session.peers.map((peer) => (
              <span
                key={peer.id}
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: peer.color }}
                title={peer.role}
              />
            ))}
            <span className="ml-1 text-xs text-muted-foreground">
              {session.peers.length + 1} here
            </span>
          </div>
          <button
            type="button"
            onClick={async () => {
              await navigator.clipboard?.writeText(shareUrl);
              setCopied(true);
              setTimeout(() => setCopied(false), 1800);
            }}
            className="inline-flex items-center gap-2 rounded-full border border-border px-3.5 py-1.5 text-xs font-medium transition-colors hover:bg-secondary"
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Link copied" : "Copy invite link"}
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <Canvas session={session} />
      </div>
    </div>
  );
}
