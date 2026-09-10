# System Design Interview Canvas — Frontend Specification

## 1. Purpose

A shared visual workspace for remotely interviewing system design candidates. The interviewer creates a session and shares a link; the candidate opens it and both parties see a synchronized canvas in real time — freeform drawing, text, and a system-design shape toolkit (boxes, databases, queues, etc.) plus standard flowchart elements.

This phase delivers the **React frontend only**, using a **mock WebSocket server** in place of the eventual FastAPI + SQLite backend. The frontend must be built against a clean API abstraction so the mock can later be swapped for the real backend with minimal changes.

## 2. Roles & Access

- No login/auth. Access is link-based only.
- **Interviewer**: creates a session, gets a shareable link containing a session ID (e.g. `/session/abc123`).
- **Candidate**: joins by opening that link.
- Role (interviewer vs. candidate) is determined purely by how the user entered — creator vs. joiner. No other behavioral difference.
- **Both roles have identical, equal editing rights** — anyone can draw, place, move, resize, group, and delete any object.

## 3. Canvas

- **Fixed-size large board** (not infinite) — e.g. 6000×4000px — larger than the viewport.
- Supports **pan** (drag/scroll) and **zoom** within that fixed area.
- Clean, minimal visual style (Excalidraw-like aesthetic): light background, simple strokes, restrained color palette.
- Canvas rendering technology (SVG, HTML canvas, or a library such as `react-flow`/`tldraw`/`konva`) is left to the implementer's discretion — pick whatever best supports attached/re-routing connectors, grouping, and resize handles.

### Minimap
- Small overview panel showing the entire board.
- Displays each participant's current viewport as a colored rectangle, matching that participant's cursor color.
- Purpose: let participants reference and navigate to off-screen locations during discussion.

## 4. Real-Time Collaboration

- Synchronization is real-time via a **mock WebSocket server**, keyed by session ID.
- Both participants' changes (shape edits, drawing, cursor movement, viewport position) propagate live to each other.
- **Live cursors**: each participant sees the other's cursor position rendered in a distinct color. No name labels.
- **Reconnection/state recovery is out of scope for this phase** — if a participant refreshes or disconnects, restoring their session is deferred to a later phase.

### API Abstraction Layer
- All collaboration actions (add/move/resize/delete object, draw stroke, group/ungroup, cursor move, viewport change) must go through a defined client-side interface (e.g. a `BackendClient` or event-bus abstraction) rather than calling the mock transport directly from UI components.
- The mock WebSocket server implements this interface for now; it should be swappable for a real FastAPI/WebSocket backend later without touching UI/component code.
- Define the event schema explicitly (event name, payload shape) as part of implementation — this schema becomes the contract for the future backend.

## 5. Toolkit — System Design Shapes

Placeable, resizable graphical elements:
- Generic box/service
- Database (cylinder)
- Queue
- Cloud / external service
- Load balancer
- Directional connector/arrow (see §6)

## 6. Toolkit — Flowchart Elements

- Decision point (diamond)
- Branching/junction point (where flow splits or merges)

## 7. Connectors

- Arrows/lines connect two shapes and **attach** to them.
- When a connected shape is moved, the connector **automatically re-routes** to follow it.
- Connectors support **text labels** (e.g. "HTTPS", "async").

## 8. Freeform Content

- **Pen tool**: simple freehand drawing. Single color, single stroke width — no color/width picker for this MVP.
- **Text/notes**: freestanding text elements, placeable anywhere on the canvas, independently movable — unless grouped with other objects (see §9), in which case they move with the group.

## 9. Object Manipulation

- **Move**: drag any placed object (shape, text, connector, drawing) anywhere on the canvas.
- **Resize**: shapes support drag handles to resize.
- **Multi-select**: via rubber-band/marquee drag over an area, **and** shift-click on individual objects (both supported).
- **Group**: selected objects can be grouped and thereafter moved/dragged as a single unit.
- **Ungroup**: a group can be broken back into independent objects.
- **Delete**: remove selected object(s).

## 10. Undo/Redo

- Each participant has their **own local undo/redo history** — it undoes/redoes only that participant's own actions, not the other participant's.
- History depth: **10 steps**.

## 11. Deferred to Later Phases (explicitly out of scope now)

- Persisting/restoring session state on reconnect or refresh.
- PDF export of the board (planned, but intentionally deferred until the real backend exists, to simplify current work).
- Real FastAPI backend and SQLite persistence (event schema from §4 should anticipate this).

## 12. Suggested Stack

- React (as specified for Lovable.dev).
- TypeScript recommended.
- Canvas rendering library left to implementer's judgment.
- Mock WebSocket server can be a lightweight local Node/WS process or an in-browser simulated transport — implementer's choice, as long as it satisfies the API abstraction in §4.
