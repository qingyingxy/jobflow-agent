export function apiError(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const value = body as { error?: { message?: string }; detail?: unknown };
  if (value.error?.message) return value.error.message;
  if (typeof value.detail === "string") return value.detail;
  if (value.detail && typeof value.detail === "object" && "message" in value.detail
      && typeof value.detail.message === "string") return value.detail.message;
  return fallback;
}
