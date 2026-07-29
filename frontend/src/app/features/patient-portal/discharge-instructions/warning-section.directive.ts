/**
 * WarningSectionDirective — applies high-visibility styling to warning signs (US-053).
 *
 * Adds the CSS class `warning-section` to the host element, which triggers
 * red border and amber background SCSS rules. Uses host class binding rather
 * than Renderer2 or inline styles to comply with OWASP A05 (CSP headers).
 *
 * Usage:
 *   <section appWarningSection aria-labelledby="section-warning">
 *     ...
 *   </section>
 *
 * Design refs:
 *   US-053 AC Scenario 4 — red border; amber background; visually distinct
 *   US-053 DoD           — appWarningSection directive
 *   WCAG 2.1 AA          — colour supplemented by ⚠ icon and explicit header text
 *   OWASP A05            — host class binding; no inline style (CSP safe)
 */
import { Directive, HostBinding } from '@angular/core';

@Directive({
  selector: '[appWarningSection]',
  standalone: true,
})
export class WarningSectionDirective {
  /**
   * Applies the `warning-section` CSS class unconditionally to the host element.
   * Styling rules are defined in the component SCSS to remain theme-overridable.
   */
  @HostBinding('class.warning-section') readonly isWarning = true;

  /**
   * Sets the ARIA role to `region` so assistive technologies announce the section
   * as a distinct landmark with high importance.
   */
  @HostBinding('attr.role') readonly role = 'region';

  /**
   * Marks the region as live so screen readers re-announce content on language change.
   * 'polite' is used to avoid interrupting ongoing announcements.
   */
  @HostBinding('attr.aria-live') readonly ariaLive = 'polite';
}
