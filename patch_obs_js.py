import re

with open(r'C:\Users\DYK\Desktop\agent\agent-loop-lab\static\index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. updateObservabilityStatus: #obs-status-badge -> #obs-status-card + #obs-status-label
old1 = """function updateObservabilityStatus(status) {
	  if (currentSessionId) {
	    sessionStatuses[currentSessionId] = status;
	  }
	  const badge = document.getElementById('obs-status-badge');
	  if (!badge) return;
	  const runningStates = ['thinking', 'executing'];
	  const successStates = ['done'];
	  const errorStates = ['error', 'max_turns', 'cancelled', 'failed'];
	  badge.className = 'obs-status-badge';
	  if (runningStates.includes(status)) badge.classList.add('running');
	  else if (successStates.includes(status)) badge.classList.add('success');
	  else if (errorStates.includes(status)) badge.classList.add('error');
	  badge.textContent = `当前状态: ${prettifyStatus(status)}`;
	}"""

new1 = """function updateObservabilityStatus(status) {
	  if (currentSessionId) {
	    sessionStatuses[currentSessionId] = status;
	  }
	  const card = document.getElementById('obs-status-card');
	  const label = document.getElementById('obs-status-label');
	  if (!card || !label) return;
	  card.className = 'obs-card';
	  const icon = card.querySelector('.obs-status-icon');
	  const runningStates = ['thinking', 'executing'];
	  const successStates = ['done', 'success'];
	  const errorStates = ['error', 'max_turns', 'cancelled', 'failed'];
	  if (runningStates.includes(status)) {
	    card.classList.add('obs-status-running');
	    if (icon) icon.textContent = '⏳';
	  } else if (successStates.includes(status)) {
	    card.classList.add('obs-status-ok');
	    if (icon) icon.textContent = '✅';
	  } else if (errorStates.includes(status)) {
	    card.classList.add('obs-status-error');
	    if (icon) icon.textContent = '❌';
	  } else {
	    card.classList.add('obs-status-ok');
	    if (icon) icon.textContent = '✅';
	  }
	  label.textContent = prettifyStatus(status);
	}"""
html = html.replace(old1, new1)

# 2. renderObservability: remove #obs-snapshots section, only keep metrics + events + status + tech details
old2 = """function renderObservability(trace) {
	  const metrics = trace?.metrics || {};
	  const events = trace?.events || [];
	  const snapshots = trace?.snapshots || [];

	  document.getElementById('obs-trace-id').textContent = trace?.trace_id || '--';
	  document.getElementById('obs-model').textContent = trace?.model || metrics.model || '--';
	  document.getElementById('obs-turns').textContent = metrics.total_turns || 0;
	  document.getElementById('obs-tools').textContent = metrics.total_tool_calls || 0;
	  document.getElementById('obs-tool-errors').textContent = metrics.total_tool_errors || 0;
	  document.getElementById('obs-tokens').textContent = (metrics.total_tokens || 0).toLocaleString();
	  document.getElementById('obs-duration').textContent = `${(metrics.duration_seconds || 0).toFixed(1)}s`;
	  document.getElementById('obs-llm-time').textContent = `${(metrics.total_llm_duration_ms || 0).toFixed(0)}ms`;
	  document.getElementById('obs-cost').textContent = `¥${(metrics.estimated_cost_cny || 0).toFixed(4)}`;
	  updateObservabilityStatus(trace?.status || sessionStatuses[currentSessionId] || 'idle');

	  const snapshotsEl = document.getElementById('obs-snapshots');
	  if (!snapshots.length) {
	    snapshotsEl.innerHTML = '<div class="obs-empty">暂无状态快照</div>';
	  } else {
	    const latest = snapshots.slice(-6).reverse();
	    snapshotsEl.innerHTML = latest.map((snap) => `
	      <div class="obs-snapshot">
	        <div class="obs-snapshot-head">
	          <strong>Turn ${snap.turn || 0}</strong>
	          <span>${formatObsTime(snap.timestamp)}</span>
	        </div>
	        <div class="obs-snapshot-grid">
	          <span>状态: ${prettifyStatus(snap.status)}</span>
	          <span>消息: ${snap.message_count || 0}</span>
	          <span>工具调用: ${snap.tool_calls || 0}</span>
	          <span>工具结果: ${snap.tool_results || 0}</span>
	          <span>总 Token: ${(snap.total_tokens || 0).toLocaleString()}</span>
	          <span>用户: ${escapeHtml((snap.last_user_preview || '--').slice(0, 24))}</span>
	        </div>
	      </div>
	    `).join('');
	  }

	  const eventsEl = document.getElementById('obs-events');
	  if (!events.length) {
	    eventsEl.innerHTML = '<div class="obs-empty">暂无执行事件</div>';
	  } else {
	    const recent = events.slice(-30).reverse();
	    eventsEl.innerHTML = recent.map((evt) => {
	      const payload = evt.payload && Object.keys(evt.payload).length
	        ? `\\n${escapeHtml(JSON.stringify(evt.payload, null, 2).slice(0, 500))}`
	        : '';
	      const body = `${escapeHtml(evt.message || '')}${payload}`;
	      return `
	        <div class="obs-timeline-item">
	          <div class="obs-timeline-meta">${formatObsTime(evt.timestamp)} · Turn ${evt.turn || 0} · ${escapeHtml(prettifyStatus(evt.status))}</div>
	          <div class="obs-timeline-title">${escapeHtml(evt.node || evt.kind || 'event')}</div>
	          <div class="obs-timeline-body">${body || '无更多信息'}</div>
	        </div>
	      `;
	    }).join('');
	  }
	}"""

new2 = """function renderObservability(trace) {
	  const metrics = trace?.metrics || {};
	  const events = trace?.events || [];

	  document.getElementById('obs-trace-id').textContent = trace?.trace_id || '--';
	  document.getElementById('obs-model').textContent = trace?.model || metrics.model || '--';
	  document.getElementById('obs-turns').textContent = metrics.total_turns || 0;
	  document.getElementById('obs-tools').textContent = metrics.total_tool_calls || 0;
	  document.getElementById('obs-tool-errors').textContent = metrics.total_tool_errors || 0;
	  document.getElementById('obs-tokens').textContent = (metrics.total_tokens || 0).toLocaleString();
	  document.getElementById('obs-duration').textContent = `${(metrics.duration_seconds || 0).toFixed(1)}s`;
	  document.getElementById('obs-llm-time').textContent = `${(metrics.total_llm_duration_ms || 0).toFixed(0)}ms`;
	  document.getElementById('obs-cost').textContent = `¥${(metrics.estimated_cost_cny || 0).toFixed(4)}`;
	  updateObservabilityStatus(trace?.status || sessionStatuses[currentSessionId] || 'idle');

	  const eventsEl = document.getElementById('obs-events');
	  if (!events.length) {
	    eventsEl.innerHTML = '<div class="obs-empty">暂无执行记录</div>';
	  } else {
	    const recent = events.slice(-30).reverse();
	    eventsEl.innerHTML = recent.map((evt) => {
	      const payload = evt.payload && Object.keys(evt.payload).length
	        ? `\\n${escapeHtml(JSON.stringify(evt.payload, null, 2).slice(0, 500))}`
	        : '';
	      const body = `${escapeHtml(evt.message || '')}${payload}`;
	      return `
	        <div class="obs-timeline-item">
	          <div class="obs-timeline-meta">${formatObsTime(evt.timestamp)} · Turn ${evt.turn || 0} · ${escapeHtml(prettifyStatus(evt.status))}</div>
	          <div class="obs-timeline-title">${escapeHtml(evt.node || evt.kind || 'event')}</div>
	          <div class="obs-timeline-body">${body || '无更多信息'}</div>
	        </div>
	      `;
	    }).join('');
	  }
	}"""
html = html.replace(old2, new2)

# 3. showObservability: modal -> sidebar
old3 = """function showObservability() {
	  document.getElementById('observability-modal').classList.add('show');
	  if (sessionTraces[currentSessionId]) {
	    renderObservability(sessionTraces[currentSessionId]);
	  } else {
	    renderObservability(null);
	  }
	  refreshObservability();
	}"""

new3 = """function showObservability() {
	  const sidebar = document.getElementById('obs-sidebar');
	  const isHidden = sidebar.classList.contains('hidden');
	  if (!isHidden) {
	    // 已打开则关闭
	    sidebar.classList.add('hidden');
	    return;
	  }
	  sidebar.classList.remove('hidden');
	  if (sessionTraces[currentSessionId]) {
	    renderObservability(sessionTraces[currentSessionId]);
	  } else {
	    renderObservability(null);
	  }
	  refreshObservability();
	}"""
html = html.replace(old3, new3)

# 4. closeObservability: modal -> sidebar
old4 = """function closeObservability() {
	  document.getElementById('observability-modal').classList.remove('show');
	}"""
new4 = """function closeObservability() {
	  document.getElementById('obs-sidebar').classList.add('hidden');
	}"""
html = html.replace(old4, new4)

# 5. selectSession obs check: observability-modal -> obs-sidebar
old5 = """if (document.getElementById('observability-modal').classList.contains('show')) {"""
new5 = """if (!document.getElementById('obs-sidebar').classList.contains('hidden')) {"""
html = html.replace(old5, new5)

# 6. SSE done handler obs check: observability-modal -> obs-sidebar
old6 = """if (document.getElementById('observability-modal').classList.contains('show') && sessionId === currentSessionId) {"""
new6 = """if (!document.getElementById('obs-sidebar').classList.contains('hidden') && sessionId === currentSessionId) {"""
html = html.replace(old6, new6)

# 7. Remove old observability-modal click event listener (lines 1899-1901)
old7 = """document.getElementById('observability-modal').addEventListener('click', function(e) {
	  if (e.target === e.currentTarget) closeObservability();
	});"""
html = html.replace(old7, '')

with open(r'C:\Users\DYK\Desktop\agent\agent-loop-lab\static\index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Done. Patched 7 JS functions/blocks.")
