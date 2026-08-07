import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { AdminUser } from '../admin-panel.component';

export interface UserDialogData {
  mode: 'add' | 'edit';
  user?: AdminUser;
}

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

  readonly roles = ['Nurse', 'Physician', 'Pharmacist', 'BedManager', 'Admin'];
  readonly units = ['4-West', '3-North', 'ICU', 'Emergency', 'Surgery'];
  readonly statuses: Array<'Active' | 'Inactive'> = ['Active', 'Inactive'];

  readonly user: AdminUser = this.data.mode === 'edit' && this.data.user
    ? { ...this.data.user }
    : { name: '', email: '', role: 'Nurse', unit: '4-West', status: 'Active', lastLogin: 'Never' };

  get title(): string {
    return this.data.mode === 'edit' ? 'Edit User' : 'Add User';
  }

  onCancel(): void {
    this.dialogRef.close();
  }

  onSave(): void {
    const saved: AdminUser = {
      ...this.user,
      lastLogin: this.user.lastLogin ?? 'Never',
    };
    this.dialogRef.close(saved);
  }
}
