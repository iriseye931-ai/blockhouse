import { useState, useEffect, useCallback, useRef, FormEvent } from 'react'

interface AmpMessage {
  id: string
  from: string
  subject: string
  timestamp: string
  status: string
  preview: string
  error?: string
}

interface ComposeState {
  recipient: string
  subject: string
  message: string
  type: string
}

const COMPOSE_DEFAULTS: ComposeState = {
  recipient: '',
  subject: '',
  message: '',
  type: 'notification',
}

const MSG_TYPES = ['notification', 'request', 'task']

function formatTs(ts: string): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

function StatusBadge({ status }: { status: string }) {
  const isUnread = status === 'unread'
  return (
    <span
      style={{
        fontSize: 8,
        padding: '1px 5px',
        borderRadius: 3,
        background: isUnread ? '#06b6d422' : '#1e293b',
        color: isUnread ? '#06b6d4' : '#475569',
        border: `1px solid ${isUnread ? '#06b6d444' : '#334155'}`,
        flexShrink: 0,
      }}
    >
      {isUnread ? 'unread' : 'read'}
    </span>
  )
}

function ComposeModal({
  onClose,
  onSent,
}: {
  onClose: () => void
  onSent: () => void
}) {
  const [form, setForm] = useState<ComposeState>(COMPOSE_DEFAULTS)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function update(field: keyof ComposeState) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((prev) => ({ ...prev, [field]: e.target.value }))
  }

  async function handleSend(e: FormEvent) {
    e.preventDefault()
    if (!form.recipient.trim() || !form.message.trim()) return
    setSending(true)
    setError(null)
    try {
      const res = await fetch('/api/amp/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const data = await res.json()
      if (!data.ok) {
        setError(data.error || 'Send failed')
      } else {
        setForm(COMPOSE_DEFAULTS)
        onSent()
        onClose()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSending(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    background: '#0a0a0f',
    border: '1px solid #1e293b',
    color: '#e2e8f0',
    borderRadius: 4,
    padding: '5px 8px',
    fontSize: 11,
    fontFamily: 'monospace',
    width: '100%',
    outline: 'none',
    boxSizing: 'border-box',
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 9,
    color: '#475569',
    fontFamily: 'monospace',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    marginBottom: 3,
    display: 'block',
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: '#0d0d1a',
          border: '1px solid #1e293b',
          borderRadius: 6,
          padding: '16px',
          width: 380,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Compose AMP
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#475569', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSend} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <label style={labelStyle}>To</label>
            <input
              type="text"
              value={form.recipient}
              onChange={update('recipient')}
              placeholder="hermes, iriseye, agent-a…"
              required
              style={inputStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>Subject</label>
            <input
              type="text"
              value={form.subject}
              onChange={update('subject')}
              placeholder="Subject"
              style={inputStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>Type</label>
            <select value={form.type} onChange={update('type')} style={{ ...inputStyle, cursor: 'pointer' }}>
              {MSG_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={labelStyle}>Message</label>
            <textarea
              value={form.message}
              onChange={update('message')}
              placeholder="Message body…"
              required
              rows={5}
              style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.5 }}
            />
          </div>

          {error && (
            <div style={{ fontSize: 10, color: '#ef4444', fontFamily: 'monospace', background: '#ef444411', border: '1px solid #ef444433', borderRadius: 3, padding: '4px 8px' }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                fontSize: 10, padding: '5px 12px', borderRadius: 4, border: '1px solid #334155',
                background: 'transparent', color: '#64748b', cursor: 'pointer', fontFamily: 'monospace',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={sending || !form.recipient.trim() || !form.message.trim()}
              style={{
                fontSize: 10, padding: '5px 12px', borderRadius: 4, border: 'none',
                background: sending ? '#06b6d466' : '#06b6d4', color: '#0a0a0f',
                cursor: sending ? 'not-allowed' : 'pointer', fontFamily: 'monospace',
                opacity: (!form.recipient.trim() || !form.message.trim()) ? 0.4 : 1,
              }}
            >
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

interface AmpEvent {
  agent: string
  ts: string
  id: string
  msg: string
}

type AmpView = 'messages' | 'events'

function routeColor(msg: string): string {
  if (msg.includes('route=hermes') || msg.includes('route=iriseye')) return '#a855f7'
  if (msg.includes('route=mlx')) return '#10b981'
  if (msg.includes('reply sent')) return '#06b6d4'
  return '#475569'
}

function EventsFeed() {
  const [events, setEvents] = useState<AmpEvent[]>([])
  const [loading, setLoading] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch('/api/amp/events')
      if (!res.ok) return
      const data = await res.json()
      setEvents(data.events ?? [])
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchEvents()
    const id = setInterval(fetchEvents, 10_000)
    return () => clearInterval(id)
  }, [fetchEvents])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  if (loading) return <p style={{ fontSize: 10, color: '#334155', padding: 10 }}>Loading…</p>
  if (events.length === 0) return <p style={{ fontSize: 10, color: '#334155', padding: 10 }}>No routing events yet — send an AMP message to see activity.</p>

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 3 }}>
      {[...events].reverse().map((ev, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '4px 0', borderBottom: '1px solid #0f172a' }}>
          <span style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', whiteSpace: 'nowrap', flexShrink: 0, paddingTop: 1 }}>
            {ev.ts.split(' ')[1] ?? ev.ts}
          </span>
          <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: '#1e293b', color: '#475569', flexShrink: 0, fontFamily: 'monospace' }}>
            {ev.agent}
          </span>
          <span style={{ fontSize: 9, color: routeColor(ev.msg), fontFamily: 'monospace', lineHeight: 1.4, wordBreak: 'break-all' }}>
            {ev.msg}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

export default function AmpInbox() {
  const [view, setView] = useState<AmpView>('events')
  const [messages, setMessages] = useState<AmpMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [composing, setComposing] = useState(false)

  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetch('/api/amp/messages')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMessages(data.messages ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load messages')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMessages()
    const interval = setInterval(fetchMessages, 30_000)
    return () => clearInterval(interval)
  }, [fetchMessages])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 10px', borderBottom: '1px solid #1e1e2e', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 0 }}>
          {(['events', 'messages'] as AmpView[]).map((v) => (
            <button key={v} onClick={() => setView(v)} style={{
              fontSize: 9, padding: '2px 10px', background: 'none',
              border: 'none', borderBottom: view === v ? '1px solid #06b6d4' : '1px solid transparent',
              color: view === v ? '#06b6d4' : '#334155', cursor: 'pointer',
              fontFamily: 'monospace', letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {v}
            </button>
          ))}
        </div>
        <button
          onClick={() => setComposing(true)}
          style={{ fontSize: 9, padding: '2px 8px', borderRadius: 3, background: '#06b6d411', color: '#06b6d4', border: '1px solid #06b6d433', cursor: 'pointer', fontFamily: 'monospace' }}
        >
          + Compose
        </button>
      </div>

      {view === 'events' && <EventsFeed />}

      {view === 'messages' && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {loading && <p style={{ fontSize: 10, color: '#334155', padding: 4 }}>Loading…</p>}
          {!loading && error && <p style={{ fontSize: 10, color: '#ef4444', fontFamily: 'monospace', padding: 4 }}>{error}</p>}
          {!loading && !error && messages.length === 0 && <p style={{ fontSize: 10, color: '#334155', padding: 4 }}>No messages in inbox.</p>}
          {messages.map((msg) => (
            <div key={msg.id || msg.timestamp} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 4, padding: '6px 8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                  <StatusBadge status={msg.status} />
                  <span style={{ fontSize: 9, color: '#94a3b8', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {msg.from || '?'}
                  </span>
                </div>
                <span style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', flexShrink: 0, marginLeft: 8 }}>
                  {formatTs(msg.timestamp)}
                </span>
              </div>
              {msg.subject && <p style={{ fontSize: 9, color: '#64748b', fontFamily: 'monospace', marginBottom: 2 }}>{msg.subject}</p>}
              {msg.preview && <p style={{ fontSize: 9, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5, wordBreak: 'break-word' }}>{msg.preview}</p>}
            </div>
          ))}
        </div>
      )}

      {composing && <ComposeModal onClose={() => setComposing(false)} onSent={fetchMessages} />}
    </div>
  )
}
