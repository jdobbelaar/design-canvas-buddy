import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Toolbar } from "./Toolbar";

const baseProps = {
  tool: "select" as const,
  onToolChange: () => {},
  selectionCount: 0,
  canGroup: false,
  canUngroup: false,
  onGroup: () => {},
  onUngroup: () => {},
  onDelete: () => {},
  onUndo: () => {},
  onRedo: () => {},
  canUndo: false,
  canRedo: false,
};

describe("Toolbar", () => {
  it("exposes every spec'd shape and drawing tool", () => {
    render(<Toolbar {...baseProps} />);
    for (const label of [
      "Select",
      "Pen",
      "Text",
      "Connector",
      "Service",
      "Database",
      "Queue",
      "External service",
      "Load balancer",
      "Decision",
      "Junction",
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it("marks the active tool and reports tool changes", () => {
    const onToolChange = vi.fn();
    render(<Toolbar {...baseProps} tool="pen" onToolChange={onToolChange} />);
    expect(screen.getByLabelText("Pen").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByLabelText("Database"));
    expect(onToolChange).toHaveBeenCalledWith("database");
  });

  it("disables group, delete, undo and redo until they are available", () => {
    const { rerender } = render(<Toolbar {...baseProps} />);
    expect((screen.getByLabelText("Group") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Delete") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Undo") as HTMLButtonElement).disabled).toBe(true);

    rerender(<Toolbar {...baseProps} canGroup selectionCount={2} canUndo canRedo canUngroup />);
    expect((screen.getByLabelText("Group") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText("Ungroup") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText("Redo") as HTMLButtonElement).disabled).toBe(false);
  });
});
