import { TestBed } from '@angular/core/testing';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';
import { ToastService } from './toast.service';

describe('ToastService', () => {
  let service: ToastService;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  beforeEach(() => {
    const snackBarMock = jasmine.createSpyObj('MatSnackBar', ['open']);

    TestBed.configureTestingModule({
      providers: [ToastService, { provide: MatSnackBar, useValue: snackBarMock }],
    });

    service = TestBed.inject(ToastService);
    snackBarSpy = TestBed.inject(MatSnackBar) as jasmine.SpyObj<MatSnackBar>;
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call snackBar.open with success message', () => {
    service.success('Test success message');
    expect(snackBarSpy.open).toHaveBeenCalledWith(
      'Test success message',
      'Close',
      jasmine.objectContaining({
        panelClass: ['toast-success'],
      }),
    );
  });

  it('should call snackBar.open with error message', () => {
    service.error('Test error message');
    expect(snackBarSpy.open).toHaveBeenCalledWith(
      'Test error message',
      'Close',
      jasmine.objectContaining({
        duration: 5000, // Error messages stay longer
        panelClass: ['toast-error'],
      }),
    );
  });

  it('should call snackBar.open with warning message', () => {
    service.warn('Test warning message');
    expect(snackBarSpy.open).toHaveBeenCalledWith(
      'Test warning message',
      'Close',
      jasmine.objectContaining({
        panelClass: ['toast-warning'],
      }),
    );
  });

  it('should call snackBar.open with info message', () => {
    service.info('Test info message');
    expect(snackBarSpy.open).toHaveBeenCalledWith(
      'Test info message',
      'Close',
      jasmine.objectContaining({
        panelClass: ['toast-info'],
      }),
    );
  });

  it('should accept custom snackbar configuration', () => {
    const customConfig: MatSnackBarConfig = { duration: 10000 };
    service.success('Test', customConfig);
    expect(snackBarSpy.open).toHaveBeenCalledWith(
      'Test',
      'Close',
      jasmine.objectContaining({
        duration: 10000,
      }),
    );
  });
});
