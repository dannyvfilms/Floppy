import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeCalendarStatuses, toggleCalendarStatus } from '../../../frontend/ui/calendarFilterState.js';

const available = { movie: ['completed', 'planning'], book: ['completed', 'reading'] };

test('legacy per-media selections become one permissive shared status selection', () => {
  assert.deepEqual(normalizeCalendarStatuses(available, { movie: ['planning'], book: ['completed'] }), {
    movie: ['completed', 'planning'], book: ['completed'],
  });
  assert.deepEqual(normalizeCalendarStatuses(available, {}), available);
});

test('toggling a status updates every applicable media type', () => {
  const withoutCompleted = toggleCalendarStatus(available, available, 'completed');
  assert.deepEqual(withoutCompleted, { movie: ['planning'], book: ['reading'] });
  assert.deepEqual(toggleCalendarStatus(available, withoutCompleted, 'completed'), {
    movie: ['planning', 'completed'], book: ['reading', 'completed'],
  });
  assert.deepEqual(available, { movie: ['completed', 'planning'], book: ['completed', 'reading'] });
});
