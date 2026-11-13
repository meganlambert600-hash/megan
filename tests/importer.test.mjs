import test from 'node:test';
import assert from 'node:assert/strict';
import '../scripts/importer.js';

const importer = globalThis.MilkTeaImporter;

test('recognizes brand, amount, expiry and Zhengzhou scope', () => {
  const result = importer.candidateFromText(
    '美团外卖｜郑州金水区\n霸王茶姬满30减10元优惠券\n有效期至2026年11月30日\nhttps://example.com/deal',
    { referenceDate: '2026-11-13T00:00:00Z' },
  );
  assert.equal(result.brand, '霸王茶姬');
  assert.equal(result.platform, '美团外卖');
  assert.equal(result.amount, '满30减10元');
  assert.equal(result.expires, '2026-11-30');
  assert.equal(result.region, '郑州');
  assert.equal(result.url, 'https://example.com/deal');
});

test('marks another city instead of relabelling it Zhengzhou', () => {
  const result = importer.candidateFromText('南昌蜜雪冰城买一送一，11月20日截止', { referenceDate: '2026-11-13' });
  assert.equal(result.brand, '蜜雪冰城');
  assert.equal(result.region, '非郑州（南昌）');
  assert.ok(result.warnings.includes('可能不适用于郑州'));
});

test('parses multiple pasted offers separated by blank lines', () => {
  const results = importer.parseBatchText('郑州喜茶9.9元优惠券\n截止11月20日\n\n全国瑞幸咖啡8折券\n截止11月30日', { referenceDate: '2026-11-13' });
  assert.equal(results.length, 2);
  assert.equal(results[0].region, '郑州');
  assert.equal(results[1].region, '全国');
});

test('parses CSV and JSON exports', () => {
  const csv = '品牌,平台,优惠名称,金额,截止日期,适用范围,链接\n古茗,微信小程序,第二杯半价,第二杯半价,2026-12-01,郑州,https://example.com/a';
  const csvResults = importer.parseCSV(csv, { referenceDate: '2026-11-13' });
  assert.equal(csvResults[0].brand, '古茗');
  assert.equal(csvResults[0].expires, '2026-12-01');
  const jsonResults = importer.parseJSON([{ brand: '茶百道', name: '10元券', region: '全国', expires: '2026-12-02' }], { referenceDate: '2026-11-13' });
  assert.equal(jsonResults[0].brand, '茶百道');
  assert.equal(jsonResults[0].region, '全国');
});

test('rejects text without a concrete deal signal', () => {
  assert.equal(importer.candidateFromText('郑州某奶茶品牌新品上市'), null);
});
