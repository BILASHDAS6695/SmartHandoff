import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';

/**
 * ToastService — system-wide notification service using Angular Material snackbars.
 *
 * Provides methods for success, error, warning, and info notifications.
 * Automatically dismisses after default duration (3 seconds).
 *
 * Usage:
 *   constructor(private readonly toast = inject(ToastService)) {}
 *
 *   onSaveSuccess() {
 *     this.toast.success('Patient updated successfully');
 *   }
 *
 *   onSaveError(error: string) {
 *     this.toast.error(error);
 *   }
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly snackBar = inject(MatSnackBar);

  private readonly defaultConfig: MatSnackBarConfig = {
    duration: 3000,
    horizontalPosition: 'end',
    verticalPosition: 'bottom',
  };

  /**
   * Display a success notification.
   * @param message The message to display
   * @param config Optional snackbar configuration
   */
  success(message: string, config?: MatSnackBarConfig): void {
    this.snackBar.open(message, 'Close', {
      ...this.defaultConfig,
      ...config,
      panelClass: ['toast-success'],
    });
  }

  /**
   * Display an error notification.
   * @param message The error message to display
   * @param config Optional snackbar configuration
   */
  error(message: string, config?: MatSnackBarConfig): void {
    this.snackBar.open(message, 'Close', {
      ...this.defaultConfig,
      duration: 5000, // Error messages stay longer
      ...config,
      panelClass: ['toast-error'],
    });
  }

  /**
   * Display a warning notification.
   * @param message The warning message to display
   * @param config Optional snackbar configuration
   */
  warn(message: string, config?: MatSnackBarConfig): void {
    this.snackBar.open(message, 'Close', {
      ...this.defaultConfig,
      ...config,
      panelClass: ['toast-warning'],
    });
  }

  /**
   * Display an info notification.
   * @param message The info message to display
   * @param config Optional snackbar configuration
   */
  info(message: string, config?: MatSnackBarConfig): void {
    this.snackBar.open(message, 'Close', {
      ...this.defaultConfig,
      ...config,
      panelClass: ['toast-info'],
    });
  }
}
