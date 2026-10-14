import assert from 'node:assert/strict';
import test from 'node:test';

import { daysLeft, kst, materialCounts, type PrepGuide } from './prep-guide-view.ts';

void test('materials linked to a profile fact count as held', () => {
  const guide = {
    evaluation_items: [
      { materials: [{ text: '실적 증명', company_facts: ['C1'] }, { text: '방법론 자료', company_facts: [] }] },
      { materials: [{ text: '인력 증빙', company_facts: [] }] },
      { materials: [] },
    ],
  } as unknown as PrepGuide;
  assert.deepEqual(materialCounts(guide), { total: 3, held: 1, needed: 2 });
});

void test('days left counts whole days and goes negative after the deadline', () => {
  const now = Date.parse('2026-10-14T00:00:00Z');
  assert.equal(daysLeft('2026-10-27T01:00:00Z', now), 13);
  assert.equal(daysLeft('2026-10-14T05:00:00Z', now), 0);
  assert.equal(daysLeft('2026-10-13T23:00:00Z', now), -1);
  assert.equal(daysLeft(null, now), null);
  assert.equal(daysLeft('not a date', now), null);
});

void test('times are written in Korean time', () => {
  assert.equal(kst('2026-10-27T01:00:00Z'), '2026.10.27 10:00');
  assert.equal(kst('2026-12-31T15:30:00Z'), '2027.01.01 00:30');
  assert.equal(kst(null), '-');
});
