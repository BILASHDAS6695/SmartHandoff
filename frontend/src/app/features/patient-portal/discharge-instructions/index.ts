/**
 * Barrel export file for discharge-instructions feature module.
 *
 * Re-exports all public components, services, directives, and types
 * so that consumers import from '@features/patient-portal/discharge-instructions'
 * rather than individual files.
 *
 * Design refs:
 *   design.md §4.1 — Angular 17 barrel exports for tree-shaking
 */

export * from './discharge-instructions.component';
export * from './discharge-instructions.types';
export * from './language-switcher.service';
export * from './warning-section.directive';
