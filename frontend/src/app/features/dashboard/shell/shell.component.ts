import { Component, OnInit, ViewChild, inject, signal, computed, effect } from '@angular/core';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { RouterOutlet } from '@angular/router';

import { SidebarComponent } from './sidebar/sidebar.component';
import { HeaderComponent } from './header/header.component';
import { SignalRService, JoinGroupsRequest } from '@core/signalr';
import { AuthService } from '@core/auth/auth.service';

/**
 * ShellComponent — Persistent authenticated layout wrapper.
 * Contains MatSidenav (sidebar), HeaderComponent, and <router-outlet>.
 * Responsive: sidenav is 'side' mode on desktop, 'over' mode on mobile.
 *
 * Design ref: US-047 DoD — sidebar navigation, header, content area
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [MatSidenavModule, RouterOutlet, SidebarComponent, HeaderComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent implements OnInit {
  @ViewChild('sidenav') sidenav!: MatSidenav;

  private readonly signalR = inject(SignalRService);
  private readonly authService = inject(AuthService);

  /** True when viewport is mobile (≤ 768px). */
  readonly isMobile = signal(false);

  /** Sidenav mode: 'side' for desktop, 'over' for mobile. */
  readonly sidenavMode = computed(() => (this.isMobile() ? 'over' : 'side'));

  /** Sidenav open state: always open on desktop, closed by default on mobile. */
  readonly sidenavOpened = computed(() => !this.isMobile());
  private lastConnectedRole: string | null = null;

  // Reconnect with the new role groups when an admin switches role in real time.
  private readonly reconnectEffect = effect(() => {
    const role = this.authService.currentUser()?.role;
    if (role && role !== this.lastConnectedRole) {
      this.lastConnectedRole = role;
      void this._reconnectSignalR();
    }
  });

  ngOnInit(): void {
    // Check initial screen size
    this.updateMobileState();

    // Listen for window resize events
    window.addEventListener('resize', () => this.updateMobileState());

    // Start the real-time hub for every authenticated shell route (bed manager,
    // dashboard, etc.). The service is idempotent, so dashboard's own init is safe.
    void this._connectSignalR();
  }

  private async _connectSignalR(): Promise<void> {
    const user = this.authService.currentUser();
    if (!user) return;

    const joinRequest: JoinGroupsRequest = {
      units: user.units || [],
      roles: [user.role],
    };

    try {
      await this.signalR.connect(joinRequest);
    } catch (error) {
      console.warn('SignalR real-time hub unavailable; falling back to polling:', error);
    }
  }

  private async _reconnectSignalR(): Promise<void> {
    try {
      await this.signalR.disconnect();
    } catch {
      // Ignore disconnect errors; connect will create a fresh connection.
    }
    await this._connectSignalR();
  }

  private updateMobileState(): void {
    // 768px is the standard tablet breakpoint
    this.isMobile.set(window.innerWidth <= 768);
  }

  onSidebarLinkClicked(): void {
    if (this.isMobile()) {
      this.sidenav.close();
    }
  }
}

