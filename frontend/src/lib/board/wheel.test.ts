import { describe, expect, it } from "vitest";
import { wheelDeltaToPixels, wheelZoomFactor } from "./wheel";

// WheelEvent.deltaMode values.
const PIXEL = 0;
const LINE = 1;
const PAGE = 2;

describe("wheelDeltaToPixels", () => {
  it("converts Firefox-style line and page deltas to pixels", () => {
    expect(wheelDeltaToPixels(100, PIXEL)).toBe(100);
    expect(wheelDeltaToPixels(3, LINE)).toBe(48);
    expect(wheelDeltaToPixels(1, PAGE)).toBe(800);
  });
});

describe("wheelZoomFactor", () => {
  it("zooms in when scrolling up and out when scrolling down", () => {
    expect(wheelZoomFactor(-40, PIXEL)).toBeGreaterThan(1);
    expect(wheelZoomFactor(40, PIXEL)).toBeLessThan(1);
    expect(wheelZoomFactor(0, PIXEL)).toBe(1);
  });

  it("is symmetric, so zooming in then out returns to the same zoom", () => {
    expect(wheelZoomFactor(-30, PIXEL) * wheelZoomFactor(30, PIXEL)).toBeCloseTo(1, 10);
  });

  it("moves gently for a trackpad pinch (a stream of tiny deltas)", () => {
    // A fixed ~8% step per event would rocket through the zoom range.
    expect(Math.abs(wheelZoomFactor(-2, PIXEL) - 1)).toBeLessThan(0.01);
  });

  it("caps a single event, however fast the wheel spins", () => {
    expect(wheelZoomFactor(-100000, PIXEL)).toBe(wheelZoomFactor(-50, PIXEL));
    expect(wheelZoomFactor(-100000, PIXEL)).toBeLessThan(1.12);
  });

  it("treats a Firefox notch (3 lines) like a Chrome notch (100px)", () => {
    expect(wheelZoomFactor(-3, LINE)).toBeCloseTo(wheelZoomFactor(-100, PIXEL), 1);
  });
});
