(function (root) {
  'use strict';

  const BRAND_ALIASES = [
    ['霸王茶姬', ['霸王茶姬', 'CHAGEE']],
    ['古茗', ['古茗']],
    ['茶百道', ['茶百道']],
    ['蜜雪冰城', ['蜜雪冰城', '蜜雪', '雪王']],
    ['喜茶', ['喜茶', 'HEYTEA']],
    ['瑞幸咖啡', ['瑞幸咖啡', '瑞幸', 'Luckin']],
    ['爷爷不泡茶', ['爷爷不泡茶']],
    ['茉莉奶白', ['茉莉奶白']],
    ['沪上阿姨', ['沪上阿姨']],
    ['益禾堂', ['益禾堂']],
    ['柠季', ['柠季']],
    ['LINLEE林里', ['LINLEE', '林里']],
    ['CoCo都可', ['CoCo都可', 'CoCo']],
    ['茉酸奶', ['茉酸奶']],
    ['库迪咖啡', ['库迪咖啡', '库迪', 'COTTI']],
    ['星巴克', ['星巴克', 'Starbucks']],
    ['书亦烧仙草', ['书亦烧仙草', '书亦']],
  ];
  const PLATFORM_ALIASES = [
    ['美团外卖', ['美团外卖', '美团']],
    ['淘宝闪购', ['淘宝闪购', '淘宝']],
    ['京东外卖', ['京东外卖', '京东秒送', '京东']],
    ['抖音团购', ['抖音团购', '抖音']],
    ['饿了么', ['饿了么']],
    ['微信小程序', ['微信小程序', '小程序', '微信']],
    ['支付宝', ['支付宝', '口碑']],
    ['云闪付', ['云闪付']],
  ];
  const DEAL_RE = /(优惠券|代金券|红包|满\s*\d+(?:\.\d+)?\s*(?:元)?\s*减\s*\d+(?:\.\d+)?|立减\s*\d+(?:\.\d+)?\s*元|\d+(?:\.\d+)?\s*元\s*(?:券|红包|优惠)|\d(?:\.\d)?\s*折|买一送一|第二杯半价|免单|免费|团购|特价)/i;
  const ZHENGZHOU_RE = /(郑州|河南|金水|二七|中原|管城|惠济|郑东新区|高新区|经开区|航空港)/;
  const NATIONAL_RE = /(全国|全网|全国通用|不限地区|不限城市|全门店)/;
  const OTHER_CITY_RE = /(北京|上海|广州|深圳|杭州|南京|苏州|武汉|长沙|成都|重庆|西安|天津|青岛|济南|合肥|南昌|厦门|福州|昆明|贵阳|太原|石家庄|沈阳|大连|哈尔滨|长春|兰州|乌鲁木齐|海口|三亚|宁波|无锡|佛山|东莞|珠海)/;

  function clean(value, limit) {
    return String(value == null ? '' : value).replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').replace(/\r/g, '').trim().slice(0, limit || 2000);
  }

  function firstAlias(text, entries, fallback) {
    const lowered = text.toLowerCase();
    for (const [canonical, aliases] of entries) {
      if (aliases.some(alias => lowered.includes(alias.toLowerCase()))) return canonical;
    }
    return fallback;
  }

  function findBrand(text) {
    return firstAlias(text, BRAND_ALIASES, '其他/通用');
  }

  function findPlatform(text) {
    return firstAlias(text, PLATFORM_ALIASES, '其他平台');
  }

  function findRegion(text) {
    if (ZHENGZHOU_RE.test(text)) return '郑州';
    if (NATIONAL_RE.test(text)) return '全国';
    const other = text.match(OTHER_CITY_RE);
    return other ? `非郑州（${other[1]}）` : '待确认';
  }

  function pad(number) {
    return String(number).padStart(2, '0');
  }

  function normalizeDate(raw, referenceDate) {
    const value = clean(raw, 50);
    if (!value) return '';
    const match = value.match(/(?:(20\d{2})\s*[年\-\/.])?\s*(\d{1,2})\s*[月\-\/.]\s*(\d{1,2})\s*日?/);
    if (!match) return '';
    const reference = referenceDate ? new Date(referenceDate) : new Date();
    let year = Number(match[1] || reference.getFullYear());
    const month = Number(match[2]), day = Number(match[3]);
    const candidate = new Date(year, month - 1, day);
    if (candidate.getMonth() !== month - 1 || candidate.getDate() !== day) return '';
    if (!match[1] && candidate.getTime() < reference.getTime() - 45 * 86400000) year += 1;
    return `${year}-${pad(month)}-${pad(day)}`;
  }

  function findExpiry(text, referenceDate) {
    const explicit = text.match(/(?:有效期(?:至|到)?|截止(?:至|到)?|到期(?:日)?|使用期限(?:至|到)?)[：:\s]*((?:20\d{2}[年\-\/.])?\s*\d{1,2}[月\-\/.]\s*\d{1,2}日?)/);
    if (explicit) return normalizeDate(explicit[1], referenceDate);
    const range = text.match(/(?:20\d{2}[年\-\/.])?\s*\d{1,2}[月\-\/.]\s*\d{1,2}日?\s*(?:至|到|[-~—])\s*((?:20\d{2}[年\-\/.])?\s*\d{1,2}[月\-\/.]\s*\d{1,2}日?)/);
    if (range) return normalizeDate(range[1], referenceDate);
    const dates = [...text.matchAll(/(?:20\d{2}[年\-\/.])?\s*\d{1,2}[月\-\/.]\s*\d{1,2}日?/g)];
    return dates.length ? normalizeDate(dates[dates.length - 1][0], referenceDate) : '';
  }

  function findDeal(text) {
    let match = text.match(/满\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*减\s*(\d+(?:\.\d+)?)/);
    if (match) return `满${match[1]}减${match[2]}元`;
    match = text.match(/立减\s*(\d+(?:\.\d+)?)\s*元/);
    if (match) return `立减${match[1]}元`;
    match = text.match(/(\d+(?:\.\d+)?)\s*元\s*(优惠券|代金券|券|红包|优惠)/);
    if (match) return `${match[1]}元${match[2]}`;
    match = text.match(/(\d(?:\.\d)?)\s*折/);
    if (match) return `${match[1]}折`;
    for (const phrase of ['买一送一', '第二杯半价', '免单', '免费', '团购', '特价']) {
      if (text.includes(phrase)) return phrase;
    }
    return '';
  }

  function findUrl(text, fallback) {
    const match = text.match(/https?:\/\/[^\s<>"'，。；]+/i);
    const raw = match ? match[0] : fallback;
    if (!raw) return '';
    try {
      const url = new URL(raw);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (_) {
      return '';
    }
  }

  function chooseTitle(text, brand, deal) {
    const lines = text.split('\n').map(line => clean(line, 140)).filter(Boolean);
    const best = lines.find(line => DEAL_RE.test(line) && line.length <= 100) || lines.find(line => line.length <= 100);
    return clean(best || `${brand} ${deal || '优惠活动'}`, 100);
  }

  function makeWarnings(candidate, text) {
    const warnings = [];
    if (candidate.brand === '其他/通用') warnings.push('品牌待确认');
    if (!candidate.amount) warnings.push('优惠金额待确认');
    if (!candidate.expires) warnings.push('期限待确认');
    if (candidate.region === '待确认') warnings.push('适用地区待确认');
    if (candidate.region.startsWith('非郑州')) warnings.push('可能不适用于郑州');
    if (!candidate.url) warnings.push('缺少原始链接');
    if (!DEAL_RE.test(text)) warnings.push('未发现明确优惠词');
    return warnings;
  }

  function candidateFromText(raw, options) {
    const text = clean(raw, 12000);
    if (!text || !DEAL_RE.test(text)) return null;
    const opts = options || {};
    const brand = findBrand(text), amount = findDeal(text);
    const candidate = {
      platform: findPlatform(text),
      brand,
      name: chooseTitle(text, brand, amount),
      url: findUrl(text, opts.sourceUrl),
      expires: findExpiry(text, opts.referenceDate),
      region: findRegion(text),
      amount,
      confidence: 0,
      warnings: [],
      raw: text.slice(0, 1200),
    };
    let score = 0.15;
    if (candidate.brand !== '其他/通用') score += 0.2;
    if (candidate.amount) score += 0.2;
    if (candidate.expires) score += 0.15;
    if (candidate.region !== '待确认') score += 0.15;
    if (candidate.url) score += 0.1;
    if (candidate.platform !== '其他平台') score += 0.05;
    candidate.confidence = Math.min(0.95, score);
    candidate.warnings = makeWarnings(candidate, text);
    return candidate;
  }

  function dedupe(candidates) {
    const seen = new Set();
    return candidates.filter(item => {
      if (!item) return false;
      const key = [item.url, item.brand, item.name, item.expires].join('|').toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function parseBatchText(raw, options) {
    const text = clean(raw, 100000);
    if (!text) return [];
    let chunks = text.split(/\n\s*\n|^\s*-{3,}\s*$/m).map(value => value.trim()).filter(Boolean);
    if (chunks.length === 1 && text.split('\n').length > 8) {
      const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
      const focused = [];
      for (let index = 0; index < lines.length; index += 1) {
        if (DEAL_RE.test(lines[index])) focused.push(lines.slice(Math.max(0, index - 1), Math.min(lines.length, index + 3)).join('\n'));
      }
      if (focused.length) chunks = focused;
    }
    return dedupe(chunks.map(chunk => candidateFromText(chunk, options)));
  }

  function parseCSVRows(text) {
    const rows = [];
    let row = [], cell = '', quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (char === '"') {
        if (quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
        else quoted = !quoted;
      } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
      else if ((char === '\n' || char === '\r') && !quoted) {
        if (char === '\r' && text[index + 1] === '\n') index += 1;
        row.push(cell); if (row.some(value => value.trim())) rows.push(row); row = []; cell = '';
      } else cell += char;
    }
    row.push(cell); if (row.some(value => value.trim())) rows.push(row);
    return rows;
  }

  function recordValue(record, keys) {
    for (const key of keys) if (record[key] != null && String(record[key]).trim()) return String(record[key]).trim();
    return '';
  }

  function candidateFromRecord(record, options) {
    const combined = Object.values(record).join('\n');
    const inferred = candidateFromText(combined, options) || {
      platform: '其他平台', brand: '其他/通用', name: '', url: '', expires: '', region: '待确认', amount: '', confidence: 0.2, warnings: [], raw: combined,
    };
    inferred.platform = recordValue(record, ['platform', '平台']) || inferred.platform;
    inferred.brand = recordValue(record, ['brand', '品牌', '商家']) || inferred.brand;
    inferred.name = recordValue(record, ['name', 'title', '优惠名称', '活动', '标题']) || inferred.name;
    inferred.url = findUrl(recordValue(record, ['url', 'link', '链接', '活动链接']), inferred.url || (options && options.sourceUrl));
    inferred.expires = normalizeDate(recordValue(record, ['expires', 'expiry', '到期日', '截止日期', '期限']), options && options.referenceDate) || inferred.expires;
    inferred.region = recordValue(record, ['region', '地域', '适用范围']) || inferred.region;
    inferred.amount = recordValue(record, ['amount', 'deal', '金额', '优惠']) || inferred.amount;
    inferred.name = clean(inferred.name || `${inferred.brand} ${inferred.amount || '优惠活动'}`, 100);
    inferred.warnings = makeWarnings(inferred, combined);
    return inferred;
  }

  function parseCSV(text, options) {
    const rows = parseCSVRows(String(text || ''));
    if (rows.length < 2) return [];
    const headers = rows[0].map(value => clean(value, 50));
    return dedupe(rows.slice(1).map(row => {
      const record = {};
      headers.forEach((header, index) => { record[header] = row[index] || ''; });
      return candidateFromRecord(record, options);
    }));
  }

  function parseJSON(value, options) {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    const records = Array.isArray(parsed) ? parsed : (parsed && (parsed.items || parsed.offers || parsed.records));
    if (!Array.isArray(records)) throw new Error('JSON 需为数组，或包含 items/offers/records 数组');
    return dedupe(records.map(record => typeof record === 'string' ? candidateFromText(record, options) : candidateFromRecord(record || {}, options)));
  }

  root.MilkTeaImporter = {
    candidateFromText,
    candidateFromRecord,
    findBrand,
    findDeal,
    findExpiry,
    findPlatform,
    findRegion,
    normalizeDate,
    parseBatchText,
    parseCSV,
    parseJSON,
  };
})(typeof globalThis !== 'undefined' ? globalThis : window);
