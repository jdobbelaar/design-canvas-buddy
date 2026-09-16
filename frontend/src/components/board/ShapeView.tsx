import type { ShapeObject } from "@/lib/collab/types";
import { ROUNDED_RECT_RADIUS, cloudPathD, databaseCapRadius } from "@/lib/board/geometry";

interface Props {
  shape: ShapeObject;
}

/** Pure SVG rendering of one system-design / flowchart shape. */
export function ShapeView({ shape }: Props) {
  const { x, y, width: w, height: h, kind } = shape;
  const common = {
    fill: "var(--shape-fill)",
    stroke: "var(--ink)",
    strokeWidth: 1.6,
    strokeLinejoin: "round" as const,
  };

  let body: React.ReactNode = null;

  if (kind === "box") {
    body = <rect x={x} y={y} width={w} height={h} rx={ROUNDED_RECT_RADIUS.box} {...common} />;
  } else if (kind === "database") {
    const ry = databaseCapRadius(h);
    body = (
      <g {...common}>
        <path
          d={`M ${x} ${y + ry} a ${w / 2} ${ry} 0 0 1 ${w} 0 v ${h - 2 * ry} a ${w / 2} ${ry} 0 0 1 ${-w} 0 Z`}
        />
        <path d={`M ${x} ${y + ry} a ${w / 2} ${ry} 0 0 0 ${w} 0`} fill="none" />
      </g>
    );
  } else if (kind === "queue") {
    body = (
      <g {...common}>
        <rect x={x} y={y} width={w} height={h} rx={ROUNDED_RECT_RADIUS.queue} />
        {[0.33, 0.66].map((t) => (
          <line key={t} x1={x + w * t} y1={y} x2={x + w * t} y2={y + h} />
        ))}
      </g>
    );
  } else if (kind === "cloud") {
    body = <path {...common} d={cloudPathD({ x, y, width: w, height: h })} />;
  } else if (kind === "loadbalancer") {
    body = (
      <g {...common}>
        <rect
          x={x}
          y={y}
          width={w}
          height={h}
          rx={ROUNDED_RECT_RADIUS.loadbalancer}
          fill="var(--shape-fill-alt)"
        />
        <path
          d={`M ${x + w * 0.2} ${y + h / 2} H ${x + w * 0.45}
              M ${x + w * 0.45} ${y + h / 2} L ${x + w * 0.78} ${y + h * 0.28}
              M ${x + w * 0.45} ${y + h / 2} L ${x + w * 0.78} ${y + h * 0.72}`}
          fill="none"
          strokeWidth={1.4}
        />
      </g>
    );
  } else if (kind === "decision") {
    body = (
      <polygon
        {...common}
        points={`${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`}
      />
    );
  } else {
    body = (
      <circle
        {...common}
        cx={x + w / 2}
        cy={y + h / 2}
        r={Math.min(w, h) / 2}
        fill="var(--shape-fill-alt)"
      />
    );
  }

  const labelY = kind === "loadbalancer" ? y + h + 16 : y + h / 2 + 5;

  return (
    <g>
      {body}
      {shape.label ? (
        <text
          x={x + w / 2}
          y={labelY}
          textAnchor="middle"
          fill="var(--ink)"
          fontSize={14}
          fontFamily="var(--font-body)"
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          {shape.label}
        </text>
      ) : null}
    </g>
  );
}
