import { Component } from '@angular/core';

/**
 * Medications List Component — stub placeholder.
 * Populated by US-025 medications feature implementation.
 *
 * Design ref: US-047 TASK-001 — feature module scaffolding.
 */
@Component({
  selector: 'app-medications-list',
  standalone: true,
  template: `
    <section aria-label="Medications list">
      <h1>Medications</h1>
      <p>Medications list feature loads here (US-025).</p>
    </section>
  `,
  styles: [`
    section {
      padding: 1rem;
    }
  `],
})
export class MedicationsListComponent {}
