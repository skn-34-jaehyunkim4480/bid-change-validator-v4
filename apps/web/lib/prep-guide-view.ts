/* 입찰 준비 지침서의 자료 모양과, 화면이 쓰는 계산(2026-10-14). 서버를 부르지 않는다. */
export type JudgedCase = {
  case_id: string;
  bid_notice_no: string;
  notice_title: string;
  institution: string | null;
  bid_closed_at: string | null;
  expired: boolean;
  overall_status: string;
  overall_label: string;
  judged_at: string;
};

export type GuideMaterial = { text: string; company_facts: string[] };
export type GuideEvaluationItem = {
  name: string; points: number | null; kind: string; quote: string; focus: string; materials: GuideMaterial[];
};
export type GuideScheduleRow = { label: string; at: string | null; when: string | null; source: string; quote: string | null };
export type GuideQuoted = { text: string; quote: string };
export type GuideStep = { title: string; detail: string; lead_time: '오래 걸림' | '보통' | '바로 가능' };
export type GuideFact = { id: string; kind: string; text: string };

export type PrepGuide = {
  case_id: string;
  notice: { bid_notice_no: string; title: string; institution: string | null };
  generated_at: string;
  schedule: GuideScheduleRow[];
  evaluation_items: GuideEvaluationItem[];
  total_points: number | null;
  submission_documents: GuideQuoted[];
  format_rules: GuideQuoted[];
  steps: GuideStep[];
  profile_facts: GuideFact[];
  warnings: string[];
  documents_read: string[];
};

/** Compute scoring from extracted hierarchy, including old browser-cached guides. */
export function evaluationTotalPoints(items: GuideEvaluationItem[]): number | null {
  if (!items.length) return null;
  const techParents = new Set(['기술능력평가', '기술평가', '기술제안서평가', '기술제안평가']);
  const priceParents = new Set(['가격평가', '입찰가격평가', '가격능력평가']);
  const tech: GuideEvaluationItem[] = [];
  const price: GuideEvaluationItem[] = [];
  const other: GuideEvaluationItem[] = [];
  for (const item of items) {
    const name = item.name.replace(/\s+/g, '');
    if (techParents.has(name) || item.kind === '기술') tech.push(item);
    else if (priceParents.has(name) || item.kind === '가격') price.push(item);
    else other.push(item);
  }
  function categoryPoints(rows: GuideEvaluationItem[], parents: Set<string>): { total: number | null; parent: boolean } {
    if (!rows.length) return { total: 0, parent: false };
    const roots = rows.filter((item) => parents.has(item.name.replace(/\s+/g, '')));
    if (roots.length > 1) return { total: null, parent: false };
    const effective = roots.length ? roots : rows;
    if (effective.some((item) => item.points == null || !Number.isFinite(item.points) || item.points <= 0))
      return { total: null, parent: false };
    return { total: effective.reduce((sum, item) => sum + (item.points ?? 0), 0), parent: roots.length > 0 };
  }
  const technical = categoryPoints(tech, techParents);
  const prices = categoryPoints(price, priceParents);
  if (technical.total == null || prices.total == null) return null;
  if (technical.parent && price.length) return technical.total + prices.total;
  const extras = categoryPoints(other, new Set());
  return extras.total == null ? null : technical.total + prices.total + extras.total;
}

/** 준비 자료가 회사 프로필에 이미 있는 것인지. 연결된 프로필 항목이 있으면 '프로필에 있음' 이다. */
export function materialCounts(guide: PrepGuide) {
  const materials = guide.evaluation_items.flatMap((item) => item.materials);
  const held = materials.filter((material) => material.company_facts.length > 0).length;
  return { total: materials.length, held, needed: materials.length - held };
}

/** 마감까지 남은 날. 지났으면 음수, 마감을 모르면 null. */
export function daysLeft(closedAt: string | null, now = Date.now()): number | null {
  if (!closedAt) return null;
  const closed = new Date(closedAt).getTime();
  return Number.isNaN(closed) ? null : Math.floor((closed - now) / 86_400_000);
}

const KST = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

export function kst(value: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const part = Object.fromEntries(KST.formatToParts(date).map((item) => [item.type, item.value]));
  return `${part.year}.${part.month}.${part.day} ${part.hour}:${part.minute}`;
}
