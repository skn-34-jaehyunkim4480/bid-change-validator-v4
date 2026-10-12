import assert from 'node:assert/strict';
import { test } from 'node:test';
import { COMPANY_REGION_OPTIONS, regionByCode, selectedRegionCode } from './company-regions.ts';

void test('active province list has unique paired codes, including 2026 integrated region', () => {
  assert.equal(COMPANY_REGION_OPTIONS.length, 16);
  assert.equal(new Set(COMPANY_REGION_OPTIONS.map(({ code }) => code)).size, 16);
  assert.equal(new Set(COMPANY_REGION_OPTIONS.map(({ name }) => name)).size, 16);
  assert.deepEqual(regionByCode('11'), { code: '11', name: '서울특별시' });
  assert.deepEqual(regionByCode('52'), { code: '52', name: '전북특별자치도' });
  assert.deepEqual(regionByCode('12'), { code: '12', name: '전남광주통합특별시' });
  assert.equal(regionByCode('29'), undefined);
  assert.equal(regionByCode('46'), undefined);
});

void test('historical name/code pairs are not silently normalized or lost', () => {
  assert.equal(selectedRegionCode('11', '서울특별시'), '11');
  assert.equal(selectedRegionCode('11', '서울특별시 강남구'), '');
  assert.equal(selectedRegionCode('29', '광주광역시'), '');
  assert.equal(selectedRegionCode('46', '전라남도'), '');
  assert.equal(selectedRegionCode('12', '전라남도'), '');
  assert.equal(selectedRegionCode('', ''), '');
});
