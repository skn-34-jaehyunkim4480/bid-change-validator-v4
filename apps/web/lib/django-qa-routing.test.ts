import { test } from 'node:test';
import assert from 'node:assert/strict';
import { copilotChatPath, type QaRoutingInput } from './django-qa-routing.ts';

const documentRequest: QaRoutingInput = {
  general: false, documentProcessing: true, semanticProcessing: false,
  responseVersion: 'legacy', intent: 'DOCUMENT_QA', hasAction: false,
};

test('only explicitly enabled document processing is routed through Django', () => {
  assert.equal(copilotChatPath(documentRequest, true), '/api/v1/django-qa/chat');
  assert.equal(copilotChatPath(documentRequest, false), '/api/v1/copilot/chat');
  assert.equal(copilotChatPath({ ...documentRequest, documentProcessing: false }, true), '/api/v1/copilot/chat');
  // The current Copilot panel enables both document and semantic consent together.
  assert.equal(copilotChatPath({ ...documentRequest, semanticProcessing: true, responseVersion: '3.1' }, true), '/api/v1/django-qa/chat');
});

test('general, guided and action requests never enter Django', () => {
  for (const override of [
    { general: true }, { hasAction: true }, { intent: 'ACTION_REQUEST' },
  ]) {
    const result = copilotChatPath({ ...documentRequest, ...override }, true);
    assert.notEqual(result, '/api/v1/django-qa/chat');
  }
  assert.equal(copilotChatPath({ ...documentRequest, general: true }, true), '/api/v1/copilot/general-chat');
});