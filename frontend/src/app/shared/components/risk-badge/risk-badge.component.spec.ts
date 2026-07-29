import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RiskBadgeComponent } from './risk-badge.component';
import { RiskTier } from '../../models';

describe('RiskBadgeComponent', () => {
  let fixture: ComponentFixture<RiskBadgeComponent>;
  let component: RiskBadgeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RiskBadgeComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(RiskBadgeComponent);
    component = fixture.componentInstance;
  });

  it('should render HIGH badge with correct CSS class and aria-label', () => {
    component.tier = RiskTier.HIGH;
    fixture.detectChanges();
    const span: HTMLElement = fixture.nativeElement.querySelector('.risk-badge');
    expect(span.classList).toContain('risk-badge--high');
    expect(span.getAttribute('aria-label')).toBe('High risk');
  });

  it('should render MEDIUM badge with correct CSS class', () => {
    component.tier = RiskTier.MEDIUM;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--medium')).toBeTruthy();
  });

  it('should render LOW badge with correct CSS class', () => {
    component.tier = RiskTier.LOW;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--low')).toBeTruthy();
  });

  it('should default to UNSCORED badge for unknown tier', () => {
    component.tier = 'UNKNOWN_VALUE';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--unscored')).toBeTruthy();
    expect(component.ariaLabel).toBe('Risk not scored');
  });
});
