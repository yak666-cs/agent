import re

with open(r'C:\Users\DYK\Desktop\agent\agent-loop-lab\static\index.html', 'r', encoding='utf-8') as f:
    raw = f.read()
html = raw.replace('\r\n', '\n')

# ======== 1. updateObservabilityStatus ========
old1 = (
    "function updateObservabilityStatus(status) {\n"
    "  if (currentSessionId) {\n"
    "    sessionStatuses[currentSessionId] = status;\n"
    "  }\n"
    "  const badge = document.getElementById('obs-status-badge');\n"
    "  if (!badge) return;\n"
    "  const runningStates = ['thinking', 'executing'];\n"
    "  const successStates = ['done'];\n"
    "  const errorStates = ['error', 'max_turns', 'cancelled', 'failed'];\n"
    "  badge.className = 'obs-status-badge';\n"
    "  if (runningStates.includes(status)) badge.classList.add('running');\n"
    "  else if (successStates.includes(status)) badge.classList.add('success');\n"
    "  else if (errorStates.includes(status)) badge.classList.add('error');\n"
    "  badge.textContent = `当前状态: ${prettifyStatus(status)}`;\n"
    "}"
)
new1 = (
    "function updateObservabilityStatus(status) {\n"
    "  if (currentSessionId) {\n"
    "    sessionStatuses[currentSessionId] = status;\n"
    "  }\n"
    "  const card = document.getElementById('obs-status-card');\n"
    "  const label = document.getElementById('obs-status-label');\n"
    "  if (!card || !label) return;\n"
    "  card.className = 'obs-card';\n"
    "  const icon = card.querySelector('.obs-status-icon');\n"
    "  const runningStates = ['thinking', 'executing'];\n"
    "  const successStates = ['done', 'success'];\n"
    "  const errorStates = ['error', 'max_turns', 'cancelled', 'failed'];\n"
    "  if (runningStates.includes(status)) {\n"
    "    card.classList.add('obs-status-running');\n"
    "    if (icon) icon.textContent = '\\u23f3';\n"
    "  } else if (successStates.includes(status)) {\n"
    "    card.classList.add('obs-status-ok');\n"
    "    if (icon) icon.textContent = '\\u2705';\n"
    "  } else if (errorStates.includes(status)) {\n"
    "    card.classList.add('obs-status-error');\n"
    "    if (icon) icon.textContent = '\\u274c';\n"
    "  } else {\n"
    "    card.classList.add('obs-status-ok');\n"
    "    if (icon) icon.textContent = '\\u2705';\n"
    "  }\n"
    "  label.textContent = prettifyStatus(status);\n"
    "}"
)
c1 = html.count(old1)
print(f"1. updateObservabilityStatus: {c1}")
if c1:
    html = html.replace(old1, new1)

# ======== 2. renderObservability — remove snapshots block ========
old2 = (
    "function renderObservability(trace) {\n"
    "  const metrics = trace?.metrics || {};\n"
    "  const events = trace?.events || [];\n"
    "  const snapshots = trace?.snapshots || [];\n"
    "\n"
    "  document.getElementById('obs-trace-id').textContent = trace?.trace_id || '--';\n"
    "  document.getElementById('obs-model').textContent = trace?.model || metrics.model || '--';\n"
    "  document.getElementById('obs-turns').textContent = metrics.total_turns || 0;\n"
    "  document.getElementById('obs-tools').textContent = metrics.total_tool_calls || 0;\n"
    "  document.getElementById('obs-tool-errors').textContent = metrics.total_tool_errors || 0;\n"
    "  document.getElementById('obs-tokens').textContent = (metrics.total_tokens || 0).toLocaleString();\n"
    "  document.getElementById('obs-duration').textContent = `${(metrics.duration_seconds || 0).toFixed(1)}s`;\n"
    "  document.getElementById('obs-llm-time').textContent = `${(metrics.total_llm_duration_ms || 0).toFixed(0)}ms`;\n"
    "  document.getElementById('obs-cost').textContent = `\\u00a5${(metrics.estimated_cost_cny || 0).toFixed(4)}`;\n"
    "  updateObservabilityStatus(trace?.status || sessionStatuses[currentSessionId] || 'idle');\n"
    "\n"
    "  const snapshotsEl = document.getElementById('obs-snapshots');\n"
    "  if (!snapshots.length) {\n"
    "    snapshotsEl.innerHTML = '<div class=\"obs-empty\">\\u6682\\u65e0\\u72b6\\u6001\\u5feb\\u7167</div>';\n"
    "  } else {\n"
    "    const latest = snapshots.slice(-6).reverse();\n"
    "    snapshotsEl.innerHTML = latest.map((snap) => `\n"
    "      <div class=\"obs-snapshot\">\n"
    "        <div class=\"obs-snapshot-head\">\n"
    "          <strong>Turn ${snap.turn || 0}</strong>\n"
    "          <span>${formatObsTime(snap.timestamp)}</span>\n"
    "        </div>\n"
    "        <div class=\"obs-snapshot-grid\">\n"
    "          <span>\\u72b6\\u6001: ${prettifyStatus(snap.status)}</span>\n"
    "          <span>\\u6d88\\u606f: ${snap.message_count || 0}</span>\n"
    "          <span>\\u5de5\\u5177\\u8c03\\u7528: ${snap.tool_calls || 0}</span>\n"
    "          <span>\\u5de5\\u5177\\u7ed3\\u679c: ${snap.tool_results || 0}</span>\n"
    "          <span>\\u603b Token: ${(snap.total_tokens || 0).toLocaleString()}</span>\n"
    "          <span>\\u7528\\u6237: ${escapeHtml((snap.last_user_preview || '--').slice(0, 24))}</span>\n"
    "        </div>\n"
    "      </div>\n"
    "    `).join('');\n"
    "  }\n"
    "\n"
    "  const eventsEl = document.getElementById('obs-events');\n"
    "  if (!events.length) {\n"
    "    eventsEl.innerHTML = '<div class=\"obs-empty\">\\u6682\\u65e0\\u6267\\u884c\\u4e8b\\u4ef6</div>';\n"
    "  } else {\n"
    "    const recent = events.slice(-30).reverse();\n"
    "    eventsEl.innerHTML = recent.map((evt) => {\n"
    "      const payload = evt.payload && Object.keys(evt.payload).length\n"
    "        ? `\\n${escapeHtml(JSON.stringify(evt.payload, null, 2).slice(0, 500))}`\n"
    "        : '';\n"
    "      const body = `${escapeHtml(evt.message || '')}${payload}`;\n"
    "      return `\n"
    "        <div class=\"obs-timeline-item\">\n"
    "          <div class=\"obs-timeline-meta\">${formatObsTime(evt.timestamp)} \\u00b7 Turn ${evt.turn || 0} \\u00b7 ${escapeHtml(prettifyStatus(evt.status))}</div>\n"
    "          <div class=\"obs-timeline-title\">${escapeHtml(evt.node || evt.kind || 'event')}</div>\n"
    "          <div class=\"obs-timeline-body\">${body || '\\u65e0\\u66f4\\u591a\\u4fe1\\u606f'}</div>\n"
    "        </div>\n"
    "      `;\n"
    "    }).join('');\n"
    "  }\n"
    "}"
)
new2 = (
    "function renderObservability(trace) {\n"
    "  const metrics = trace?.metrics || {};\n"
    "  const events = trace?.events || [];\n"
    "\n"
    "  document.getElementById('obs-trace-id').textContent = trace?.trace_id || '--';\n"
    "  document.getElementById('obs-model').textContent = trace?.model || metrics.model || '--';\n"
    "  document.getElementById('obs-turns').textContent = metrics.total_turns || 0;\n"
    "  document.getElementById('obs-tools').textContent = metrics.total_tool_calls || 0;\n"
    "  document.getElementById('obs-tool-errors').textContent = metrics.total_tool_errors || 0;\n"
    "  document.getElementById('obs-tokens').textContent = (metrics.total_tokens || 0).toLocaleString();\n"
    "  document.getElementById('obs-duration').textContent = `${(metrics.duration_seconds || 0).toFixed(1)}s`;\n"
    "  document.getElementById('obs-llm-time').textContent = `${(metrics.total_llm_duration_ms || 0).toFixed(0)}ms`;\n"
    "  document.getElementById('obs-cost').textContent = `\\u00a5${(metrics.estimated_cost_cny || 0).toFixed(4)}`;\n"
    "  updateObservabilityStatus(trace?.status || sessionStatuses[currentSessionId] || 'idle');\n"
    "\n"
    "  const eventsEl = document.getElementById('obs-events');\n"
    "  if (!events.length) {\n"
    "    eventsEl.innerHTML = '<div class=\"obs-empty\">\\u6682\\u65e0\\u6267\\u884c\\u8bb0\\u5f55</div>';\n"
    "  } else {\n"
    "    const recent = events.slice(-30).reverse();\n"
    "    eventsEl.innerHTML = recent.map((evt) => {\n"
    "      const payload = evt.payload && Object.keys(evt.payload).length\n"
    "        ? `\\n${escapeHtml(JSON.stringify(evt.payload, null, 2).slice(0, 500))}`\n"
    "        : '';\n"
    "      const body = `${escapeHtml(evt.message || '')}${payload}`;\n"
    "      return `\n"
    "        <div class=\"obs-timeline-item\">\n"
    "          <div class=\"obs-timeline-meta\">${formatObsTime(evt.timestamp)} \\u00b7 Turn ${evt.turn || 0} \\u00b7 ${escapeHtml(prettifyStatus(evt.status))}</div>\n"
    "          <div class=\"obs-timeline-title\">${escapeHtml(evt.node || evt.kind || 'event')}</div>\n"
    "          <div class=\"obs-timeline-body\">${body || '\\u65e0\\u66f4\\u591a\\u4fe1\\u606f'}</div>\n"
    "        </div>\n"
    "      `;\n"
    "    }).join('');\n"
    "  }\n"
    "}"
)
c2 = html.count(old2)
print(f"2. renderObservability: {c2}")
if c2:
    html = html.replace(old2, new2)

# ======== 3. showObservability ========
old3 = (
    "function showObservability() {\n"
    "  document.getElementById('observability-modal').classList.add('show');\n"
    "  if (sessionTraces[currentSessionId]) {\n"
    "    renderObservability(sessionTraces[currentSessionId]);\n"
    "  } else {\n"
    "    renderObservability(null);\n"
    "  }\n"
    "  refreshObservability();\n"
    "}"
)
new3 = (
    "function showObservability() {\n"
    "  const sidebar = document.getElementById('obs-sidebar');\n"
    "  const isHidden = sidebar.classList.contains('hidden');\n"
    "  if (!isHidden) {\n"
    "    sidebar.classList.add('hidden');\n"
    "    return;\n"
    "  }\n"
    "  sidebar.classList.remove('hidden');\n"
    "  if (sessionTraces[currentSessionId]) {\n"
    "    renderObservability(sessionTraces[currentSessionId]);\n"
    "  } else {\n"
    "    renderObservability(null);\n"
    "  }\n"
    "  refreshObservability();\n"
    "}"
)
c3 = html.count(old3)
print(f"3. showObservability: {c3}")
if c3:
    html = html.replace(old3, new3)

# ======== 4. closeObservability ========
old4 = (
    "function closeObservability() {\n"
    "  document.getElementById('observability-modal').classList.remove('show');\n"
    "}"
)
new4 = (
    "function closeObservability() {\n"
    "  document.getElementById('obs-sidebar').classList.add('hidden');\n"
    "}"
)
c4 = html.count(old4)
print(f"4. closeObservability: {c4}")
if c4:
    html = html.replace(old4, new4)

# ======== 5. selectSession obs check ========
old5 = "if (document.getElementById('observability-modal').classList.contains('show')) {"
c5 = html.count(old5)
print(f"5. selectSession check: {c5}")
if c5:
    html = html.replace(old5, "if (!document.getElementById('obs-sidebar').classList.contains('hidden')) {")

# ======== 6. SSE done handler ========
old6 = "if (document.getElementById('observability-modal').classList.contains('show') && sessionId === currentSessionId) {"
c6 = html.count(old6)
print(f"6. SSE done check: {c6}")
if c6:
    html = html.replace(old6, "if (!document.getElementById('obs-sidebar').classList.contains('hidden') && sessionId === currentSessionId) {")

# ======== 7. Remove old modal click listener ========
old7 = (
    "document.getElementById('observability-modal').addEventListener('click', function(e) {\n"
    "  if (e.target === e.currentTarget) closeObservability();\n"
    "});"
)
c7 = html.count(old7)
print(f"7. Modal listener: {c7}")
if c7:
    html = html.replace(old7, "")

# Restore CRLF
html = html.replace('\n', '\r\n')
with open(r'C:\Users\DYK\Desktop\agent\agent-loop-lab\static\index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("\nDone!")
