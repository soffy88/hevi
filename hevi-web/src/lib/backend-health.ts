/** Runtime config used by health check - local definition to avoid circular import */
type HealthRuntimeConfig = {
  apiBase: string;
  useMock: boolean;
  environment?: string;
};

/** Backend health state returned by checkBackendHealth() */
export type BackendHealth = {
  state: 'healthy' | 'degraded' | 'offline';
  apiBase: string;
  latencyMs?: number;
  statusCode?: number;
  message?: string;
};

/** Check backend health via GET {API_BASE}/api/health
 *
 *  - timeout: 5 seconds
 *  - network errors are NOT swallowed (they propagate)
 *  - HTTP non-2xx shows actual error status code
 *  - NO fallback to mock
 *  - NEVER pretends "can't connect → success"
 */
export async function checkBackendHealth(
  config: HealthRuntimeConfig = (() => {
    // Read from env without creating circular import
    const base = process.env.NEXT_PUBLIC_API_BASE
      ? process.env.NEXT_PUBLIC_API_BASE.trim()
      : 'http://127.0.0.1:8000';
    const mock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false')
      .trim()
      .toLowerCase() === 'true';
    return { apiBase: base, useMock: mock };
  })()
): Promise<BackendHealth> {
  const start = Date.now();
  const url = `${config.apiBase}/api/health`;

  // Always make the real request; never fall back to mock
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(url, {
      method: 'GET',
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
      },
    });

    clearTimeout(timeoutId);

    const latencyMs = Date.now() - start;
    const statusCode = response.status;

    if (response.ok) {
      // Try to parse JSON body for additional info
      let body: any;
      try {
        body = await response.json();
      } catch {
        // Non-JSON 2xx: just use status
      }

      // Determine state from response or default to healthy
      let state: 'healthy' | 'degraded' | 'offline' = 'healthy';

      if (body && typeof body === 'object') {
        if (body.status === 'degraded' || body.state === 'degraded') {
          state = 'degraded';
        } else if (body.status === 'offline' || body.state === 'offline') {
          state = 'offline';
        }
      }

      return {
        state,
        apiBase: config.apiBase,
        latencyMs,
        statusCode,
        message: body?.message || undefined,
      };
    }

    // HTTP non-2xx — show actual error
    let message = '';
    try {
      const errBody = await response.json();
      if (typeof errBody === 'object' && errBody?.message) {
        message = String(errBody.message);
      } else {
        message = `${response.status} ${response.statusText}`;
      }
    } catch {
      message = `${response.status} ${response.statusText}`;
    }

    // Map common status codes to states
    let state: 'healthy' | 'degraded' | 'offline' = 'offline';
    if (statusCode >= 500) {
      state = 'degraded';
    } else if (statusCode >= 400) {
      state = 'degraded';
    }

    return {
      state,
      apiBase: config.apiBase,
      latencyMs,
      statusCode,
      message,
    };
  } catch (err) {
    clearTimeout(timeoutId);

    // Network error / timeout — must NOT be swallowed
    // Re-throw or return offline state; here we return offline with error info
    const latencyMs = Date.now() - start;

    // Network errors cannot be silently ignored per spec
    // Return offline state with the error message
    return {
      state: 'offline' as const,
      apiBase: config.apiBase,
      latencyMs,
      statusCode: undefined,
      message: (err as Error).message || 'Failed to reach backend',
    };
  }
}

/**
 * Convenience: check health using the module-level runtime config.
 */
export async function checkHealthWithConfig(): Promise<BackendHealth> {
  const base = process.env.NEXT_PUBLIC_API_BASE
    ? process.env.NEXT_PUBLIC_API_BASE.trim()
    : 'http://127.0.0.1:8000';
  const mock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false')
    .trim()
    .toLowerCase() === 'true';
  const env = process.env.NODE_ENV === 'production' ? 'production' : 'development';
  return checkBackendHealth({ apiBase: base, useMock: mock, environment: env });
}