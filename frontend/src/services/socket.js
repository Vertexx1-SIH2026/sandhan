const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE || "ws://localhost:8000";

/**
 * Connects to /ws/v1/graphstream for a given case (or "*" for all cases)
 * and calls onMessage(payload) for every event: ingestion stage-by-stage
 * progress, and the single consolidated "analytics_complete" event.
 * Returns a cleanup function.
 */
export function connectGraphStream(caseId, onMessage, onOpen, onClose) {
  const ws = new WebSocket(`${WS_BASE}/ws/v1/graphstream?case_id=${encodeURIComponent(caseId)}`);

  ws.onopen = () => onOpen && onOpen();
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onclose = () => onClose && onClose();

  return () => {
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  };
}
