import assert from 'node:assert/strict';
import test from 'node:test';

import { signupProblems } from './signup-rules.ts';

void test('a good username and password pass', () => {
  assert.deepEqual(signupProblems('  New.User_1 ', 'good-pass-42', 'good-pass-42'), []);
});

void test('each rule is reported in plain words', () => {
  assert.match(signupProblems('ab', 'good-pass-42', 'good-pass-42')[0], /4~30자/);
  assert.match(signupProblems('한글아이디', 'good-pass-42', 'good-pass-42')[0], /영문 소문자/);
  assert.match(signupProblems('-dash', 'good-pass-42', 'good-pass-42')[0], /시작해야/);
  assert.deepEqual(signupProblems('valid-name', 'short', 'short'), ['비밀번호는 8자 이상이어야 합니다.']);
  assert.deepEqual(signupProblems('valid-name', 'Valid-Name', 'Valid-Name'), ['비밀번호는 아이디와 달라야 합니다.']);
  assert.deepEqual(signupProblems('valid-name', 'aaaaaaaaaa', 'aaaaaaaaaa'), ['비밀번호에 서로 다른 글자를 4개 이상 넣어 주세요.']);
  assert.deepEqual(signupProblems('valid-name', 'good-pass-42', 'good-pass-43'), ['비밀번호 확인이 비밀번호와 다릅니다.']);
});
