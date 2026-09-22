export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly endpoint?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  retries?: number;
}

function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export async function requestJson<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 4000, retries = 0, ...init } = options;
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(endpoint, {
        cache: "no-store",
        credentials: "same-origin",
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...init.headers,
        },
      });
      if (!response.ok) {
        throw new ApiError(`HTTP ${response.status}`, response.status, endpoint);
      }
      const text = await response.text();
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new ApiError("Ugyldigt JSON-svar", response.status, endpoint);
      }
    } catch (error) {
      lastError = error;
      if (attempt < retries) await delay(180 * (attempt + 1));
    } finally {
      window.clearTimeout(timer);
    }
  }

  if (lastError instanceof ApiError) throw lastError;
  if (lastError instanceof DOMException && lastError.name === "AbortError") {
    throw new ApiError("Timeout", undefined, endpoint);
  }
  throw new ApiError(lastError instanceof Error ? lastError.message : "Ukendt netværksfejl", undefined, endpoint);
}

export function postJson<T>(endpoint: string, body: unknown, csrf?: string): Promise<T> {
  return requestJson<T>(endpoint, {
    method: "POST",
    timeoutMs: 5000,
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: JSON.stringify(body),
  });
}
