/**
 * OfflineBannerComponent — displays an accessibility-compliant offline status
 * banner in the patient portal when network connectivity is lost (US-054).
 *
 * Renders when NetworkStatusService.isOffline() === true.
 * Dismisses automatically when connectivity is restored.
 *
 * Accessibility:
 *   role="status"     — non-intrusive live region
 *   aria-live="polite" — screen reader announces banner without interrupting focus
 *
 * Design refs:
 *   US-054 Scenario 2     — banner text "You're viewing cached instructions"
 *   US-054 DoD            — offline event listener → MatBanner equivalent
 *   web-accessibility-standards — aria-live for dynamic regions
 */
import {
  ChangeDetectionStrategy,
  Component,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { NetworkStatusService } from '../../../core/network/network-status.service';

@Component({
  selector: 'app-offline-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatIconModule],
  templateUrl: './offline-banner.component.html',
  styleUrl: './offline-banner.component.scss',
})
export class OfflineBannerComponent {
  protected readonly networkStatus = inject(NetworkStatusService);
}
