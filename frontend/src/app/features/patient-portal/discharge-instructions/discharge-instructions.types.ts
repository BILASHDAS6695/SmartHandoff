/**
 * TypeScript interfaces modelling Document.translations JSONB structure (US-053).
 *
 * Defines strongly-typed contracts for structured discharge instruction content
 * and the language switcher. All downstream components and directives import
 * from this file to ensure a single source of truth (DRY).
 *
 * Design refs:
 *   US-053 Technical Notes — Document.translations JSONB shape
 *   US-053 DoD             — sections: medications, activity, diet, follow_up, warning_signs
 *   design.md §4.1         — strict TypeScript mode; Angular 17
 */

/** Supported language codes backed by Document.translations keys. */
export type SupportedLanguage = 'en' | 'es' | 'fr' | 'zh' | 'ar' | 'pt';

/** A single medication item in the instructions. */
export interface MedicationItem {
  /** Drug name (brand + generic where applicable). */
  name: string;
  /** Dosage instructions in the target language. */
  dosage: string;
  /** Frequency (e.g. "twice daily"). */
  frequency: string;
  /** Special instructions (e.g. "take with food"). */
  notes?: string;
}

/** A single follow-up appointment entry. */
export interface FollowUpItem {
  /** Provider or clinic name. */
  provider: string;
  /** Recommended timeframe (e.g. "within 7 days"). */
  timeframe: string;
  /** Contact phone number or booking URL. */
  contact?: string;
}

/**
 * Structured content for a single language variant.
 *
 * Maps directly to one language key inside `Document.translations` JSONB.
 */
export interface InstructionContent {
  /** List of medication items the patient must take at home. */
  medications: MedicationItem[];
  /** Activity restrictions or allowances in plain language. */
  activity: string;
  /** Dietary guidelines in plain language. */
  diet: string;
  /** Follow-up appointment recommendations. */
  follow_up: FollowUpItem[];
  /**
   * Warning signs that require immediate medical attention.
   * Displayed with high-visibility styling (red border, amber background).
   */
  warning_signs: string[];
}

/**
 * Full translations map as stored in Document.translations JSONB.
 *
 * At minimum the 'en' key must be present; other languages are optional.
 */
export type InstructionTranslations = {
  en: InstructionContent;
} & Partial<Record<SupportedLanguage, InstructionContent>>;

/**
 * Section metadata for template rendering.
 * Each instruction section has an icon code and display label.
 */
export interface InstructionSectionMetadata {
  key: 'medications' | 'activity' | 'diet' | 'follow_up' | 'warning_signs';
  icon: string;
  label: string;
}

/**
 * Mapping of section keys to their icons and labels.
 * Used to drive *ngFor in the template.
 */
export const INSTRUCTION_SECTIONS: InstructionSectionMetadata[] = [
  { key: 'medications', icon: 'medication', label: 'Your Medications' },
  { key: 'activity', icon: 'directions_walk', label: 'Activity' },
  { key: 'diet', icon: 'restaurant', label: 'Diet' },
  { key: 'follow_up', icon: 'calendar_today', label: 'Follow-up Appointments' },
  { key: 'warning_signs', icon: 'warning', label: 'Warning Signs' },
];

/**
 * Mapping of language codes to display labels for MatButtonToggle.
 */
export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  es: 'Español',
  fr: 'Français',
  zh: '中文',
  ar: 'العربية',
  pt: 'Português',
};
