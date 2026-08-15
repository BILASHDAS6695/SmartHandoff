/**
 * In-app notification model.
 *
 * Represents a single notification shown in the header bell dropdown (UXR-021).
 * Notifications can originate from SignalR events (task completions, alerts,
 * ADT events) or be pushed by client-side workflows.
 */
export interface AppNotification {
  /** Unique notification identifier. */
  id: string;

  /** Short headline shown in the notification row. */
  title: string;

  /** Optional longer description. */
  message?: string;

  /**
   * Visual tone mapped to a colour and icon.
   *   - info:    blue  (task assigned, general updates)
   *   - warning: amber (medication conflict, SLA warning)
   *   - error:   red   (critical alert, failed task)
   *   - success: green (task completed, message received)
   */
  tone: 'info' | 'warning' | 'error' | 'success';

  /** Whether the user has already seen / clicked the notification. */
  read: boolean;

  /** ISO-8601 timestamp when the notification was created. */
  timestamp: string;

  /** Optional deep-link route (e.g. '/patients/smith'). */
  route?: string;

  /** Optional query params for the route. */
  queryParams?: Record<string, string>;

  /**
   * Optional deduplication key. When set, add() will skip creating a new
   * notification if a notification with the same key already exists.
   */
  key?: string;
}
