import {
  ArrowRight,
  Boxes,
  Cloud,
  Database,
  Diamond,
  Circle,
  ListEnd,
  MousePointer2,
  Pencil,
  Redo2,
  Scaling,
  Square,
  Trash2,
  Type,
  Ungroup,
  Undo2,
} from "lucide-react";
import type { ShapeKind } from "@/lib/collab/types";
import { cn } from "@/lib/utils";

export type Tool = "select" | "pen" | "text" | "connector" | ShapeKind;

const TOOLS: { tool: Tool; label: string; icon: typeof Square; hotkey?: string }[] = [
  { tool: "select", label: "Select", icon: MousePointer2, hotkey: "V" },
  { tool: "pen", label: "Pen", icon: Pencil, hotkey: "P" },
  { tool: "text", label: "Text", icon: Type, hotkey: "T" },
  { tool: "connector", label: "Connector", icon: ArrowRight, hotkey: "C" },
  { tool: "box", label: "Service", icon: Square },
  { tool: "database", label: "Database", icon: Database },
  { tool: "queue", label: "Queue", icon: ListEnd },
  { tool: "cloud", label: "External service", icon: Cloud },
  { tool: "loadbalancer", label: "Load balancer", icon: Scaling },
  { tool: "decision", label: "Decision", icon: Diamond },
  { tool: "junction", label: "Junction", icon: Circle },
];

interface Props {
  tool: Tool;
  onToolChange: (tool: Tool) => void;
  selectionCount: number;
  canGroup: boolean;
  canUngroup: boolean;
  onGroup: () => void;
  onUngroup: () => void;
  onDelete: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function Toolbar(props: Props) {
  const iconButton =
    "inline-flex h-9 w-9 items-center justify-center rounded-md text-ink-soft transition-colors hover:bg-secondary disabled:opacity-35 disabled:hover:bg-transparent";

  return (
    <div className="board-panel flex items-center gap-1 px-2 py-1.5">
      {TOOLS.map(({ tool, label, icon: Icon, hotkey }) => (
        <button
          key={tool}
          type="button"
          title={hotkey ? `${label} (${hotkey})` : label}
          aria-label={label}
          aria-pressed={props.tool === tool}
          onClick={() => props.onToolChange(tool)}
          className={cn(
            iconButton,
            props.tool === tool && "bg-accent text-accent-foreground hover:bg-accent",
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </button>
      ))}

      <span className="mx-1 h-6 w-px bg-border" />

      <button
        type="button"
        aria-label="Group"
        title="Group (Ctrl+G)"
        disabled={!props.canGroup}
        onClick={props.onGroup}
        className={iconButton}
      >
        <Boxes className="h-[18px] w-[18px]" />
      </button>
      <button
        type="button"
        aria-label="Ungroup"
        title="Ungroup (Ctrl+Shift+G)"
        disabled={!props.canUngroup}
        onClick={props.onUngroup}
        className={iconButton}
      >
        <Ungroup className="h-[18px] w-[18px]" />
      </button>
      <button
        type="button"
        aria-label="Delete"
        title="Delete (Del)"
        disabled={props.selectionCount === 0}
        onClick={props.onDelete}
        className={iconButton}
      >
        <Trash2 className="h-[18px] w-[18px]" />
      </button>

      <span className="mx-1 h-6 w-px bg-border" />

      <button
        type="button"
        aria-label="Undo"
        title="Undo (Ctrl+Z)"
        disabled={!props.canUndo}
        onClick={props.onUndo}
        className={iconButton}
      >
        <Undo2 className="h-[18px] w-[18px]" />
      </button>
      <button
        type="button"
        aria-label="Redo"
        title="Redo (Ctrl+Shift+Z)"
        disabled={!props.canRedo}
        onClick={props.onRedo}
        className={iconButton}
      >
        <Redo2 className="h-[18px] w-[18px]" />
      </button>
    </div>
  );
}
