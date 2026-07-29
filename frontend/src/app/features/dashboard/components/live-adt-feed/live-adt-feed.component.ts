/**
 * Live ADT Events panel displayed on the `/dashboard` route.
 * Renders the last 20 ADT events in real time using CDK virtual scrolling.
 * Connection status is shown in the panel header via SignalRService.connectionState signal.
 *
 * US-048 TASK-003
 */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScrollingModule } from '@angular/cdk/scrolling';
import { MatBadgeModule } from '@angular/material/badge';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AdtEventHandlerService } from '@core/signalr/handlers/adt-event-handler.service';
import { SignalRService } from '@core/signalr/signalr.service';
import { RelativeTimePipe } from '@shared/pipes/relative-time.pipe';
import { AdtEventPayload } from '@core/signalr/signalr.models';

/** Row height in pixels for CDK virtual scroll — must match SCSS `.event-row` height. */
const ROW_HEIGHT_PX = 56;

/**
 * Live ADT Events panel displayed on the `/dashboard` route.
 * Renders the last 20 ADT events in real time using CDK virtual scrolling.
 * Connection status is shown in the panel header via SignalRService.connectionState signal.
 *
 * Uses OnPush change detection — updates trigger automatically via signal reads in template.
 */
@Component({
  selector: 'app-live-adt-feed',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ScrollingModule,
    MatBadgeModule,
    MatIconModule,
    MatTooltipModule,
    RelativeTimePipe,
  ],
  templateUrl: './live-adt-feed.component.html',
  styleUrl: './live-adt-feed.component.scss',
})
export class LiveAdtFeedComponent {
  protected readonly adtHandler = inject(AdtEventHandlerService);
  protected readonly signalR = inject(SignalRService);

  /** Exposed for template binding */
  protected readonly adtEvents = this.adtHandler.adtEvents;
  protected readonly connectionState = this.signalR.connectionState;

  protected readonly rowHeight = ROW_HEIGHT_PX;

  /** Maps HL7 event type to a display label */
  protected eventTypeLabel(eventType: string): string {
    const labels: Record<string, string> = {
      A01: 'Admit',
      A02: 'Transfer',
      A03: 'Discharge',
      A04: 'Register',
      A08: 'Update',
      A11: 'Cancel Admit',
      A13: 'Cancel Discharge',
    };
    return labels[eventType] ?? eventType;
  }

  /** Maps HL7 event type to a CSS modifier class for badge colouring */
  protected eventTypeCssClass(eventType: string): string {
    const classes: Record<string, string> = {
      A01: 'event-badge--admit',
      A03: 'event-badge--discharge',
      A02: 'event-badge--transfer',
    };
    return classes[eventType] ?? 'event-badge--default';
  }

  /** TrackBy for virtual scroll — prevents full list re-render on append */
  protected trackByEncounterId(
    _index: number,
    event: AdtEventPayload,
  ): string {
    return `${event.encounterId}-${event.timestamp}`;
  }
}
