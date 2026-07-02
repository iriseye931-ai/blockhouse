import { useState, type CSSProperties } from 'react'
import { useDashboardStore } from '../store/dashboardStore'

const C = {
  border: 'rgba(156,234,255,0.24)',
  text: '#effcff',
  soft: '#a8c7d5',
  dim: '#6d93a2',
  cyan: '#dffbff',
  teal: '#9aefff',
  green: '#79ff98',
  danger: '#ff8f8f',
}

function formatTime(value: string) {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return '—'
  return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const inputStyle: CSSProperties = {
  width: '100%',
  border: '1px solid rgba(156,234,255,0.14)',
  background: 'rgba(255,255,255,0.04)',
  color: C.text,
  borderRadius: 6,
  padding: '6px 8px',
  fontSize: 10,
  outline: 'none',
}

export default function AgentInbox() {
  const messages = useDashboardStore((s) => s.agentMessages)
  const agents = useDashboardStore((s) => s.agents)
  const items = messages.slice(-3).reverse()
  const latestBySender = new Map<string, (typeof messages)[number]>()
  for (const message of messages) latestBySender.set(message.from, message)
  const currentWork = Array.from(latestBySender.values())
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .slice(-3)
    .reverse()
  const availableAgents = Array.from(
    new Set([
      ...agents.map((agent) => agent.name.toLowerCase()),
      ...messages.flatMap((message) => [message.from, message.to]),
      'codex',
      'claude',
    ]),
  ).filter(Boolean)
  const [fromAgent, setFromAgent] = useState('codex')
  const [toAgent, setToAgent] = useState('claude')
  const [summary, setSummary] = useState('')
  const [details, setDetails] = useState('')
  const [files, setFiles] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [composerOpen, setComposerOpen] = useState(false)

  async function sendMessage() {
    if (!summary.trim() || isSending) return
    setIsSending(true)
    setStatus(null)
    try {
      const response = await fetch('/api/agent-messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_agent: fromAgent,
          to_agent: toAgent,
          role: 'handoff',
          task: 'dashboard realism',
          summary: summary.trim(),
          details: details.trim(),
          files: files
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
        }),
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `HTTP ${response.status}`)
      }

      setSummary('')
      setDetails('')
      setFiles('')
      setStatus('sent')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'send failed')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div
      style={{
        width: 260,
        padding: '10px 11px',
        borderRadius: 12,
        background: 'linear-gradient(180deg, rgba(6,18,28,0.82), rgba(4,10,16,0.68))',
        border: `1px solid ${C.border}`,
        boxShadow: '0 0 24px rgba(120,224,255,0.08)',
        backdropFilter: 'blur(16px)',
        pointerEvents: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div>
          <div style={{ fontSize: 10, color: C.cyan, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
            Agent Inbox
          </div>
          <div style={{ marginTop: 3, fontSize: 9, color: C.soft, lineHeight: 1.4 }}>
            live handoffs and operator notes
          </div>
        </div>
        <button
          type="button"
          onClick={() => setComposerOpen((value) => !value)}
          style={{
            border: `1px solid ${C.border}`,
            background: composerOpen ? 'rgba(120,224,255,0.14)' : 'rgba(255,255,255,0.03)',
            color: C.cyan,
            borderRadius: 999,
            padding: '4px 8px',
            fontSize: 8,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            cursor: 'pointer',
          }}
        >
          {composerOpen ? 'Hide Compose' : 'Compose'}
        </button>
      </div>

      <div
        style={{
          marginTop: 10,
          padding: '8px 9px 9px',
          borderRadius: 8,
          border: '1px solid rgba(156,234,255,0.12)',
          background: 'rgba(255,255,255,0.03)',
          display: 'grid',
          gap: 6,
        }}
      >
        <div style={{ fontSize: 9, color: C.cyan, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Current Work
        </div>
        {currentWork.length === 0 ? (
          <div style={{ fontSize: 10, color: C.dim }}>waiting for active handoffs</div>
        ) : (
          currentWork.map((message) => (
            <div key={`current-${message.id}`} style={{ fontSize: 10, color: C.text, lineHeight: 1.5 }} title={message.summary}>
              <span style={{ color: C.teal, textTransform: 'uppercase' }}>{message.from}:</span> {message.summary}
            </div>
          ))
        )}
      </div>

      <div style={{ marginTop: 10, display: 'grid', gap: 8, maxHeight: 156, overflowY: 'auto', paddingRight: 2 }}>
        {items.length === 0 ? (
          <div style={{ fontSize: 11, color: C.dim }}>waiting for agent messages</div>
        ) : (
          items.map((message) => (
            <div
              key={message.id}
              style={{
                padding: '8px 9px',
                borderRadius: 8,
                border: '1px solid rgba(156,234,255,0.12)',
                background: 'rgba(255,255,255,0.03)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                <div style={{ fontSize: 9, color: C.cyan, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  {message.from} → {message.to}
                </div>
                <div style={{ fontSize: 8, color: C.dim }}>{formatTime(message.timestamp)}</div>
              </div>
              <div style={{ marginTop: 4, fontSize: 11, color: C.text, lineHeight: 1.5 }} title={message.summary}>{message.summary}</div>
              {message.details && (
                <div style={{ marginTop: 4, fontSize: 9, color: C.soft, lineHeight: 1.5 }} title={message.details}>
                  {message.details}
                </div>
              )}
              {message.files.length > 0 && (
                <div style={{ marginTop: 4, fontSize: 8, color: C.dim, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {message.files.join(' • ')}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(156,234,255,0.12)', display: 'grid', gap: 8 }}>
        <div style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          {composerOpen ? 'Direct handoff composer' : 'Composer collapsed to keep the board readable'}
        </div>
        {composerOpen && (
          <>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>From</span>
            <select value={fromAgent} onChange={(e) => setFromAgent(e.target.value)} style={inputStyle}>
              {availableAgents.map((agent) => (
                <option key={`from-${agent}`} value={agent}>{agent}</option>
              ))}
            </select>
          </label>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>To</span>
            <select value={toAgent} onChange={(e) => setToAgent(e.target.value)} style={inputStyle}>
              {availableAgents.map((agent) => (
                <option key={`to-${agent}`} value={agent}>{agent}</option>
              ))}
            </select>
          </label>
        </div>

        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>Summary</span>
          <input value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="what changed?" style={inputStyle} />
        </label>

        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>Details</span>
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            placeholder="technical note for the other agent"
            rows={2}
            style={{ ...inputStyle, resize: 'vertical', minHeight: 48 }}
          />
        </label>

        <label style={{ display: 'grid', gap: 4 }}>
          <span style={{ fontSize: 8, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>Files</span>
          <input value={files} onChange={(e) => setFiles(e.target.value)} placeholder="file1.tsx, file2.tsx" style={inputStyle} />
        </label>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 9, color: status === 'sent' ? C.green : status ? C.danger : C.dim }}>
            {status === 'sent' ? 'message sent' : status || 'local inbox composer'}
          </div>
          <button
            type="button"
            onClick={sendMessage}
            disabled={isSending || !summary.trim()}
            style={{
              border: `1px solid ${C.border}`,
              background: isSending ? 'rgba(255,255,255,0.06)' : 'rgba(120,224,255,0.12)',
              color: C.cyan,
              borderRadius: 6,
              padding: '6px 10px',
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              cursor: isSending ? 'default' : 'pointer',
            }}
          >
            {isSending ? 'Sending' : 'Send'}
          </button>
        </div>
          </>
        )}
      </div>
    </div>
  )
}
