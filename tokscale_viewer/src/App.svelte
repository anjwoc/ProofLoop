<script>
  import { onMount } from 'svelte';
  
  let runs = $state([]);
  let summary = $state({
    totalCostUsd: 0,
    totalTokens: { rawTotal: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    byModel: {},
    byRole: {}
  });
  let activeTab = $state('runs');
  let searchQuery = $state('');
  let filterType = $state('ALL');
  let selectedRun = $state(null);

  let filteredRuns = $derived(
    runs.filter(r => {
      const matchSearch = r.runId.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          (r.request || '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchFilter = filterType === 'ALL' || r.routingType === filterType;
      return matchSearch && matchFilter;
    })
  );

  let multiRunsCount = $derived(runs.filter(r => r.routingType === 'MULTI_MODEL_ROUTING').length);
  let multiPct = $derived(runs.length > 0 ? ((multiRunsCount / runs.length) * 100).toFixed(1) : '0.0');
  let uniqueModelsList = $derived(Object.keys(summary.byModel || {}));

  let maxModelRaw = $derived(Math.max(...Object.values(summary.byModel || {}).map(m => m.rawTotal || 0), 1));
  let maxRoleRaw = $derived(Math.max(...Object.values(summary.byRole || {}).map(r => r.rawTotal || 0), 1));

  async function fetchData() {
    try {
      const res = await fetch('/api/data');
      if (res.ok) {
        const data = await res.json();
        runs = data.runs || [];
        summary = data.summary || summary;
      }
    } catch (e) {
      console.error('Failed fetching data:', e);
    }
  }

  onMount(() => {
    fetchData();
    const timer = setInterval(fetchData, 10000);
    return () => clearInterval(timer);
  });

  function formatNumber(num) {
    return new Intl.NumberFormat().format(num || 0);
  }

  function formatCost(cost) {
    return '$' + (cost || 0).toFixed(6);
  }
</script>

<header class="header">
  <div class="brand">
    <div class="brand-icon">⚡</div>
    <div class="brand-title">
      <h1>ProofLoop TokScale & Model Routing Viewer</h1>
      <p>Svelte 5 반응형 엔진 — 작업별 토큰 사용량 및 멀티모델 라우팅 정밀 분석 리포트</p>
    </div>
  </div>
  <div class="status-pill">
    <div class="status-dot"></div>
    <span>Live Local Engine Connected</span>
  </div>
</header>

<main class="container">
  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">총 누적 토큰 비용 (Total Cost)</div>
      <div class="kpi-value cost-val">{formatCost(summary.totalCostUsd)}</div>
      <div class="kpi-subtext">TokScale 정밀 계산 기준</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">총 소모 토큰 (Raw Total Tokens)</div>
      <div class="kpi-value">{formatNumber(summary.totalTokens.rawTotal)}</div>
      <div class="kpi-subtext">In: {formatNumber(summary.totalTokens.input)} | Out: {formatNumber(summary.totalTokens.output)} | Cache: {formatNumber(summary.totalTokens.cacheRead)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">분석된 총 작업 수 (Analyzed Runs)</div>
      <div class="kpi-value">{formatNumber(runs.length)}</div>
      <div class="kpi-subtext">멀티모델 라우팅: {multiRunsCount}건 ({multiPct}%)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">활용된 고유 모델 수 (Unique Models)</div>
      <div class="kpi-value">{uniqueModelsList.length}</div>
      <div class="kpi-subtext" title={uniqueModelsList.join(', ')}>
        {uniqueModelsList.slice(0, 3).join(', ')}{uniqueModelsList.length > 3 ? '...' : ''}
      </div>
    </div>
  </div>

  <!-- Controls Bar -->
  <div class="controls-bar">
    <div class="tabs">
      <button class="tab-btn {activeTab === 'runs' ? 'active' : ''}" onclick={() => activeTab = 'runs'}>
        <span>📋</span> 전체 작업 및 라우팅 보고서
      </button>
      <button class="tab-btn {activeTab === 'models' ? 'active' : ''}" onclick={() => activeTab = 'models'}>
        <span>🤖</span> 모델별 사용량 분석
      </button>
      <button class="tab-btn {activeTab === 'roles' ? 'active' : ''}" onclick={() => activeTab = 'roles'}>
        <span>🎭</span> 역할별(Role) 소모량 Breakdown
      </button>
    </div>

    <div class="filter-group">
      <input 
        type="text" 
        class="search-input" 
        placeholder="Run ID 또는 요청 내용 검색..." 
        bind:value={searchQuery}
      />
      <select class="filter-select" bind:value={filterType}>
        <option value="ALL">전체 라우팅 타입 (All)</option>
        <option value="MULTI_MODEL_ROUTING">⚡ 멀티모델 라우팅 동반 작업</option>
        <option value="SINGLE_MODEL">🔹 단일 모델 작업</option>
        <option value="NO_INVOCATION">🚫 차단 / 토큰 미소모</option>
      </select>
    </div>
  </div>

  <!-- View 1: Runs Table -->
  {#if activeTab === 'runs'}
    <div class="data-card">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Run ID & 생성 일시</th>
              <th>작업 요청 내용 (Snippet)</th>
              <th>라우팅 타입 리포트</th>
              <th>투입 모델 (Models Used)</th>
              <th>총 토큰 소모 (Raw)</th>
              <th>캐시 읽기 (Cache Read)</th>
              <th>토큰 비용 (Cost USD)</th>
            </tr>
          </thead>
          <tbody>
            {#if filteredRuns.length === 0}
              <tr>
                <td colspan="7" class="empty-state">해당 조건에 맞는 작업 내역이 없습니다.</td>
              </tr>
            {:else}
              {#each filteredRuns as r (r.runId)}
                <tr onclick={() => selectedRun = r}>
                  <td>
                    <div class="run-id">{r.runId}</div>
                    <div class="run-time">{r.timestamp || '-'}</div>
                  </td>
                  <td>
                    <div class="req-snippet" title={r.request}>{r.request || '요청 정보 없음'}</div>
                  </td>
                  <td>
                    {#if r.routingType === 'MULTI_MODEL_ROUTING'}
                      <span class="badge badge-multi">⚡ 멀티모델 라우팅</span>
                    {:else if r.routingType === 'SINGLE_MODEL'}
                      <span class="badge badge-single">🔹 단일 모델</span>
                    {:else}
                      <span class="badge badge-blocked">🚫 토큰 미소모/차단</span>
                    {/if}
                  </td>
                  <td>
                    <div class="model-tags">
                      {#if r.modelsUsed && r.modelsUsed.length > 0}
                        {#each r.modelsUsed as m}
                          <span class="model-tag">{m}</span>
                        {/each}
                      {:else}
                        <span style="color:var(--text-dim)">호출 없음</span>
                      {/if}
                    </div>
                  </td>
                  <td class="mono-num">{formatNumber(r.usage?.totals?.rawTotal)}</td>
                  <td class="mono-num" style="color:var(--text-muted);">{formatNumber(r.usage?.totals?.cacheRead)}</td>
                  <td class="mono-num cost-val">{formatCost(r.usage?.totals?.costUsd)}</td>
                </tr>
              {/each}
            {/if}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  <!-- View 2: Models Breakdown -->
  {#if activeTab === 'models'}
    <div class="analytics-grid">
      {#each Object.entries(summary.byModel || {}) as [modelName, data]}
        {@const pct = ((data.rawTotal / maxModelRaw) * 100).toFixed(1)}
        <div class="chart-card">
          <div class="chart-title">🤖 {modelName}</div>
          <div class="bar-row">
            <div class="bar-label-area">
              <span class="bar-label">누적 토큰 점유율 ({formatNumber(data.rawTotal)} Tokens)</span>
              <span class="bar-val">{pct}% of peak</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" style="width: {pct}%; background: var(--accent-gradient);"></div>
            </div>
          </div>
          <div class="chart-footer">
            <span>호출 횟수: <b>{formatNumber(data.invocations)}회</b></span>
            <span>누적 비용: <b style="color:#34d399;">{formatCost(data.costUsd)}</b></span>
          </div>
        </div>
      {/each}
    </div>
    <div class="data-card">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>모델명 (Model Name)</th>
              <th>호출 횟수 (Invocations)</th>
              <th>Input 토큰</th>
              <th>Output 토큰</th>
              <th>Cache Read 토큰</th>
              <th>Cache Write 토큰</th>
              <th>총 소모 비용 ($ USD)</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(summary.byModel || {}) as [modelName, data]}
              <tr>
                <td class="run-id">{modelName}</td>
                <td class="mono-num">{formatNumber(data.invocations)}</td>
                <td class="mono-num">{formatNumber(data.input)}</td>
                <td class="mono-num">{formatNumber(data.output)}</td>
                <td class="mono-num">{formatNumber(data.cacheRead)}</td>
                <td class="mono-num">{formatNumber(data.cacheWrite)}</td>
                <td class="mono-num cost-val">{formatCost(data.costUsd)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  <!-- View 3: Roles Breakdown -->
  {#if activeTab === 'roles'}
    <div class="analytics-grid">
      {#each Object.entries(summary.byRole || {}) as [roleName, data]}
        {@const pct = ((data.rawTotal / maxRoleRaw) * 100).toFixed(1)}
        <div class="chart-card">
          <div class="chart-title">🎭 {roleName}</div>
          <div class="bar-row">
            <div class="bar-label-area">
              <span class="bar-label">소모 토큰 ({formatNumber(data.rawTotal)} Tokens)</span>
              <span class="bar-val">{pct}% of peak</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" style="width: {pct}%; background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%);"></div>
            </div>
          </div>
          <div class="chart-footer">
            <span>호출 횟수: <b>{formatNumber(data.invocations)}회</b></span>
            <span>누적 비용: <b style="color:#34d399;">{formatCost(data.costUsd)}</b></span>
          </div>
        </div>
      {/each}
    </div>
    <div class="data-card">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>역할 (Role Name)</th>
              <th>호출 횟수 (Invocations)</th>
              <th>Input 토큰</th>
              <th>Output 토큰</th>
              <th>Cache Read 토큰</th>
              <th>Cache Write 토큰</th>
              <th>총 소모 비용 ($ USD)</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(summary.byRole || {}) as [roleName, data]}
              <tr>
                <td class="run-id" style="color:var(--accent-primary);">{roleName}</td>
                <td class="mono-num">{formatNumber(data.invocations)}</td>
                <td class="mono-num">{formatNumber(data.input)}</td>
                <td class="mono-num">{formatNumber(data.output)}</td>
                <td class="mono-num">{formatNumber(data.cacheRead)}</td>
                <td class="mono-num">{formatNumber(data.cacheWrite)}</td>
                <td class="mono-num cost-val">{formatCost(data.costUsd)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</main>

<!-- Detail Drawer -->
<div 
  class="drawer-overlay {selectedRun ? 'active' : ''}" 
  onclick={(e) => { if (e.target === e.currentTarget) selectedRun = null; }}
  role="presentation"
>
  {#if selectedRun}
    <div class="drawer">
      <div class="drawer-header">
        <div>
          {#if selectedRun.routingType === 'MULTI_MODEL_ROUTING'}
            <span class="badge badge-multi" style="margin-bottom: 0.6rem;">⚡ 멀티모델 라우팅 동반 작업</span>
          {:else if selectedRun.routingType === 'SINGLE_MODEL'}
            <span class="badge badge-single" style="margin-bottom: 0.6rem;">🔹 단일 모델 작업</span>
          {:else}
            <span class="badge badge-blocked" style="margin-bottom: 0.6rem;">🚫 토큰 미소모 / 차단</span>
          {/if}
          <h2 class="run-id" style="font-size: 1.4rem;">{selectedRun.runId}</h2>
          <div class="run-time">{selectedRun.timestamp || '-'}</div>
        </div>
        <button class="close-btn" onclick={() => selectedRun = null}>✕</button>
      </div>

      <div class="section-title">💬 사용자 원본 요청 (Original Request)</div>
      <div class="code-box">{selectedRun.request || '요청 정보 없음'}</div>

      <div class="section-title">🔀 모델 라우팅 및 역할별 호출 내역 (Role & Model Routing)</div>
      <div class="routing-nodes">
        {#if !selectedRun.usage?.byInvocation || selectedRun.usage.byInvocation.length === 0}
          <div class="routing-node" style="color:var(--text-dim);">이 작업 중에는 LLM 역할(Role) 호출이 기록되지 않았습니다.</div>
        {:else}
          {#each selectedRun.usage.byInvocation as inv}
            <div class="routing-node">
              <div class="routing-header">
                <span class="role-name">▶ Role: {inv.role}</span>
                <span class="mono-num cost-val">{formatCost(inv.costUsd)}</span>
              </div>
              <div style="font-size:0.88rem; color:#e2e8f0; margin-bottom: 0.5rem;">
                라우팅 모델: <b style="color:#60a5fa;">{inv.model}</b> 
                {#if inv.requestedModel && inv.requestedModel !== inv.model}
                  (요청: {inv.requestedModel})
                {/if}
                <span style="color:var(--text-dim); font-size:0.75rem; margin-left: 0.5rem;">[{inv.evidenceLevel || 'REPORTED'}]</span>
              </div>
              <div class="token-breakdown-pills">
                <span class="t-pill" style="color:#3b82f6;">In: {formatNumber(inv.tokens?.input)}</span>
                <span class="t-pill" style="color:#10b981;">Out: {formatNumber(inv.tokens?.output)}</span>
                <span class="t-pill" style="color:#a855f7;">Cache Read: {formatNumber(inv.tokens?.cacheRead)}</span>
                <span class="t-pill" style="color:#f59e0b;">Cache Write: {formatNumber(inv.tokens?.cacheWrite)}</span>
              </div>
            </div>
          {/each}
        {/if}
      </div>

      <div class="section-title">📊 이 작업의 토큰 소모 요약 (Task Usage Summary)</div>
      <div class="kpi-grid" style="grid-template-columns: 1fr 1fr; margin-bottom: 1.5rem;">
        <div class="kpi-card" style="padding: 1.2rem;">
          <div class="kpi-label">이 작업의 비용</div>
          <div class="kpi-value cost-val" style="font-size: 1.4rem;">{formatCost(selectedRun.usage?.totals?.costUsd)}</div>
        </div>
        <div class="kpi-card" style="padding: 1.2rem;">
          <div class="kpi-label">이 작업의 총 토큰</div>
          <div class="kpi-value" style="font-size: 1.4rem;">{formatNumber(selectedRun.usage?.totals?.rawTotal)}</div>
        </div>
      </div>

      <div class="section-title">🏁 최종 검증 및 Truth 판정 (Truth Verdict)</div>
      <div class="code-box" style="max-height: 180px;">{JSON.stringify(selectedRun.truthReport || { status: 'UNKNOWN' }, null, 2)}</div>
    </div>
  {/if}
</div>

<style>
  .header {
    padding: 2rem 3rem 1.5rem;
    border-bottom: 1px solid var(--border-color);
    backdrop-filter: blur(16px);
    position: sticky;
    top: 0;
    z-index: 50;
    background: rgba(10, 13, 20, 0.85);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .brand { display: flex; align-items: center; gap: 1rem; }
  .brand-icon {
    width: 42px; height: 42px; border-radius: 12px;
    background: var(--accent-gradient);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 1.4rem; color: white;
    box-shadow: 0 0 20px rgba(139, 92, 246, 0.4);
  }
  .brand-title h1 {
    font-size: 1.5rem; font-weight: 700;
    background: linear-gradient(to right, #fff, #cbd5e1);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .brand-title p { font-size: 0.85rem; color: var(--text-muted); }
  .status-pill {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.4rem 0.9rem;
    background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 999px; font-size: 0.85rem; color: #34d399; font-weight: 500;
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #10b981; box-shadow: 0 0 8px #10b981;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.9); }
  }
  .container { max-width: 1440px; margin: 0 auto; padding: 2rem 3rem; }
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1.5rem; margin-bottom: 2.5rem;
  }
  .kpi-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 16px; padding: 1.5rem; backdrop-filter: blur(12px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden;
  }
  .kpi-card::before {
    content: ''; position: absolute; top: 0; left: 0;
    width: 100%; height: 3px; background: var(--border-color);
    transition: background 0.3s ease;
  }
  .kpi-card:hover {
    transform: translateY(-3px); border-color: rgba(139, 92, 246, 0.3);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4);
  }
  .kpi-card:hover::before { background: var(--accent-gradient); }
  .kpi-label {
    font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.05em; font-weight: 600; margin-bottom: 0.5rem;
  }
  .kpi-value { font-family: 'JetBrains Mono', monospace; font-size: 1.9rem; font-weight: 700; color: #fff; }
  .kpi-subtext { font-size: 0.8rem; color: var(--text-dim); margin-top: 0.4rem; }
  .controls-bar {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem;
  }
  .tabs {
    display: flex; background: rgba(15, 23, 42, 0.6); padding: 0.35rem;
    border-radius: 12px; border: 1px solid var(--border-color); gap: 0.35rem;
  }
  .tab-btn {
    background: transparent; border: none; color: var(--text-muted);
    padding: 0.6rem 1.25rem; border-radius: 8px; font-family: 'Outfit', sans-serif;
    font-size: 0.95rem; font-weight: 500; cursor: pointer; transition: all 0.2s ease;
    display: flex; align-items: center; gap: 0.5rem;
  }
  .tab-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.05); }
  .tab-btn.active {
    background: var(--accent-gradient); color: white; font-weight: 600;
    box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
  }
  .filter-group { display: flex; gap: 0.75rem; align-items: center; }
  .search-input {
    background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border-color);
    border-radius: 10px; padding: 0.6rem 1rem; color: white; font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; width: 260px; outline: none; transition: border-color 0.2s ease;
  }
  .search-input:focus { border-color: var(--accent-primary); }
  .filter-select {
    background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border-color);
    border-radius: 10px; padding: 0.6rem 1rem; color: white; font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; outline: none; cursor: pointer;
  }
  .data-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 16px; overflow: hidden; backdrop-filter: blur(12px); margin-bottom: 2rem;
  }
  .table-container { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; text-align: left; }
  th {
    padding: 1.1rem 1.5rem; font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--text-muted); background: rgba(15, 23, 42, 0.8);
    border-bottom: 1px solid var(--border-color);
  }
  td {
    padding: 1.25rem 1.5rem; font-size: 0.95rem; border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    vertical-align: middle;
  }
  tr:last-child td { border-bottom: none; }
  tbody tr { transition: background 0.2s ease; cursor: pointer; }
  tbody tr:hover { background: var(--bg-card-hover); }
  .badge {
    display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.35rem 0.8rem;
    border-radius: 999px; font-size: 0.78rem; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase;
  }
  .badge-multi { background: var(--badge-multi); color: white; box-shadow: 0 0 12px rgba(168, 85, 247, 0.3); }
  .badge-single { background: var(--badge-single); color: white; box-shadow: 0 0 12px rgba(16, 185, 129, 0.3); }
  .badge-blocked { background: var(--badge-blocked); color: #cbd5e1; }
  .run-id { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #fff; }
  .run-time { font-size: 0.8rem; color: var(--text-dim); margin-top: 0.25rem; }
  .req-snippet {
    max-width: 380px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    color: var(--text-muted); font-size: 0.9rem;
  }
  .mono-num { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #fff; }
  .cost-val { color: #34d399; }
  .model-tags { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .model-tag {
    font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
    background: rgba(255, 255, 255, 0.07); border: 1px solid rgba(255, 255, 255, 0.12);
    padding: 0.2rem 0.55rem; border-radius: 6px; color: #e2e8f0;
  }
  .analytics-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
    gap: 1.5rem; margin-bottom: 2rem;
  }
  .chart-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 16px; padding: 1.75rem; backdrop-filter: blur(12px);
  }
  .chart-title {
    font-size: 1.15rem; font-weight: 600; margin-bottom: 1.5rem;
    display: flex; align-items: center; gap: 0.6rem; color: #fff;
  }
  .bar-row { margin-bottom: 1.25rem; }
  .bar-label-area { display: flex; justify-content: space-between; margin-bottom: 0.4rem; font-size: 0.9rem; }
  .bar-label { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--text-main); }
  .bar-val { font-family: 'JetBrains Mono', monospace; color: var(--text-muted); font-size: 0.85rem; }
  .bar-track {
    width: 100%; height: 10px; background: rgba(255, 255, 255, 0.06);
    border-radius: 999px; overflow: hidden; display: flex;
  }
  .bar-fill { height: 100%; border-radius: 999px; transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1); }
  .chart-footer {
    display: flex; justify-content: space-between; margin-top: 1rem;
    font-size: 0.85rem; color: var(--text-muted);
  }
  .drawer-overlay {
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(5, 7, 12, 0.8); backdrop-filter: blur(8px);
    z-index: 100; display: flex; justify-content: flex-end;
    opacity: 0; pointer-events: none; transition: opacity 0.3s ease;
  }
  .drawer-overlay.active { opacity: 1; pointer-events: auto; }
  .drawer {
    width: 780px; max-width: 90vw; background: #0f1422;
    border-left: 1px solid rgba(139, 92, 246, 0.3); height: 100vh;
    overflow-y: auto; padding: 2.5rem; transform: translateX(100%);
    transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
    box-shadow: -20px 0 50px rgba(0, 0, 0, 0.6);
  }
  .drawer-overlay.active .drawer { transform: translateX(0); }
  .drawer-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border-color);
  }
  .close-btn {
    background: rgba(255, 255, 255, 0.08); border: none; color: white;
    width: 36px; height: 36px; border-radius: 10px; font-size: 1.2rem; cursor: pointer;
    display: flex; align-items: center; justify-content: center; transition: background 0.2s ease;
  }
  .close-btn:hover { background: rgba(255, 255, 255, 0.18); }
  .section-title {
    font-size: 1rem; font-weight: 600; color: #fff; margin: 1.75rem 0 0.8rem;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .code-box {
    background: rgba(10, 13, 20, 0.9); border: 1px solid var(--border-color);
    border-radius: 12px; padding: 1.25rem; font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem; color: #cbd5e1; white-space: pre-wrap; max-height: 280px;
    overflow-y: auto; line-height: 1.6;
  }
  .routing-node {
    background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color);
    border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem;
  }
  .routing-header {
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;
  }
  .role-name { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #a855f7; font-size: 0.95rem; }
  .token-breakdown-pills { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.8rem; }
  .t-pill {
    background: rgba(255, 255, 255, 0.05); border-radius: 6px; padding: 0.3rem 0.65rem;
    font-size: 0.78rem; font-family: 'JetBrains Mono', monospace;
  }
  .empty-state { text-align: center; padding: 4rem 2rem; color: var(--text-muted); }
</style>
