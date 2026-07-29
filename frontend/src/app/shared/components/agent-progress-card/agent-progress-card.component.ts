import {
  Component, Input, ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AgentTask, AgentStatus, AGENT_DISPLAY_NAMES } from '../../models/agent-task.model';
import { AgentStatusIconPipe } from '../../pipes/agent-status-icon.pipe';

/**
 * Reusable card displaying per-agent progress for an encounter.
 * Shows 5 agent rows with status icon, label, and SLA breach indicator.
 *
 * Usage: <app-agent-progress-card [tasks]="encounter.agentTasks" />
 */
@Component({
  selector: 'app-agent-progress-card',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatTooltipModule, AgentStatusIconPipe],
  templateUrl: './agent-progress-card.component.html',
  styleUrls: ['./agent-progress-card.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentProgressCardComponent {
  @Input({ required: true }) tasks!: AgentTask[];

  readonly agentDisplayNames = AGENT_DISPLAY_NAMES;

  /** Returns CSS class for icon colour based on status */
  statusClass(status: AgentStatus | string): string {
    const map: Record<string, string> = {
      COMPLETED: 'agent-progress__icon--completed',
      IN_PROGRESS: 'agent-progress__icon--in-progress',
      PENDING: 'agent-progress__icon--pending',
      FAILED: 'agent-progress__icon--failed',
    };
    return map[status] ?? '';
  }

  trackByAgent(index: number, task: AgentTask): string {
    return task.agentType;
  }
}
