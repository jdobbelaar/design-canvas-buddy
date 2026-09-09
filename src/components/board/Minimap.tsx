import { BOARD_HEIGHT, BOARD_WIDTH, type BoardDoc, type Participant } from "@/lib/collab/types";
import { boundsOf } from "@/lib/board/geometry";

const MAP_WIDTH = 208;
const MAP_HEIGHT = (MAP_WIDTH * BOARD_HEIGHT) / BOARD_WIDTH;

interface Props {
  doc: BoardDoc;
  viewport: { x: number; y: number; width: number; height: number };
  me: Participant;
  peers: Participant[];
  onNavigate: (center: { x: number; y: number }) => void;
}

/** Board overview with every participant's viewport drawn in their color. */
export function Minimap({ doc, viewport, me, peers, onNavigate }: Props) {
  const rects = [
    { color: me.color, viewport, id: me.id },
    ...peers
      .filter((p) => p.viewport)
      .map((p) => ({ color: p.color, viewport: p.viewport!, id: p.id })),
  ];

  return (
    <div className="board-panel p-2" aria-label="Board minimap">
      <svg
        width={MAP_WIDTH}
        height={MAP_HEIGHT}
        viewBox={`0 0 ${BOARD_WIDTH} ${BOARD_HEIGHT}`}
        className="cursor-pointer rounded-[6px] bg-board-surface"
        role="img"
        onPointerDown={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          onNavigate({
            x: ((event.clientX - rect.left) / rect.width) * BOARD_WIDTH,
            y: ((event.clientY - rect.top) / rect.height) * BOARD_HEIGHT,
          });
        }}
      >
        {Object.values(doc).map((object) => {
          const bounds = boundsOf(object, doc);
          if (!bounds) return null;
          return (
            <rect
              key={object.id}
              x={bounds.x}
              y={bounds.y}
              width={Math.max(bounds.width, 24)}
              height={Math.max(bounds.height, 24)}
              fill="var(--ink-soft)"
              opacity={0.45}
            />
          );
        })}
        {rects.map((r) => (
          <rect
            key={r.id}
            x={r.viewport.x}
            y={r.viewport.y}
            width={r.viewport.width}
            height={r.viewport.height}
            fill={r.color}
            fillOpacity={0.08}
            stroke={r.color}
            strokeWidth={18}
          />
        ))}
      </svg>
    </div>
  );
}
