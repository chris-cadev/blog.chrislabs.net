interface UmamiEventData {
  [key: string]: string | number | boolean | null | undefined;
}

interface UmamiTrackOptions {
  beacon?: boolean;
}

const MAX_PENDING = 100;
const FLUSH_RETRY_MS = 500;

let pending: Array<[string, UmamiEventData?]> = [];
let ready = false;
let flushTimer: number | null = null;
let injected = false;

function sendBeacon(event: string, data?: UmamiEventData): void {
  try {
    const body = JSON.stringify({ event, data: data ?? {} });
    navigator.sendBeacon(
      "/api/track",
      new Blob([body], { type: "application/json" })
    );
  } catch {
    /* ignore beacon failures; never break the page */
  }
}

function flushPending(): void {
  const queue = pending;
  pending = [];
  for (const [event, data] of queue) {
    window.umami!.track(event, data);
  }
}

function ensureTrackerReady(): boolean {
  if (ready) return true;
  if (window.umami?.track) {
    ready = true;
    flushPending();
    return true;
  }
  return false;
}

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    if (pending.length > 0 && !ensureTrackerReady()) {
      scheduleFlush();
    }
  }, FLUSH_RETRY_MS);
}

export function trackUmami(
  event: string,
  data?: UmamiEventData,
  options?: UmamiTrackOptions
): void {
  if (options?.beacon !== false) {
    sendBeacon(event, data);
  }
  try {
    if (ensureTrackerReady()) {
      window.umami!.track(event, data);
    } else if (pending.length < MAX_PENDING) {
      pending.push([event, data]);
      scheduleFlush();
    }
  } catch {
    /* ignore tracking failures; never break the page */
  }
}

export function initUmami(): void {
  if (injected) return;
  const body = document.body;
  const scriptUrl = body?.getAttribute("data-umami-script");
  const recorderUrl = body?.getAttribute("data-umami-recorder");
  const websiteId = body?.getAttribute("data-umami-website-id");
  if (!scriptUrl || !websiteId) return;
  injected = true;

  const el = document.createElement("script");
  el.async = true;
  el.defer = true;
  el.src = scriptUrl;
  el.setAttribute("data-website-id", websiteId);
  el.setAttribute("data-do-not-track", "true");
  document.head.appendChild(el);

  if (recorderUrl) {
    const rec = document.createElement("script");
    rec.defer = true;
    rec.src = recorderUrl;
    rec.setAttribute("data-website-id", websiteId);
    rec.setAttribute("data-mask-level", "moderate");
    document.head.appendChild(rec);
  }

  window.trackUmami = trackUmami;
}
