import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { AdminUser } from '../../services/admin-users-api.service';

export interface UserDialogData {
  mode: 'add' | 'edit';
  user?: AdminUser;
}

/** UI-facing role options (mapped to backend lowercase values). */
const ROLE_OPTIONS: { label: string; value: string }[] = [
  { label: 'Nurse', value: 'nurse' },
  { label: 'Physician', value: 'physician' },
  { label: 'Pharmacist', value: 'pharmacist' },
  { label: 'BedManager', value: 'bed_manager' },
  { label: 'Admin', value: 'admin' },
];

/**
 * UserDialogComponent — Add/Edit user modal matching SCR-011 wireframe.
 */
@Component({
  selector: 'app-user-dialog',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule, MatButtonModule],
  templateUrl: './user-dialog.component.html',
  styleUrl: './user-dialog.component.scss',
})
export class UserDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<UserDialogComponent>);
  readonly data = inject<UserDialogData>(MAT_DIALOG_DATA);

  readonly roles = ROLE_OPTIONS;
  readonly units = ['4-West', '3-North', 'ICU', 'Emergency', 'Surgery'];

  readonly full_name = signal<string>(this.data.user?.full_name ?? '');
  readonly email = signal<string>(this.data.user?.email ?? '');
  readonly role = signal<string>(this.data.user?.role ?? 'nurse');
  readonly unit = signal<string>(this.data.user?.unit ?? '4-West');
  readonly saving = signal<boolean>(false);

  get title(): string {
    return this.data.mode === 'edit' ? 'Edit User' : 'Add User';
  }

  isValid(): boolean {
    return this.full_name().trim().length > 0 && this.email().trim().length > 0;
  }

  onCancel(): void {
    if (this.saving()) return;
    this.dialogRef.close();
  }

  onSave(): void {
    if (!this.isValid() || this.saving()) return;

    this.saving.set(true);
    this.dialogRef.close({
      full_name: this.full_name().trim(),
      email: this.email().trim(),
      role: this.role(),
      unit: this.unit(),
    });
  }
}
