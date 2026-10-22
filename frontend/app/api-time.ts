/** Legacy API timestamps without an offset were stored in UTC, including SQLite reads. */
export function parseApiTimestamp(value: string): Date {
  const timestamp = value.trim();
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(timestamp);
  return new Date(naive ? `${timestamp.replace(" ", "T")}Z` : timestamp);
}
