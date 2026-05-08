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
  return Promise.resolve({ items: [] });
}

export async function markNotificationRead(notificationId: number): Promise<{ ok: boolean; updated: number }> {
  return Promise.resolve({ ok: true, updated: 0 });
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean; updated: number }> {
  return Promise.resolve({ ok: true, updated: 0 });
}