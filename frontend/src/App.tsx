import { useEffect, useRef, useState, useCallback, type CSSProperties } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useDashboardStore } from './store/dashboardStore'
import type { GraphSelection, SignalWatcherState, ServiceHealth } from './types'
import CrewStage from './components/CrewStage'
import AgentInbox from './components/AgentInbox'

// ── Color palette ─────────────────────────────────────────────────────────────

const C = {
  text: '#f4eeff',
  soft: '#9b85c8',
  dim: '#4a3568',
  cyan: '#e8d8ff',
  teal: '#b580ff',
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
        ctx.fillStyle = `rgba(190,150,255,${a})`
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
        background: 'radial-gradient(ellipse 70% 50% at 28% 62%, rgba(80,30,140,0.18), transparent)',
        animation: 'fog-breathe 12s ease-in-out infinite',
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 45% at 72% 38%, rgba(60,20,120,0.14), transparent)',
        animation: 'fog-breathe 16s ease-in-out infinite 5s',
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 80% 30% at 50% 90%, rgba(30,10,70,0.22), transparent)',
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

// ── Clock dot — minimal right-column indicator ────────────────────────────────

function ClockDot({ isConnected }: { isConnected: boolean }) {
  const lastUpdate = useDashboardStore((s) => s.lastUpdate)
  const [time, setTime] = useState(() => new Date().toLocaleTimeString())
  const [live, setLive] = useState(false)

  useEffect(() => {
    const id = setInterval(() => {
      setTime(new Date().toLocaleTimeString())
      setLive(lastUpdate ? Date.now() - lastUpdate.getTime() < 6000 : false)
    }, 1000)
    return () => clearInterval(id)
  }, [lastUpdate])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isConnected && live ? C.teal : C.dim,
          boxShadow: isConnected && live ? `0 0 8px ${C.teal}` : 'none',
          animation: !isConnected ? 'link-blink 1.4s ease-in-out infinite' : undefined,
        }} />
        <span style={{ fontSize: 18, color: C.text, letterSpacing: '0.06em', fontVariantNumeric: 'tabular-nums', fontFamily: '"Fira Code", monospace' }}>
          {time}
        </span>
      </div>
      {!isConnected && (
        <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
          reconnecting…
        </span>
      )}
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

// ── Mesh status bar — replaces StatusLegend + OpsStrip + AlertsLine + OpsUtilityBlock ──

function MeshStatusBar({ onSelect }: { onSelect: (s: GraphSelection) => void }) {
  const services = useDashboardStore((s) => s.services)
  const memorySummary = useDashboardStore((s) => s.memorySummary)
  const routingSummary = useDashboardStore((s) => s.routingSummary)

  type Alert = { text: string; tone: string; sel?: GraphSelection }
  const alerts: Alert[] = []

  for (const [key, svc] of Object.entries(services)) {
    if (svc.status === 'down' || svc.status === 'degraded') {
      const tone = svc.status === 'down' ? C.red : C.amber
      alerts.push({ text: `${svc.name ?? key} ${svc.status}`, tone, sel: { type: 'service', key, label: svc.name ?? key } })
    }
  }
  if (memorySummary?.primary_cause?.kind && memorySummary.primary_cause.kind !== 'healthy') {
    const kind = memorySummary.primary_cause.kind
    alerts.push({
      text: `memory ${kind}: ${memorySummary.primary_cause.summary}`,
      tone: kind === 'pressure' || kind === 'stale' ? C.amber : C.red,
      sel: { type: 'service', key: 'memory_mcp', label: 'Memory' },
    })
  }
  if (routingSummary?.warnings?.[0]) {
    alerts.push({ text: routingSummary.warnings[0].slice(0, 60), tone: C.amber })
  }

  if (alerts.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px' }}>
        <span style={{ width: 4, height: 4, borderRadius: '50%', background: C.green, boxShadow: `0 0 6px ${C.green}` }} />
        <span style={{ fontSize: 10, color: C.dim, letterSpacing: '0.2em', textTransform: 'uppercase' }}>Mesh nominal</span>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6,
      padding: '5px 10px',
      border: `1px solid ${alerts.some(a => a.tone === C.red) ? 'rgba(255,112,96,0.28)' : 'rgba(240,192,64,0.28)'}`,
      background: 'rgba(10,4,18,0.55)',
      maxWidth: 680,
    }}>
      {alerts.slice(0, 3).map((alert, i) => (
        <button
          key={i}
          type="button"
          onClick={() => alert.sel && onSelect(alert.sel)}
          style={{
            display: 'flex', alignItems: 'center', gap: 5,
            background: 'transparent', border: 'none', padding: 0, cursor: alert.sel ? 'pointer' : 'default',
          }}
        >
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: alert.tone, boxShadow: `0 0 5px ${alert.tone}`, flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: alert.tone, letterSpacing: '0.06em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 260 }}>
            {alert.text}
          </span>
        </button>
      ))}
      {alerts.length > 3 && (
        <span style={{ fontSize: 9, color: C.dim, letterSpacing: '0.14em', textTransform: 'uppercase' }}>
          +{alerts.length - 3}
        </span>
      )}
    </div>
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
      background: 'rgba(10,5,22,0.74)',
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

function fmtIn(secs: number | null | undefined) {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  return `${Math.floor(secs / 3600)}h`
}


// ── OS notifications ─────────────────────────────────────────────────────────

function useServiceNotifications() {
  const services = useDashboardStore((s) => s.services)
  const prevRef = useRef<Record<string, string>>({})
  const lastFiredRef = useRef<Record<string, number>>({})
  const DEBOUNCE_MS = 60_000

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  useEffect(() => {
    if (!('Notification' in window) || Notification.permission !== 'granted') return
    const prev = prevRef.current
    const now = Date.now()
    for (const [key, svc] of Object.entries(services) as [string, ServiceHealth][]) {
      const newStatus = svc.status
      const oldStatus = prev[key]
      if (oldStatus && oldStatus !== newStatus && (newStatus === 'down' || newStatus === 'degraded')) {
        const lastFired = lastFiredRef.current[key] ?? 0
        if (now - lastFired >= DEBOUNCE_MS) {
          new Notification(`Mesh alert: ${svc.name ?? key}`, {
            body: `Status changed to ${newStatus.toUpperCase()}`,
            tag: key,
          })
          lastFiredRef.current[key] = now
        }
      }
      prev[key] = newStatus
    }
    prevRef.current = { ...prev }
  }, [services])
}

// ── Timeline scrubber ────────────────────────────────────────────────────────

function TimelineScrubber() {
  const [replayMode, setReplayMode] = useState(false)
  const [replayLabel, setReplayLabel] = useState<string | null>(null)
  const [sliderVal, setSliderVal] = useState(100)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchSnapshot = useCallback(async (pct: number) => {
    if (pct >= 100) { setReplayMode(false); setReplayLabel(null); return }
    const now = Date.now()
    const earliest = now - 24 * 60 * 60 * 1000
    const targetMs = earliest + (pct / 100) * (now - earliest)
    const t = new Date(targetMs).toISOString()
    try {
      const res = await fetch(`/api/history?t=${encodeURIComponent(t)}`)
      const data = await res.json()
      if (data.snapshot) {
        setReplayMode(true)
        setReplayLabel(new Date(data.snapshot.ts).toLocaleTimeString())
      }
    } catch { /* silent */ }
  }, [])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value)
    setSliderVal(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchSnapshot(val), 300)
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '4px 10px',
      border: `1px solid ${replayMode ? 'rgba(240,192,64,0.4)' : 'rgba(160,100,255,0.14)'}`,
      background: replayMode ? 'rgba(20,12,2,0.55)' : 'rgba(8,4,16,0.36)',
      transition: 'border-color 0.2s, background 0.2s',
    }}>
      <span style={{ fontSize: 9, letterSpacing: '0.16em', color: replayMode ? C.amber : C.dim, textTransform: 'uppercase', whiteSpace: 'nowrap', minWidth: 48 }}>
        {replayMode ? `↩ ${replayLabel ?? '…'}` : 'Live'}
      </span>
      <input
        type="range" min={0} max={100} value={sliderVal}
        onChange={handleChange}
        style={{ width: 120, accentColor: replayMode ? C.amber : C.teal, cursor: 'pointer' }}
        title="Drag left to replay mesh history (24h)"
      />
      {replayMode && (
        <button
          onClick={() => { setSliderVal(100); setReplayMode(false); setReplayLabel(null) }}
          style={{ fontSize: 9, color: C.amber, background: 'none', border: 'none', cursor: 'pointer', letterSpacing: '0.1em', textTransform: 'uppercase', padding: 0 }}
        >
          ← Live
        </button>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const { isConnected } = useWebSocket()
  const system = useDashboardStore((s) => s.system)
  const agents = useDashboardStore((s) => s.agents)
  const [graphSelection, setGraphSelection] = useState<GraphSelection | null>(null)

  useServiceNotifications()

  const onlineAgents = agents.filter((a) => ['online', 'active', 'busy'].includes(a.status)).length

  return (
    <div
      className="h-screen overflow-hidden"
      style={{
        background: [
          'radial-gradient(circle at 50% 44%, rgba(140,80,255,0.16), transparent 18%)',
          'radial-gradient(circle at 50% 50%, rgba(90,40,200,0.09), transparent 36%)',
          'linear-gradient(180deg, #07030f 0%, #04010a 100%)',
        ].join(', '),
        color: C.text,
        fontFamily: '"Orbitron", ui-sans-serif, system-ui, sans-serif',
      }}
    >
      <div style={{ position: 'relative', width: '100%', height: '100%' }}>

        <VolumetricFog />
        <CrewStage />
        <FloatingParticles />

        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 4 }}>

          {/* Top bar — left: identity / center: single alert bar / right: clock dot */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0,
            display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            padding: '14px 20px 0',
            gap: 16,
          }}>
            <div style={{ pointerEvents: 'all' }}>
              <CommandHeader onlineAgents={onlineAgents} totalAgents={agents.length} />
            </div>
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', paddingTop: 6, pointerEvents: 'all' }}>
              <MeshStatusBar onSelect={setGraphSelection} />
            </div>
            <div style={{ pointerEvents: 'all' }}>
              <ClockDot isConnected={isConnected} />
            </div>
          </div>

          {/* Right rail — agent inbox */}
          <div style={{ position: 'absolute', top: 64, right: 20, pointerEvents: 'all' }}>
            <AgentInbox />
          </div>

          {/* Bottom strip — hover to reveal */}
          <div
            style={{
              position: 'absolute', bottom: 16, left: 0, right: 0,
              display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10,
              flexWrap: 'wrap',
              opacity: 0,
              transition: 'opacity 0.25s ease',
              pointerEvents: 'all',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = '1' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = '0' }}
          >
            <StatPill label="System Memory" value={system?.ram_pct != null ? `${Math.round(system.ram_pct)}%` : '—'} sub={system ? `${system.ram_used_gb}/${system.ram_total_gb} GB` : undefined} />
            <StatPill label="MLX Memory"    value={system?.mlx_ram_pct != null ? `${Math.round(system.mlx_ram_pct)}%` : '—'} sub={system?.mlx_ram_gb ? `${system.mlx_ram_gb} GB` : undefined} />
            <StatPill label="CPU Load"      value={system?.cpu_pct != null ? `${Math.round(system.cpu_pct)}%` : '—'} sub={system?.load_1m ? `${system.load_1m} avg` : undefined} />
            <StatPill label="Disk"          value={system?.disk_pct != null ? `${Math.round(system.disk_pct)}%` : '—'} sub={system ? `${system.disk_used_gb}/${system.disk_total_gb} GB` : undefined} warn={system?.disk_pct != null && system.disk_pct > 85} />
            <StatPill label="Mesh Online"   value={`${onlineAgents}/${agents.length || '—'}`} sub={system?.uptime_seconds ? `UP ${formatUptime(system.uptime_seconds)}` : undefined} />
            <TimelineScrubber />
          </div>

        </div>
      </div>
    </div>
  )
}
