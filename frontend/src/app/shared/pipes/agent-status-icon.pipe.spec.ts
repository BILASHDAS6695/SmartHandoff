import { AgentStatusIconPipe } from './agent-status-icon.pipe';

describe('AgentStatusIconPipe', () => {
  const pipe = new AgentStatusIconPipe();

  it('maps COMPLETED to check_circle', () => expect(pipe.transform('COMPLETED')).toBe('check_circle'));
  it('maps IN_PROGRESS to sync', () => expect(pipe.transform('IN_PROGRESS')).toBe('sync'));
  it('maps PENDING to schedule', () => expect(pipe.transform('PENDING')).toBe('schedule'));
  it('maps FAILED to cancel', () => expect(pipe.transform('FAILED')).toBe('cancel'));
  it('returns help_outline for unknown status', () => expect(pipe.transform('UNKNOWN')).toBe('help_outline'));
});
