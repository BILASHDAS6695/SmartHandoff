import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';
import { DOCUMENT } from '@angular/common';

import { IdleTimeoutService } from './idle-timeout.service';

/**
 * Unit tests for IdleTimeoutService.
 *
 * Coverage target: ≥80% branch coverage (TR-020).
 *
 * Design refs:
 *   US-059 TASK-006 — unit tests: idle timeout event
 *   BR-013 — 30-minute inactivity limit
 */
describe('IdleTimeoutService', () => {
  let service: IdleTimeoutService;
  let onTimeoutSpy: jasmine.Spy;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<any>>;

  beforeEach(() => {
    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', [
      'afterOpened',
      'afterClosed',
      'close',
    ]);
    dialogRefSpy.afterOpened.and.returnValue(of(null));
    dialogRefSpy.afterClosed.and.returnValue(of(null));

    dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);
    dialogSpy.open.and.returnValue(dialogRefSpy);

    TestBed.configureTestingModule({
      imports: [RouterTestingModule],
      providers: [
        IdleTimeoutService,
        { provide: MatDialog, useValue: dialogSpy },
      ],
    });
    service = TestBed.inject(IdleTimeoutService);
    onTimeoutSpy = jasmine.createSpy('onTimeout');
  });

  afterEach(() => service.stop());

  it('should create', () => {
    expect(service).toBeTruthy();
  });

  it('should call onTimeout callback after 30 minutes of inactivity', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(30 * 60 * 1000);  // 30 minutes
    expect(onTimeoutSpy).toHaveBeenCalledTimes(1);
  }));

  it('should NOT fire timeout when activity occurs before 30 minutes', fakeAsync(() => {
    const doc = TestBed.inject(DOCUMENT);
    service.start(onTimeoutSpy);
    tick(29 * 60 * 1000);  // 29 minutes — almost there

    // Simulate user activity — should reset the timer
    doc.dispatchEvent(new Event('mousemove'));
    tick(29 * 60 * 1000);  // another 29 minutes from the activity (< 30 total from last event)

    expect(onTimeoutSpy).not.toHaveBeenCalled();
  }));

  it('should open SessionExpiredDialogComponent on timeout', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(30 * 60 * 1000);
    expect(dialogSpy.open).toHaveBeenCalledTimes(1);
  }));

  it('stop() should cancel the timer — onTimeout not called after stop', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(15 * 60 * 1000);  // 15 minutes in
    service.stop();
    tick(30 * 60 * 1000);  // let the full interval pass after stop
    expect(onTimeoutSpy).not.toHaveBeenCalled();
  }));

  it('start() called twice should not create duplicate subscriptions', fakeAsync(() => {
    service.start(onTimeoutSpy);
    service.start(onTimeoutSpy);  // second call should clear first
    tick(30 * 60 * 1000);
    // Callback should only fire once — not twice
    expect(onTimeoutSpy).toHaveBeenCalledTimes(1);
  }));

  it('should reset timer on keypress event', fakeAsync(() => {
    const doc = TestBed.inject(DOCUMENT);
    service.start(onTimeoutSpy);
    tick(20 * 60 * 1000);  // 20 minutes

    // Simulate keypress — resets the timer
    doc.dispatchEvent(new Event('keypress'));
    tick(20 * 60 * 1000);  // another 20 min (< 30 from keypress)

    expect(onTimeoutSpy).not.toHaveBeenCalled();

    tick(10 * 60 * 1000 + 1);  // cross the 30-minute mark from last keypress
    expect(onTimeoutSpy).toHaveBeenCalledTimes(1);
  }));

  it('should open dialog with disableClose: true', fakeAsync(() => {
    service.start(onTimeoutSpy);
    tick(30 * 60 * 1000);
    const openCall = dialogSpy.open.calls.mostRecent();
    expect(openCall.args[1]).toEqual(
      jasmine.objectContaining({ disableClose: true })
    );
  }));
});
