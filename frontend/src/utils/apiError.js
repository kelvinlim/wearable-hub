/**
 * Format a FastAPI `detail` payload for the researcher toast.
 *
 * String details (400/403/404 copy) pass through. Structured pull errors expose
 * `message`, `guidance`, and `error_id` only — never unknown fields that might
 * one day carry a traceback or token.
 */
export function formatApiError(detail, fallback = "Request failed") {
  if (typeof detail === "string" && detail.trim()) return detail.trim();

  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && typeof first === "object" && typeof first.msg === "string" && first.msg.trim()) {
      return first.msg.trim();
    }
    return fallback;
  }

  if (detail && typeof detail === "object") {
    const parts = [];
    if (typeof detail.message === "string" && detail.message.trim()) {
      parts.push(detail.message.trim());
    }
    if (typeof detail.guidance === "string" && detail.guidance.trim()) {
      const g = detail.guidance.trim();
      if (!parts.some((p) => p.includes(g))) parts.push(g);
    }
    if (typeof detail.error_id === "string" && detail.error_id.trim()) {
      parts.push(`Ref ${detail.error_id.trim()}`);
    }
    if (parts.length) return parts.join(" ");
  }

  return fallback || "Request failed";
}
