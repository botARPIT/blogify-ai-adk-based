import { request } from './base';

export interface AuthUser {
  id: number;
  email: string;
  display_name: string | null;
}

export interface AuthMeResponse {
  authenticated: boolean;
  user: AuthUser | null;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export async function login(payload: LoginPayload): Promise<AuthMeResponse> {
  return request<AuthMeResponse>('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/api/v1/auth/logout', {
    method: 'POST',
  });
}

export async function getMe(): Promise<AuthMeResponse> {
  return request<AuthMeResponse>('/api/v1/auth/me');
}
