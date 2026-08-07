import { ComponentFixture, TestBed, signal } from '@angular/core/testing';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { HeaderComponent } from './header.component';
import { ThemeService } from '@core/theme/theme.service';
import { AuthService } from '@core/auth/auth.service';
import { NotificationService } from '@core/notifications/notification.service';
import { axe } from '@core/testing/axe-setup';

describe('HeaderComponent Accessibility (axe)', () => {
  let component: HeaderComponent;
  let fixture: ComponentFixture<HeaderComponent>;

  beforeEach(async () => {
    const themeServiceSpy = jasmine.createSpyObj('ThemeService', ['toggleDarkMode', 'setDarkMode'], {
      isDarkMode: () => false,
    });
    const authServiceSpy = jasmine.createSpyObj('AuthService', ['logout'], {
      currentUser: () => null,
    });
    const notificationServiceMock = {
      notifications: signal([]),
      unreadCount: signal(0),
    };

    await TestBed.configureTestingModule({
      imports: [HeaderComponent, BrowserAnimationsModule],
      providers: [
        { provide: ThemeService, useValue: themeServiceSpy },
        { provide: AuthService, useValue: authServiceSpy },
        { provide: NotificationService, useValue: notificationServiceMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should not have axe violations in header', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });
});
