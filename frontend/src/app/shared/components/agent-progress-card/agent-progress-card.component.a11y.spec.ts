import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { AgentProgressCardComponent } from './agent-progress-card.component';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_TASKS = [
  { agentType: 'TRANSITION_COORDINATOR' as const, status: 'COMPLETED' as const, updatedAt: '2026-07-17T09:00:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:30:00Z' },
  { agentType: 'DOCUMENTATION' as const, status: 'IN_PROGRESS' as const, updatedAt: '2026-07-17T09:10:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:40:00Z' },
  { agentType: 'MEDICATION_RECONCILIATION' as const, status: 'PENDING' as const, updatedAt: '2026-07-17T09:05:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:35:00Z' },
  { agentType: 'BED_MANAGEMENT' as const, status: 'FAILED' as const, updatedAt: '2026-07-17T08:55:00Z', slaBreach: true, slaDeadline: '2026-07-17T09:00:00Z' },
  { agentType: 'FOLLOW_UP_CARE' as const, status: 'PENDING' as const, updatedAt: '2026-07-17T09:05:00Z', slaBreach: false, slaDeadline: '2026-07-17T10:00:00Z' },
];

describe('AgentProgressCardComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AgentProgressCardComponent],
      providers: [provideAnimationsAsync()],
    }).compileComponents();
  });

  it('should have no WCAG 2.1 AA violations', async () => {
    const fixture = TestBed.createComponent(AgentProgressCardComponent);
    fixture.componentRef.setInput('tasks', MOCK_TASKS);
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });

  it('should render SLA breach row with red alarm icon for BED_MANAGEMENT', () => {
    const fixture = TestBed.createComponent(AgentProgressCardComponent);
    fixture.componentRef.setInput('tasks', MOCK_TASKS);
    fixture.detectChanges();

    const slaIcons = fixture.nativeElement.querySelectorAll('.agent-progress__sla-icon');
    expect(slaIcons.length).toBe(1);
  });
});
