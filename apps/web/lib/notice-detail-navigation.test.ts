import { test } from 'node:test';
import assert from 'node:assert/strict';
import { caseDestinationHref, hasNoticeChangeVersion } from './notice-detail-navigation.ts';

void test('review link always uses a case ID', () => {
  assert.equal(caseDestinationHref('0aa365e2-e8b0-486f-83b0-cda45444ddab'), '/qualification?caseId=0aa365e2-e8b0-486f-83b0-cda45444ddab');
  assert.equal(caseDestinationHref('id&other=1', 'changes'), '/changes?caseId=id%26other%3D1');
});
void test('single notice version does not claim changed notice', () => {
  assert.equal(hasNoticeChangeVersion([{ version_number: 1 }]), false);
  assert.equal(hasNoticeChangeVersion([{ version_number: 1 }, { version_number: 1 }]), false);
  assert.equal(hasNoticeChangeVersion([{ version_number: 2 }, { version_number: 1 }]), true);
});
