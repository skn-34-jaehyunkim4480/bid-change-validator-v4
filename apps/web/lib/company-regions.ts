/** 2026-07-01+ active 시·도, using first two digits of the legal-dong code.
 * The existing institution-derived sigungu vocabulary stores names/parents,
 * NOT authoritative district codes. Do not guess district codes here.
 * https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=127039
 * https://www.data.go.kr/data/15102109/openapi.do (integrated 12 vs legacy 29/46)
 */
export const COMPANY_REGION_OPTIONS = [
  { code: '11', name: '서울특별시' },
  { code: '26', name: '부산광역시' },
  { code: '27', name: '대구광역시' },
  { code: '28', name: '인천광역시' },
  { code: '30', name: '대전광역시' },
  { code: '31', name: '울산광역시' },
  { code: '36', name: '세종특별자치시' },
  { code: '41', name: '경기도' },
  { code: '51', name: '강원특별자치도' },
  { code: '43', name: '충청북도' },
  { code: '44', name: '충청남도' },
  { code: '52', name: '전북특별자치도' },
  { code: '12', name: '전남광주통합특별시' },
  { code: '47', name: '경상북도' },
  { code: '48', name: '경상남도' },
  { code: '50', name: '제주특별자치도' },
] as const;

export function regionByCode(code: string) {
  return COMPANY_REGION_OPTIONS.find((item) => item.code === code);
}

/** Do not silently replace historic codes or full addresses on unrelated edits. */
export function selectedRegionCode(code: string, name: string): string {
  return COMPANY_REGION_OPTIONS.some((item) => item.code === code && item.name === name) ? code : '';
}
