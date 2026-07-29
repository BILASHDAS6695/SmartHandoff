import { Injectable, signal, effect } from '@angular/core';

/**
 * ThemeService — manages light/dark theme toggle for SmartHandoff.
 *
 * Features:
 *   - Persists theme preference to localStorage under key 'sh-theme'
 *   - Applies CSS class to <html> element to activate Material theme
 *   - Default theme: light
 *
 * Usage in component:
 *   export class HeaderComponent {
 *     private readonly theme = inject(ThemeService);
 *     toggleTheme(): void {
 *       this.theme.toggleDarkMode();
 *     }
 *     isDarkMode = this.theme.isDarkMode;
 *   }
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly STORAGE_KEY = 'sh-theme';
  private readonly DARK_CLASS = 'dark-theme';

  /** Reactive signal indicating current dark mode state. */
  readonly isDarkMode = signal<boolean>(false);

  constructor() {
    // Initialize theme from localStorage or system preference
    this.initializeTheme();

    // Apply theme class whenever isDarkMode changes
    effect(() => {
      this.applyTheme(this.isDarkMode());
    });
  }

  /**
   * Toggle between light and dark mode.
   * Updates localStorage and applies the theme.
   */
  toggleDarkMode(): void {
    this.isDarkMode.update((current) => !current);
    localStorage.setItem(this.STORAGE_KEY, this.isDarkMode() ? 'dark' : 'light');
  }

  /**
   * Set dark mode state explicitly.
   * @param darkMode true for dark mode, false for light mode
   */
  setDarkMode(darkMode: boolean): void {
    this.isDarkMode.set(darkMode);
    localStorage.setItem(this.STORAGE_KEY, darkMode ? 'dark' : 'light');
  }

  /**
   * Initialize theme from localStorage or system preference.
   * @private
   */
  private initializeTheme(): void {
    const saved = localStorage.getItem(this.STORAGE_KEY);

    if (saved === 'dark' || saved === 'light') {
      this.isDarkMode.set(saved === 'dark');
    } else {
      // Use system preference if available
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      this.isDarkMode.set(prefersDark);
    }
  }

  /**
   * Apply the theme class to <html> element.
   * @private
   */
  private applyTheme(darkMode: boolean): void {
    const htmlElement = document.documentElement;
    if (darkMode) {
      htmlElement.classList.add(this.DARK_CLASS);
    } else {
      htmlElement.classList.remove(this.DARK_CLASS);
    }
  }
}
