/**
 * Unit tests for WarningSectionDirective (US-053 TASK-004).
 *
 * Covers: CSS class binding, role attribute, aria-live attribute.
 */
import { Component, DebugElement } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { WarningSectionDirective } from './warning-section.directive';

@Component({
  template: `
    <section appWarningSection>
      Warning signs
    </section>
  `,
  standalone: true,
  imports: [WarningSectionDirective],
})
class TestComponent {}

describe('WarningSectionDirective', () => {
  let fixture: ComponentFixture<TestComponent>;
  let section: DebugElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WarningSectionDirective, TestComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(TestComponent);
    fixture.detectChanges();
    section = fixture.debugElement.query(By.directive(WarningSectionDirective));
  });

  it('should apply warning-section CSS class', () => {
    expect(section.nativeElement.classList.contains('warning-section')).toBe(true);
  });

  it('should set role to region', () => {
    expect(section.nativeElement.getAttribute('role')).toBe('region');
  });

  it('should set aria-live to polite', () => {
    expect(section.nativeElement.getAttribute('aria-live')).toBe('polite');
  });
});
