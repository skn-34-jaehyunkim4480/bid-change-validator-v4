/** Optional Django proxy applies ONLY to consented, read-only document QA (legacy or 3.1).
 * All qualification, action and general Copilot calls stay on FastAPI.
 */
export type QaRoutingInput = {
  general: boolean;
  documentProcessing: boolean;
  semanticProcessing: boolean;
  responseVersion?: 'legacy' | '3.1';
  intent?: string | null;
  hasAction: boolean;
};

export function copilotChatPath(input: QaRoutingInput, djangoEnabled: boolean): string {
  if (input.general) return '/api/v1/copilot/general-chat';
  if (djangoEnabled && input.documentProcessing && !input.hasAction &&
      (input.responseVersion === 'legacy' || input.responseVersion === '3.1') &&
      (input.intent === 'DOCUMENT_QA' || input.intent == null)) {
    return '/api/v1/django-qa/chat';
  }
  return '/api/v1/copilot/chat';
}