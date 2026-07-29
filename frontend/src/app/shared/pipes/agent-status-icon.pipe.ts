import { Pipe, PipeTransform } from '@angular/core';
import { AgentStatus } from '../models/agent-task.model';

/**
 * Converts an AgentStatus value to a Material icon name.
 *
 * Usage: {{ task.status | agentStatusIcon }}
 *
 * COMPLETED  → 'check_circle'
 * IN_PROGRESS → 'sync'
 * PENDING    → 'schedule'
 * FAILED     → 'cancel'
 */
@Pipe({ name: 'agentStatusIcon', standalone: true, pure: true })
export class AgentStatusIconPipe implements PipeTransform {
  private static readonly ICON_MAP: Record<AgentStatus, string> = {
    COMPLETED: 'check_circle',
    IN_PROGRESS: 'sync',
    PENDING: 'schedule',
    FAILED: 'cancel',
  };

  transform(status: AgentStatus | string): string {
    return AgentStatusIconPipe.ICON_MAP[status as AgentStatus] ?? 'help_outline';
  }
}
