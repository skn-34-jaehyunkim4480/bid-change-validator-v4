import type { ActionProposal, CopilotChatResponse, CopilotSource, OverallStatus } from './copilot-api';

export function getCopilotStatusLabel(status: OverallStatus): string {
  return { core_met: '핵심 요건 충족', core_unmet: '핵심 요건 미충족', needs_review: '확인 필요' }[status];
}

export function getCopilotActionLabel(action: ActionProposal): string {
  return action.title;
}

export function getSourceLabel(source: CopilotSource): string {
  return source.source_origin === 'PRODUCT_EVIDENCE' ? '공고 원문 근거' : '문서 검색 결과';
}

/**
 * 문서 발췌 하나가 걸친 위치 목록을 한 줄로 줄인다. 발췌는 블록 수십 개로 이뤄질 수 있어, 위치를 그대로 나열하면
 * "section 1 · paragraph 4, section 1 · paragraph 5, …" 가 수십 번 이어진다.
 *   ["section 1 · paragraph 4", …, "section 1 · paragraph 32"] → "섹션 1 · 문단 4–32"
 * 형식을 모르는 위치는 겹치는 것만 지우고, 많으면 앞의 셋만 보여 준다.
 */
export function summarizeSourceLocations(locations: string[]): string {
  const bySection = new Map<number, number[]>();
  const others: string[] = [];
  for (const location of locations) {
    const match = /^section (\d+) · paragraph (\d+)$/.exec(location.trim());
    if (match) bySection.set(Number(match[1]), [...(bySection.get(Number(match[1])) ?? []), Number(match[2])]);
    else if (location.trim() && !others.includes(location.trim())) others.push(location.trim());
  }
  const parts = [...bySection.entries()].sort(([a], [b]) => a - b).map(([section, paragraphs]) => {
    const sorted = [...new Set(paragraphs)].sort((a, b) => a - b);
    const ranges: string[] = [];
    for (let start = 0; start < sorted.length;) {
      let end = start;
      while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end += 1;
      ranges.push(end > start ? `${sorted[start]}–${sorted[end]}` : `${sorted[start]}`);
      start = end + 1;
    }
    return `섹션 ${section} · 문단 ${ranges.join(', ')}`;
  });
  const shown = others.slice(0, 3).join(', ') + (others.length > 3 ? ` 외 ${others.length - 3}곳` : '');
  return [...parts, shown].filter(Boolean).join(' / ');
}

export function getSourceLocationLabel(source: CopilotSource): string {
  const product = source.source_origin === 'PRODUCT_EVIDENCE' ? source.evidence.location : null;
  const clause = product ? product.clause_label : source.source_origin === 'DOCUMENT_RAG' ? source.clause_label : null;
  const locations = source.source_origin === 'DOCUMENT_RAG' ? source.source_locations.filter(Boolean) : [];
  const page = product ? product.page : source.source_origin === 'DOCUMENT_RAG' ? source.page : null;
  const parts = [
    page != null ? `p.${page}` : '',
    product?.section_index != null ? `섹션 ${product.section_index}` : '',
    product?.paragraph_start != null ? `문단 ${product.paragraph_start}–${product.paragraph_end ?? product.paragraph_start}` : '',
    product?.block_start != null ? `블록 ${product.block_start}–${product.block_end ?? product.block_start}` : '',
    product?.source_line_start != null ? `줄 ${product.source_line_start}–${product.source_line_end ?? product.source_line_start}` : '',
  ].filter(Boolean);
  const location = summarizeSourceLocations(locations) || product?.display || parts.join(' · ');
  return [clause ? `조항 ${clause}` : '', location].filter(Boolean).join(' · ') || '위치 정보 없음';
}

export function getCopilotWarningItems(response: CopilotChatResponse): string[] {
  return [...response.warnings];
}
