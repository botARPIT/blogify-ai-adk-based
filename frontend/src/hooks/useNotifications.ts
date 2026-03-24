import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from '../lib/api/notifications';

const TOAST_COPY: Record<string, { title: string; variant: 'success' | 'warning' | 'error' }> = {
  outline_review_required: { title: 'Outline review needed', variant: 'warning' },
  final_review_required: { title: 'Draft ready for final review', variant: 'warning' },
  blog_completed: { title: 'Blog generation completed', variant: 'success' },
  blog_failed: { title: 'Blog generation failed', variant: 'error' },
};

export function useNotifications(enabled: boolean) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const surfacedIds = useRef<Set<number>>(new Set());

  const refresh = async () => {
    if (!enabled) return;
    const response = await getNotifications({ limit: 25 });
    setItems(response.items);

    for (const item of response.items) {
      if (item.status !== 'unread' || surfacedIds.current.has(item.id)) continue;
      surfacedIds.current.add(item.id);
      const meta = TOAST_COPY[item.type];
      if (!meta) continue;
      if (meta.variant === 'success') {
        toast.success(meta.title, { description: item.message });
      } else if (meta.variant === 'warning') {
        toast.warning(meta.title, { description: item.message });
      } else {
        toast.error(meta.title, { description: item.message });
      }
    }
  };

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      return;
    }
    refresh().catch(() => undefined);
    const interval = setInterval(() => {
      refresh().catch(() => undefined);
    }, 15000);
    return () => clearInterval(interval);
  }, [enabled]);

  const unreadCount = useMemo(
    () => items.filter((item) => item.status === 'unread').length,
    [items],
  );

  const markRead = async (notificationId: number) => {
    await markNotificationRead(notificationId);
    setItems((current) =>
      current.map((item) => (item.id === notificationId ? { ...item, status: 'read' } : item)),
    );
  };

  const markAllRead = async () => {
    await markAllNotificationsRead();
    setItems((current) => current.map((item) => ({ ...item, status: 'read' })));
  };

  return {
    items,
    unreadCount,
    refresh,
    markRead,
    markAllRead,
  };
}
