export interface ApiErrorShape {
  success?: boolean;
  error_code?: string;
  message?: string;
  request_id?: string;
}

export class ApiError extends Error {
  status: number;
  errorCode: string;
  requestId?: string;

  constructor({
    message,
    status,
    errorCode,
    requestId,
  }: {
    message: string;
    status: number;
    errorCode: string;
    requestId?: string;
  }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.requestId = requestId;
  }
}

export async function parseJsonOrText<T>(res: Response): Promise<T> {
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return (await res.json()) as T;
  }
  throw new Error(await res.text());
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isMutating = Boolean(init?.method && init.method !== 'GET' && init.method !== 'HEAD');
  const headers = new Headers(init?.headers || {});

  if (isMutating && !headers.has('X-Requested-With')) {
    headers.set('X-Requested-With', 'XMLHttpRequest');
  }

  const res = await fetch(path, {
    credentials: 'include',
    ...init,
    headers,
  });

  if (!res.ok) {
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        const payload = (await res.json()) as ApiErrorShape;
        throw new ApiError({
          message: payload.message || `Request failed: ${res.status}`,
          status: res.status,
          errorCode: payload.error_code || 'UNKNOWN_ERROR',
          requestId: payload.request_id,
        });
      } catch (error) {
        if (error instanceof ApiError) {
          throw error;
        }
      }
    }

    const body = (await res.text()).trim();
    throw new ApiError({
      message: body || `Request failed: ${res.status}`,
      status: res.status,
      errorCode: 'UNKNOWN_ERROR',
    });
  }
  return parseJsonOrText<T>(res);
}
