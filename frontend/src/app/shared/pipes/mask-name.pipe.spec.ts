import { MaskNamePipe } from './mask-name.pipe';

describe('MaskNamePipe', () => {
  let pipe: MaskNamePipe;

  beforeEach(() => {
    pipe = new MaskNamePipe();
  });

  it('masks two-word name to initials', () => {
    expect(pipe.transform('John Doe')).toBe('J.D.');
  });

  it('masks three-word name', () => {
    expect(pipe.transform('Mary Jane Watson')).toBe('M.J.W.');
  });

  it('handles single name', () => {
    expect(pipe.transform('Madonna')).toBe('M.');
  });

  it('returns dash for null', () => {
    expect(pipe.transform(null)).toBe('—');
  });

  it('returns dash for empty string', () => {
    expect(pipe.transform('')).toBe('—');
  });

  it('trims excess whitespace', () => {
    expect(pipe.transform('  John  Doe  ')).toBe('J.D.');
  });

  it('uppercases initials from lowercase input', () => {
    expect(pipe.transform('jean-luc picard')).toBe('J.P.');
  });
});
