/*
  내 입찰 건 목록의 검색과 정렬(2026-10-14).
  검토 건은 한 번에 100건까지 받아 오므로 브라우저에서 거르고 줄 세운다.
*/

export type CaseListItem = {
  id: string;
  bid_notice_no: string;
  notice_title: string;
  title: string;
  bid_closed_at?: string | null;
  expired?: boolean;
  created_at: string;
  updated_at: string;
};

export type CaseSort = 'recent' | 'oldest' | 'deadline' | 'title';

export const CASE_SORT_OPTIONS: Array<{ value: CaseSort; label: string }> = [
  { value: 'recent', label: '최근에 다룬 순' },
  { value: 'oldest', label: '오래된 순' },
  { value: 'deadline', label: '마감 가까운 순' },
  { value: 'title', label: '공고명 순' },
];

const squash = (value: string) => value.replace(/\s+/g, '').toLowerCase();

/** 공고번호·공고명·검토 건 이름에 낱말이 모두 들어 있는 것만 남긴다. 띄어쓰기와 대소문자는 보지 않는다. */
export function filterCases<T extends CaseListItem>(cases: T[], query: string): T[] {
  const words = query.trim().split(/\s+/).filter(Boolean).map(squash);
  if (!words.length) return cases;
  return cases.filter((item) => {
    const haystack = squash(`${item.bid_notice_no} ${item.notice_title} ${item.title}`);
    return words.every((word) => haystack.includes(word));
  });
}

const time = (value: string | null | undefined) => (value ? new Date(value).getTime() : Number.NaN);

/**
 * 고른 기준으로 줄 세운다. 원래 배열은 바꾸지 않는다.
 * '마감 가까운 순' 은 아직 마감 전인 공고를 가까운 것부터 놓고, 그 뒤에 마감을 모르는 공고, 맨 뒤에 만료된 공고(최근에 끝난 것부터)를 둔다 —
 * 이미 끝난 공고가 "가장 가까운 마감" 으로 맨 앞에 오지 않게 한다.
 */
export function sortCases<T extends CaseListItem>(cases: T[], sort: CaseSort): T[] {
  const list = [...cases];
  if (sort === 'oldest') return list.sort((a, b) => time(a.created_at) - time(b.created_at));
  if (sort === 'title') return list.sort((a, b) => (a.notice_title || a.title).localeCompare(b.notice_title || b.title, 'ko'));
  if (sort === 'deadline') {
    const group = (item: T) => (item.expired ? 2 : item.bid_closed_at ? 0 : 1);
    return list.sort((a, b) => {
      const byGroup = group(a) - group(b);
      if (byGroup) return byGroup;
      if (group(a) === 0) return time(a.bid_closed_at) - time(b.bid_closed_at);
      if (group(a) === 2) return time(b.bid_closed_at) - time(a.bid_closed_at);
      return time(b.updated_at) - time(a.updated_at);
    });
  }
  return list.sort((a, b) => time(b.updated_at) - time(a.updated_at));
}
