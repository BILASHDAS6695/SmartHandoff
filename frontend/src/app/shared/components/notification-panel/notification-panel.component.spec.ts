import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

import { NotificationPanelComponent } from './notification-panel.component';
import { AppNotification } from '@core/models';

describe('NotificationPanelComponent', () => {
  let fixture: ComponentFixture<NotificationPanelComponent>;
  let component: NotificationPanelComponent;

  const mockNotifications: AppNotification[] = [
    {
      id: 'n1',
      title: 'New discharge task assigned',
      message: 'Smith, John',
      tone: 'info',
      read: false,
      timestamp: new Date().toISOString(),
    },
    {
      id: 'n2',
      title: 'Medication conflict',
      tone: 'error',
      read: true,
      timestamp: new Date().toISOString(),
    },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NotificationPanelComponent, BrowserAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(NotificationPanelComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should render notification list when open', () => {
    component.isOpen = true;
    component.notifications = mockNotifications;
    component.unreadCount = 1;
    fixture.detectChanges();

    const items = fixture.nativeElement.querySelectorAll('.notification-item');
    expect(items.length).toBe(2);
  });

  it('should mark notification as read when clicked', () => {
    component.isOpen = true;
    component.notifications = mockNotifications;
    fixture.detectChanges();

    const markSpy = spyOn(component.markAsRead, 'emit');
    const clickSpy = spyOn(component.notificationClick, 'emit');
    const row = fixture.nativeElement.querySelector('.notification-row');
    row.click();

    expect(markSpy).toHaveBeenCalledWith('n1');
    expect(clickSpy).toHaveBeenCalledWith(mockNotifications[0]);
  });

  it('should not re-emit markAsRead for already read notifications', () => {
    component.isOpen = true;
    component.notifications = [mockNotifications[1]];
    fixture.detectChanges();

    const markSpy = spyOn(component.markAsRead, 'emit');
    const row = fixture.nativeElement.querySelector('.notification-row');
    row.click();

    expect(markSpy).not.toHaveBeenCalled();
  });

  it('should emit dismiss when close button clicked', () => {
    component.isOpen = true;
    component.notifications = mockNotifications;
    fixture.detectChanges();

    const spy = spyOn(component.dismiss, 'emit');
    const dismissBtn = fixture.nativeElement.querySelector('.btn-dismiss');
    dismissBtn.click();

    expect(spy).toHaveBeenCalledWith('n1');
  });

  it('should emit markAllAsRead', () => {
    component.isOpen = true;
    component.notifications = mockNotifications;
    component.unreadCount = 1;
    fixture.detectChanges();

    const spy = spyOn(component.markAllAsRead, 'emit');
    const btn = fixture.nativeElement.querySelector('.btn-mark-all');
    btn.click();

    expect(spy).toHaveBeenCalled();
  });

  it('should render empty state when no notifications', () => {
    component.isOpen = true;
    component.notifications = [];
    fixture.detectChanges();

    expect(
      fixture.nativeElement.querySelector('.empty-state'),
    ).toBeTruthy();
  });

  it('should emit closePanel on Escape key', () => {
    component.isOpen = true;
    fixture.detectChanges();

    const spy = spyOn(component.closePanel, 'emit');
    component.onEscape();

    expect(spy).toHaveBeenCalled();
  });

  it('should map tone to correct icon and class', () => {
    expect(component.getToneIcon('info')).toBe('info');
    expect(component.getToneIcon('warning')).toBe('warning');
    expect(component.getToneIcon('error')).toBe('error');
    expect(component.getToneIcon('success')).toBe('check_circle');

    expect(component.getToneClass('success')).toBe('tone-success');
  });
});
