import { Pipe, PipeTransform } from '@angular/core';

/**
 * Transforms a full patient name to initials (e.g., "John Doe" → "J.D.").
 * Complies with PHI privacy requirements (US-050 AC4).
 */
@Pipe({ name: 'maskName', standalone: true })
export class MaskNamePipe implements PipeTransform {
  transform(fullName: string | null): string {
    if (!fullName) return '—';
    return fullName
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .map(part => `${part.charAt(0).toUpperCase()}.`)
      .join('');
  }
}
