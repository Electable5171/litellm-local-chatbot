/** A failure the user can understand: a stable code plus a readable message. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly retryAfterS?: number

  constructor(code: string, message: string, status = 0, retryAfterS?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryAfterS = retryAfterS
  }
}

/** Turn a non-2xx response into an ApiError, reading the backend's {"error": {...}} body. */
export async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json()
    const error = (body as { error?: { code?: string; message?: string; retry_after_s?: number } })
      ?.error
    if (error?.code) {
      return new ApiError(error.code, error.message ?? error.code, response.status, error.retry_after_s)
    }
    if (Array.isArray((body as { detail?: unknown })?.detail)) {
      return new ApiError('invalid_request', 'The request was not valid.', response.status)
    }
  } catch {
    // not JSON: fall through to the generic message
  }
  return new ApiError('http_error', `The server answered ${response.status}.`, response.status)
}

/** Describe anything thrown while talking to the backend. */
export function describeError(error: unknown): { code: string; message: string; retryAfterS?: number } {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, retryAfterS: error.retryAfterS }
  }
  return { code: 'network_error', message: 'Cannot reach the app. Is it still running?' }
}
