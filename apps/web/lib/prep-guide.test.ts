import assert from 'node:assert/strict';
import test from 'node:test';

import { daysLeft, evaluationTotalPoints, kst, materialCounts, type PrepGuide } from './prep-guide-view.ts';

void test('profile facts do not prove possession of supporting documents', () => {
  const guide = {
    profile_facts: [{ id: 'C1', kind: '업종', text: '여행업' }],
    evaluation_items: [
      { materials: [{ text: '실적 증명', company_facts: ['C1'] }, { text: '방법론 자료', company_facts: [] }] },
      { materials: [{ text: '인력 증빙', company_facts: ['invalid-reference'] }] },
    ],
  } as unknown as PrepGuide;
  assert.deepEqual(materialCounts(guide), { total: 3, profileLinked: 1 });
  assert.deepEqual(materialCounts({ ...guide, profile_facts: [] }), { total: 3, profileLinked: 0 });
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


void test('J22 score totals use 90 + 10, not 145 from nested criteria', () => {
  const rows = [
    { name: '기술능력평가', points: 90, kind: '기술' },
    { name: '어학연수 프로그램', points: 15, kind: '기술' },
    { name: '교육·문화체험 프로그램', points: 10, kind: '기술' },
    { name: '경영상태', points: 6, kind: '기술' },
    { name: '인력 보유상태', points: 6, kind: '기술' },
    { name: '사업수행 실적', points: 6, kind: '기술' },
    { name: '신인도', points: 2, kind: '기술' },
    { name: '가격평가', points: 10, kind: '가격' },
    { name: '홈스테이 및 생활관리', points: null, kind: '기타' },
  ] as unknown as PrepGuide['evaluation_items'];
  assert.equal(evaluationTotalPoints(rows), 100);
});

void test('unknown or conflicting scoring does not show a false total', () => {
  const rows = [
    { name: '어학연수 프로그램', points: 15, kind: '기술' },
    { name: '기타 요소', points: null, kind: '기타' },
  ] as unknown as PrepGuide['evaluation_items'];
  assert.equal(evaluationTotalPoints(rows), null);
  const conflicting = [
    { name: '기술능력평가', points: 90, kind: '기술' },
    { name: '기술평가', points: 85, kind: '기술' },
  ] as unknown as PrepGuide['evaluation_items'];
  assert.equal(evaluationTotalPoints(conflicting), null);
});
