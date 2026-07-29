/**
 * Unit tests for PwaInstallPromptService (US-054 TASK-004).
 *
 * Covers:
 *   - canInstall signal becomes true when BeforeInstallPromptEvent fires
 *   - canInstall resets to false after appinstalled event
 *   - prompt() method calls the deferred prompt
 *   - Event listeners cleaned up in ngOnDestroy
 */
import { TestBed } from '@angular/core/testing';
import { PwaInstallPromptService } from './pwa-install-prompt.service';

describe('PwaInstallPromptService', () => {
  let service: PwaInstallPromptService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [PwaInstallPromptService],
    });
    service = TestBed.inject(PwaInstallPromptService);
  });

  afterEach(() => {
    service.ngOnDestroy();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should initialize canInstall to false', () => {
    expect(service.canInstall()).toBe(false);
  });

  it('should set canInstall to true when beforeinstallprompt fires', () => {
    const event = new Event('beforeinstallprompt');
    // Mock the event interface
    (event as any).preventDefault = jest.fn();
    window.dispatchEvent(event);
    expect(service.canInstall()).toBe(true);
  });

  it('should reset canInstall to false when appinstalled fires', () => {
    service.canInstall.set(true);
    const event = new Event('appinstalled');
    window.dispatchEvent(event);
    expect(service.canInstall()).toBe(false);
  });

  it('should handle prompt() call gracefully', async () => {
    // Create a mock BeforeInstallPromptEvent
    const mockPromptEvent = new Event('beforeinstallprompt');
    (mockPromptEvent as any).prompt = jest.fn().mockResolvedValue(undefined);
    (mockPromptEvent as any).userChoice = Promise.resolve({ outcome: 'accepted' });
    window.dispatchEvent(mockPromptEvent);

    // prompt() should not throw
    await expect(service.prompt()).resolves.toBeUndefined();
  });

  it('should remove event listeners on ngOnDestroy', () => {
    const removeEventListenerSpy = jest.spyOn(window, 'removeEventListener');
    service.ngOnDestroy();
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'beforeinstallprompt',
      expect.any(Function),
    );
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'appinstalled',
      expect.any(Function),
    );
    removeEventListenerSpy.mockRestore();
  });
});
