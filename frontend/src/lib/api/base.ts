export interface ApiErrorShape {
  success?: boolean;
  error_code?: string;
  message?: string;
  request_id?: string;
  detail?: string | { error_code?: string; message?: string; request_id?: string };
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

// In production (Vercel) this is the absolute EC2 API URL, e.g.
//   https://api.blogifyai.arpitdev.site
// In development it is empty so that the Vite proxy handles /api/* locally.
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isMutating = Boolean(init?.method && init.method !== 'GET' && init.method !== 'HEAD');
  const headers = new Headers(init?.headers || {});

  if (isMutating && !headers.has('X-Requested-With')) {
    headers.set('X-Requested-With', 'XMLHttpRequest');
  }

  if (isMutating && !headers.has('Idempotency-Key')) {
    headers.set('Idempotency-Key', crypto.randomUUID());
  }

  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    credentials: 'include',
    ...init,
    headers,
  });

  if (!res.ok) {
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        const payload = (await res.json()) as ApiErrorShape;
        const detail = typeof payload.detail === 'string' ? undefined : payload.detail;
        throw new ApiError({
          message: payload.message || detail?.message || (typeof payload.detail === 'string' ? payload.detail : undefined) || `Request failed: ${res.status}`,
          status: res.status,
          errorCode: payload.error_code || detail?.error_code || 'UNKNOWN_ERROR',
          requestId: payload.request_id || detail?.request_id,
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

export async function requestFile(path: string): Promise<{ blob: Blob; filename: string | null }> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
  if (!res.ok) {
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        const payload = (await res.json()) as ApiErrorShape;
        const detail = typeof payload.detail === 'string' ? undefined : payload.detail;
        throw new ApiError({
          message: payload.message || detail?.message || (typeof payload.detail === 'string' ? payload.detail : undefined) || `Request failed: ${res.status}`,
          status: res.status,
          errorCode: payload.error_code || detail?.error_code || 'UNKNOWN_ERROR',
          requestId: payload.request_id || detail?.request_id,
        });
      } catch (error) {
        if (error instanceof ApiError) throw error;
      }
    }
    throw new ApiError({
      message: (await res.text()).trim() || `Request failed: ${res.status}`,
      status: res.status,
      errorCode: 'UNKNOWN_ERROR',
    });
  }

  const disposition = res.headers.get('content-disposition') || '';
  const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const regularFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const filename = encodedFilename
    ? decodeURIComponent(encodedFilename)
    : regularFilename || null;
  return { blob: await res.blob(), filename };
}
