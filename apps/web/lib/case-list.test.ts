import assert from 'node:assert/strict';
import test from 'node:test';

import { filterCases, sortCases, type CaseListItem } from './case-list.ts';

const item = (id: string, patch: Partial<CaseListItem>): CaseListItem => ({
  id, bid_notice_no: `R26BK0${id}`, notice_title: `공고 ${id}`, title: `${id} 참가자격 검토`,
  bid_closed_at: null, expired: false, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', ...patch,
});

const cases = [
  item('1', { notice_title: '전산장비 및 소프트웨어 통합유지관리 용역', bid_closed_at: '2026-11-03T01:00:00Z', created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-12T00:00:00Z' }),
  item('2', { notice_title: '기상 증착 시뮬레이션 소프트웨어', bid_closed_at: '2026-10-20T01:00:00Z', created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-13T00:00:00Z' }),
  item('3', { notice_title: '12G 산탄총 구매', bid_closed_at: '2026-09-15T05:00:00Z', expired: true, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-10T00:00:00Z' }),
  item('4', { notice_title: '학교 AI 비상벨 시스템 도입', bid_closed_at: '2026-10-06T08:00:00Z', expired: true, created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-07T00:00:00Z' }),
  item('5', { notice_title: '마감을 모르는 공고', bid_closed_at: null, created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-11T00:00:00Z' }),
];
const ids = (list: CaseListItem[]) => list.map((row) => row.id).join('');

void test('search matches every word, ignoring spaces and case', () => {
  assert.equal(ids(filterCases(cases, '소프트웨어')), '12');
  assert.equal(ids(filterCases(cases, '통합 유지관리')), '1');       // 제목의 띄어쓰기와 달라도 찾는다
  assert.equal(ids(filterCases(cases, 'ai 비상벨')), '4');
  assert.equal(ids(filterCases(cases, 'r26bk03')), '3');             // 공고번호
  assert.equal(ids(filterCases(cases, '소프트웨어 산탄총')), '');      // 낱말은 모두 들어 있어야 한다
  assert.equal(filterCases(cases, '   '), cases);                    // 빈 검색어는 그대로
});

void test('sorts by recent, oldest and title without changing the input', () => {
  assert.equal(ids(sortCases(cases, 'recent')), '21534');
  assert.equal(ids(sortCases(cases, 'oldest')), '32451');
  assert.equal(ids(sortCases(cases, 'title')), '32514');
  assert.equal(ids(cases), '12345');
});

void test('nearest deadline puts open notices first, unknown next, expired last', () => {
  // 마감 전(가까운 것부터) → 마감 모름 → 만료(최근에 끝난 것부터)
  assert.equal(ids(sortCases(cases, 'deadline')), '21543');
});
