// The wall's layout and pinned cameras, remembered per browser (OMNI-512).
//
// Kept in localStorage, which can be missing or refuse to work (a private window,
// storage blocked by the browser, a full quota): every read and write is wrapped,
// and anything unexpected falls back to the defaults (3x3, nothing pinned). It is a
// convenience for one operator at one browser, not shared, not on the server.

// A pinned camera's place on the wall: its slot counting across pages, from 0 at
// the top left of page 1. Keyed by camera id.
export type Pins = Record<string, number>;

export interface WallSettings {
  layout: number | null;
  pins: Pins;
}

const KEY = "omnisight.wall.v1";
const EMPTY: WallSettings = { layout: null, pins: {} };

export function loadWallSettings(): WallSettings {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<WallSettings>;
    const pins: Pins = {};
    for (const [id, slot] of Object.entries(parsed.pins ?? {})) {
      if (Number.isInteger(slot) && slot >= 0) pins[id] = slot;
    }
    return { layout: typeof parsed.layout === "number" ? parsed.layout : null, pins };
  } catch {
    return EMPTY;
  }
}

export function saveWallSettings(settings: WallSettings): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // Storage refused: the wall still works, it just will not remember.
  }
}

// Pin a camera to a slot. A camera already pinned to that slot gives it up, so two
// cameras never claim the same place.
export function pinTo(pins: Pins, cameraId: number, slot: number): Pins {
  const next: Pins = {};
  for (const [id, taken] of Object.entries(pins)) {
    if (taken !== slot && id !== String(cameraId)) next[id] = taken;
  }
  next[String(cameraId)] = slot;
  return next;
}

export function unpin(pins: Pins, cameraId: number): Pins {
  const next = { ...pins };
  delete next[String(cameraId)];
  return next;
}

// The order the wall shows cameras in: each pinned camera in its slot, the others
// filling the free slots in their usual order (group, then name, as the API sends
// them). A camera added, removed or renamed moves the unpinned ones around the
// pinned ones, never the pinned ones. A pin beyond the end of the list (fewer
// cameras than its slot) puts that camera last instead of leaving holes.
export function arrange<T extends { camera_id: number }>(cameras: T[], pins: Pins): T[] {
  const pinnedAt = new Map<number, T>();
  const unpinned: T[] = [];
  for (const camera of cameras) {
    const slot = pins[String(camera.camera_id)];
    if (slot !== undefined && !pinnedAt.has(slot)) pinnedAt.set(slot, camera);
    else unpinned.push(camera);
  }
  const out: T[] = [];
  const used = new Set<number>();
  for (let slot = 0; out.length < cameras.length; slot += 1) {
    const pinned = pinnedAt.get(slot);
    if (pinned) {
      out.push(pinned);
      used.add(slot);
    } else if (unpinned.length > 0) {
      out.push(unpinned.shift()!);
    } else {
      // Only pins beyond the end remain: append them in slot order.
      const rest = [...pinnedAt.entries()].filter(([s]) => !used.has(s)).sort(([a], [b]) => a - b);
      for (const [s, camera] of rest) {
        out.push(camera);
        used.add(s);
      }
      break;
    }
  }
  return out;
}
