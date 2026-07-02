import { useEffect, useRef, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { CrewMember, CrewEvent, CrewStatus } from '../types'

// ── Palette (identity colors follow the agent, status colors reserved) ───────

const INK = { text: '#f2f1f7', soft: '#a29db8', dim: '#575370' }
const PANEL_BORDER = '1px solid rgba(150,146,172,0.16)'
const STATUS: Record<CrewStatus, string> = {
  idle: '#5a5878',
  thinking: '#7ee8ff',
  working: '#79ff98',
  talking: '#b580ff',
  waiting: '#f0c040',
}
const LEGO_YELLOW = '#ffce3a'
const LEGO_YELLOW_SHADE = '#e0a81e'
// classic brick colors for confetti
const BRICK_COLORS = ['#e3000b', '#ffd500', '#0055bf', '#237841', '#ff7e14']

interface AgentSkin {
  accent: string      // identity color — torso, helmet, console trim
  accentShade: string
  glow: string
}

const SKINS: Record<string, AgentSkin> = {
  atlas: { accent: '#8f5cff', accentShade: '#6a3fd0', glow: 'rgba(143,92,255,0.5)' },
  hermes: { accent: '#f0a821', accentShade: '#c4830f', glow: 'rgba(240,168,33,0.5)' },
}

// Anchor positions as fractions of the canvas (Atlas left, Hermes right)
const ANCHORS: Record<string, { x: number; y: number; flip: boolean }> = {
  atlas: { x: 0.25, y: 0.60, flip: false },
  hermes: { x: 0.75, y: 0.60, flip: true },
}

const PX = 5 // logical pixel size

// Service key → flight-controller callsign for the GO/NO-GO board
const CALLSIGNS: [string, string][] = [
  ['openviking', 'VIKING'],
  ['memory_mcp', 'MEMORY'],
  ['hermes_gateway', 'COMMS'],
  ['mlx_server', 'MLX-35'],
  ['mlx_aux', 'MLX-9'],
  ['ollama', 'EMBED'],
  ['whisper_stt', 'VOICE'],
  ['screenpipe', 'OPTICS'],
]

// Wall plaques — missions flown out of this room
const PLAQUES = ['v0.1', 'v0.2', 'v0.3', 'v0.4']

// ── Confetti ──────────────────────────────────────────────────────────────────

interface Confetto {
  x: number; y: number; vx: number; vy: number
  w: number; h: number; rot: number; vrot: number
  color: string; life: number
}

function spawnConfetti(pool: Confetto[], cx: number, cy: number) {
  for (let i = 0; i < 42; i++) {
    pool.push({
      x: cx + (Math.random() - 0.5) * 40,
      y: cy - 120 + (Math.random() - 0.5) * 30,
      vx: (Math.random() - 0.5) * 5,
      vy: -Math.random() * 6 - 2,
      w: 5 + Math.random() * 4,
      h: 3 + Math.random() * 3,
      rot: Math.random() * Math.PI,
      vrot: (Math.random() - 0.5) * 0.3,
      color: BRICK_COLORS[i % BRICK_COLORS.length],
      life: 1,
    })
  }
}

function stepConfetti(ctx: CanvasRenderingContext2D, pool: Confetto[], groundY: number) {
  for (let i = pool.length - 1; i >= 0; i--) {
    const c = pool[i]
    c.vy += 0.18
    c.x += c.vx
    c.y += c.vy
    c.rot += c.vrot
    if (c.y > groundY + 8) { c.y = groundY + 8; c.vy = 0; c.vx *= 0.9; c.life -= 0.03 }
    if (c.life <= 0) { pool.splice(i, 1); continue }
    ctx.save()
    ctx.translate(c.x, c.y)
    ctx.rotate(c.rot)
    ctx.globalAlpha = Math.min(1, c.life * 2)
    ctx.fillStyle = c.color
    ctx.fillRect(-c.w / 2, -c.h / 2, c.w, c.h)
    ctx.restore()
  }
  ctx.globalAlpha = 1
}

// ── LEGO minifig ─────────────────────────────────────────────────────────────

/**
 * Draws a classic minifig: stud head, yellow face with grin, flared torso,
 * claw hands, hip + blocky legs. `celebrate` raises the arms.
 */
function drawMinifig(ctx: CanvasRenderingContext2D, cx: number, groundY: number,
                     skin: AgentSkin, status: CrewStatus, t: number, flip: boolean,
                     celebrating: boolean, waving = false) {
  const working = status === 'working'
  const bobSpeed = celebrating ? 10 : working ? 7 : status === 'thinking' ? 3 : 1.6
  const bobAmp = celebrating ? 4 : working ? 1.2 : 1.6
  const bob = Math.sin(t * bobSpeed) * bobAmp
  const S = PX
  const y0 = groundY + bob * 2 // feet line

  // Convention: gy = height of the TOP edge above the feet; boxes extend DOWN by gh.
  // gx = left edge relative to center (mirrored around cx when flip). gw always > 0.
  const X = (gx: number) => flip ? cx - gx * S : cx + gx * S
  const Y = (gy: number) => y0 - gy * S
  const rect = (gx: number, gy: number, gw: number, gh: number, color: string) => {
    ctx.fillStyle = color
    const x = flip ? cx - (gx + gw) * S : cx + gx * S
    ctx.fillRect(Math.round(x), Math.round(Y(gy)), Math.round(gw * S), Math.round(gh * S))
  }

  // glow pad under feet
  const grd = ctx.createRadialGradient(cx, groundY + 4, 2, cx, groundY + 4, 62)
  grd.addColorStop(0, skin.glow)
  grd.addColorStop(1, 'transparent')
  ctx.fillStyle = grd
  ctx.beginPath()
  ctx.ellipse(cx, groundY + 4, 62, 13, 0, 0, Math.PI * 2)
  ctx.fill()

  // ── legs (0..6.1) + hip (6.1..7.9)
  rect(-3.6, 6.1, 3.2, 6.1, skin.accentShade)
  rect(0.4, 6.1, 3.2, 6.1, skin.accentShade)
  rect(-3.6, 0.9, 3.2, 0.9, '#1b1926')          // feet line
  rect(0.4, 0.9, 3.2, 0.9, '#1b1926')
  rect(-0.35, 6.1, 0.7, 4.8, '#141220')          // gap between legs
  rect(-3.9, 7.9, 7.8, 1.8, skin.accentShade)   // hip piece

  // ── torso (7.9..15.3): lego trapezoid, flares downward
  ctx.fillStyle = skin.accent
  ctx.beginPath()
  const topW = 6.2 * S / 2, botW = 8.6 * S / 2
  ctx.moveTo(cx - topW, Y(15.3))
  ctx.lineTo(cx + topW, Y(15.3))
  ctx.lineTo(cx + botW, Y(7.9))
  ctx.lineTo(cx - botW, Y(7.9))
  ctx.closePath()
  ctx.fill()
  // chest sticker: control panel with live status LED
  rect(-1.6, 13.2, 3.2, 2.6, 'rgba(0,0,0,0.30)')
  rect(-1.1, 12.7, 0.9, 0.9, STATUS[status])
  rect(0.25, 12.7, 0.9, 0.9, 'rgba(255,255,255,0.35)')
  // neck bracket (15.3..16.0)
  rect(-1.4, 16.0, 2.8, 0.7, '#1b1926')

  // ── arms: shoulder top at 15.0
  const claw = (px_: number, py: number) => {
    ctx.strokeStyle = LEGO_YELLOW
    ctx.lineWidth = 2.4
    ctx.beginPath()
    ctx.arc(X(px_), Y(py), 3.2, 0.35, Math.PI * 1.45)
    ctx.stroke()
  }
  const phase = Math.sin(t * 13)
  if (celebrating) {
    // both arms up in a V
    for (const s of [-1, 1] as const) {
      rect(s * 3.6 - 0.9 + (s < 0 ? -1.8 : 0) + 0.9 * (s < 0 ? 1 : 0), 17.6, 1.8, 3.0, skin.accentShade)
      rect(s * 5.0 + (s < 0 ? -1.8 : 0), 20.6, 1.8, 3.2, skin.accentShade)
      claw(s * 5.9, 21.4)
    }
  } else if (waving) {
    // near arm waves hello; far arm hangs
    const wig = Math.sin(t * 12) * 1.1
    rect(2.7, 17.4, 1.8, 2.8, skin.accentShade)
    rect(3.4 + wig, 20.6, 1.8, 3.4, skin.accentShade)
    claw(4.3 + wig, 21.3)
    rect(-4.5, 15.0, 1.8, 5.4, skin.accentShade)
    claw(-3.6, 8.6)
  } else if (working) {
    // near arm (desk side, +x) types with a little bounce; far arm hangs
    const dip = phase > 0 ? 0.4 : 0
    rect(2.7, 15.0, 1.8, 2.4, skin.accentShade)                 // near upper arm
    rect(3.0, 12.9 - dip, 3.6, 1.6, skin.accentShade)           // forearm toward desk
    claw(7.2, 12.4 - dip)
    rect(-4.5, 15.0, 1.8, 5.4, skin.accentShade)                // far arm hangs
    claw(-3.6, 8.6)
  } else {
    for (const s of [-1, 1] as const) {
      rect(s * 3.6 - 0.9, 15.0, 1.8, 5.4, skin.accentShade)
      claw(s * 3.6, 8.6)
    }
  }

  // ── head (16.0..21.6): yellow with stud on top
  rect(-2.8, 21.6, 5.6, 5.6, LEGO_YELLOW)
  rect(-2.8, 16.8, 5.6, 0.8, LEGO_YELLOW_SHADE)                 // chin shade
  rect(-1.5, 22.9, 3.0, 1.3, LEGO_YELLOW)                       // stud
  // helmet band in identity color, hugging the top of the head
  rect(-3.1, 21.9, 6.2, 1.6, skin.accent)
  rect(-3.1, 21.9, 0.7, 3.2, skin.accent)                       // side pieces
  rect(2.4, 21.9, 0.7, 3.2, skin.accent)

  // ── face: dot eyes + the classic grin
  const blink = (t % 4.3) > 4.12
  const eyeTop = 19.9 + (working ? -0.3 : status === 'thinking' ? 0.35 : 0)
  if (!blink) {
    rect(-1.7, eyeTop, 0.85, 0.95, '#20180a')
    rect(0.85, eyeTop, 0.85, 0.95, '#20180a')
  } else {
    rect(-1.7, eyeTop - 0.35, 0.85, 0.3, '#20180a')
    rect(0.85, eyeTop - 0.35, 0.85, 0.3, '#20180a')
  }
  ctx.strokeStyle = '#20180a'
  ctx.lineWidth = 1.8
  ctx.beginPath()
  if (status === 'talking' && Math.sin(t * 10) > 0) {
    ctx.arc(cx, Y(17.6), 2.2, 0, Math.PI * 2)                   // open mouth
  } else {
    const grinR = celebrating ? 5.2 : 4.0
    ctx.arc(cx, Y(18.9), grinR, Math.PI * 0.24, Math.PI * 0.76) // grin
  }
  ctx.stroke()
}

// ── Consoles, floor, wall board ───────────────────────────────────────────────

function drawConsole(ctx: CanvasRenderingContext2D, cx: number, groundY: number,
                     skin: AgentSkin, active: boolean, t: number, flip: boolean) {
  const y = groundY - 30 * PX
  const P = (gx: number, gy: number, gw: number, gh: number, c: string) => {
    ctx.fillStyle = c
    const x = flip ? cx - (gx + gw) * PX : cx + gx * PX
    ctx.fillRect(Math.round(x), Math.round(y + gy * PX), gw * PX, gh * PX)
  }
  P(7, 20, 10, 1.6, '#26233a')               // desk top
  P(7.6, 21.6, 1.4, 8.6, '#1b1928')          // legs
  P(15, 21.6, 1.4, 8.6, '#1b1928')
  // studs on the desk — it's a lego desk
  for (let i = 0; i < 4; i++) P(8 + i * 2.3, 19.5, 1.1, 0.5, '#312d48')
  // mug of coffee (fun, tiny)
  P(15.2, 18.9, 1.3, 1.1, '#e3000b')
  P(15.45, 18.55, 0.8, 0.4, '#7a4a2b')
  // monitor
  P(8.4, 11, 8, 8, '#12101e')
  P(8.9, 11.5, 7, 7, active ? '#0d1f16' : '#0d0b16')
  P(11.6, 19, 1.6, 1.2, '#1b1928')
  P(8.4, 11, 8, 0.6, skin.accent)
  if (active) {
    for (let i = 0; i < 5; i++) {
      const lineT = (t * 2 + i * 0.9) % 4.5
      const w = 2 + ((i * 37 + Math.floor(t)) % 4)
      if (lineT < 4) P(9.3, 12.1 + lineT * 1.3, w, 0.55, i % 3 === 0 ? skin.accent : '#79ff98')
    }
  }
}

/** LEGO baseplate floor — perspective rows of studs. */
function drawBaseplate(ctx: CanvasRenderingContext2D, w: number, h: number, groundY: number) {
  ctx.fillStyle = 'rgba(148,144,170,0.05)'
  ctx.fillRect(0, groundY + 2, w, h - groundY)
  for (let row = 0; row < 7; row++) {
    const yy = groundY + 14 + row * row * 5.5
    if (yy > h) break
    const scale = 1 + row * 0.35
    const rx = 5 * scale, ry = 1.8 * scale
    const spacing = 46 * scale
    const offset = (row % 2) * spacing * 0.5
    ctx.fillStyle = `rgba(148,144,170,${0.10 - row * 0.011})`
    for (let x = -offset; x < w + spacing; x += spacing) {
      ctx.beginPath()
      ctx.ellipse(x, yy, rx, ry, 0, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

/** Board geometry shared by the renderer and the click handler. */
function boardGeometry(w: number, groundY: number) {
  const bw = Math.min(w * 0.44, 560)
  const bh = 168
  const bx = w / 2 - bw / 2
  const by = groundY - 30 * PX - bh + 46
  const cols = 4
  const cellW = (bw - 32) / cols
  return { bw, bh, bx, by, cols, cellW }
}

/** The Big Board — NASA-style front screen with MET clock, ticker, GO/NO-GO. */
function drawWallBoard(ctx: CanvasRenderingContext2D, w: number, groundY: number,
                       t: number, metSeconds: number,
                       services: Record<string, { status?: string }>,
                       ticker: string) {
  const { bw, bh, bx, by, cols, cellW } = boardGeometry(w, groundY)

  // frame
  ctx.fillStyle = 'rgba(16,14,26,0.92)'
  ctx.strokeStyle = 'rgba(148,144,170,0.28)'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.roundRect(bx, by, bw, bh, 6)
  ctx.fill()
  ctx.stroke()
  // legs to the floor
  ctx.fillStyle = '#1b1928'
  ctx.fillRect(w / 2 - bw / 2 + 24, by + bh, 8, groundY - by - bh)
  ctx.fillRect(w / 2 + bw / 2 - 32, by + bh, 8, groundY - by - bh)

  // header: MET clock
  const hh = Math.floor(metSeconds / 3600), mm = Math.floor((metSeconds % 3600) / 60), ss = Math.floor(metSeconds % 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  ctx.font = '600 11px "Fira Code", monospace'
  ctx.fillStyle = INK.dim
  ctx.textAlign = 'left'
  ctx.fillText('SHIFT ELAPSED TIME', bx + 16, by + 22)
  ctx.font = '700 22px "Fira Code", monospace'
  ctx.fillStyle = INK.text
  ctx.fillText(`${pad(hh)}:${pad(mm)}:${pad(ss)}`, bx + 16, by + 46)

  // orbit trace — apollo ground-track, dot sweeps a sine path
  const ox = bx + bw * 0.44, ow = bw * 0.52, oy = by + 30, oh = 26
  ctx.strokeStyle = 'rgba(148,144,170,0.25)'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let i = 0; i <= ow; i += 3) {
    const yy = oy + Math.sin((i / ow) * Math.PI * 2) * oh * 0.5
    i === 0 ? ctx.moveTo(ox + i, yy) : ctx.lineTo(ox + i, yy)
  }
  ctx.stroke()
  const p = (t * 0.07) % 1
  const dotX = ox + p * ow
  const dotY = oy + Math.sin(p * Math.PI * 2) * oh * 0.5
  ctx.fillStyle = '#79ff98'
  ctx.beginPath()
  ctx.arc(dotX, dotY, 3, 0, Math.PI * 2)
  ctx.fill()

  // GO / NO-GO board
  CALLSIGNS.forEach(([key, callsign], i) => {
    const col = i % cols, row = Math.floor(i / cols)
    const gx = bx + 16 + col * cellW
    const gy = by + 66 + row * 34
    const svc = services[key]
    const st = svc?.status ?? 'unknown'
    const go = st === 'up'
    const hold = st === 'degraded'
    const color = go ? '#79ff98' : hold ? '#f0c040' : '#ff7060'
    ctx.font = '600 9px "Fira Code", monospace'
    ctx.fillStyle = INK.dim
    ctx.fillText(callsign, gx, gy)
    ctx.font = '700 12px "Fira Code", monospace'
    ctx.fillStyle = color
    ctx.fillText(go ? 'GO' : hold ? 'HOLD' : 'NO GO', gx, gy + 14)
  })

  // ticker — latest ops event scrolls across the bottom
  if (ticker) {
    ctx.save()
    ctx.beginPath()
    ctx.rect(bx + 2, by + bh - 24, bw - 4, 20)
    ctx.clip()
    ctx.fillStyle = 'rgba(148,144,170,0.08)'
    ctx.fillRect(bx + 2, by + bh - 24, bw - 4, 20)
    ctx.font = '500 11px "Fira Code", monospace'
    ctx.fillStyle = INK.soft
    const text = `▸ ${ticker}   `
    const tw = ctx.measureText(text).width
    const shift = (t * 40) % (tw + bw)
    ctx.fillText(text, bx + bw - shift, by + bh - 9)
    ctx.restore()
  }
}

/** Mission plaques on the upper wall — one per version flown from this room. */
function drawPlaques(ctx: CanvasRenderingContext2D, w: number, groundY: number) {
  const y = groundY - 30 * PX - 158
  PLAQUES.forEach((label, i) => {
    const x = w * 0.5 + (i - (PLAQUES.length - 1) / 2) * 56 - 20
    ctx.fillStyle = 'rgba(148,144,170,0.10)'
    ctx.strokeStyle = 'rgba(148,144,170,0.22)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.roundRect(x, y - 44, 40, 26, 4)
    ctx.fill()
    ctx.stroke()
    ctx.font = '600 10px "Fira Code", monospace'
    ctx.fillStyle = INK.dim
    ctx.textAlign = 'center'
    ctx.fillText(label, x + 20, y - 27)
    ctx.textAlign = 'left'
  })
}

function drawThoughtDots(ctx: CanvasRenderingContext2D, cx: number, groundY: number, t: number, color: string) {
  const y = groundY - 26 * PX
  for (let i = 0; i < 3; i++) {
    const phase = Math.sin(t * 4 - i * 0.9)
    ctx.globalAlpha = 0.35 + Math.max(0, phase) * 0.65
    ctx.fillStyle = color
    ctx.fillRect(cx - 12 + i * 12, y - Math.max(0, phase) * 4, 6, 6)
  }
  ctx.globalAlpha = 1
}

function drawWaitingMark(ctx: CanvasRenderingContext2D, cx: number, groundY: number, t: number) {
  const y = groundY - 27 * PX + Math.sin(t * 5) * 3
  ctx.fillStyle = STATUS.waiting
  ctx.fillRect(cx - 2, y - 14, 5, 10)
  ctx.fillRect(cx - 2, y, 5, 4)
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
      background: 'rgba(12,8,22,0.92)',
      border: `1px solid ${skin.accent}`,
      boxShadow: '0 12px 28px -12px rgba(0,0,0,0.5)',
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
        width: 10, height: 10, background: 'rgba(12,8,22,0.92)',
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
      top: 'min(calc(66% + 40px), calc(100% - 132px))',
      ...(side === 'left'
        ? { left: `calc(${ANCHORS.atlas.x * 100}% - 125px)` }
        : { right: `calc(${(1 - ANCHORS.hermes.x) * 100}% - 125px)` }),
      width: 250,
      padding: '10px 14px 12px',
      background: 'rgba(11,8,18,0.82)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: PANEL_BORDER,
      borderTop: `2px solid ${skin.accent}`,
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 16px 32px -16px rgba(0,0,0,0.45)',
      zIndex: 5,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 15, letterSpacing: '0.14em', color: skin.accent, textTransform: 'uppercase', fontWeight: 700 }}>
          {member.name}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: statusColor,
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

const OPS_FILTERS = ['all', 'atlas', 'hermes', 'speech'] as const

export function OpsLog() {
  const allEvents = useDashboardStore((s) => s.crewEvents)
  const filter = useDashboardStore((s) => s.opsFilter)
  const setOpsFilter = useDashboardStore((s) => s.setOpsFilter)
  const events = filter === 'all' ? allEvents
    : filter === 'speech' ? allEvents.filter((e) => e.kind === 'speech')
    : allEvents.filter((e) => e.agent === filter)
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0,
      padding: '10px 0 6px',
      background: 'rgba(9,7,15,0.72)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: PANEL_BORDER,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 14px 8px', borderBottom: '1px solid rgba(150,146,172,0.10)', flexShrink: 0 }}>
        <span style={{ fontSize: 10, letterSpacing: '0.22em', color: INK.dim, textTransform: 'uppercase' }}>
          Ops log — live
        </span>
        <span style={{ display: 'flex', gap: 4 }}>
          {OPS_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setOpsFilter(f)}
              style={{
                background: 'none', padding: '1px 6px', cursor: 'pointer',
                border: `1px solid ${filter === f ? 'rgba(150,146,172,0.4)' : 'transparent'}`,
                color: filter === f
                  ? (SKINS[f]?.accent ?? INK.text)
                  : INK.dim,
                fontSize: 8.5, letterSpacing: '0.12em', textTransform: 'uppercase',
              }}
            >
              {f}
            </button>
          ))}
        </span>
      </div>
      <div style={{ padding: '6px 0', overflowY: 'auto', minHeight: 0 }}>
        {events.length === 0 && (
          <div style={{ padding: '10px 14px', fontSize: 11, color: INK.dim }}>
            {filter === 'all' ? 'waiting for crew activity…' : `no ${filter} events yet`}
          </div>
        )}
        {events.slice(0, 60).map((e) => {
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
  const containerRef = useRef<HTMLDivElement>(null)
  const crew = useDashboardStore((s) => s.crew)
  const crewEvents = useDashboardStore((s) => s.crewEvents)
  const setCrew = useDashboardStore((s) => s.setCrew)
  const setCrewEvents = useDashboardStore((s) => s.setCrewEvents)
  const [bubbles, setBubbles] = useState<Record<string, Bubble>>({})
  const [selectedService, setSelectedService] = useState<string | null>(null)
  const celebrateRef = useRef<Record<string, { until: number; spawned: boolean }>>({})
  const waveRef = useRef<Record<string, number>>({})
  const mountedAtRef = useRef(Date.now())
  const services = useDashboardStore((s) => s.services)
  const setOpsFilter = useDashboardStore((s) => s.setOpsFilter)

  // click routing: minifig -> wave + filter log; GO/NO-GO cell -> service detail
  const handleStageClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const r = canvas.getBoundingClientRect()
    const x = e.clientX - r.left, y = e.clientY - r.top
    const w = canvas.width, groundY = canvas.height * 0.66

    for (const id of ['atlas', 'hermes'] as const) {
      const ax = w * ANCHORS[id].x
      if (Math.abs(x - ax) < 60 && y > groundY - 24 * PX - 20 && y < groundY + 12) {
        waveRef.current[id] = Date.now() + 1800
        setOpsFilter(id)
        return
      }
    }
    const g = boardGeometry(w, groundY)
    if (x >= g.bx && x <= g.bx + g.bw && y >= g.by + 54 && y <= g.by + 54 + 2 * 34 + 6) {
      const col = Math.floor((x - (g.bx + 16)) / g.cellW)
      const row = Math.floor((y - (g.by + 54)) / 34)
      const idx = row * g.cols + col
      if (idx >= 0 && idx < CALLSIGNS.length) {
        setSelectedService((cur) => cur === CALLSIGNS[idx][0] ? null : CALLSIGNS[idx][0])
        return
      }
    }
    setSelectedService(null)
  }

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

  // speech events -> bubbles; finished turns -> celebration
  useEffect(() => {
    const latest = crewEvents[0]
    if (!latest) return
    if (latest.kind === 'speech') {
      const agent = latest.meta.from && SKINS[latest.meta.from] ? latest.meta.from : latest.agent
      setBubbles((b) => ({ ...b, [agent]: { agent, text: latest.text, until: Date.now() + 8000 } }))
    }
    if (latest.kind === 'lifecycle' && latest.text.includes('finished')) {
      celebrateRef.current[latest.agent] = { until: Date.now() + 2600, spawned: false }
    }
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

  // canvas loop — reads latest state via getState() so it never re-mounts
  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const resize = () => {
      canvas.width = container.clientWidth
      canvas.height = container.clientHeight
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(container)

    const confetti: Confetto[] = []
    let raf: number
    const frame = () => {
      const t = performance.now() / 1000
      const now = Date.now()
      const w = canvas.width, h = canvas.height
      const groundY = h * 0.66
      const state = useDashboardStore.getState()
      const liveCrew = state.crew
      ctx.clearRect(0, 0, w, h)
      ctx.imageSmoothingEnabled = false

      drawBaseplate(ctx, w, h, groundY)
      drawPlaques(ctx, w, groundY)
      drawWallBoard(
        ctx, w, groundY, t,
        (now - mountedAtRef.current) / 1000,
        state.services,
        state.crewEvents[0] ? `${state.crewEvents[0].agent}: ${state.crewEvents[0].text}` : '',
      )

      for (const id of ['atlas', 'hermes']) {
        const member = liveCrew[id]
        const status: CrewStatus = member?.status ?? 'idle'
        const anchor = ANCHORS[id]
        const skin = SKINS[id]
        const cx = w * anchor.x
        const cel = celebrateRef.current[id]
        const celebrating = !!cel && cel.until > now
        const waving = (waveRef.current[id] ?? 0) > now
        if (cel && celebrating && !cel.spawned) {
          spawnConfetti(confetti, cx, groundY)
          cel.spawned = true
        }
        drawConsole(ctx, cx, groundY, skin, status === 'working', t + (id === 'hermes' ? 1.7 : 0), anchor.flip)
        drawMinifig(ctx, cx, groundY, skin, status, t + (id === 'hermes' ? 2.3 : 0), anchor.flip, celebrating, waving)
        if (!celebrating && status === 'thinking') drawThoughtDots(ctx, cx, groundY, t, skin.accent)
        if (!celebrating && status === 'waiting') drawWaitingMark(ctx, cx, groundY, t)
        if (status === 'talking') drawLinkBeam(ctx, w, groundY, t, id)
      }

      stepConfetti(ctx, confetti, groundY)
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => { ro.disconnect(); cancelAnimationFrame(raf) }
  }, [])

  const svcDetail = selectedService ? services[selectedService] : null
  const svcCallsign = selectedService ? CALLSIGNS.find(([k]) => k === selectedService)?.[1] : null

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: '100%', minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
      <canvas ref={canvasRef} onClick={handleStageClick} style={{ position: 'absolute', inset: 0, cursor: 'pointer' }} />

      {Object.values(bubbles).map((b) => (
        <SpeechBubble key={b.agent} bubble={b} side={b.agent === 'atlas' ? 'left' : 'right'} />
      ))}

      {(['atlas', 'hermes'] as const).map((id) =>
        crew[id] ? <StatusPlate key={id} member={crew[id]} id={id} side={id === 'atlas' ? 'left' : 'right'} /> : null
      )}

      {/* Service detail popover — opens from a GO/NO-GO cell */}
      {svcDetail && (
        <div style={{
          position: 'absolute', top: 24, left: '50%', transform: 'translateX(-50%)',
          width: 320, padding: '10px 14px 12px', zIndex: 7,
          background: 'rgba(11,8,18,0.94)', border: PANEL_BORDER,
          borderTop: `2px solid ${svcDetail.status === 'up' ? '#79ff98' : svcDetail.status === 'degraded' ? '#f0c040' : '#ff7060'}`,
          boxShadow: '0 16px 32px -16px rgba(0,0,0,0.6)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 12, letterSpacing: '0.16em', color: INK.text, fontWeight: 700 }}>
              {svcCallsign} <span style={{ color: INK.dim, fontWeight: 400 }}>· {svcDetail.name ?? selectedService}</span>
            </span>
            <button onClick={() => setSelectedService(null)} style={{ background: 'none', border: 'none', color: INK.dim, cursor: 'pointer', fontSize: 12 }}>✕</button>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, fontFamily: '"Fira Code", monospace', color: svcDetail.status === 'up' ? '#79ff98' : svcDetail.status === 'degraded' ? '#f0c040' : '#ff7060' }}>
            {String(svcDetail.status ?? 'unknown').toUpperCase()}
          </div>
          {svcDetail.url && <div style={{ marginTop: 4, fontSize: 10, color: INK.soft, fontFamily: '"Fira Code", monospace' }}>{svcDetail.url}</div>}
          {svcDetail.error && <div style={{ marginTop: 4, fontSize: 10, color: '#ff9d90', fontFamily: '"Fira Code", monospace' }}>{svcDetail.error}</div>}
        </div>
      )}

      <CapcomConsole />
    </div>
  )
}

// ── CAPCOM — talk to the crew from mission control ────────────────────────────

function CapcomConsole() {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const send = async () => {
    const message = text.trim()
    if (!message || sending) return
    setSending(true)
    try {
      if (message.startsWith('/task ')) {
        // /task <title> — queue real work on Hermes's kanban
        const r = await fetch('/api/crew/task', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: message.slice(6).trim() }),
        })
        const d = await r.json()
        setNote(d.ok ? `task queued ▸ ${d.task?.id ?? ''}` : `task failed: ${d.error ?? '?'}`)
        if (d.ok) setText('')
      } else {
        await fetch('/api/amp/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recipient: 'hermes', subject: 'capcom', message, type: 'notification' }),
        })
        setText('')
        setNote(null)
      }
    } catch { setNote('backend unreachable') }
    setSending(false)
    setTimeout(() => setNote(null), 6000)
  }

  return (
    <div style={{
      position: 'absolute', bottom: 10, left: '50%', transform: 'translateX(-50%)',
      display: 'flex', alignItems: 'center', gap: 8,
      width: 'min(480px, 80%)', padding: '7px 10px', zIndex: 6,
      background: 'rgba(11,8,18,0.85)', border: PANEL_BORDER,
      backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
    }}>
      <span style={{ fontSize: 9, letterSpacing: '0.2em', color: INK.dim, flexShrink: 0 }}>CAPCOM ▸</span>
      {note && (
        <span style={{
          position: 'absolute', top: -22, left: 10, fontSize: 10,
          fontFamily: '"Fira Code", monospace',
          color: note.startsWith('task queued') ? '#79ff98' : '#f0c040',
        }}>
          {note}
        </span>
      )}
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') send() }}
        placeholder="message hermes over AMP… (/task <title> queues kanban work)"
        style={{
          flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none',
          color: INK.text, fontSize: 12, fontFamily: '"Fira Code", monospace',
        }}
      />
      <button
        onClick={send}
        disabled={sending || !text.trim()}
        style={{
          background: 'none', border: `1px solid ${SKINS.hermes.accent}`, color: SKINS.hermes.accent,
          fontSize: 10, letterSpacing: '0.14em', padding: '3px 10px',
          cursor: sending || !text.trim() ? 'default' : 'pointer',
          opacity: sending || !text.trim() ? 0.4 : 1,
        }}
      >
        {sending ? '…' : 'SEND'}
      </button>
    </div>
  )
}
