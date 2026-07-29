/**
 * RelativeTimePipe — converts an ISO-8601 timestamp to a human-readable relative string.
 * Examples: "just now", "30 seconds ago", "2 minutes ago"
 *
 * US-048 TASK-003
 */
import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'relativeTime',
  standalone: true,
  pure: false,
})
export class RelativeTimePipe implements PipeTransform {
  transform(isoTimestamp: string | null | undefined): string {
    if (!isoTimestamp) return '';

    try {
      const diffMs = Date.now() - new Date(isoTimestamp).getTime();
      const diffSec = Math.floor(diffMs / 1000);

      if (diffSec < 5) return 'just now';
      if (diffSec < 60) return `${diffSec} seconds ago`;

      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60)
        return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;

      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24)
        return `${diffHr} hour${diffHr !== 1 ? 's' : ''} ago`;

      const diffDays = Math.floor(diffHr / 24);
      return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
    } catch (error) {
      console.error('Error parsing timestamp for relativeTime pipe:', error);
      return 'unknown';
    }
  }
}
