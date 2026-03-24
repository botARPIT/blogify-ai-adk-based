import { request } from './base';

export type NotificationType =
  | 'blog_queued'
  | 'outline_review_required'
  | 'final_review_required'
  | 'blog_completed'
  | 'blog_failed';

export interface NotificationItem {
  id: number;
  type: NotificationType;
  title: string;
  message: string;
  session_id: number | null;
  status: 'read' | 'unread';
  created_at: string;
  action_url: string | null;
}

export interface NotificationListResponse {
  items: NotificationItem[];
}

export async function getNotifications(
  options: { limit?: number; unreadOnly?: boolean } = {},
): Promise<NotificationListResponse> {
  const params = new URLSearchParams();
  if (options.limit) params.set('limit', String(options.limit));
  if (options.unreadOnly) params.set('unread_only', 'true');
  const query = params.toString();
  return request<NotificationListResponse>(`/api/v1/notifications${query ? `?${query}` : ''}`);
}

export async function markNotificationRead(notificationId: number): Promise<{ ok: boolean; updated: number }> {
  return request(`/api/v1/notifications/${notificationId}/read`, {
    method: 'POST',
  });
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean; updated: number }> {
  return request('/api/v1/notifications/read-all', {
    method: 'POST',
  });
}
