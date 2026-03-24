import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { NotificationItem } from '../../lib/api/notifications';

interface NotificationBellProps {
  items: NotificationItem[];
  unreadCount: number;
  onMarkRead: (id: number) => Promise<void>;
  onMarkAllRead: () => Promise<void>;
}

const NotificationBell: React.FC<NotificationBellProps> = ({
  items,
  unreadCount,
  onMarkRead,
  onMarkAllRead,
}) => {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const hasItems = items.length > 0;
  const unreadLabel = useMemo(() => (unreadCount > 99 ? '99+' : String(unreadCount)), [unreadCount]);

  const handleOpenItem = async (item: NotificationItem) => {
    if (item.status === 'unread') {
      await onMarkRead(item.id);
    }
    setOpen(false);
    if (item.action_url) {
      navigate(item.action_url);
    }
  };

  return (
    <div className="notification-shell">
      <button className="icon-button notification-trigger" onClick={() => setOpen((value) => !value)} type="button">
        <span>Inbox</span>
        {unreadCount > 0 ? <span className="notification-count">{unreadLabel}</span> : null}
      </button>
      {open ? (
        <div className="notification-panel">
          <div className="notification-panel-header">
            <div>
              <span className="eyebrow-label">Workflow Alerts</span>
              <h3 className="card-title" style={{ margin: 0 }}>Notifications</h3>
            </div>
            <button className="text-button" type="button" onClick={() => void onMarkAllRead()}>
              Mark all read
            </button>
          </div>
          <div className="notification-list">
            {!hasItems ? <p className="text-secondary">No notifications yet.</p> : null}
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`notification-item ${item.status === 'unread' ? 'unread' : ''}`}
                onClick={() => void handleOpenItem(item)}
              >
                <div className="notification-item-header">
                  <strong>{item.title}</strong>
                  {item.status === 'unread' ? <span className="status-dot" /> : null}
                </div>
                <p>{item.message}</p>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default NotificationBell;
