import { ComponentFixture, TestBed, signal } from '@angular/core/testing';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';

import { HeaderComponent } from './header.component';
import { ThemeService } from '@core/theme/theme.service';
import { AuthService } from '@core/auth/auth.service';
import { NotificationService } from '@core/notifications/notification.service';
import { AppNotification } from '@core/models';

describe('HeaderComponent', () => {
  let fixture: ComponentFixture<HeaderComponent>;
  let component: HeaderComponent;
  let notificationServiceMock: {
    notifications: ReturnType<typeof signal<AppNotification[]>>;
    unreadCount: ReturnType<typeof signal<number>>;
    markAsRead: jasmine.Spy;
    dismiss: jasmine.Spy;
    markAllAsRead: jasmine.Spy;
  };
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    const themeServiceSpy = jasmine.createSpyObj('ThemeService', ['toggleDarkMode'], {
      isDarkMode: () => false,
    });
    const authServiceSpy = jasmine.createSpyObj('AuthService', ['logout'], {
      currentUser: () => ({ email: 'nancy@example.com', role: 'nurse' }),
    });
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    notificationServiceMock = {
      notifications: signal<AppNotification[]>([
        {
          id: 'n1',
          title: 'New discharge task assigned',
          tone: 'info',
          read: false,
          timestamp: new Date().toISOString(),
          route: '/patients',
        },
      ]),
      unreadCount: signal(1),
      markAsRead: jasmine.createSpy('markAsRead'),
      dismiss: jasmine.createSpy('dismiss'),
      markAllAsRead: jasmine.createSpy('markAllAsRead'),
    };

    await TestBed.configureTestingModule({
      imports: [HeaderComponent, BrowserAnimationsModule],
      providers: [
        { provide: ThemeService, useValue: themeServiceSpy },
        { provide: AuthService, useValue: authServiceSpy },
        { provide: NotificationService, useValue: notificationServiceMock },
        { provide: Router, useValue: routerSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display unread notification count badge', () => {
    const badge = fixture.nativeElement.querySelector('.notification-badge');
    expect(badge).toBeTruthy();
    expect(badge.textContent.trim()).toBe('1');
  });

  it('should toggle notification panel open and closed', () => {
    component.toggleNotificationPanel();
    expect(component.isNotificationPanelOpen()).toBeTrue();
    component.toggleNotificationPanel();
    expect(component.isNotificationPanelOpen()).toBeFalse();
    expect(notificationServiceMock.markAllAsRead).not.toHaveBeenCalled();
  });

  it('should close notification panel', () => {
    component.isNotificationPanelOpen.set(true);
    component.closeNotificationPanel();
    expect(component.isNotificationPanelOpen()).toBeFalse();
  });

  it('should navigate when a notification is clicked', () => {
    const notification = notificationServiceMock.notifications()[0];
    component.onNotificationClick(notification);
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/patients'], { queryParams: undefined });
    expect(component.isNotificationPanelOpen()).toBeFalse();
  });

  it('should delegate dismiss to notification service', () => {
    component.onDismiss('n1');
    expect(notificationServiceMock.dismiss).toHaveBeenCalledWith('n1');
  });

  it('should delegate mark all as read to notification service', () => {
    component.onMarkAllAsRead();
    expect(notificationServiceMock.markAllAsRead).toHaveBeenCalled();
  });
});
