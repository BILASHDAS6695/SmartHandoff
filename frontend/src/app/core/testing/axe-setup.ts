import { axe, toHaveNoViolations } from 'jest-axe';

/**
 * axe-core setup helper for Jest component tests.
 *
 * Makes the `toHaveNoViolations()` matcher available in all test suites.
 * Usage:
 *   const results = await axe(fixture.nativeElement);
 *   expect(results).toHaveNoViolations();
 */
expect.extend(toHaveNoViolations);

export { axe };
