import { useEffect, useRef, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { CrewMember, CrewEvent, CrewStatus } from '../types'

// ── Palette (identity colors follow the agent, status colors reserved) ───────

const INK = { text: '#f4eeff', soft: '#9b85c8', dim: '#4a3568' }
const STATUS: Record<CrewStatus, string> = {
  idle: '#5a4a78',
  thinking: '#7ee8ff',
  working: '#79ff98',
  talking: '#b580ff',
  waiting: '#f0c040',
}

interface AgentSkin {
  accent: string      // identity color — helmet, console trim
  suit: string
  suitShade: string
  visor: string
  glow: string
}

const SKINS: Record<string, AgentSkin> = {
  atlas: {
    accent: '#b580ff', suit: '#3d2a66', suitShade: '#2a1c4a',
    visor: '#e8d8ff', glow: 'rgba(181,128,255,0.55)',
  },
  hermes: {
    accent: '#f0b840', suit: '#5a4420', suitShade: '#3d2e14',
    visor: '#ffe9b8', glow: 'rgba(240,184,64,0.55)',
  },
}

// Anchor positions as fractions of the canvas (Atlas left, Hermes right)
const ANCHORS: Record<string, { x: number; y: number; flip: boolean }> = {
  atlas: { x: 0.335, y: 0.60, flip: false },
  hermes: { x: 0.665, y: 0.60, flip: true },
}

const PX = 5 // logical pixel size — everything is drawn on a chunky grid

// ── Canvas scene ──────────────────────────────────────────────────────────────

/** Fill a rect on the chunky-pixel grid, optionally mirrored around cx. */
function px(ctx: CanvasRenderingContext2D, cx: number, baseY: number, gx: number, gy: number,
            gw: number, gh: number, color: string, flip: boolean) {
  const x = flip ? cx - (gx + gw) * PX : cx + gx * PX
  ctx.fillStyle = color
  ctx.fillRect(Math.round(x), Math.round(baseY + gy * PX), gw * PX, gh * PX)
}

function drawAgent(ctx: CanvasRenderingContext2D, cx: number, groundY: number,
                   skin: AgentSkin, status: CrewStatus, t: number, flip: boolean) {
  const working = status === 'working'
  const bobSpeed = working ? 7 : status === 'thinking' ? 3 : 1.6
  const bob = Math.round(Math.sin(t * bobSpeed) * (working ? 1 : 1.4))
  const y = groundY - 30 * PX + bob * 2

  const P = (gx: number, gy: number, gw: number, gh: number, c: string) =>
    px(ctx, cx, y, gx, gy, gw, gh, c, flip)

  // glow pad under feet
  const grd = ctx.createRadialGradient(cx, groundY + 4, 2, cx, groundY + 4, 60)
  grd.addColorStop(0, skin.glow)
  grd.addColorStop(1, 'transparent')
  ctx.fillStyle = grd
  ctx.beginPath()
  ctx.ellipse(cx, groundY + 4, 60, 12, 0, 0, Math.PI * 2)
  ctx.fill()

  // legs
  P(-3, 24, 2.6, 6, skin.suitShade)
  P(0.6, 24, 2.6, 6, skin.suitShade)
  P(-3.4, 29.4, 3.4, 1.4, '#151022')   // boots
  P(0.4, 29.4, 3.4, 1.4, '#151022')

  // torso (lego-brick taper: wider at shoulders)
  P(-4.4, 14, 8.8, 10, skin.suit)
  P(-4.4, 14, 8.8, 1.2, skin.accent)         // shoulder line
  P(-1, 16, 2, 5, skin.suitShade)            // chest panel
  P(-0.6, 16.4, 1.2, 1.2, STATUS[status])    // status LED on chest

  // arms — type at the console when working
  const armPhase = Math.sin(t * 13)
  if (working) {
    const lY = 19 + (armPhase > 0 ? 0.6 : 0)
    const rY = 19 + (armPhase > 0 ? 0 : 0.6)
    P(-6.4, 15, 2, 4, skin.suit)             // upper arms
    P(4.4, 15, 2, 4, skin.suit)
    P(-6.4, lY, 4, 1.8, skin.suit)           // forearms reach forward
    P(2.4, rY, 4, 1.8, skin.suit)
    P(-3, lY + 0.2, 1.4, 1.4, '#ffd9b8')     // hands
    P(1.6, rY + 0.2, 1.4, 1.4, '#ffd9b8')
  } else {
    P(-6.4, 15, 2, 8.4, skin.suit)
    P(4.4, 15, 2, 8.4, skin.suit)
    P(-6.2, 22.6, 1.6, 1.6, '#ffd9b8')
    P(4.6, 22.6, 1.6, 1.6, '#ffd9b8')
  }

  // head — blocky, with the lego stud on top
  P(-3.4, 4, 6.8, 8.4, '#ffd9b8')            // face block
  P(-3.4, 4, 6.8, 2.2, skin.accent)          // helmet brow
  P(-2, 1.8, 4, 2.2, skin.accent)            // stud
  P(-3.8, 5, 0.8, 6, skin.accent)            // helmet sides
  P(3.0, 5, 0.8, 6, skin.accent)

  // eyes — blink every ~4s; look down while working, up while thinking
  const blink = (t % 4) > 3.82
  const eyeY = 7.6 + (working ? 0.8 : status === 'thinking' ? -0.4 : 0)
  if (!blink) {
    P(-2, eyeY, 1.2, 1.6, '#241a38')
    P(1, eyeY, 1.2, 1.6, '#241a38')
  } else {
    P(-2, eyeY + 0.8, 1.2, 0.5, '#241a38')
    P(1, eyeY + 0.8, 1.2, 0.5, '#241a38')
  }
  // mouth
  P(-0.8, 10.6, 1.8, 0.6, status === 'talking' && Math.sin(t * 10) > 0 ? '#7a3a3a' : '#c9977a')
}

function drawConsole(ctx: CanvasRenderingContext2D, cx: number, groundY: number,
                     skin: AgentSkin, active: boolean, t: number, flip: boolean) {
  const y = groundY - 30 * PX
  const P = (gx: number, gy: number, gw: number, gh: number, c: string) =>
    px(ctx, cx, y, gx, gy, gw, gh, c, flip)

  // desk sits in front of the agent (toward center)
  P(7, 20, 10, 1.6, '#241a3d')               // desk top
  P(7.6, 21.6, 1.4, 8.6, '#1a1230')          // legs
  P(15, 21.6, 1.4, 8.6, '#1a1230')
  // monitor
  P(8.4, 11, 8, 8, '#100a20')
  P(8.9, 11.5, 7, 7, active ? '#0d1f16' : '#0d0a18')
  P(11.6, 19, 1.6, 1.2, '#1a1230')           // stand
  P(8.4, 11, 8, 0.6, skin.accent)            // trim

  if (active) {
    // scrolling code lines
    ctx.save()
    for (let i = 0; i < 5; i++) {
      const lineT = (t * 2 + i * 0.9) % 4.5
      const w = 2 + ((i * 37 + Math.floor(t)) % 4)
      if (lineT < 4) {
        P(9.3, 12.1 + lineT * 1.3, w, 0.55, i % 3 === 0 ? skin.accent : '#79ff98')
      }
    }
    ctx.restore()
    // screen glow
    const g = ctx.createRadialGradient(
      flip ? cx - 12.4 * PX : cx + 12.4 * PX, y + 15 * PX, 4,
      flip ? cx - 12.4 * PX : cx + 12.4 * PX, y + 15 * PX, 55)
    g.addColorStop(0, 'rgba(121,255,152,0.14)')
    g.addColorStop(1, 'transparent')
    ctx.fillStyle = g
    ctx.fillRect(cx - 120, y, 240, 200)
  }
}

function drawThoughtDots(ctx: CanvasRenderingContext2D, cx: number, groundY: number, t: number, color: string) {
  const y = groundY - 34 * PX
  for (let i = 0; i < 3; i++) {
    const phase = Math.sin(t * 4 - i * 0.9)
    ctx.globalAlpha = 0.35 + Math.max(0, phase) * 0.65
    ctx.fillStyle = color
    ctx.fillRect(cx - 12 + i * 12, y - Math.max(0, phase) * 4, 6, 6)
  }
  ctx.globalAlpha = 1
}

function drawWaitingMark(ctx: CanvasRenderingContext2D, cx: number, groundY: number, t: number) {
  const y = groundY - 35 * PX + Math.sin(t * 5) * 3
  ctx.fillStyle = STATUS.waiting
  ctx.fillRect(cx - 2, y - 14, 5, 10)
  ctx.fillRect(cx - 2, y, 5, 4)
}

function drawFloor(ctx: CanvasRenderingContext2D, w: number, h: number, groundY: number, t: number) {
  // perspective grid
  ctx.strokeStyle = 'rgba(120,80,200,0.10)'
  ctx.lineWidth = 1
  const vpX = w / 2, vpY = groundY - 140
  for (let i = -14; i <= 14; i++) {
    ctx.beginPath()
    ctx.moveTo(vpX, vpY)
    ctx.lineTo(w / 2 + i * (w / 16), h)
    ctx.stroke()
  }
  for (let i = 0; i < 6; i++) {
    const yy = groundY + 8 + i * i * 9
    if (yy > h) break
    ctx.beginPath()
    ctx.moveTo(0, yy)
    ctx.lineTo(w, yy)
    ctx.stroke()
  }
  // center emblem ring
  ctx.save()
  ctx.translate(w / 2, groundY + 26)
  ctx.scale(1, 0.32)
  ctx.strokeStyle = 'rgba(150,100,255,0.22)'
  ctx.lineWidth = 2
  ctx.beginPath(); ctx.arc(0, 0, 74, 0, Math.PI * 2); ctx.stroke()
  ctx.strokeStyle = 'rgba(150,100,255,0.10)'
  ctx.beginPath(); ctx.arc(0, 0, 96, t % (Math.PI * 2), (t % (Math.PI * 2)) + 4.4); ctx.stroke()
  ctx.restore()
}

/** Data beam between consoles when someone is talking. */
function drawLinkBeam(ctx: CanvasRenderingContext2D, w: number, groundY: number, t: number, from: string) {
  const y = groundY - 16 * PX
  const x0 = w * (from === 'atlas' ? ANCHORS.atlas.x : ANCHORS.hermes.x)
  const x1 = w * (from === 'atlas' ? ANCHORS.hermes.x : ANCHORS.atlas.x)
  const skin = SKINS[from] ?? SKINS.atlas
  for (let i = 0; i < 5; i++) {
    const p = ((t * 0.55 + i / 5) % 1)
    const x = x0 + (x1 - x0) * p
    const arc = Math.sin(p * Math.PI) * 40
    ctx.globalAlpha = Math.sin(p * Math.PI) * 0.9
    ctx.fillStyle = skin.accent
    ctx.fillRect(x - 2, y - arc - 60, 5, 5)
  }
  ctx.globalAlpha = 1
}

// ── Speech bubble / status plate overlays (HTML for crisp text) ───────────────

interface Bubble { agent: string; text: string; until: number }

function SpeechBubble({ bubble, side }: { bubble: Bubble; side: 'left' | 'right' }) {
  const skin = SKINS[bubble.agent] ?? SKINS.atlas
  return (
    <div style={{
      position: 'absolute',
      bottom: 'calc(34% + 170px)',
      ...(side === 'left'
        ? { left: `calc(${ANCHORS.atlas.x * 100}% - 130px)` }
        : { right: `calc(${(1 - ANCHORS.hermes.x) * 100}% - 130px)` }),
      maxWidth: 260,
      padding: '9px 12px',
      background: 'rgba(12,6,24,0.92)',
      border: `1px solid ${skin.accent}`,
      boxShadow: `0 0 18px ${skin.glow}`,
      color: INK.text,
      fontSize: 12,
      lineHeight: 1.45,
      fontFamily: '"Fira Code", monospace',
      animation: 'bubble-in 0.18s ease-out',
      zIndex: 6,
    }}>
      <div style={{ fontSize: 9, letterSpacing: '0.18em', color: skin.accent, textTransform: 'uppercase', marginBottom: 3 }}>
        {bubble.agent} · amp
      </div>
      {bubble.text}
      <div style={{
        position: 'absolute', bottom: -6, ...(side === 'left' ? { left: 26 } : { right: 26 }),
        width: 10, height: 10, background: 'rgba(12,6,24,0.92)',
        borderRight: `1px solid ${skin.accent}`, borderBottom: `1px solid ${skin.accent}`,
        transform: 'rotate(45deg)',
      }} />
    </div>
  )
}

function StatusPlate({ member, id, side }: { member: CrewMember; id: string; side: 'left' | 'right' }) {
  const skin = SKINS[id] ?? SKINS.atlas
  const statusColor = STATUS[member.status] ?? STATUS.idle
  return (
    <div style={{
      position: 'absolute',
      top: 'calc(66% + 40px)',
      ...(side === 'left'
        ? { left: `calc(${ANCHORS.atlas.x * 100}% - 125px)` }
        : { right: `calc(${(1 - ANCHORS.hermes.x) * 100}% - 125px)` }),
      width: 250,
      padding: '10px 14px 12px',
      background: 'rgba(10,5,20,0.82)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      borderTop: `2px solid ${skin.accent}`,
      border: `1px solid rgba(150,100,255,0.16)`,
      zIndex: 5,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 15, letterSpacing: '0.14em', color: skin.accent, textTransform: 'uppercase', fontWeight: 700 }}>
          {member.name}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: statusColor,
            boxShadow: `0 0 7px ${statusColor}`,
            animation: member.status !== 'idle' ? 'led-pulse 1.2s ease-in-out infinite' : undefined,
          }} />
          <span style={{ fontSize: 10, letterSpacing: '0.16em', color: statusColor, textTransform: 'uppercase' }}>
            {member.status}
          </span>
        </span>
      </div>
      <div style={{ fontSize: 9.5, color: INK.dim, letterSpacing: '0.1em', marginTop: 2 }}>
        {member.role} · {member.model}
      </div>
      <div style={{
        marginTop: 7, fontSize: 11.5, color: INK.text, fontFamily: '"Fira Code", monospace',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minHeight: 16,
      }}>
        {member.activity ?? 'standing by'}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 9.5, color: INK.soft, letterSpacing: '0.06em' }}>
        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 130 }}>
          {member.task ? `▸ ${member.task}` : '▸ no task'}
        </span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>
          {member.tokens_out > 0
            ? `${(member.tokens_in / 1000).toFixed(0)}k→${(member.tokens_out / 1000).toFixed(1)}k tk`
            : `${member.events_today} ev`}
        </span>
      </div>
    </div>
  )
}

// ── Ops log (left rail) ───────────────────────────────────────────────────────

const KIND_GLYPH: Record<CrewEvent['kind'], string> = {
  tool: '⚙', thought: '◌', speech: '▸', lifecycle: '●', hook: '·',
}

function OpsLog({ events }: { events: CrewEvent[] }) {
  return (
    <div style={{
      width: 300, maxHeight: '34vh', overflow: 'hidden',
      padding: '10px 0 6px',
      background: 'rgba(8,4,16,0.72)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: '1px solid rgba(150,100,255,0.14)',
    }}>
      <div style={{ fontSize: 10, letterSpacing: '0.22em', color: INK.dim, textTransform: 'uppercase', padding: '0 14px 8px', borderBottom: '1px solid rgba(150,100,255,0.10)' }}>
        Ops log — live
      </div>
      <div style={{ padding: '6px 0' }}>
        {events.length === 0 && (
          <div style={{ padding: '10px 14px', fontSize: 11, color: INK.dim }}>waiting for crew activity…</div>
        )}
        {events.slice(0, 16).map((e) => {
          const skin = SKINS[e.agent] ?? SKINS.atlas
          return (
            <div key={e.id} style={{ display: 'flex', gap: 8, padding: '3px 14px', alignItems: 'baseline' }}>
              <span style={{ fontSize: 9, color: INK.dim, fontVariantNumeric: 'tabular-nums', fontFamily: '"Fira Code", monospace', flexShrink: 0 }}>
                {new Date(e.ts).toLocaleTimeString([], { hour12: false })}
              </span>
              <span style={{ color: skin.accent, fontSize: 10, flexShrink: 0 }}>{KIND_GLYPH[e.kind] ?? '·'}</span>
              <span style={{
                fontSize: 11, color: e.kind === 'speech' ? skin.accent : INK.soft,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                fontFamily: '"Fira Code", monospace',
              }}>
                <span style={{ color: skin.accent }}>{e.agent}</span> {e.text}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage ─────────────────────────────────────────────────────────────────────

export default function CrewStage() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const crew = useDashboardStore((s) => s.crew)
  const crewEvents = useDashboardStore((s) => s.crewEvents)
  const setCrew = useDashboardStore((s) => s.setCrew)
  const setCrewEvents = useDashboardStore((s) => s.setCrewEvents)
  const [bubbles, setBubbles] = useState<Record<string, Bubble>>({})

  // seed from REST so the stage is alive before the first WS frame
  useEffect(() => {
    fetch('/api/crew')
      .then((r) => r.json())
      .then((d) => {
        if (d.crew) setCrew(d.crew)
        if (d.events) setCrewEvents([...d.events].reverse())
      })
      .catch(() => { /* backend not up yet */ })
  }, [setCrew, setCrewEvents])

  // speech events -> bubbles with a TTL
  useEffect(() => {
    const latest = crewEvents[0]
    if (!latest || latest.kind !== 'speech') return
    const agent = latest.meta.from && SKINS[latest.meta.from] ? latest.meta.from : latest.agent
    setBubbles((b) => ({ ...b, [agent]: { agent, text: latest.text, until: Date.now() + 8000 } }))
  }, [crewEvents])

  useEffect(() => {
    const id = setInterval(() => {
      setBubbles((b) => {
        const now = Date.now()
        const kept = Object.fromEntries(Object.entries(b).filter(([, v]) => v.until > now))
        return Object.keys(kept).length === Object.keys(b).length ? b : kept
      })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  // canvas loop — reads latest crew via getState() so it never re-mounts
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    let raf: number
    const frame = () => {
      const t = performance.now() / 1000
      const w = canvas.width, h = canvas.height
      const groundY = h * 0.66
      const liveCrew = useDashboardStore.getState().crew
      ctx.clearRect(0, 0, w, h)
      ctx.imageSmoothingEnabled = false

      drawFloor(ctx, w, h, groundY, t)

      for (const id of ['atlas', 'hermes']) {
        const member = liveCrew[id]
        const status: CrewStatus = member?.status ?? 'idle'
        const anchor = ANCHORS[id]
        const skin = SKINS[id]
        const cx = w * anchor.x
        drawConsole(ctx, cx, groundY, skin, status === 'working', t + (id === 'hermes' ? 1.7 : 0), anchor.flip)
        drawAgent(ctx, cx, groundY, skin, status, t + (id === 'hermes' ? 2.3 : 0), anchor.flip)
        if (status === 'thinking') drawThoughtDots(ctx, cx, groundY, t, skin.accent)
        if (status === 'waiting') drawWaitingMark(ctx, cx, groundY, t)
        if (status === 'talking') drawLinkBeam(ctx, w, groundY, t, id)
      }
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(raf) }
  }, [])

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 2 }}>
      <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0 }} />

      {Object.values(bubbles).map((b) => (
        <SpeechBubble key={b.agent} bubble={b} side={b.agent === 'atlas' ? 'left' : 'right'} />
      ))}

      {(['atlas', 'hermes'] as const).map((id) =>
        crew[id] ? <StatusPlate key={id} member={crew[id]} id={id} side={id === 'atlas' ? 'left' : 'right'} /> : null
      )}

      <div style={{ position: 'absolute', left: 20, bottom: 54, zIndex: 5 }}>
        <OpsLog events={crewEvents} />
      </div>
    </div>
  )
}
