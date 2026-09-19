/** Mouse-wheel maths for the canvas, kept pure so it can be unit tested. */

const LINE_PX = 16;
const PAGE_PX = 800;

/**
 * Browsers report a wheel notch in different units: Chrome and Safari send
 * pixels (~100 per notch), but Firefox sends *lines* (~3 per notch). Treating
 * the raw number as pixels makes a Firefox wheel pan look broken (3px a notch).
 */
export function wheelDeltaToPixels(delta: number, deltaMode: number): number {
  if (deltaMode === 1) return delta * LINE_PX;
  if (deltaMode === 2) return delta * PAGE_PX;
  return delta;
}

// One event never changes zoom by more than ~10% (exp(0.002 * 50)), however
// fast the wheel spins.
const MAX_STEP_PX = 50;
const ZOOM_PER_PX = 0.002;

/**
 * Zoom multiplier for one Ctrl/Cmd+wheel event (>1 zooms in). Proportional to
 * the delta rather than a fixed step, because a trackpad pinch arrives as a
 * stream of tiny Ctrl+wheel events: a fixed step per event would be far too
 * fast, while a mouse-wheel notch (large delta) is capped by MAX_STEP_PX.
 */
export function wheelZoomFactor(deltaY: number, deltaMode: number): number {
  const px = wheelDeltaToPixels(deltaY, deltaMode);
  const capped = Math.max(-MAX_STEP_PX, Math.min(MAX_STEP_PX, px));
  return Math.exp(-capped * ZOOM_PER_PX);
}
