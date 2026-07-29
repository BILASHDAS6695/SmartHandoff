/**
 * Unit tests for NetworkStatusService (US-054 TASK-003).
 *
 * Covers:
 *   - isOffline signal initialises from navigator.onLine
 *   - isOffline updates to true when offline event fires
 *   - isOffline updates to false when online event fires
 *   - Event listeners cleaned up in ngOnDestroy
 */
import { TestBed } from '@angular/core/testing';
import { NetworkStatusService } from './network-status.service';

describe('NetworkStatusService', () => {
  let service: NetworkStatusService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [NetworkStatusService],
    });
    service = TestBed.inject(NetworkStatusService);
  });

  afterEach(() => {
    service.ngOnDestroy();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should initialize isOffline from navigator.onLine', () => {
    // Verify the signal is set based on current navigator.onLine state
    const expected = !navigator.onLine;
    expect(service.isOffline()).toBe(expected);
  });

  it('should set isOffline to true when offline event fires', () => {
    service.isOffline.set(false); // Start online
    const offlineEvent = new Event('offline');
    window.dispatchEvent(offlineEvent);
    expect(service.isOffline()).toBe(true);
  });

  it('should set isOffline to false when online event fires', () => {
    service.isOffline.set(true); // Start offline
    const onlineEvent = new Event('online');
    window.dispatchEvent(onlineEvent);
    expect(service.isOffline()).toBe(false);
  });

  it('should remove event listeners on ngOnDestroy', () => {
    const removeEventListenerSpy = jest.spyOn(window, 'removeEventListener');
    service.ngOnDestroy();
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'online',
      expect.any(Function),
    );
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'offline',
      expect.any(Function),
    );
    removeEventListenerSpy.mockRestore();
  });
});
