import assert from 'node:assert/strict';
import test from 'node:test';
import { splitAnswerBlocks, summarizeSourceLocations } from './copilot-view-model.ts';

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

void test('free chat answers are split into paragraphs and bullet lists', () => {
  const answer = '제출 서류는 다음과 같습니다.\n- 입찰참가신청서\n* 법인 서류: 등기부등본, 인감증명서\n\n세부 양식은 공고 원문을 확인하세요.';
  assert.deepEqual(splitAnswerBlocks(answer), [
    { kind: 'text', text: '제출 서류는 다음과 같습니다.' },
    { kind: 'list', items: ['입찰참가신청서', '법인 서류: 등기부등본, 인감증명서'] },
    { kind: 'text', text: '세부 양식은 공고 원문을 확인하세요.' },
  ]);
  assert.deepEqual(splitAnswerBlocks('입찰 마감은 10월 6일 오후 2시입니다.'), [{ kind: 'text', text: '입찰 마감은 10월 6일 오후 2시입니다.' }]);
  // 날짜 범위나 음수처럼 줄 앞이 아닌 곳의 '-' 는 목록이 아니다.
  assert.deepEqual(splitAnswerBlocks('기간은 10-12월입니다.'), [{ kind: 'text', text: '기간은 10-12월입니다.' }]);
});

void test('a blank line separates paragraphs so the summary heading stands alone', () => {
  const answer = ['서류는 열네 가지입니다.', '마감은 14:00입니다.', '', '요약', '- 서류: 구비서류 준비', '- 기한: 10월 6일 14:00'].join('\n');
  assert.deepEqual(splitAnswerBlocks(answer), [
    { kind: 'text', text: '서류는 열네 가지입니다.\n마감은 14:00입니다.' },
    { kind: 'text', text: '요약' },
    { kind: 'list', items: ['서류: 구비서류 준비', '기한: 10월 6일 14:00'] },
  ]);
});
