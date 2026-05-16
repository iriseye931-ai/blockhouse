import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useDashboardStore } from './store/dashboardStore'
import type { GraphSelection } from './types'
import MeshGraph from './components/MeshGraph'

// ── Color palette ─────────────────────────────────────────────────────────────

const C = {
  text: '#effcff',
  soft: '#7aabbd',
  dim: '#345668',
  cyan: '#dffbff',
  teal: '#9aefff',
  // status — canonical; keep in sync with MeshGraph STATUS_COLORS
  green: '#79ff98',
  amber: '#f0c040',
  red: '#ff7060',
}

// ── Floating particles (canvas) ───────────────────────────────────────────────

interface Particle {
  x: number; y: number; vx: number; vy: number
  r: number; alpha: number; life: number; decay: number
}

function FloatingParticles() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    const mkParticle = (w: number, h: number): Particle => ({
      x: Math.random() * w,
      y: Math.random() * h + h * 0.1,
      vx: (Math.random() - 0.5) * 0.25,
      vy: -Math.random() * 0.35 - 0.08,
      r: Math.random() * 1.4 + 0.2,
      alpha: Math.random() * 0.45 + 0.05,
      life: 1,
      decay: 0.0008 + Math.random() * 0.0012,
    })

    const particles: Particle[] = Array.from({ length: 70 }, (_, i) => {
      const p = mkParticle(canvas.width, canvas.height)
      p.life = i / 70
      return p
    })

    let id: number
    const frame = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy; p.life -= p.decay
        if (p.life <= 0 || p.y < -10) {
          Object.assign(p, mkParticle(canvas.width, canvas.height))
          p.y = canvas.height + 4
          p.life = 1
        }
        const a = p.alpha * Math.min(p.life * 4, 1)
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(165,235,255,${a})`
        ctx.fill()
      }
      id = requestAnimationFrame(frame)
    }
    frame()
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(id) }
  }, [])

  return (
    <canvas ref={ref} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }} />
  )
}

// ── Volumetric fog ────────────────────────────────────────────────────────────

function VolumetricFog() {
  return (
    <>
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 70% 50% at 28% 62%, rgba(16,60,130,0.15), transparent)',
        animation: 'fog-breathe 12s ease-in-out infinite',
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 45% at 72% 38%, rgba(10,50,120,0.12), transparent)',
        animation: 'fog-breathe 16s ease-in-out infinite 5s',
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 80% 30% at 50% 90%, rgba(8,30,80,0.18), transparent)',
      }} />
    </>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatUptime(s: number): string {
  if (!s || s < 0) return '—'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function shortModelName(raw: string | undefined): string | null {
  if (!raw) return null
  const base = raw.split('/').pop() ?? raw
  return base.replace(/-4bit$/i, '').replace(/_4bit$/i, '').slice(0, 22)
}

// ── Telemetry stamp (top-right) ───────────────────────────────────────────────

function TelemetryStamp({ isConnected }: { isConnected: boolean }) {
  const lastUpdate = useDashboardStore((s) => s.lastUpdate)
  const system = useDashboardStore((s) => s.system)
  const llmActive = useDashboardStore((s) => s.llmActive)
  const services = useDashboardStore((s) => s.services)
  const [time, setTime] = useState(() => new Date().toLocaleTimeString())
  const [live, setLive] = useState(false)

  useEffect(() => {
    const id = setInterval(() => {
      setTime(new Date().toLocaleTimeString())
      setLive(lastUpdate ? Date.now() - lastUpdate.getTime() < 6000 : false)
    }, 1000)
    return () => clearInterval(id)
  }, [lastUpdate])

  const uptime = system?.uptime_seconds ? formatUptime(system.uptime_seconds) : null
  const modelName = shortModelName(services.mlx_server?.active_model ?? services.mlx_server?.models?.[0])
  const backendLabel = llmActive ? llmActive.toUpperCase() : 'LLM'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 8px',
          border: '1px solid rgba(156,234,255,0.22)',
          background: 'linear-gradient(180deg, rgba(5,14,22,0.78), rgba(4,10,16,0.62))',
          color: '#effcff',
          fontSize: 12,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}
        title={modelName ?? undefined}
      >
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: llmActive ? '#9aefff' : '#86979f', boxShadow: llmActive ? '0 0 8px rgba(154,239,255,0.75)' : 'none' }} />
        <span style={{ color: llmActive ? '#9aefff' : C.soft }}>{backendLabel}</span>
        {modelName ? <span style={{ color: '#effcff', textTransform: 'none', letterSpacing: '0.03em' }}>{modelName}</span> : null}
      </div>
      {uptime && (
        <span style={{ fontSize: 10, letterSpacing: '0.14em', color: C.dim, textTransform: 'uppercase' }}>
          UP {uptime}
        </span>
      )}
      <span style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: isConnected && live ? C.teal : C.dim, animation: !isConnected ? 'link-blink 1.4s ease-in-out infinite' : undefined }}>
        {isConnected ? 'TELEMETRY LIVE' : 'RECONNECTING…'}
      </span>
      <span style={{ fontSize: 20, color: C.text, letterSpacing: '0.08em', fontVariantNumeric: 'tabular-nums', fontFamily: '"Fira Code", monospace' }}>
        {time}
      </span>
    </div>
  )
}

function CommandHeader({ onlineAgents, totalAgents }: { onlineAgents: number; totalAgents: number }) {
  return (
    <div
      style={{
        display: 'grid',
        gap: 1,
        padding: '2px 0',
      }}
    >
      <div style={{ fontSize: 11, color: C.dim, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
        Mission Control
      </div>
      <div style={{ fontSize: 19, color: C.soft, letterSpacing: '0.09em', textTransform: 'uppercase' }}>
        Agent Mesh
      </div>
      <div style={{ fontSize: 11, color: C.dim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
        {onlineAgents}/{totalAgents || 0} online
      </div>
    </div>
  )
}

function StatusLegend() {
  const items = [
    { label: 'online', color: C.green },
    { label: 'degraded', color: C.amber },
    { label: 'offline', color: C.red },
  ]

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 9px',
        border: '1px solid rgba(120,210,255,0.14)',
        background: 'rgba(4,10,16,0.36)',
      }}
    >
      <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
        States
      </span>
      {items.map((item) => (
        <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: C.dim, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: item.color, boxShadow: `0 0 6px ${item.color}` }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}

function Sparkline({ points }: { points: { up: boolean }[] | undefined }) {
  if (!points || points.length < 2) return null
  const w = 40
  const h = 10
  const step = w / Math.max(points.length - 1, 1)
  const coords = points
    .map((point, index) => `${index * step},${point.up ? 1.5 : h - 1.5}`)
    .join(' ')
  const stroke = points[points.length - 1]?.up ? C.green : C.red

  return (
    <svg width={w} height={h} style={{ display: 'block', flexShrink: 0 }}>
      <polyline
        points={coords}
        fill="none"
        stroke={stroke}
        strokeWidth="1"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

// ── Bottom stat pills ─────────────────────────────────────────────────────────

function StatPill({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  const pctMatch = value.match(/^(\d+(\.\d+)?)%$/)
  const numericPct = pctMatch ? parseFloat(pctMatch[1]) : null
  const accent = warn || (numericPct != null && numericPct > 85)
    ? '#ffb04d'
    : numericPct != null && numericPct > 70
      ? C.amber
      : '#7ee8ff'
  const [pulsing, setPulsing] = useState(false)
  const prevValue = useRef(value)
  useEffect(() => {
    if (prevValue.current !== value && prevValue.current !== '') {
      setPulsing(true)
      const t = setTimeout(() => setPulsing(false), 400)
      prevValue.current = value
      return () => clearTimeout(t)
    }
    prevValue.current = value
  }, [value])
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
      padding: '6px 14px 7px',
      borderRadius: 0,
      border: `1px solid ${warn || (numericPct != null && numericPct > 85) ? 'rgba(255,176,77,0.44)' : numericPct != null && numericPct > 70 ? 'rgba(240,192,64,0.4)' : 'rgba(100,210,255,0.34)'}`,
      background: 'rgba(4,12,28,0.72)',
      backdropFilter: 'blur(14px)',
      WebkitBackdropFilter: 'blur(14px)',
      minWidth: 100,
    }}>
      <span style={{ fontSize: 10, letterSpacing: '0.2em', color: C.soft, textTransform: 'uppercase', marginBottom: 3 }}>{label}</span>
      <span style={{ fontSize: 24, color: accent, fontWeight: 700, letterSpacing: '0.04em', lineHeight: 1, fontFamily: '"Fira Code", monospace', animation: pulsing ? 'stat-pulse 0.4s ease-out' : undefined }}>{value}</span>
      {sub && <span style={{ fontSize: 10, color: C.dim, letterSpacing: '0.1em', marginTop: 3 }}>{sub}</span>}
    </div>
  )
}

function OpsStrip({ onSelect }: { onSelect: (selection: GraphSelection) => void }) {
  const services = useDashboardStore((s) => s.services)
  const serviceHistory = useDashboardStore((s) => s.serviceHistory)
  const routingSummary = useDashboardStore((s) => s.routingSummary)
  const memorySummary = useDashboardStore((s) => s.memorySummary)

  const serviceItems = [
    ['Gateway', 'openviking', services.openviking?.status],
    ['Memory', 'memory_mcp', services.memory_mcp?.status],
    ['MLX', 'mlx_server', services.mlx_server?.status],
    ['OpenClaw', 'openclaw_mcp', services.openclaw_mcp?.status],
    ['AMP', 'aimaestro', services.aimaestro?.status],
  ] as const satisfies ReadonlyArray<readonly [string, string, string | undefined]>

  const historyKeys: Record<string, string> = {
    Gateway: 'openviking',
    Memory: 'memory_mcp',
    MLX: 'mlx_server',
    OpenClaw: 'openclaw_mcp',
    AMP: 'aimaestro',
  }

  const toneFor = (status?: string) =>
    status === 'up' || status === 'healthy' ? C.green : status === 'down' ? C.red : C.amber

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
        padding: '8px 12px',
        border: '1px solid rgba(120,210,255,0.14)',
        background: 'rgba(4,10,16,0.34)',
      }}
    >
      <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
        Ops
      </span>
      {serviceItems.map(([label, serviceKey, status]) => (
        <button
          key={label}
          type="button"
          onClick={() => onSelect({ type: 'service', key: serviceKey, label })}
          style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.soft, letterSpacing: '0.1em', textTransform: 'uppercase', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }}
        >
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: toneFor(status), boxShadow: `0 0 6px ${toneFor(status)}` }} />
          {label}
          <Sparkline points={serviceHistory[historyKeys[label]]} />
        </button>
      ))}
      <span style={{ width: 1, height: 12, background: 'rgba(120,210,255,0.12)' }} />
      <button
        type="button"
        onClick={() => onSelect({ type: 'service', key: 'memory_mcp', label: 'Memory' })}
        style={{ fontSize: 11, color: C.soft, letterSpacing: '0.1em', textTransform: 'uppercase', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }}
        title="View memory service details"
      >
        MEM · {routingSummary?.memory_mode ?? memorySummary?.primary_cause?.kind ?? 'healthy'}
      </button>
      <button
        type="button"
        onClick={() => onSelect({ type: 'agent', key: (routingSummary?.guidance?.memory_heavy ?? 'hermes').toLowerCase(), label: routingSummary?.guidance?.memory_heavy ?? 'Hermes' })}
        style={{ fontSize: 11, color: C.soft, letterSpacing: '0.1em', textTransform: 'uppercase', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer' }}
        title="View active routing agent"
      >
        VIA → {routingSummary?.guidance?.memory_heavy ?? '—'}{routingSummary?.guidance?.memory_heavy?.toLowerCase() === 'hermes' && routingSummary?.profile_guidance?.memory_heavy ? ` · ${routingSummary.profile_guidance.memory_heavy}` : ''}
      </button>
    </div>
  )
}

function AlertsLine() {
  const services = useDashboardStore((s) => s.services)
  const routingSummary = useDashboardStore((s) => s.routingSummary)
  const memorySummary = useDashboardStore((s) => s.memorySummary)

  const alerts: Array<{ text: string; tone: string }> = []
  if (memorySummary?.primary_cause?.kind && memorySummary.primary_cause.kind !== 'healthy') {
    alerts.push({
      text: `memory ${memorySummary.primary_cause.kind}: ${memorySummary.primary_cause.summary}`,
      tone: memorySummary.primary_cause.kind === 'pressure' || memorySummary.primary_cause.kind === 'stale' ? C.amber : C.red,
    })
  }
  if (services.hermes_gateway?.status === 'degraded' || services.hermes_gateway?.status === 'down') {
    alerts.push({
      text: `hermes gateway ${services.hermes_gateway.status}`,
      tone: services.hermes_gateway.status === 'down' ? C.red : C.amber,
    })
  }
  if (routingSummary?.warnings?.length) {
    alerts.push({ text: routingSummary.warnings[0], tone: C.amber })
  }

  const primary = alerts[0]
  if (!primary) return null

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        maxWidth: 520,
        padding: '7px 11px',
        border: '1px solid rgba(120,210,255,0.12)',
        background: 'rgba(4,10,16,0.28)',
      }}
    >
      <span style={{ fontSize: 9, color: primary.tone, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
        Alert
      </span>
      <span style={{ fontSize: 11, color: C.soft, letterSpacing: '0.06em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {primary.text}
      </span>
      {alerts.length > 1 && (
        <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.14em', textTransform: 'uppercase', flexShrink: 0 }}>
          +{alerts.length - 1} more
        </span>
      )}
    </div>
  )
}

function fmtIn(secs: number | null | undefined) {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  return `${Math.floor(secs / 3600)}h`
}

function OpsUtilityBlock({ onSelect }: { onSelect: (selection: GraphSelection) => void }) {
  const cronJobs = useDashboardStore((s) => s.cronJobs)
  const permissionAuditSummary = useDashboardStore((s) => s.permissionAuditSummary)
  const agentMessages = useDashboardStore((s) => s.agentMessages)
  const memorySummary = useDashboardStore((s) => s.memorySummary)
  const [expanded, setExpanded] = useState(false)

  const nextJob = cronJobs
    .filter((job) => job.enabled !== false && job.next_run_in_seconds != null)
    .sort((a, b) => (a.next_run_in_seconds ?? Infinity) - (b.next_run_in_seconds ?? Infinity))[0]

  const denyCount = permissionAuditSummary?.decision_counts?.deny ?? 0
  const askCount = permissionAuditSummary?.decision_counts?.ask ?? 0
  const memoryAlerts = memorySummary?.warnings?.length ?? 0

  const summaryItems: Array<[string, string, GraphSelection]> = [
    ['Next cron', nextJob ? `${nextJob.name.slice(0, 12)} · ${fmtIn(nextJob.next_run_in_seconds)}` : 'idle', { type: 'agent', key: 'hermes', label: 'Hermes' }],
    ['Audit', `${denyCount} deny · ${askCount} ask`, { type: 'agent', key: 'atlas', label: 'Lead' }],
    ['Queue', `${agentMessages.length} msgs`, { type: 'service', key: 'aimaestro', label: 'AMP' }],
    ['Memory', `${memoryAlerts} alerts`, { type: 'service', key: 'memory_mcp', label: 'Memory' }],
  ]

  return (
    <div
      style={{
        pointerEvents: 'all',
        minWidth: expanded ? 220 : 170,
        border: '1px solid rgba(120,210,255,0.14)',
        background: 'rgba(4,10,16,0.34)',
        padding: '9px 12px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
          Operator
        </span>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          style={{
            border: 'none',
            background: 'transparent',
            color: C.soft,
            cursor: 'pointer',
            fontSize: 10,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            padding: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          {!expanded && (denyCount > 0 || memoryAlerts > 0) && (
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: denyCount > 0 ? C.red : C.amber, boxShadow: `0 0 6px ${denyCount > 0 ? C.red : C.amber}` }} />
          )}
          {expanded ? 'collapse' : 'expand'}
        </button>
      </div>

      <div style={{ display: 'grid', gap: 4, marginTop: 6 }}>
        {summaryItems.map(([label, value, selection]) => (
          <button
            key={label}
            type="button"
            onClick={() => onSelect(selection)}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 10, background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left' }}
          >
            <span style={{ fontSize: 10, color: C.dim, letterSpacing: '0.14em', textTransform: 'uppercase' }}>{label}</span>
            <span style={{ fontSize: 11, color: C.soft, letterSpacing: '0.05em', textAlign: 'right' }}>{value}</span>
          </button>
        ))}
      </div>

      {expanded ? (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(120,210,255,0.1)', display: 'grid', gap: 5 }}>
          {nextJob ? (
            <div style={{ fontSize: 10, color: C.soft, lineHeight: 1.5 }}>
              cron target: <span style={{ color: C.text }}>{nextJob.name}</span>
            </div>
          ) : null}
          <div style={{ fontSize: 10, color: C.soft, lineHeight: 1.5 }}>
            audit posture: <span style={{ color: C.text }}>{denyCount > 0 || askCount > 0 ? 'active approvals' : 'quiet'}</span>
          </div>
          <div style={{ fontSize: 10, color: C.soft, lineHeight: 1.5 }}>
            queue state: <span style={{ color: C.text }}>{agentMessages.length > 0 ? 'traffic present' : 'clear'}</span>
          </div>
        </div>
      ) : null}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const { isConnected } = useWebSocket()
  const system = useDashboardStore((s) => s.system)
  const agents = useDashboardStore((s) => s.agents)
  const [graphSelection, setGraphSelection] = useState<GraphSelection | null>(null)

  const onlineAgents = agents.filter((a) => ['online', 'active', 'busy'].includes(a.status)).length

  return (
    <div
      className="h-screen overflow-hidden"
      style={{
        background: [
          'radial-gradient(circle at 50% 44%, rgba(130,215,255,0.17), transparent 18%)',
          'radial-gradient(circle at 50% 50%, rgba(90,180,255,0.09), transparent 36%)',
          'linear-gradient(180deg, #020609 0%, #010203 100%)',
        ].join(', '),
        color: C.text,
        fontFamily: '"Orbitron", ui-sans-serif, system-ui, sans-serif',
      }}
    >
      <div style={{ position: 'relative', width: '100%', height: '100%' }}>

        {/* Volumetric fog — behind sphere */}
        <VolumetricFog />

        {/* Central sphere with built-in HUD panels */}
        <MeshGraph selected={graphSelection} onSelectionChange={setGraphSelection} />

        {/* Floating particles — above sphere */}
        <FloatingParticles />

        {/* Top bar + bottom stat strip — above particles */}
        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 4 }}>

          {/* Top bar */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0,
            display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            padding: '12px 18px 0',
            gap: 16,
          }}>
            <div style={{ flex: 1.1, maxWidth: 140, pointerEvents: 'all' }}>
              <CommandHeader onlineAgents={onlineAgents} totalAgents={agents.length} />
            </div>
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', paddingTop: 4 }}>
              <div style={{ display: 'grid', gap: 6, justifyItems: 'center', width: 'min(720px, 100%)' }}>
                <StatusLegend />
                <OpsStrip onSelect={setGraphSelection} />
                <AlertsLine />
                <OpsUtilityBlock onSelect={setGraphSelection} />
              </div>
            </div>
            <div style={{ flex: 1.1, display: 'flex', justifyContent: 'flex-end', pointerEvents: 'all' }}>
              <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
                <TelemetryStamp isConnected={isConnected} />
              </div>
            </div>
          </div>

          {/* Bottom stat strip */}
          <div style={{
            position: 'absolute', bottom: 16, left: 0, right: 0,
            display: 'flex', justifyContent: 'center', gap: 10,
            flexWrap: 'wrap',
          }}>
            <StatPill label="System Memory" value={system?.ram_pct != null ? `${Math.round(system.ram_pct)}%` : '—'} sub={system ? `${system.ram_used_gb}/${system.ram_total_gb} GB` : undefined} />
            <StatPill label="MLX Memory"    value={system?.mlx_ram_pct != null ? `${Math.round(system.mlx_ram_pct)}%` : '—'} sub={system?.mlx_ram_gb ? `${system.mlx_ram_gb} GB` : undefined} />
            <StatPill label="CPU Load"      value={system?.cpu_pct != null ? `${Math.round(system.cpu_pct)}%` : '—'} sub={system?.load_1m ? `${system.load_1m} avg` : undefined} />
            <StatPill label="Disk"          value={system?.disk_pct != null ? `${Math.round(system.disk_pct)}%` : '—'} sub={system ? `${system.disk_used_gb}/${system.disk_total_gb} GB` : undefined} warn={system?.disk_pct != null && system.disk_pct > 85} />
            <StatPill label="Mesh Online"   value={`${onlineAgents}/${agents.length || '—'}`} sub={system?.uptime_seconds ? `UP ${formatUptime(system.uptime_seconds)}` : undefined} />
          </div>

        </div>
      </div>
    </div>
  )
}
