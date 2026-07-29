import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  let service: ThemeService;
  let store: { [key: string]: string } = {};

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(ThemeService);

    // Mock localStorage
    store = {};
    const mockLocalStorage = {
      getItem: (key: string) => store[key] || null,
      setItem: (key: string, value: string) => {
        store[key] = value;
      },
      removeItem: (key: string) => {
        delete store[key];
      },
      clear: () => {
        store = {};
      },
    };

    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((key: string) => mockLocalStorage.getItem(key));
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation((key: string, value: string) => {
      mockLocalStorage.setItem(key, value);
    });
  });

  afterEach(() => {
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should initialize with light mode by default', () => {
    expect(service.isDarkMode()).toBe(false);
  });

  it('should toggle dark mode', () => {
    expect(service.isDarkMode()).toBe(false);
    service.toggleDarkMode();
    expect(service.isDarkMode()).toBe(true);
    service.toggleDarkMode();
    expect(service.isDarkMode()).toBe(false);
  });

  it('should persist dark mode to localStorage', () => {
    service.setDarkMode(true);
    expect(localStorage.getItem('sh-theme')).toBe('dark');

    service.setDarkMode(false);
    expect(localStorage.getItem('sh-theme')).toBe('light');
  });

  it('should apply .dark-theme class to <html> element when dark mode is enabled', fakeAsync(() => {
    service.setDarkMode(true);
    tick();
    expect(document.documentElement.classList.contains('dark-theme')).toBe(true);
  }));

  it('should remove .dark-theme class from <html> element when dark mode is disabled', fakeAsync(() => {
    service.setDarkMode(false);
    tick();
    expect(document.documentElement.classList.contains('dark-theme')).toBe(false);
  }));
});

