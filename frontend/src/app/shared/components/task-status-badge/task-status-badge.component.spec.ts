/**
 * Unit tests for TaskStatusBadgeComponent
 * US-048 TASK-004
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TaskStatusBadgeComponent } from './task-status-badge.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

describe('TaskStatusBadgeComponent', () => {
  let component: TaskStatusBadgeComponent;
  let fixture: ComponentFixture<TaskStatusBadgeComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TaskStatusBadgeComponent, BrowserAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(TaskStatusBadgeComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('PENDING status', () => {
    beforeEach(() => {
      component.status = 'PENDING';
      fixture.detectChanges();
    });

    it('should render badge with pending class', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--pending')).toBeTrue();
    });

    it('should display PENDING text', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.textContent).toContain('PENDING');
    });

    it('should not have spinning animation', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--spinning')).toBeFalse();
    });

    it('should have correct ARIA label', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('aria-label')).toContain('PENDING');
    });
  });

  describe('IN_PROGRESS status', () => {
    beforeEach(() => {
      component.status = 'IN_PROGRESS';
      fixture.detectChanges();
    });

    it('should render badge with in-progress class', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--in-progress')).toBeTrue();
    });

    it('should display IN_PROGRESS text', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.textContent).toContain('IN_PROGRESS');
    });

    it('should have spinning animation applied', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--spinning')).toBeTrue();
    });

    it('should have correct ARIA label', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('aria-label')).toContain('IN_PROGRESS');
    });
  });

  describe('COMPLETED status', () => {
    beforeEach(() => {
      component.status = 'COMPLETED';
      fixture.detectChanges();
    });

    it('should render badge with completed class', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--completed')).toBeTrue();
    });

    it('should display COMPLETED text', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.textContent).toContain('COMPLETED');
    });

    it('should not have spinning animation', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--spinning')).toBeFalse();
    });

    it('should have correct ARIA label', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('aria-label')).toContain('COMPLETED');
    });

    it('should render success icon', () => {
      const icon = fixture.nativeElement.querySelector('.status-badge__icon');
      expect(icon?.classList.contains('status-badge__icon--success')).toBeTrue();
    });
  });

  describe('FAILED status', () => {
    beforeEach(() => {
      component.status = 'FAILED';
      fixture.detectChanges();
    });

    it('should render badge with failed class', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--failed')).toBeTrue();
    });

    it('should display FAILED text', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.textContent).toContain('FAILED');
    });

    it('should not have spinning animation', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--spinning')).toBeFalse();
    });

    it('should have correct ARIA label', () => {
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('aria-label')).toContain('FAILED');
    });

    it('should render error icon', () => {
      const icon = fixture.nativeElement.querySelector('.status-badge__icon');
      expect(icon?.classList.contains('status-badge__icon--error')).toBeTrue();
    });
  });

  describe('Status transitions', () => {
    it('should update CSS class when status changes from PENDING to IN_PROGRESS', () => {
      component.status = 'PENDING';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--pending')).toBeTrue();

      component.status = 'IN_PROGRESS';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--in-progress')).toBeTrue();
    });

    it('should update animation when transitioning to IN_PROGRESS', () => {
      component.status = 'PENDING';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--spinning')).toBeFalse();

      component.status = 'IN_PROGRESS';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--spinning')).toBeTrue();
    });

    it('should stop animation when transitioning from IN_PROGRESS to COMPLETED', () => {
      component.status = 'IN_PROGRESS';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--spinning')).toBeTrue();

      component.status = 'COMPLETED';
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-badge')?.classList.contains('status-badge--spinning')).toBeFalse();
    });
  });

  describe('Accessibility', () => {
    it('should have role="status" for screen readers', () => {
      component.status = 'COMPLETED';
      fixture.detectChanges();
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('role')).toBe('status');
    });

    it('should have aria-live="polite" for dynamic updates', () => {
      component.status = 'IN_PROGRESS';
      fixture.detectChanges();
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.getAttribute('aria-live')).toBe('polite');
    });

    it('should provide descriptive label for all states', () => {
      const states = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'];
      states.forEach((state) => {
        component.status = state as any;
        fixture.detectChanges();
        const badge = fixture.nativeElement.querySelector('.status-badge');
        expect(badge?.getAttribute('aria-label')).toBeTruthy();
        expect(badge?.getAttribute('aria-label')).toContain(state);
      });
    });

    it('should render icon with aria-hidden for visual-only elements', () => {
      component.status = 'COMPLETED';
      fixture.detectChanges();
      const icon = fixture.nativeElement.querySelector('.status-badge__icon');
      expect(icon?.getAttribute('aria-hidden')).toBe('true');
    });
  });

  describe('CSS class binding', () => {
    it('should bind ngClass with correct status class', () => {
      component.status = 'PENDING';
      fixture.detectChanges();
      let badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--pending')).toBeTrue();

      component.status = 'COMPLETED';
      fixture.detectChanges();
      badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge?.classList.contains('status-badge--completed')).toBeTrue();
    });

    it('should conditionally apply spinning class only for IN_PROGRESS', () => {
      const states = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'];
      states.forEach((state) => {
        component.status = state as any;
        fixture.detectChanges();
        const badge = fixture.nativeElement.querySelector('.status-badge');
        if (state === 'IN_PROGRESS') {
          expect(badge?.classList.contains('status-badge--spinning')).toBeTrue();
        } else {
          expect(badge?.classList.contains('status-badge--spinning')).toBeFalse();
        }
      });
    });
  });

  describe('Template structure', () => {
    it('should render badge container with correct structure', () => {
      component.status = 'COMPLETED';
      fixture.detectChanges();
      const badge = fixture.nativeElement.querySelector('.status-badge');
      expect(badge).toBeTruthy();
      expect(badge?.querySelector('.status-badge__content')).toBeTruthy();
    });

    it('should render text content in badge', () => {
      component.status = 'PENDING';
      fixture.detectChanges();
      const content = fixture.nativeElement.querySelector('.status-badge__content');
      expect(content?.textContent).toBeTruthy();
    });

    it('should render icon only for terminal states', () => {
      component.status = 'PENDING';
      fixture.detectChanges();
      let icon = fixture.nativeElement.querySelector('.status-badge__icon');
      expect(icon).toBeFalsy();

      component.status = 'COMPLETED';
      fixture.detectChanges();
      icon = fixture.nativeElement.querySelector('.status-badge__icon');
      expect(icon).toBeTruthy();
    });
  });

  describe('Component inputs', () => {
    it('should accept and render all valid status values', () => {
      const validStatuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'];
      validStatuses.forEach((status) => {
        component.status = status as any;
        fixture.detectChanges();
        const badge = fixture.nativeElement.querySelector('.status-badge');
        expect(badge).toBeTruthy();
        expect(badge?.textContent).toContain(status);
      });
    });
  });
});
