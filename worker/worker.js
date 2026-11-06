/**
 * Milk Tea Radar trigger gateway. Deploy as Cloudflare Worker.
 * Secrets: GITHUB_TOKEN, TRIGGER_KEY. No credentials may be embedded in the web page.
 */
const OWNER = 'meganlambert600-hash';
const REPO = 'megan';
const WORKFLOW = 'collect.yml';
const SITE_ORIGIN = 'https://meganlambert600-hash.github.io';
const GH_API = `https://api.github.com/repos/${OWNER}/${REPO}/actions`;

const json = (payload, status = 200, origin = SITE_ORIGIN) => new Response(JSON.stringify(payload), {
  status,
  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': origin, 'Vary': 'Origin', 'X-Content-Type-Options': 'nosniff' }
});

async function sameSecret(a, b) {
  if (!a || !b) return false;
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([crypto.subtle.digest('SHA-256', enc.encode(a)), crypto.subtle.digest('SHA-256', enc.encode(b))]);
  const left = new Uint8Array(x), right = new Uint8Array(y);
  let diff = 0;
  for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}

async function github(path, token, init = {}) {
  const response = await fetch(`${GH_API}${path}`, {
    ...init,
    headers: { 'Accept': 'application/vnd.github+json', 'Authorization': `Bearer ${token}`,
      'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'milk-tea-radar-worker',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}) }
  });
  return response;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin');
    const url = new URL(request.url);
    if (origin && origin !== SITE_ORIGIN) return json({ error: '来源不允许' }, 403);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: {
      'Access-Control-Allow-Origin': SITE_ORIGIN, 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'X-Trigger-Key, Content-Type', 'Access-Control-Max-Age': '600', 'Vary': 'Origin'
    }});
    if (url.pathname === '/health' && request.method === 'GET') return json({ ok: true, service: 'milk-tea-radar-trigger' });
    if (!env.GITHUB_TOKEN || !env.TRIGGER_KEY) return json({ error: '服务端尚未配置密钥' }, 503);
    if (!(await sameSecret(request.headers.get('X-Trigger-Key'), env.TRIGGER_KEY))) return json({ error: '访问口令错误' }, 401);
    try {
      if (url.pathname === '/trigger' && request.method === 'POST') {
        const runs = await github(`/workflows/${WORKFLOW}/runs?event=workflow_dispatch&per_page=5`, env.GITHUB_TOKEN);
        if (!runs.ok) return json({ error: `无法查询任务状态（${runs.status}）` }, 502);
        const history = await runs.json();
        const recent = (history.workflow_runs || []).some(run => Date.now() - Date.parse(run.created_at) < 10 * 60 * 1000);
        if (recent) return json({ error: '十分钟内已有手动采集任务，请稍后再试' }, 429);
        const dispatch = await github(`/workflows/${WORKFLOW}/dispatches`, env.GITHUB_TOKEN, {
          method: 'POST', body: JSON.stringify({ ref: 'main', return_run_details: true })
        });
        if (!dispatch.ok) return json({ error: `GitHub 未接受任务（${dispatch.status}）` }, 502);
        if (dispatch.status === 200) {
          const detail = await dispatch.json();
          return json({ accepted: true, run_id: detail.workflow_run_id, run_url: detail.html_url }, 202);
        }
        return json({ accepted: true, run_id: null, message: 'GitHub 已接受任务，暂未返回任务编号' }, 202);
      }
      if (url.pathname === '/status' && request.method === 'GET') {
        const id = url.searchParams.get('run_id');
        if (!/^\d+$/.test(id || '')) return json({ error: '无效任务编号' }, 400);
        const response = await github(`/runs/${id}`, env.GITHUB_TOKEN);
        if (!response.ok) return json({ error: `任务状态查询失败（${response.status}）` }, 502);
        const run = await response.json();
        if (run.path && !run.path.startsWith('.github/workflows/' + WORKFLOW)) return json({ error: '任务编号不属于采集工作流' }, 400);
        return json({ run_id: run.id, status: run.status, conclusion: run.conclusion,
          run_url: run.html_url, updated_at: run.updated_at });
      }
      return json({ error: '未找到接口' }, 404);
    } catch (err) {
      return json({ error: '上游服务暂时不可用，请稍后重试' }, 502);
    }
  }
};
