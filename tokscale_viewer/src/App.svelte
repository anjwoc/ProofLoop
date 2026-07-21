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
    if (!num || num === 0) return '—';
    return new Intl.NumberFormat().format(num);
  }

  function formatTimestamp(ts) {
    if (!ts) return '-';
    return ts.replace('T', ' ').split('+')[0];
  }
</script>

<header class="header">
  <div class="brand">
    <div class="brand-icon">⚡</div>
    <div class="brand-title">
      <h1>ProofLoop TokScale & Model Routing Viewer</h1>
      <p>Svelte 5 UI/UX Pro Max Engine — 정밀 토큰 소모 및 멀티모델 라우팅 오퍼레이셔널 대시보드</p>
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
      <div class="kpi-icon-header">
        <span class="kpi-label">총 누적 토큰 비용 (Total Cost)</span>
        <span class="kpi-icon">🪙</span>
      </div>
      <div class="kpi-value cost-val">
        {#if !summary.totalCostUsd || summary.totalCostUsd === 0}
          <span class="zero-val">$0.000000</span>
        {:else}
          ${summary.totalCostUsd.toFixed(6)}
        {/if}
      </div>
      <div class="kpi-subtext">TokScale 정밀 계산 기준 ($USD)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon-header">
        <span class="kpi-label">총 소모 토큰 (Raw Total Tokens)</span>
        <span class="kpi-icon">📦</span>
      </div>
      <div class="kpi-value">{formatNumber(summary.totalTokens.rawTotal)}</div>
      <div class="kpi-subtext">
        <span class="token-pill-micro in-pill">In: {formatNumber(summary.totalTokens.input)}</span>
        <span class="token-pill-micro out-pill">Out: {formatNumber(summary.totalTokens.output)}</span>
        <span class="token-pill-micro cache-pill">Cache: {formatNumber(summary.totalTokens.cacheRead)}</span>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon-header">
        <span class="kpi-label">분석된 총 작업 수 (Analyzed Runs)</span>
        <span class="kpi-icon">📋</span>
      </div>
      <div class="kpi-value">{runs.length} <span style="font-size: 1.1rem; color: var(--text-dim); font-weight: 500;">건</span></div>
      <div class="kpi-subtext">
        <span class="multi-highlight">⚡ 멀티모델 라우팅: {multiRunsCount}건 ({multiPct}%)</span>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon-header">
        <span class="kpi-label">활용된 고유 모델 수 (Unique Models)</span>
        <span class="kpi-icon">🤖</span>
      </div>
      <div class="kpi-value">{uniqueModelsList.length} <span style="font-size: 1.1rem; color: var(--text-dim); font-weight: 500;">개 모델</span></div>
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
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input 
          type="text" 
          class="search-input" 
          placeholder="Run ID 또는 요청 내용 검색..." 
          bind:value={searchQuery}
        />
      </div>
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
              <th style="width: 24%;">Run ID & 생성 일시</th>
              <th style="width: 26%;">작업 요청 내용 (Snippet)</th>
              <th style="width: 16%;">라우팅 타입 리포트</th>
              <th style="width: 14%;">투입 모델 (Models Used)</th>
              <th style="width: 9%; text-align: right;">총 토큰 소모</th>
              <th style="width: 8%; text-align: right;">캐시 읽기</th>
              <th style="width: 11%; text-align: right;">토큰 비용 (USD)</th>
              <th style="width: 4%; text-align: center;"></th>
            </tr>
          </thead>
          <tbody>
            {#if filteredRuns.length === 0}
              <tr>
                <td colspan="8" class="empty-state">
                  <div style="font-size: 2rem; margin-bottom: 0.5rem;">🔍</div>
                  해당 필터 또는 검색 조건에 맞는 작업 내역이 없습니다.
                </td>
              </tr>
            {:else}
              {#each filteredRuns as r (r.runId)}
                <tr onclick={() => selectedRun = r}>
                  <td>
                    <div class="run-id">{r.runId}</div>
                    <div class="run-time">🕒 {formatTimestamp(r.timestamp)}</div>
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
                      <span class="badge badge-blocked">🚫 토큰 미소모 / 차단</span>
                    {/if}
                  </td>
                  <td>
                    <div class="model-tags">
                      {#if r.modelsUsed && r.modelsUsed.length > 0}
                        {#each r.modelsUsed as m}
                          <span class="model-tag">{m}</span>
                        {/each}
                      {:else}
                        <span class="zero-val">호출 없음</span>
                      {/if}
                    </div>
                  </td>
                  <td class="mono-num right-num">
                    {#if !r.usage?.totals?.rawTotal || r.usage.totals.rawTotal === 0}
                      <span class="zero-val">—</span>
                    {:else}
                      {formatNumber(r.usage.totals.rawTotal)}
                    {/if}
                  </td>
                  <td class="mono-num right-num" style="color:var(--text-muted);">
                    {#if !r.usage?.totals?.cacheRead || r.usage.totals.cacheRead === 0}
                      <span class="zero-val">—</span>
                    {:else}
                      {formatNumber(r.usage.totals.cacheRead)}
                    {/if}
                  </td>
                  <td class="mono-num right-num">
                    {#if !r.usage?.totals?.costUsd || r.usage.totals.costUsd === 0}
                      <span class="zero-val">$0.000000</span>
                    {:else}
                      <span class="cost-val">${r.usage.totals.costUsd.toFixed(6)}</span>
                    {/if}
                  </td>
                  <td class="arrow-td">
                    <span class="row-arrow">→</span>
                  </td>
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
          <div class="chart-title">
            <span class="chart-icon">🤖</span>
            <span class="model-name-title">{modelName}</span>
          </div>
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
            <span>호출 횟수: <b style="color: #fff;">{formatNumber(data.invocations)}회</b></span>
            <span>누적 비용: <b class="cost-val">${(data.costUsd || 0).toFixed(6)}</b></span>
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
              <th style="text-align: right;">호출 횟수</th>
              <th style="text-align: right;">Input 토큰</th>
              <th style="text-align: right;">Output 토큰</th>
              <th style="text-align: right;">Cache Read</th>
              <th style="text-align: right;">Cache Write</th>
              <th style="text-align: right;">총 소모 비용 (USD)</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(summary.byModel || {}) as [modelName, data]}
              <tr>
                <td class="run-id">{modelName}</td>
                <td class="mono-num right-num">{formatNumber(data.invocations)}</td>
                <td class="mono-num right-num">{formatNumber(data.input)}</td>
                <td class="mono-num right-num">{formatNumber(data.output)}</td>
                <td class="mono-num right-num">{formatNumber(data.cacheRead)}</td>
                <td class="mono-num right-num">{formatNumber(data.cacheWrite)}</td>
                <td class="mono-num right-num cost-val">${(data.costUsd || 0).toFixed(6)}</td>
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
          <div class="chart-title">
            <span class="chart-icon">🎭</span>
            <span class="model-name-title" style="color: #a855f7;">{roleName}</span>
          </div>
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
            <span>호출 횟수: <b style="color: #fff;">{formatNumber(data.invocations)}회</b></span>
            <span>누적 비용: <b class="cost-val">${(data.costUsd || 0).toFixed(6)}</b></span>
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
              <th style="text-align: right;">호출 횟수</th>
              <th style="text-align: right;">Input 토큰</th>
              <th style="text-align: right;">Output 토큰</th>
              <th style="text-align: right;">Cache Read</th>
              <th style="text-align: right;">Cache Write</th>
              <th style="text-align: right;">총 소모 비용 (USD)</th>
            </tr>
          </thead>
          <tbody>
            {#each Object.entries(summary.byRole || {}) as [roleName, data]}
              <tr>
                <td class="run-id" style="color:var(--accent-primary); font-weight: 700;">{roleName}</td>
                <td class="mono-num right-num">{formatNumber(data.invocations)}</td>
                <td class="mono-num right-num">{formatNumber(data.input)}</td>
                <td class="mono-num right-num">{formatNumber(data.output)}</td>
                <td class="mono-num right-num">{formatNumber(data.cacheRead)}</td>
                <td class="mono-num right-num">{formatNumber(data.cacheWrite)}</td>
                <td class="mono-num right-num cost-val">${(data.costUsd || 0).toFixed(6)}</td>
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
            <span class="badge badge-multi" style="margin-bottom: 0.8rem;">⚡ 멀티모델 라우팅 동반 작업</span>
          {:else if selectedRun.routingType === 'SINGLE_MODEL'}
            <span class="badge badge-single" style="margin-bottom: 0.8rem;">🔹 단일 모델 작업</span>
          {:else}
            <span class="badge badge-blocked" style="margin-bottom: 0.8rem;">🚫 토큰 미소모 / 차단</span>
          {/if}
          <h2 class="run-id" style="font-size: 1.35rem; color: #fff; margin-top: 0.3rem;">{selectedRun.runId}</h2>
          <div class="run-time" style="font-size: 0.85rem; margin-top: 0.4rem;">🕒 {formatTimestamp(selectedRun.timestamp)}</div>
        </div>
        <button class="close-btn" onclick={() => selectedRun = null}>✕</button>
      </div>

      <div class="section-title">💬 사용자 원본 요청 (Original Request)</div>
      <div class="code-box">{selectedRun.request || '요청 정보 없음'}</div>

      <div class="section-title">🔀 모델 라우팅 및 역할별 호출 내역 (Role & Model Routing)</div>
      <div class="routing-nodes">
        {#if !selectedRun.usage?.byInvocation || selectedRun.usage.byInvocation.length === 0}
          <div class="routing-node" style="color:var(--text-dim); text-align: center; padding: 2rem;">이 작업 중에는 LLM 역할(Role) 호출이 기록되지 않았습니다.</div>
        {:else}
          {#each selectedRun.usage.byInvocation as inv}
            <div class="routing-node">
              <div class="routing-header">
                <span class="role-name">▶ Role: {inv.role}</span>
                <span class="mono-num cost-val" style="font-size: 1rem;">${(inv.costUsd || 0).toFixed(6)}</span>
              </div>
              <div style="font-size:0.9rem; color:#e2e8f0; margin-bottom: 0.65rem;">
                라우팅 모델: <b style="color:#60a5fa; font-family: 'JetBrains Mono', monospace;">{inv.model}</b> 
                {#if inv.requestedModel && inv.requestedModel !== inv.model}
                  <span style="color: #94a3b8; font-size: 0.82rem;">(요청: {inv.requestedModel})</span>
                {/if}
                <span class="evidence-tag">[{inv.evidenceLevel || 'REPORTED'}]</span>
              </div>
              <div class="token-breakdown-pills">
                <span class="t-pill in-pill">In: {formatNumber(inv.tokens?.input)}</span>
                <span class="t-pill out-pill">Out: {formatNumber(inv.tokens?.output)}</span>
                <span class="t-pill cache-pill">Cache Read: {formatNumber(inv.tokens?.cacheRead)}</span>
                <span class="t-pill write-pill">Cache Write: {formatNumber(inv.tokens?.cacheWrite)}</span>
              </div>
            </div>
          {/each}
        {/if}
      </div>

      <div class="section-title">📊 이 작업의 토큰 소모 요약 (Task Usage Summary)</div>
      <div class="kpi-grid" style="grid-template-columns: 1fr 1fr; margin-bottom: 1.5rem; gap: 1rem;">
        <div class="kpi-card" style="padding: 1.2rem;">
          <div class="kpi-label">이 작업의 비용</div>
          <div class="kpi-value cost-val" style="font-size: 1.5rem;">
            {#if !selectedRun.usage?.totals?.costUsd || selectedRun.usage.totals.costUsd === 0}
              <span class="zero-val">$0.000000</span>
            {:else}
              ${selectedRun.usage.totals.costUsd.toFixed(6)}
            {/if}
          </div>
        </div>
        <div class="kpi-card" style="padding: 1.2rem;">
          <div class="kpi-label">이 작업의 총 토큰</div>
          <div class="kpi-value" style="font-size: 1.5rem;">{formatNumber(selectedRun.usage?.totals?.rawTotal)}</div>
        </div>
      </div>

      <div class="section-title">🏁 최종 검증 및 Truth 판정 (Truth Verdict)</div>
      <div class="code-box" style="max-height: 200px;">{JSON.stringify(selectedRun.truthReport || { status: 'UNKNOWN' }, null, 2)}</div>
    </div>
  {/if}
</div>

<style>
  .header {
    padding: 1.75rem 3.5rem;
    border-bottom: 1px solid var(--border-color);
    backdrop-filter: blur(20px);
    position: sticky;
    top: 0;
    z-index: 50;
    background: rgba(10, 13, 20, 0.9);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .brand { display: flex; align-items: center; gap: 1.2rem; }
  .brand-icon {
    width: 46px; height: 46px; border-radius: 14px;
    background: var(--accent-gradient);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 1.5rem; color: white;
    box-shadow: 0 0 25px rgba(139, 92, 246, 0.45);
  }
  .brand-title h1 {
    font-size: 1.55rem; font-weight: 700; letter-spacing: -0.02em;
    background: linear-gradient(to right, #ffffff, #cbd5e1);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .brand-title p { font-size: 0.85rem; color: var(--text-muted); margin-top: 0.2rem; font-weight: 400; }
  .status-pill {
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.45rem 1rem;
    background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35);
    border-radius: 999px; font-size: 0.85rem; color: #34d399; font-weight: 600;
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
  .container { max-width: 1560px; margin: 0 auto; padding: 2.5rem 3.5rem; }
  
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 1.5rem; margin-bottom: 2.5rem;
  }
  .kpi-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 18px; padding: 1.6rem; backdrop-filter: blur(14px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden;
  }
  .kpi-card::before {
    content: ''; position: absolute; top: 0; left: 0;
    width: 100%; height: 3px; background: var(--border-color);
    transition: background 0.3s ease;
  }
  .kpi-card:hover {
    transform: translateY(-3px); border-color: rgba(139, 92, 246, 0.4);
    box-shadow: 0 16px 36px rgba(0, 0, 0, 0.45);
  }
  .kpi-card:hover::before { background: var(--accent-gradient); }
  .kpi-icon-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; }
  .kpi-label {
    font-size: 0.82rem; color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.06em; font-weight: 600;
  }
  .kpi-icon { font-size: 1.25rem; opacity: 0.85; }
  .kpi-value { font-family: 'JetBrains Mono', monospace; font-size: 1.95rem; font-weight: 700; color: #fff; line-height: 1.2; }
  .kpi-subtext { font-size: 0.8rem; color: var(--text-dim); margin-top: 0.65rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .multi-highlight { color: #c084fc; font-weight: 600; }
  
  .token-pill-micro {
    padding: 0.15rem 0.45rem; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
  }
  .in-pill { background: rgba(59, 130, 246, 0.12); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.25); }
  .out-pill { background: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25); }
  .cache-pill { background: rgba(168, 85, 247, 0.12); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.25); }
  .write-pill { background: rgba(245, 158, 11, 0.12); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.25); }
  
  .controls-bar {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1.2rem;
  }
  .tabs {
    display: flex; background: rgba(15, 23, 42, 0.75); padding: 0.35rem;
    border-radius: 14px; border: 1px solid var(--border-color); gap: 0.35rem;
  }
  .tab-btn {
    background: transparent; border: none; color: var(--text-muted);
    padding: 0.65rem 1.35rem; border-radius: 10px; font-family: 'Outfit', sans-serif;
    font-size: 0.95rem; font-weight: 500; cursor: pointer; transition: all 0.2s ease;
    display: flex; align-items: center; gap: 0.55rem;
  }
  .tab-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.06); }
  .tab-btn.active {
    background: var(--accent-gradient); color: white; font-weight: 600;
    box-shadow: 0 4px 14px rgba(139, 92, 246, 0.35);
  }
  .filter-group { display: flex; gap: 0.85rem; align-items: center; }
  .search-box {
    position: relative; display: flex; align-items: center;
  }
  .search-icon { position: absolute; left: 1rem; font-size: 0.9rem; pointer-events: none; opacity: 0.7; }
  .search-input {
    background: rgba(15, 23, 42, 0.75); border: 1px solid var(--border-color);
    border-radius: 12px; padding: 0.65rem 1rem 0.65rem 2.6rem; color: white; font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; width: 280px; outline: none; transition: all 0.2s ease;
  }
  .search-input:focus { border-color: var(--accent-primary); box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.18); width: 320px; }
  .filter-select {
    background: rgba(15, 23, 42, 0.75); border: 1px solid var(--border-color);
    border-radius: 12px; padding: 0.65rem 1.25rem; color: white; font-family: 'Outfit', sans-serif;
    font-size: 0.9rem; outline: none; cursor: pointer; transition: border-color 0.2s ease;
  }
  .filter-select:focus { border-color: var(--accent-primary); }

  .data-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 18px; overflow: hidden; backdrop-filter: blur(14px); margin-bottom: 2.5rem;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
  }
  .table-container { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; text-align: left; }
  th {
    padding: 1.1rem 1.5rem; font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; color: #94a3b8; background: rgba(15, 23, 42, 0.92);
    border-bottom: 2px solid rgba(139, 92, 246, 0.25); white-space: nowrap;
  }
  td {
    padding: 1.1rem 1.5rem; font-size: 0.94rem; border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    vertical-align: middle; transition: background 0.15s ease;
  }
  tr:last-child td { border-bottom: none; }
  tbody tr { cursor: pointer; }
  tbody tr:hover td { background: var(--bg-card-hover); }
  
  .badge {
    display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; padding: 0.4rem 0.85rem;
    border-radius: 999px; font-size: 0.76rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
    white-space: nowrap; word-break: keep-all; flex-shrink: 0;
  }
  .badge-multi { background: var(--badge-multi); color: white; box-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
  .badge-single { background: var(--badge-single); color: white; box-shadow: 0 0 14px rgba(16, 185, 129, 0.3); }
  .badge-blocked { background: var(--badge-blocked); color: #e2e8f0; border: 1px solid rgba(255, 255, 255, 0.12); }
  
  .run-id { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #f8fafc; font-size: 0.9rem; word-break: break-all; }
  .run-time { font-size: 0.78rem; color: var(--text-dim); margin-top: 0.3rem; font-family: 'JetBrains Mono', monospace; }
  .req-snippet {
    max-width: 420px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    color: #cbd5e1; font-size: 0.92rem; font-weight: 400; line-height: 1.4;
  }
  .mono-num { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #fff; font-size: 0.92rem; }
  .right-num { text-align: right; }
  .cost-val { color: #34d399; font-weight: 700; }
  .zero-val { color: #64748b; font-weight: 400; font-family: 'JetBrains Mono', monospace; }
  
  .model-tags { display: flex; flex-wrap: wrap; gap: 0.45rem; }
  .model-tag {
    font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
    background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.15);
    padding: 0.22rem 0.6rem; border-radius: 6px; color: #e2e8f0; white-space: nowrap;
  }
  
  .arrow-td { text-align: center; color: var(--text-dim); font-size: 1.1rem; }
  .row-arrow { transition: transform 0.2s ease, color 0.2s ease; display: inline-block; }
  tbody tr:hover .row-arrow { transform: translateX(4px); color: var(--accent-primary); }

  .analytics-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
    gap: 1.5rem; margin-bottom: 2.5rem;
  }
  .chart-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 18px; padding: 1.85rem; backdrop-filter: blur(14px);
  }
  .chart-title {
    font-size: 1.2rem; font-weight: 600; margin-bottom: 1.5rem;
    display: flex; align-items: center; gap: 0.65rem; color: #fff;
  }
  .chart-icon { font-size: 1.4rem; }
  .model-name-title { font-family: 'JetBrains Mono', monospace; font-weight: 700; }
  .bar-row { margin-bottom: 1.35rem; }
  .bar-label-area { display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .bar-label { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--text-main); }
  .bar-val { font-family: 'JetBrains Mono', monospace; color: var(--text-muted); font-size: 0.85rem; }
  .bar-track {
    width: 100%; height: 12px; background: rgba(255, 255, 255, 0.06);
    border-radius: 999px; overflow: hidden; display: flex;
  }
  .bar-fill { height: 100%; border-radius: 999px; transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1); }
  .chart-footer {
    display: flex; justify-content: space-between; margin-top: 1.2rem; padding-top: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.06); font-size: 0.88rem; color: var(--text-muted);
  }

  .drawer-overlay {
    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(5, 7, 12, 0.82); backdrop-filter: blur(10px);
    z-index: 100; display: flex; justify-content: flex-end;
    opacity: 0; pointer-events: none; transition: opacity 0.3s ease;
  }
  .drawer-overlay.active { opacity: 1; pointer-events: auto; }
  .drawer {
    width: 820px; max-width: 92vw; background: #0f1422;
    border-left: 1px solid rgba(139, 92, 246, 0.35); height: 100vh;
    overflow-y: auto; padding: 2.75rem; transform: translateX(100%);
    transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
    box-shadow: -25px 0 60px rgba(0, 0, 0, 0.7);
  }
  .drawer-overlay.active .drawer { transform: translateX(0); }
  .drawer-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 2.2rem; padding-bottom: 1.6rem; border-bottom: 1px solid var(--border-color);
  }
  .close-btn {
    background: rgba(255, 255, 255, 0.08); border: none; color: white;
    width: 38px; height: 38px; border-radius: 10px; font-size: 1.25rem; cursor: pointer;
    display: flex; align-items: center; justify-content: center; transition: background 0.2s ease;
  }
  .close-btn:hover { background: rgba(255, 255, 255, 0.2); }
  .section-title {
    font-size: 0.95rem; font-weight: 700; color: #f8fafc; margin: 2rem 0 0.9rem;
    text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; gap: 0.5rem;
  }
  .code-box {
    background: rgba(10, 13, 20, 0.95); border: 1px solid var(--border-color);
    border-radius: 14px; padding: 1.35rem; font-family: 'JetBrains Mono', monospace;
    font-size: 0.88rem; color: #cbd5e1; white-space: pre-wrap; max-height: 300px;
    overflow-y: auto; line-height: 1.65;
  }
  .routing-node {
    background: rgba(255, 255, 255, 0.035); border: 1px solid var(--border-color);
    border-radius: 14px; padding: 1.35rem; margin-bottom: 1.2rem;
    transition: border-color 0.2s ease;
  }
  .routing-node:hover { border-color: rgba(139, 92, 246, 0.35); }
  .routing-header {
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.85rem;
  }
  .role-name { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #c084fc; font-size: 1rem; }
  .evidence-tag { font-family: 'JetBrains Mono', monospace; font-size: 0.76rem; color: #64748b; margin-left: 0.6rem; }
  .token-breakdown-pills { display: flex; gap: 0.65rem; flex-wrap: wrap; margin-top: 0.9rem; }
  .t-pill {
    border-radius: 6px; padding: 0.32rem 0.75rem;
    font-size: 0.8rem; font-family: 'JetBrains Mono', monospace; font-weight: 600;
  }
  .empty-state { text-align: center; padding: 5rem 2rem; color: var(--text-muted); }
</style>
