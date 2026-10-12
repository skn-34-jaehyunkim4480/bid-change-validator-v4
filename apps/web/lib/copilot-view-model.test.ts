import assert from 'node:assert/strict';
import test from 'node:test';
import { summarizeSourceLocations } from './copilot-view-model.ts';

void test('a passage spanning many paragraphs is shown as ranges, not one entry per paragraph', () => {
  const locations = [4, 5, 6, 7, 8, 9, 10, 12, 13, 14].map((n) => `section 1 · paragraph ${n}`);
  assert.equal(summarizeSourceLocations(locations), '섹션 1 · 문단 4–10, 12–14');
  assert.equal(summarizeSourceLocations(['section 2 · paragraph 3', 'section 1 · paragraph 7', 'section 1 · paragraph 7']),
    '섹션 1 · 문단 7 / 섹션 2 · 문단 3');
});

void test('locations in another format are kept, deduplicated and capped', () => {
  assert.equal(summarizeSourceLocations(['p.2', 'p.3', 'p.2']), 'p.2, p.3');
  assert.equal(summarizeSourceLocations(['p.1', 'p.2', 'p.3', 'p.4', 'p.5']), 'p.1, p.2, p.3 외 2곳');
  assert.equal(summarizeSourceLocations([]), '');
});
