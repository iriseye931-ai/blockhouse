import { useEffect, useMemo, useRef, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { Agent, GraphSelection, ServiceHealth } from '../types'
import {
  STATUS_COLORS, AGENT_COLORS, SERVICE_COLORS, SERVICE_LABELS,
  AGENT_LABELS, AGENT_ROLES, WATCH_AGENTS, AGENT_POINTS,
  SERVICE_POINTS, STAR_POINTS, SHELL_POINTS, POLY_LINES,
  type Vec3, type GraphNodeMeta, type PanelDatum,
} from './mesh/constants'
import { hexToRgb, normKey, clamp, agentSignature, panelPath, rotateY, rotateX, project, selectionMeta } from './mesh/utils'

export default function MeshGraph({
  selected = null,
  onSelectionChange,
}: {
  selected?: GraphSelection | null
  onSelectionChange?: (selection: GraphSelection | null) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const nodesRef = useRef<GraphNodeMeta[]>([])

  const agents = useDashboardStore((s) => s.agents)
  const services = useDashboardStore((s) => s.services)
  const system = useDashboardStore((s) => s.system)
  const llmActive = useDashboardStore((s) => s.llmActive)
  const voiceActive = useDashboardStore((s) => s.voiceActive)
  const lastUpdate = useDashboardStore((s) => s.lastUpdate)
  const memorySummary = useDashboardStore((s) => s.memorySummary)
  const routingSummary = useDashboardStore((s) => s.routingSummary)
  const hermesStatus = useDashboardStore((s) => s.hermesStatus)
  const [hoveredNode, setHoveredNode] = useState<GraphNodeMeta | null>(null)
  const [pinnedNode, setPinnedNode] = useState<GraphNodeMeta | null>(null)

  const agentLookup = useMemo(() => {
    const map: Record<string, Agent> = {}
    for (const agent of agents) map[normKey(agent.name)] = agent
    return map
  }, [agents])

  const serviceLookup = useMemo(() => services as Record<string, ServiceHealth>, [services])

  const realPanelData = useMemo<PanelDatum[]>(() => {
    const online = agents.filter((agent) => ['online', 'active', 'busy'].includes(agent.status)).length
    const registered = agents.filter((agent) => agent.presence?.status === 'registered').length
    const offline = Math.max(agents.length - online - registered, 0)
    const serviceList = Object.values(services)
    const up = serviceList.filter((service) => service.status === 'up' || service.status === 'healthy').length
    const degraded = serviceList.filter((service) => service.status === 'degraded').length
    const down = Math.max(serviceList.length - up - degraded, 0)
    const lastSyncSeconds = lastUpdate ? Math.max(0, Math.floor((Date.now() - lastUpdate.getTime()) / 1000)) : null
    const hermesAgent = agents.find((agent) => normKey(agent.name) === 'hermes')
    const liveAgentStatuses = WATCH_AGENTS.map((agentKey) => {
      const agent = agents.find((item) => normKey(item.name) === agentKey)
      const status = agent?.health_status ?? agent?.presence?.status ?? agent?.status ?? 'offline'
        return {
          label: (agent?.label ?? agent?.name ?? agentKey).toUpperCase(),
          status: status.toUpperCase(),
          live: ['online', 'active', 'busy', 'registered'].includes(status.toLowerCase()),
        }
      })

    return [
      {
        title: 'MISSION STATUS',
        rows: [
          ['LINK', lastSyncSeconds == null ? 'WAITING' : lastSyncSeconds < 5 ? 'LIVE' : `${lastSyncSeconds}s`],
          ['CREW', `${online}/${agents.length || 0} ON`],
          ['LLM', (llmActive ?? 'idle').toUpperCase()],
          ['HERMES', (hermesAgent?.health_status ?? hermesAgent?.presence?.status ?? hermesAgent?.status ?? 'idle').toUpperCase()],
        ],
        bars: agents.length > 0 ? [online / agents.length, registered / agents.length, offline / Math.max(agents.length, 1)] : [0, 0, 0],
      },
      {
        title: 'SYSTEM METRICS',
        rows: [
          ['CPU', system?.cpu_pct != null ? `${Math.round(system.cpu_pct)}%` : '—'],
          ['RAM', system?.ram_pct != null ? `${Math.round(system.ram_pct)}%` : '—'],
          ['MLX', system?.mlx_ram_pct != null ? `${Math.round(system.mlx_ram_pct)}%` : '—'],
          ['LOCAL', system?.local_pct != null ? `${Math.round(system.local_pct)}%` : '—'],
        ],
        bars: [
          (system?.cpu_pct ?? 0) / 100,
          (system?.ram_pct ?? 0) / 100,
          (system?.mlx_ram_pct ?? 0) / 100,
          (system?.local_pct ?? 0) / 100,
        ],
      },
      {
        title: 'AGENT WATCH',
        kind: 'agents',
        rows: [],
        agents: liveAgentStatuses,
        bars: agents.length > 0 ? [online / agents.length] : [0],
      },
      {
        title: 'SECTOR RADAR',
        rows: [
          ['SVCS', `${up}/${serviceList.length || 0} UP`],
          ['DEG', `${degraded}`],
          ['DOWN', `${down}`],
          ['MODELS', `${Object.values(services).reduce((count, service) => count + (service.models?.length ?? 0), 0)}`],
        ],
        bars: serviceList.length > 0 ? [up / serviceList.length, degraded / serviceList.length, down / serviceList.length] : [0, 0, 0],
      },
    ]
  }, [agents, lastUpdate, services, system])

  useEffect(() => {
    setPinnedNode(selectionMeta(selected))
  }, [selected])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let running = true

    const draw = (ts: number) => {
      if (!running) return
      const t = ts / 1000
      const W = canvas.offsetWidth
      const H = canvas.offsetHeight
      const compactLayout = W < 1180 || H < 780
      const topHudClear = compactLayout ? 170 : 188
      const bottomHudClear = compactLayout ? 92 : 100
      const edgePad = compactLayout ? 10 : 18
      const panelGap = compactLayout ? 12 : 18
      const topPanelH = compactLayout ? 108 : 128
      const middlePanelH = compactLayout ? 132 : 164
      const sidePanelW = clamp(W * (compactLayout ? 0.18 : 0.17), compactLayout ? 190 : 240, compactLayout ? 248 : 308)
      const detailDockW = clamp(W * (compactLayout ? 0.22 : 0.19), compactLayout ? 220 : 270, compactLayout ? 280 : 320)
      const sphereSideClear = compactLayout ? 6 : 12
      const availableVertical = H - topHudClear - bottomHudClear
      const contentLeft = edgePad + detailDockW + panelGap
      const contentRight = W - edgePad - sidePanelW - panelGap
      const maxRadiusX = (contentRight - contentLeft - sphereSideClear * 2) / 2
      const maxRadiusY = (availableVertical - topPanelH - panelGap) / 2
      const radius = Math.max(110, Math.min(Math.min(W, H) * 1.12, maxRadiusX, maxRadiusY))
      const cx = (contentLeft + contentRight) / 2
      const cy = topHudClear + topPanelH + panelGap + radius - (compactLayout ? 86 : 108)
      const activeFocus = pinnedNode ?? hoveredNode
      const breathe = 1 + Math.sin(t * 1.1) * 0.035
      const liveRadius = radius * breathe

      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.imageSmoothingEnabled = true
      nodesRef.current = []

      const bg = ctx.createRadialGradient(cx, cy, radius * 0.1, cx, cy, Math.max(W, H) * 0.75)
      bg.addColorStop(0, 'rgba(18,8,36,0.86)')
      bg.addColorStop(0.22, 'rgba(10,5,22,0.94)')
      bg.addColorStop(0.5, 'rgba(5,3,12,0.99)')
      bg.addColorStop(1, 'rgba(4,2,10,1)')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, W, H)

      const smoke = ctx.createRadialGradient(cx, cy, liveRadius * 0.4, cx, cy, Math.max(W, H) * 0.82)
      smoke.addColorStop(0, 'rgba(200,170,255,0.03)')
      smoke.addColorStop(0.35, 'rgba(150,100,255,0.05)')
      smoke.addColorStop(0.7, 'rgba(140,90,255,0.024)')
      smoke.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = smoke
      ctx.fillRect(0, 0, W, H)

      for (let i = 0; i < 42; i++) {
        const x = (i * 97 + t * (i % 4 === 0 ? 3 : 1.2)) % W
        const y = (i * 57 + t * 5) % H
        ctx.fillStyle = i % 6 === 0 ? 'rgba(220,200,255,0.2)' : 'rgba(160,110,255,0.18)'
        ctx.fillRect(x, y, 1.4, 1.4)
      }

      const panels: Array<[number, number, number, number, PanelDatum | undefined]> = [
        [W - edgePad - sidePanelW, topHudClear, sidePanelW, topPanelH, realPanelData[1]],
      ]

      panels.forEach(([x, y, w, h, panel], index) => {
        const cut = compactLayout ? 10 : 14
        const panelGlow = ctx.createLinearGradient(x, y, x + w, y + h)
        panelGlow.addColorStop(0, 'rgba(10,5,20,0.9)')
        panelGlow.addColorStop(1, 'rgba(6,3,14,0.86)')
        panelPath(ctx, x, y, w, h, cut)
        ctx.fillStyle = panelGlow
        ctx.fill()
        panelPath(ctx, x, y, w, h, cut)
        ctx.strokeStyle = 'rgba(160,100,255,0.26)'
        ctx.lineWidth = 1
        ctx.stroke()
        // inner depth layer — thin highlight for glass-like depth
        panelPath(ctx, x + 1, y + 1, w - 2, h - 2, Math.max(cut - 2, 6))
        ctx.strokeStyle = 'rgba(255,255,255,0.03)'
        ctx.lineWidth = 0.4
        ctx.stroke()
        ctx.strokeStyle = 'rgba(160,100,255,0.64)'
        ctx.lineWidth = 1.2
        ctx.beginPath()
        ctx.moveTo(x + 2, y + cut + 2)
        ctx.lineTo(x + 2, y + 14)
        ctx.lineTo(x + 12, y + 2)
        ctx.moveTo(x + w - 22, y + 2)
        ctx.lineTo(x + w - 2, y + 2)
        ctx.lineTo(x + w - 2, y + 14)
        ctx.moveTo(x + 9, y + h - 2)
        ctx.lineTo(x + 18, y + h - 2)
        ctx.moveTo(x + w - 14, y + h - 10)
        ctx.lineTo(x + w - 2, y + h - 10)
        ctx.lineTo(x + w - 2, y + h - 2)
        ctx.stroke()
        ctx.fillStyle = 'rgba(170,120,255,0.05)'
        ctx.fillRect(x + 10, y + 10, w - 20, 1)
        if (panel) {
          if (panel.kind === 'agents') {
            // ── Agent Watch rows ─────────────────────────────────────────
            panel.agents?.forEach((agent, rowIndex) => {
              const rowY = y + 36 + rowIndex * 26
              // subtle row tint on hover (alternating)
              if (rowIndex % 2 === 0) {
                ctx.fillStyle = 'rgba(160,100,255,0.014)'
                ctx.fillRect(x + 8, rowY - 11, w - 16, 19)
              }
              // status dot with glow for live agents
              if (agent.live) { ctx.shadowColor = STATUS_COLORS.green; ctx.shadowBlur = 10 }
              ctx.fillStyle = agent.live ? STATUS_COLORS.green : 'rgba(210,240,248,0.18)'
              ctx.beginPath()
              ctx.arc(x + 14, rowY - 3, 5, 0, Math.PI * 2)
              ctx.fill()
              ctx.shadowBlur = 0
              // agent name
              ctx.fillStyle = 'rgba(210,190,255,0.94)'
              ctx.font = '600 9px sans-serif'
              ctx.textAlign = 'left'
              ctx.fillText(agent.label, x + 26, rowY)
              // color-coded status text
              const st = agent.status.toUpperCase()
              const stColor = agent.live ? STATUS_COLORS.green
                : (st === 'DEGRADED' || st === 'BUSY') ? STATUS_COLORS.amber
                : 'rgba(168,194,214,0.38)'
              ctx.fillStyle = stColor
              ctx.font = `${agent.live ? '700' : '600'} 9px sans-serif`
              ctx.fillText(st, x + Math.min(108, w * 0.52), rowY)
            })
          } else {
            // ── Instrument rows (MISSION STATUS, SYSTEM METRICS, SECTOR RADAR) ──
            const valCol = x + Math.min(74, w * 0.42)
            const barStart = valCol + 38
            const barMaxW = x + w - 10 - barStart

            panel.rows.forEach(([label, value], rowIndex) => {
              const rowY = y + 32 + rowIndex * 22

              // row separator
              if (rowIndex > 0) {
                ctx.fillStyle = 'rgba(100,200,255,0.032)'
                ctx.fillRect(x + 8, rowY - 13, w - 16, 1)
              }

              // label
              ctx.fillStyle = 'rgba(128,184,204,0.58)'
              ctx.font = '600 8px sans-serif'
              ctx.textAlign = 'left'
              ctx.fillText(label, x + 10, rowY)

              // value — color-coded for semantic status strings
              const vUp = /^(live|up|ok|idle)$/i.test(value)
              const vDeg = /degraded|partial|busy/i.test(value)
              const vDown = /^(down|offline|error|—)$/i.test(value)
              const vColor = vUp ? STATUS_COLORS.green : vDeg ? STATUS_COLORS.amber : vDown ? STATUS_COLORS.red : 'rgba(245,252,255,0.98)'
              ctx.fillStyle = vColor
              ctx.font = '700 11px sans-serif'
              ctx.fillText(value, valCol, rowY)

              // inline mini progress bar for percentage values
              const pctMatch = value.match(/^(\d+(\.\d+)?)%$/)
              if (pctMatch && barMaxW > 18) {
                const pct = Math.min(parseFloat(pctMatch[1]) / 100, 1)
                // track
                ctx.fillStyle = 'rgba(100,200,255,0.07)'
                ctx.fillRect(barStart, rowY - 8, barMaxW, 3)
                // fill — amber warning above 85%
                const fillC = pct > 0.85 ? 'rgba(240,168,76,0.92)' : pct > 0.6 ? 'rgba(180,244,255,0.84)' : 'rgba(122,220,255,0.64)'
                ctx.fillStyle = fillC
                ctx.fillRect(barStart, rowY - 8, barMaxW * pct, 3)
              }
            })
          }

          // ── Bottom multi-bar (stacked, each bar on its own row) ───────
          const barsData = panel.bars.slice(0, 4).filter(b => b > 0)
          const bBaseY = y + h - 8 - barsData.length * 5
          panel.bars.slice(0, 4).forEach((bar, bi) => {
            const bY = bBaseY + bi * 5
            const totalW = w - 20
            const fillW = Math.max(0, totalW * Math.max(0, Math.min(bar, 1)))
            // track
            ctx.fillStyle = 'rgba(100,200,255,0.05)'
            ctx.fillRect(x + 10, bY, totalW, 3)
            // fill — first bar brighter
            ctx.fillStyle = bi === 0
              ? 'rgba(232,250,255,0.94)'
              : bi === 1 ? 'rgba(162,232,255,0.72)'
              : 'rgba(112,196,228,0.5)'
            ctx.fillRect(x + 10, bY, fillW, 3)
          })
        }

        // ── Corner radar emblem (bottom panels only) ──────────────────────
        if (index === 0) {
          const rx = x + w - 26
          const ry = y + h - 26
          const upPct   = panel?.bars[0] ?? 0
          const degPct  = panel?.bars[1] ?? 0

          // track rings
          ctx.strokeStyle = 'rgba(155,236,255,0.14)'
          ctx.lineWidth = 1
          for (let ring = 0; ring < 3; ring++) {
            ctx.beginPath()
            ctx.arc(rx, ry, 8 + ring * 6, 0, Math.PI * 2)
            ctx.stroke()
          }
          // data arc (up ratio) on outer ring
          if (upPct > 0) {
            ctx.strokeStyle = 'rgba(121,255,152,0.6)'
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.arc(rx, ry, 20, -Math.PI / 2, -Math.PI / 2 + upPct * Math.PI * 2)
            ctx.stroke()
          }
          // degraded arc on middle ring
          if (degPct > 0) {
            ctx.strokeStyle = 'rgba(240,192,64,0.55)'
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.arc(rx, ry, 14, -Math.PI / 2, -Math.PI / 2 + degPct * Math.PI * 2)
            ctx.stroke()
          }
          // crosshair
          ctx.strokeStyle = 'rgba(155,236,255,0.2)'
          ctx.lineWidth = 0.8
          ctx.beginPath()
          ctx.moveTo(rx - 22, ry); ctx.lineTo(rx + 6, ry)
          ctx.moveTo(rx, ry - 22); ctx.lineTo(rx, ry + 6)
          ctx.stroke()
        }

      })
      const globeGlow = ctx.createRadialGradient(cx, cy, liveRadius * 0.14, cx, cy, liveRadius * 1.5)
      globeGlow.addColorStop(0, 'rgba(255,255,255,0.52)')
      globeGlow.addColorStop(0.2, 'rgba(228,250,255,0.32)')
      globeGlow.addColorStop(0.5, 'rgba(165,232,255,0.18)')
      globeGlow.addColorStop(0.8, 'rgba(120,184,255,0.07)')
      globeGlow.addColorStop(1, 'rgba(120,184,255,0)')
      ctx.fillStyle = globeGlow
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 1.48, 0, Math.PI * 2)
      ctx.fill()

      const shellAura = ctx.createRadialGradient(cx, cy, liveRadius * 0.78, cx, cy, liveRadius * 1.08)
      shellAura.addColorStop(0, 'rgba(255,255,255,0)')
      shellAura.addColorStop(0.72, 'rgba(206,246,255,0.12)')
      shellAura.addColorStop(1, 'rgba(225,250,255,0.28)')
      ctx.fillStyle = shellAura
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 1.08, 0, Math.PI * 2)
      ctx.fill()

      const haze = ctx.createRadialGradient(cx, cy, liveRadius * 0.24, cx, cy, liveRadius * 1.92)
      haze.addColorStop(0, 'rgba(255,255,255,0.05)')
      haze.addColorStop(0.44, 'rgba(165,236,255,0.05)')
      haze.addColorStop(0.78, 'rgba(132,184,255,0.022)')
      haze.addColorStop(1, 'rgba(120,184,255,0)')
      ctx.fillStyle = haze
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 1.95, 0, Math.PI * 2)
      ctx.fill()

      const coreGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, liveRadius * 0.9)
      coreGlow.addColorStop(0, 'rgba(255,255,255,0.4)')
      coreGlow.addColorStop(0.18, 'rgba(240,252,255,0.38)')
      coreGlow.addColorStop(0.38, 'rgba(194,238,255,0.25)')
      coreGlow.addColorStop(0.68, 'rgba(132,184,255,0.09)')
      coreGlow.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = coreGlow
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 0.92, 0, Math.PI * 2)
      ctx.fill()

      const coreBloom = ctx.createRadialGradient(cx, cy, liveRadius * 0.02, cx, cy, liveRadius * 0.42)
      coreBloom.addColorStop(0, 'rgba(255,255,255,0.42)')
      coreBloom.addColorStop(0.26, 'rgba(236,250,255,0.22)')
      coreBloom.addColorStop(0.7, 'rgba(172,226,255,0.06)')
      coreBloom.addColorStop(1, 'rgba(120,184,255,0)')
      ctx.fillStyle = coreBloom
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 0.44, 0, Math.PI * 2)
      ctx.fill()

      const coreStar = ctx.createRadialGradient(cx, cy, 0, cx, cy, liveRadius * 0.15)
      coreStar.addColorStop(0, 'rgba(255,255,255,0.95)')
      coreStar.addColorStop(0.16, 'rgba(248,254,255,0.84)')
      coreStar.addColorStop(0.52, 'rgba(190,236,255,0.28)')
      coreStar.addColorStop(1, 'rgba(145,210,255,0)')
      ctx.fillStyle = coreStar
      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius * 0.24, 0, Math.PI * 2)
      ctx.fill()

      const lensFlare = ctx.createLinearGradient(cx - liveRadius * 1.2, cy, cx + liveRadius * 1.2, cy)
      lensFlare.addColorStop(0, 'rgba(255,255,255,0)')
      lensFlare.addColorStop(0.48, 'rgba(225,250,255,0.16)')
      lensFlare.addColorStop(0.5, 'rgba(255,255,255,0.44)')
      lensFlare.addColorStop(0.52, 'rgba(225,250,255,0.16)')
      lensFlare.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.strokeStyle = lensFlare
      ctx.lineWidth = 1.6
      ctx.beginPath()
      ctx.moveTo(cx - liveRadius * 1.35, cy)
      ctx.lineTo(cx + liveRadius * 1.35, cy)
      ctx.stroke()

      // secondary vertical lens flare artifact
      const lensFlareV = ctx.createLinearGradient(cx, cy - liveRadius * 0.9, cx, cy + liveRadius * 0.9)
      lensFlareV.addColorStop(0, 'rgba(255,255,255,0)')
      lensFlareV.addColorStop(0.46, 'rgba(200,242,255,0.05)')
      lensFlareV.addColorStop(0.5, 'rgba(255,255,255,0.18)')
      lensFlareV.addColorStop(0.54, 'rgba(200,242,255,0.05)')
      lensFlareV.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.strokeStyle = lensFlareV
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(cx, cy - liveRadius * 0.96)
      ctx.lineTo(cx, cy + liveRadius * 0.96)
      ctx.stroke()

      const rotation = t * 0.18
      const pitch = -0.32

      ctx.beginPath()
      ctx.arc(cx, cy, liveRadius, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(205,245,255,0.12)'
      ctx.lineWidth = 1
      ctx.stroke()

      POLY_LINES.forEach(([from, to], index) => {
        const a = project(rotateX(rotateY(from, rotation), pitch), cx, cy, liveRadius)
        const b = project(rotateX(rotateY(to, rotation), pitch), cx, cy, liveRadius)
        // depth: 0=back, 1=front — use midpoint z for consistent per-edge depth
        const depth = ((a.z + b.z + 2) / 4)  // 0..1
        const alpha = 0.028 + depth * 0.22     // 0.028 (far) → 0.248 (near)
        const lw = 0.35 + depth * 0.75         // 0.35 (far) → 1.1 (near)
        const touchesMemory = from === SERVICE_POINTS.memory_mcp || to === SERVICE_POINTS.memory_mcp
        const touchesGateway = from === SERVICE_POINTS.openviking || to === SERVICE_POINTS.openviking
        const touchesTargetAgent =
          (memoryHeavyTarget === 'atlas' && (from === AGENT_POINTS.atlas || to === AGENT_POINTS.atlas)) ||
          (memoryHeavyTarget === 'hermes' && (from === AGENT_POINTS.hermes || to === AGENT_POINTS.hermes)) ||
          (memoryHeavyTarget === 'iriseye' && (from === AGENT_POINTS.iriseye || to === AGENT_POINTS.iriseye))
        // color: far=deep blue-indigo, near=bright cyan-white
        const accent = index % 5 === 0
        if (touchesMemory && memoryCause !== 'healthy') {
          ctx.strokeStyle = memoryCause === 'pressure' || memoryCause === 'stale'
            ? `rgba(240,192,64,${0.1 + depth * 0.22})`
            : `rgba(255,112,96,${0.12 + depth * 0.26})`
          ctx.lineWidth = lw + 0.45
        } else if (touchesGateway && memoryCause === 'gateway') {
          ctx.strokeStyle = `rgba(255,112,96,${0.12 + depth * 0.24})`
          ctx.lineWidth = lw + 0.35
        } else if (touchesMemory && touchesTargetAgent) {
          ctx.strokeStyle = `rgba(223,251,255,${0.1 + depth * 0.24})`
          ctx.lineWidth = lw + 0.35
        } else if (accent) {
          // accent lines: near=pure white, far=soft blue
          const r = Math.round(160 + depth * 85)
          const g = Math.round(215 + depth * 37)
          ctx.strokeStyle = `rgba(${r},${g},255,${alpha})`
          ctx.lineWidth = lw
        } else {
          // standard lines: near=cyan, far=indigo-blue
          const r = Math.round(90 + depth * 80)
          const g = Math.round(170 + depth * 55)
          ctx.strokeStyle = `rgba(${r},${g},255,${alpha})`
          ctx.lineWidth = lw
        }
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
      })

      const projectedShell = SHELL_POINTS.map((point, index) => {
        const wave = Math.sin(t * 0.7 + index * 0.19) * 0.01
        const rotated = rotateX(rotateY({
          x: point.x * (1 + wave),
          y: point.y * (1 - wave),
          z: point.z,
        }, rotation * 1.02), pitch)
        return project(rotated, cx, cy, liveRadius)
      })

      for (let i = 0; i < projectedShell.length; i += 1) {
        const a = projectedShell[i]
        const neighbors = [projectedShell[(i + 1) % projectedShell.length], projectedShell[(i + 8) % projectedShell.length]]
        neighbors.forEach((b, nIndex) => {
          const depth = (a.z + b.z + 2) / 4  // 0..1
          const alpha = 0.018 + depth * 0.12  // 0.018 (far) → 0.138 (near)
          const lw = 0.28 + depth * 0.44      // 0.28 (far) → 0.72 (near)
          const r = nIndex === 0 ? Math.round(200 + depth * 45) : Math.round(120 + depth * 60)
          const g = nIndex === 0 ? Math.round(236 + depth * 16) : Math.round(200 + depth * 30)
          ctx.strokeStyle = `rgba(${r},${g},255,${alpha})`
          ctx.lineWidth = lw
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        })
      }

      projectedShell.forEach((p, index) => {
        const alpha = 0.14 + (p.z + 1) * 0.2
        const size = 0.55 + p.scale * 1.1
        // depth-based color: near=white, far=deeper blue
        const nearness = (p.z + 1) / 2
        const r = Math.round(190 + nearness * 65)
        const g = Math.round(222 + nearness * 33)
        ctx.fillStyle = index % 11 === 0
          ? `rgba(255,255,255,${alpha})`
          : `rgba(${r},${g},255,${alpha * 0.85})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, size, 0, Math.PI * 2)
        ctx.fill()
      })

      // Milky-way particle field on the sphere
      STAR_POINTS.forEach((point, index) => {
        const wobble = Math.sin(t * 0.9 + index * 0.13) * 0.026
        const rotated = rotateX(rotateY({
          x: point.x * (1 + wobble),
          y: point.y * (1 - wobble * 0.6),
          z: point.z,
        }, rotation * 1.06), pitch + Math.sin(t * 0.3) * 0.05)
        const pr = project(rotated, cx, cy, liveRadius)
        const depth = (pr.z + 1) / 2
        const alpha = 0.16 + depth * 0.3
        const size = 0.45 + pr.scale * 1.9 + Math.sin(t * 0.8 + index * 0.15) * 0.08
        ctx.fillStyle = index % 17 === 0
          ? `rgba(255,255,255,${alpha})`
          : index % 11 === 0
            ? `rgba(235,248,255,${alpha * 0.95})`
            : `rgba(175,225,255,${alpha * 0.82})`
        ctx.beginPath()
        ctx.arc(pr.x, pr.y, size, 0, Math.PI * 2)
        ctx.fill()

        if (depth > 0.68 && index % 5 === 0) {
          const particleGlow = ctx.createRadialGradient(pr.x, pr.y, 0, pr.x, pr.y, 8 * pr.scale)
          particleGlow.addColorStop(0, `rgba(240,250,255,${alpha * 0.22})`)
          particleGlow.addColorStop(1, 'rgba(120,210,255,0)')
          ctx.fillStyle = particleGlow
          ctx.beginPath()
          ctx.arc(pr.x, pr.y, 8 * pr.scale, 0, Math.PI * 2)
          ctx.fill()
        }
        // bright flare spike on select deep-front stars
        if (depth > 0.82 && index % 37 === 0) {
          const flen = 11 * pr.scale
          const fGrad = ctx.createLinearGradient(pr.x - flen, pr.y, pr.x + flen, pr.y)
          fGrad.addColorStop(0, 'rgba(255,255,255,0)')
          fGrad.addColorStop(0.5, `rgba(255,255,255,${alpha * 0.9})`)
          fGrad.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.strokeStyle = fGrad
          ctx.lineWidth = 0.8
          ctx.beginPath()
          ctx.moveTo(pr.x - flen, pr.y); ctx.lineTo(pr.x + flen, pr.y)
          ctx.stroke()
          const fGradV = ctx.createLinearGradient(pr.x, pr.y - flen, pr.x, pr.y + flen)
          fGradV.addColorStop(0, 'rgba(255,255,255,0)')
          fGradV.addColorStop(0.5, `rgba(255,255,255,${alpha * 0.9})`)
          fGradV.addColorStop(1, 'rgba(255,255,255,0)')
          ctx.strokeStyle = fGradV
          ctx.beginPath()
          ctx.moveTo(pr.x, pr.y - flen); ctx.lineTo(pr.x, pr.y + flen)
          ctx.stroke()
        }
      })

      // soft inner light drift
      for (let i = 0; i < 36; i++) {
        const eccentricity = 0.18 + (i % 3) * 0.08
        const angle = t * 0.16 + (i / 36) * Math.PI * 2
        const px = cx + Math.cos(angle) * liveRadius * (0.26 + eccentricity)
        const py = cy + Math.sin(angle * 1.4 + i * 0.18) * liveRadius * (0.12 + eccentricity * 0.5)
        const glow = ctx.createRadialGradient(px, py, 0, px, py, liveRadius * 0.2)
        glow.addColorStop(0, 'rgba(245,252,255,0.09)')
        glow.addColorStop(0.45, 'rgba(150,225,255,0.045)')
        glow.addColorStop(1, 'rgba(120,210,255,0)')
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(px, py, liveRadius * 0.16, 0, Math.PI * 2)
        ctx.fill()
      }

      for (let i = 0; i < 4; i++) {
        const angle = t * 0.25 + (i / 4) * Math.PI * 2
        const beamX = cx + Math.cos(angle) * liveRadius * 1.2
        const beamY = cy + Math.sin(angle) * liveRadius * 0.36
        const beam = ctx.createLinearGradient(cx, cy, beamX, beamY)
        beam.addColorStop(0, 'rgba(255,255,255,0.72)')
        beam.addColorStop(0.18, 'rgba(225,250,255,0.34)')
        beam.addColorStop(0.48, 'rgba(140,214,255,0.18)')
        beam.addColorStop(1, 'rgba(120,210,255,0)')
        ctx.strokeStyle = beam
        ctx.lineWidth = 2.6
        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.lineTo(beamX, beamY)
        ctx.stroke()
      }

      for (let i = 0; i < 3; i++) {
        const arcAngle = t * 0.42 + i * 1.9
        const startX = cx + Math.cos(arcAngle) * liveRadius * 0.78
        const startY = cy + Math.sin(arcAngle) * liveRadius * 0.24
        const endX = cx - Math.cos(arcAngle * 1.2) * liveRadius * 0.74
        const endY = cy - Math.sin(arcAngle * 0.9) * liveRadius * 0.28
        const ctrlX = cx + Math.sin(arcAngle * 1.4) * liveRadius * 0.16
        const ctrlY = cy + Math.cos(arcAngle * 1.1) * liveRadius * 0.16
        const arcGrad = ctx.createLinearGradient(startX, startY, endX, endY)
        arcGrad.addColorStop(0, 'rgba(180,225,255,0)')
        arcGrad.addColorStop(0.35, 'rgba(150,218,255,0.22)')
        arcGrad.addColorStop(0.65, 'rgba(245,252,255,0.32)')
        arcGrad.addColorStop(1, 'rgba(255,255,255,0)')
        ctx.strokeStyle = arcGrad
        ctx.lineWidth = 1.4
        ctx.beginPath()
        ctx.moveTo(startX, startY)
        ctx.quadraticCurveTo(ctrlX, ctrlY, endX, endY)
        ctx.stroke()
      }

      // Project nodes
      const projected: Array<{
        node: GraphNodeMeta
        z: number
        scale: number
        color: string
        kind: 'agent' | 'service'
        active: boolean
        status: string
        activityStatus: string | null
      }> = []

      for (const [key, point] of Object.entries(SERVICE_POINTS)) {
        const rotated = rotateX(rotateY(point, rotation), pitch)
        const pr = project(rotated, cx, cy, liveRadius)
        const status = serviceLookup[key]?.status ?? 'unknown'
        let color = SERVICE_COLORS[key] ?? '#f1f1f1'
        if (key === 'memory_mcp' && memoryCause !== 'healthy') {
          color = memoryCause === 'pressure' || memoryCause === 'stale' ? '#f0c040' : '#ff7060'
        } else if (key === 'openviking' && memoryCause === 'gateway') {
          color = '#ff7060'
        }
        projected.push({
          node: { type: 'service', key, label: SERVICE_LABELS[key] ?? key, x: pr.x, y: pr.y, radius: 20 + pr.scale * 8 },
          z: pr.z,
          scale: pr.scale,
          color,
          kind: 'service',
          active: status === 'up' || status === 'healthy',
          status,
          activityStatus: null,
        })
      }

      for (const [key, point] of Object.entries(AGENT_POINTS)) {
        const rotated = rotateX(rotateY(point, rotation), pitch)
        const pr = project(rotated, cx, cy, liveRadius)
        const agent = agentLookup[key]
        const status = agent?.presence?.status ?? agent?.status ?? 'offline'
        const activityStatus = agent?.activity_status ?? null
        const isLive = activityStatus === 'live'
        const isIdleOrGone = activityStatus === 'idle' || activityStatus === 'stale' || !agent
        const baseRadius = key === 'atlas' ? 24 : 20
        const radiusMult = isLive ? 1.22 : isIdleOrGone ? 0.88 : 1.0
        projected.push({
          node: { type: 'agent', key, label: AGENT_LABELS[key] ?? key, x: pr.x, y: pr.y, radius: baseRadius * radiusMult + pr.scale * 8 },
          z: pr.z,
          scale: pr.scale,
          color: AGENT_COLORS[key] ?? '#f1f1f1',
          kind: 'agent',
          active: ['online', 'active', 'busy', 'registered'].includes(status),
          status,
          activityStatus,
        })
      }

      projected.sort((a, b) => a.z - b.z)

      // data orbits
      projected.forEach((item, index) => {
        const alpha = item.active ? 0.03 : 0.012
        ctx.strokeStyle = `rgba(${hexToRgb(item.color)},${alpha})`
        ctx.lineWidth = 1
        ctx.setLineDash([4, 12])
        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.lineTo(item.node.x, item.node.y)
        ctx.stroke()
        ctx.setLineDash([])
        const phase  = ((t * 0.22) + index * 0.11) % 1
        const phase2 = (phase + 0.5) % 1
        const dotAlpha = item.active ? 0.36 : 0.08
        const col = hexToRgb(item.color)
        // forward packet with glow halo
        const fpx = cx + (item.node.x - cx) * phase
        const fpy = cy + (item.node.y - cy) * phase
        if (item.active) {
          const pGlow = ctx.createRadialGradient(fpx, fpy, 0, fpx, fpy, 6)
          pGlow.addColorStop(0, `rgba(${col},${dotAlpha})`)
          pGlow.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = pGlow
          ctx.beginPath()
          ctx.arc(fpx, fpy, 6, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.fillStyle = `rgba(${col},${dotAlpha})`
        ctx.beginPath()
        ctx.arc(fpx, fpy, item.active ? 2 : 1, 0, Math.PI * 2)
        ctx.fill()
        // reverse packet (bidirectional traffic)
        const rpx = cx + (item.node.x - cx) * phase2
        const rpy = cy + (item.node.y - cy) * phase2
        ctx.fillStyle = `rgba(${col},${dotAlpha * 0.55})`
        ctx.beginPath()
        ctx.arc(rpx, rpy, item.active ? 1.5 : 1, 0, Math.PI * 2)
        ctx.fill()
      })

      projected.forEach((item) => {
        const focused = activeFocus?.type === item.node.type && activeFocus.key === item.node.key
        nodesRef.current.push(item.node)

        if (item.kind === 'service') {
          const r = 1.3 + item.scale * 1.1
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, r + (focused ? 1.6 : 0), 0, Math.PI * 2)
          ctx.fillStyle = item.active ? `rgba(${hexToRgb(item.color)},0.34)` : 'rgba(110,128,150,0.16)'
          ctx.fill()
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, r * 2.8, 0, Math.PI * 2)
          ctx.strokeStyle = focused ? `rgba(${hexToRgb(item.color)},0.36)` : `rgba(${hexToRgb(item.color)},0.14)`
          ctx.lineWidth = 1
          ctx.stroke()
          if (focused) {
            const reticleRadius = r * 5.2
            const bracketArc = Math.PI * 0.16
            ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.46)`
            ctx.lineWidth = 1
            ;[0, Math.PI / 2, Math.PI, Math.PI * 1.5].forEach((angle) => {
              ctx.beginPath()
              ctx.arc(item.node.x, item.node.y, reticleRadius, angle - bracketArc, angle + bracketArc)
              ctx.stroke()
            })
            ctx.textAlign = 'center'
            ctx.font = `${Math.max(7, 7 * item.scale)}px sans-serif`
            ctx.fillStyle = '#f2f2f2'
            ctx.fillText(item.node.label.toUpperCase(), item.node.x, item.node.y - 10)
          }
          return
        }

        const sig = agentSignature(item.node.key)
        const statusRaw = (item.status || '').toLowerCase()
        const isDegradedNode = statusRaw.includes('degraded') || statusRaw.includes('partial')
        const isLiveNode = item.activityStatus === 'live' || (item.activityStatus == null && item.active)
        const isRecentNode = item.activityStatus === 'recent'
        const isIdleNode = item.activityStatus === 'idle' || item.activityStatus === 'stale'
        const isOfflineNode = !isLiveNode && !isRecentNode && !isDegradedNode
        const statusCadence = isOfflineNode ? 0.22 : isDegradedNode ? 1.9 : isRecentNode ? sig.cadence * 0.45 : sig.cadence
        const pulse = 0.5 + 0.5 * Math.sin(t * 2.4 * statusCadence + item.node.key.length)
        const orbitPhase = t * (item.node.key === 'atlas' ? 0.95 : 1.25) * statusCadence + item.node.key.length * 0.7
        const orbitRadius = item.node.radius + 10 + pulse * 3 * sig.orbitA
        const orbitRadiusB = item.node.radius + 15 + pulse * 2.5 * sig.orbitB
        const jitter = isDegradedNode ? Math.sin(t * 8 + item.node.key.length * 0.9) * 1.4 : 0
        if (isLiveNode) {
          const halo = ctx.createRadialGradient(item.node.x, item.node.y, item.node.radius * 0.2, item.node.x, item.node.y, item.node.radius * 1.8)
          halo.addColorStop(0, `rgba(${hexToRgb(item.color)},${sig.halo})`)
          halo.addColorStop(0.55, `rgba(${hexToRgb(item.color)},0.08)`)
          halo.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = halo
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 1.82, 0, Math.PI * 2)
          ctx.fill()

          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius + 6 + pulse * 4, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},${0.04 + pulse * 0.04})`
          ctx.lineWidth = 1.1
          ctx.stroke()

          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, orbitRadius, orbitPhase, orbitPhase + Math.PI * (item.node.key === 'atlas' ? 0.84 : 1.18))
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.22)`
          ctx.lineWidth = 1
          ctx.stroke()

          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, orbitRadiusB, -orbitPhase * 0.8, -orbitPhase * 0.8 + Math.PI * (item.node.key === 'iriseye' ? 0.52 : 0.86))
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.14)`
          ctx.lineWidth = 0.8
          ctx.stroke()

          const orbiterX = item.node.x + Math.cos(orbitPhase) * orbitRadius
          const orbiterY = item.node.y + Math.sin(orbitPhase) * orbitRadius * 0.82
          const orbiterGlow = ctx.createRadialGradient(orbiterX, orbiterY, 0, orbiterX, orbiterY, 7)
          orbiterGlow.addColorStop(0, `rgba(${hexToRgb(item.color)},0.4)`)
          orbiterGlow.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = orbiterGlow
          ctx.beginPath()
          ctx.arc(orbiterX, orbiterY, 7, 0, Math.PI * 2)
          ctx.fill()
          ctx.fillStyle = `rgba(255,255,255,${0.75 + pulse * 0.15})`
          ctx.beginPath()
          ctx.arc(orbiterX, orbiterY, 1.8, 0, Math.PI * 2)
          ctx.fill()

          const orbiterX2 = item.node.x + Math.cos(-orbitPhase * 0.8) * orbitRadiusB
          const orbiterY2 = item.node.y + Math.sin(-orbitPhase * 0.8) * orbitRadiusB * 0.8
          ctx.fillStyle = `rgba(${hexToRgb(item.color)},0.55)`
          ctx.beginPath()
          ctx.arc(orbiterX2, orbiterY2, 1.2, 0, Math.PI * 2)
          ctx.fill()
        } else if (isRecentNode) {
          // Amber halo — half the radius of active, much softer
          const recentHalo = ctx.createRadialGradient(item.node.x, item.node.y, item.node.radius * 0.25, item.node.x, item.node.y, item.node.radius * 1.45)
          recentHalo.addColorStop(0, 'rgba(240,192,64,0.09)')
          recentHalo.addColorStop(0.6, 'rgba(240,192,64,0.04)')
          recentHalo.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = recentHalo
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 1.45, 0, Math.PI * 2)
          ctx.fill()

          // Single slow orbit arc — no orbiter dot
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, orbitRadius, orbitPhase, orbitPhase + Math.PI * 0.68)
          ctx.strokeStyle = 'rgba(240,192,64,0.20)'
          ctx.lineWidth = 0.8
          ctx.stroke()

          // Gentle pulse ring
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius + 3 + pulse * 2.5, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(240,192,64,${0.03 + pulse * 0.05})`
          ctx.lineWidth = 0.9
          ctx.stroke()
        } else if (isDegradedNode) {
          ctx.beginPath()
          ctx.arc(item.node.x + jitter, item.node.y - jitter * 0.4, item.node.radius + 5 + pulse * 2, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.12)`
          ctx.lineWidth = 0.9
          ctx.setLineDash([3, 6])
          ctx.stroke()
          ctx.setLineDash([])
        }

        const nodeFill = ctx.createRadialGradient(
          item.node.x - item.node.radius * 0.18,
          item.node.y - item.node.radius * 0.22,
          item.node.radius * 0.08,
          item.node.x,
          item.node.y,
          item.node.radius,
        )
        if (isLiveNode) {
          nodeFill.addColorStop(0, 'rgba(242,252,255,0.16)')
          nodeFill.addColorStop(0.28, `rgba(${hexToRgb(item.color)},0.14)`)
          nodeFill.addColorStop(1, 'rgba(4,10,18,0.26)')
        } else if (isRecentNode) {
          nodeFill.addColorStop(0, 'rgba(255,210,120,0.07)')
          nodeFill.addColorStop(0.3, 'rgba(240,192,64,0.06)')
          nodeFill.addColorStop(1, 'rgba(4,10,18,0.20)')
        } else {
          nodeFill.addColorStop(0, 'rgba(180,196,208,0.06)')
          nodeFill.addColorStop(0.3, 'rgba(78,96,112,0.08)')
          nodeFill.addColorStop(1, 'rgba(4,10,18,0.18)')
        }
        ctx.beginPath()
        ctx.arc(item.node.x, item.node.y, item.node.radius, 0, Math.PI * 2)
        ctx.fillStyle = nodeFill
        ctx.fill()
        ctx.strokeStyle = focused
          ? `rgba(${hexToRgb(item.color)},0.9)`
          : isLiveNode ? `rgba(${hexToRgb(item.color)},0.22)`
          : isRecentNode ? 'rgba(240,192,64,0.20)'
          : `rgba(${hexToRgb(item.color)},0.06)`
        ctx.lineWidth = 1
        ctx.stroke()

        if (isLiveNode) {
          const coreHighlight = ctx.createRadialGradient(item.node.x, item.node.y, 0, item.node.x, item.node.y, item.node.radius * 0.58)
          coreHighlight.addColorStop(0, 'rgba(255,255,255,0.34)')
          coreHighlight.addColorStop(0.35, `rgba(${hexToRgb(item.color)},0.16)`)
          coreHighlight.addColorStop(1, 'rgba(0,0,0,0)')
          ctx.fillStyle = coreHighlight
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 0.62, 0, Math.PI * 2)
          ctx.fill()
        }

        ctx.beginPath()
        ctx.arc(item.node.x, item.node.y, item.node.radius * 0.4, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(${hexToRgb(item.color)},${isLiveNode ? 0.4 : isRecentNode ? 0.16 : 0.12})`
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.strokeStyle = `rgba(${hexToRgb(item.color)},${isLiveNode ? 0.28 : isRecentNode ? 0.14 : isDegradedNode ? 0.12 : 0.05})`
        if (sig.shell === 'command') {
          ctx.beginPath()
          ctx.moveTo(item.node.x - item.node.radius * 0.55, item.node.y)
          ctx.lineTo(item.node.x + item.node.radius * 0.55, item.node.y)
          ctx.moveTo(item.node.x, item.node.y - item.node.radius * 0.55)
          ctx.lineTo(item.node.x, item.node.y + item.node.radius * 0.55)
          ctx.stroke()
          ctx.beginPath()
          ctx.rect(item.node.x - item.node.radius * 0.22, item.node.y - item.node.radius * 0.22, item.node.radius * 0.44, item.node.radius * 0.44)
          ctx.stroke()
        } else if (sig.shell === 'relay') {
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 0.58, -Math.PI * 0.22, Math.PI * 1.22)
          ctx.stroke()
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 0.26, 0, Math.PI * 2)
          ctx.stroke()
        } else if (sig.shell === 'sensor') {
          ctx.beginPath()
          ctx.ellipse(item.node.x, item.node.y, item.node.radius * 0.56, item.node.radius * 0.32, 0, 0, Math.PI * 2)
          ctx.stroke()
          ctx.beginPath()
          ctx.moveTo(item.node.x - item.node.radius * 0.52, item.node.y)
          ctx.lineTo(item.node.x + item.node.radius * 0.52, item.node.y)
          ctx.stroke()
          ctx.beginPath()
          ctx.arc(item.node.x, item.node.y, item.node.radius * 0.12, 0, Math.PI * 2)
          ctx.stroke()
        }

        if (focused) {
          const reticleRadius = item.node.radius * 2.2 + pulse * 1.5
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.42)`
          ctx.lineWidth = 1.2
          if (sig.shell === 'command') {
            ctx.beginPath()
            ctx.rect(item.node.x - reticleRadius, item.node.y - reticleRadius, reticleRadius * 2, reticleRadius * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(item.node.x - reticleRadius * 1.15, item.node.y)
            ctx.lineTo(item.node.x + reticleRadius * 1.15, item.node.y)
            ctx.moveTo(item.node.x, item.node.y - reticleRadius * 1.15)
            ctx.lineTo(item.node.x, item.node.y + reticleRadius * 1.15)
            ctx.stroke()
          } else if (sig.shell === 'relay') {
            const bracketArc = Math.PI * 0.12
            ;[0, Math.PI / 2, Math.PI, Math.PI * 1.5].forEach((angle) => {
              ctx.beginPath()
              ctx.arc(item.node.x, item.node.y, reticleRadius, angle - bracketArc, angle + bracketArc)
              ctx.stroke()
            })
          } else {
            ctx.beginPath()
            ctx.ellipse(item.node.x, item.node.y, reticleRadius * 1.04, reticleRadius * 0.62, 0, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(item.node.x - reticleRadius * 0.9, item.node.y)
            ctx.lineTo(item.node.x + reticleRadius * 0.9, item.node.y)
            ctx.stroke()
          }
          ctx.fillStyle = 'rgba(8,8,8,0.92)'
          ctx.fillRect(item.node.x - 34 * item.scale, item.node.y + item.node.radius + 10, 68 * item.scale, 10 * item.scale)
          ctx.strokeStyle = `rgba(${hexToRgb(item.color)},0.24)`
          ctx.strokeRect(item.node.x - 34 * item.scale, item.node.y + item.node.radius + 10, 68 * item.scale, 10 * item.scale)
          ctx.textAlign = 'center'
          ctx.font = `${Math.max(7, 7.4 * item.scale)}px sans-serif`
          ctx.fillStyle = '#f2f2f2'
          ctx.fillText(item.node.label.toUpperCase(), item.node.x, item.node.y + item.node.radius + 17)
        } else {
          // Always-visible name label, color encodes activity state
          const nameOpacity = isLiveNode ? 0.72 : isRecentNode ? 0.62 : isIdleNode ? 0.30 : 0.16
          const nameColor = isRecentNode
            ? `rgba(240,192,64,${nameOpacity})`
            : `rgba(${hexToRgb(item.color)},${nameOpacity})`
          const labelY = item.node.y + item.node.radius + Math.max(11, 13 * item.scale)
          ctx.textAlign = 'center'
          ctx.font = `${Math.max(6.5, 7.5 * item.scale)}px monospace`
          ctx.fillStyle = nameColor
          ctx.fillText(item.node.label.toUpperCase(), item.node.x, labelY)
          // Activity dot below name for live/recent agents
          if (isLiveNode || isRecentNode) {
            const dotColor = isLiveNode ? STATUS_COLORS.green : STATUS_COLORS.amber
            const dotY = labelY + Math.max(7, 8 * item.scale)
            const dotR = Math.max(1.8, 2.2 * item.scale)
            if (isLiveNode) { ctx.shadowColor = STATUS_COLORS.green; ctx.shadowBlur = 5 }
            ctx.fillStyle = dotColor
            ctx.beginPath()
            ctx.arc(item.node.x, dotY, dotR, 0, Math.PI * 2)
            ctx.fill()
            ctx.shadowBlur = 0
          }
        }
      })

      // Core
      ctx.beginPath()
      ctx.arc(cx, cy, 20 * breathe, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(10,10,10,0.42)'
      ctx.fill()
      ctx.strokeStyle = 'rgba(225,246,255,0.44)'
      ctx.lineWidth = 1.4
      ctx.stroke()
      ctx.fillStyle = 'rgba(225,225,225,0.22)'
      ctx.beginPath()
      ctx.arc(cx, cy, 10 * breathe, 0, Math.PI * 2)
      ctx.fill()

      ctx.fillStyle = 'rgba(255,255,255,0.98)'
      ctx.beginPath()
      ctx.arc(cx, cy, 4.2, 0, Math.PI * 2)
      ctx.fill()

      ctx.strokeStyle = 'rgba(255,255,255,0.1)'
      ctx.lineWidth = 0.8
      ctx.beginPath()
      ctx.moveTo(W * 0.22, cy)
      ctx.lineTo(W * 0.78, cy)
      ctx.moveTo(cx, H * 0.2)
      ctx.lineTo(cx, H * 0.8)
      ctx.stroke()

      // ── Scanline / CRT interlace overlay ─────────────────────────────────
      const scanlineAlpha = 0.026 + Math.sin(t * 0.38) * 0.005
      const scanlineStep = 3
      const scanlineScroll = Math.floor(t * 20) % scanlineStep
      ctx.fillStyle = `rgba(0,0,0,${scanlineAlpha})`
      for (let sy = scanlineScroll; sy < H; sy += scanlineStep) {
        ctx.fillRect(0, sy, W, 1)
      }
      // slow-drifting horizontal glow band — holographic refresh artifact
      const scanBandY = (t * 0.055 % 1) * H
      const scanBand = ctx.createLinearGradient(0, scanBandY - 28, 0, scanBandY + 28)
      scanBand.addColorStop(0, 'rgba(120,210,255,0)')
      scanBand.addColorStop(0.5, 'rgba(120,210,255,0.018)')
      scanBand.addColorStop(1, 'rgba(120,210,255,0)')
      ctx.fillStyle = scanBand
      ctx.fillRect(0, scanBandY - 28, W, 56)

      animRef.current = requestAnimationFrame(draw)
    }

    animRef.current = requestAnimationFrame(draw)
    return () => {
      running = false
      cancelAnimationFrame(animRef.current)
    }
  }, [agentLookup, hoveredNode, pinnedNode, realPanelData, serviceLookup])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const resize = () => {
      const ratio = window.devicePixelRatio || 1
      canvas.width = canvas.offsetWidth * ratio
      canvas.height = canvas.offsetHeight * ratio
      const ctx = canvas.getContext('2d')
      if (ctx) ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    }
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const findNode = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect()
      const x = clientX - rect.left
      const y = clientY - rect.top
      const reversed = [...nodesRef.current].reverse()
      return reversed.find((node) => Math.hypot(x - node.x, y - node.y) <= node.radius) ?? null
    }

    const onMove = (e: MouseEvent) => {
      const hit = findNode(e.clientX, e.clientY)
      setHoveredNode(hit)
      canvas.style.cursor = hit ? 'pointer' : 'default'
    }

    const onLeave = () => {
      setHoveredNode(null)
      canvas.style.cursor = 'default'
    }

    const onClick = (e: MouseEvent) => {
      const hit = findNode(e.clientX, e.clientY)
      setPinnedNode((prev) => {
        if (!hit) {
          onSelectionChange?.(null)
          return null
        }
        if (prev && prev.type === hit.type && prev.key === hit.key) {
          onSelectionChange?.(null)
          return null
        }
        onSelectionChange?.({ type: hit.type, key: hit.key, label: hit.label })
        return hit
      })
    }

    canvas.addEventListener('mousemove', onMove)
    canvas.addEventListener('mouseleave', onLeave)
    canvas.addEventListener('click', onClick)
    return () => {
      canvas.removeEventListener('mousemove', onMove)
      canvas.removeEventListener('mouseleave', onLeave)
      canvas.removeEventListener('click', onClick)
    }
  }, [onSelectionChange])

  const activeNode = pinnedNode ?? hoveredNode
  const activeAgent = activeNode?.type === 'agent' ? agentLookup[activeNode.key] : null
  const activeService = activeNode?.type === 'service' ? serviceLookup[activeNode.key] : null
  const isCompact = typeof window !== 'undefined' ? window.innerWidth < 860 : false
  const permanentAgentKeys = Object.keys(AGENT_POINTS)
  const memoryCause = memorySummary?.primary_cause?.kind ?? routingSummary?.memory_mode ?? 'healthy'
  const memoryCauseSummary = memorySummary?.primary_cause?.summary ?? 'Memory path is healthy.'
  const memoryCauseColor =
    memoryCause === 'healthy' ? STATUS_COLORS.green
      : memoryCause === 'pressure' || memoryCause === 'stale' ? STATUS_COLORS.amber
      : STATUS_COLORS.red
  const memoryHeavyTarget = routingSummary?.guidance?.memory_heavy

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
      <div
        style={{
          position: 'absolute',
          left: isCompact ? 10 : 20,
          top: isCompact ? 10 : 132,
          bottom: isCompact ? 10 : 20,
          width: isCompact ? 'min(280px, calc(100% - 20px))' : 292,
          display: 'flex',
          flexDirection: 'column',
          background: 'linear-gradient(160deg, rgba(8,4,18,0.92), rgba(4,2,12,0.88))',
          border: '1px solid rgba(160,100,255,0.24)',
          backdropFilter: 'blur(18px)',
          WebkitBackdropFilter: 'blur(18px)',
          boxShadow: '0 0 32px rgba(160,100,255,0.08), inset 0 0 20px rgba(160,100,255,0.03)',
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
      >
        {([['top','left'],['top','right'],['bottom','left'],['bottom','right']] as const).map(([tb,lr]) => (
          <div key={`dock-${tb}${lr}`} style={{
            position:'absolute', [tb]:0, [lr]:0, width:10, height:10,
            [`border${tb.charAt(0).toUpperCase()+tb.slice(1)}`]: '1.5px solid rgba(100,214,255,0.64)',
            [`border${lr.charAt(0).toUpperCase()+lr.slice(1)}`]: '1.5px solid rgba(100,214,255,0.64)',
            pointerEvents:'none',
          }} />
        ))}
        <div style={{ padding: '12px 14px 14px', overflowY: 'auto', flex: 1, minHeight: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: 'rgba(180,140,255,0.6)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>
              Agent Mesh
            </span>
            {pinnedNode ? (
              <button
                type="button"
                onClick={() => { setPinnedNode(null); onSelectionChange?.(null) }}
                style={{ border: 'none', background: 'transparent', color: 'rgba(140,100,200,0.6)', fontSize: 10, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.14em', padding: 0 }}
              >
                ✕ clear
              </button>
            ) : (
              <span style={{ fontSize: 10, color: 'rgba(140,100,200,0.4)', letterSpacing: '0.12em' }}>live</span>
            )}
          </div>

          <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
            {permanentAgentKeys.map((agentKey) => {
              const agent = agentLookup[agentKey]
              const isFocused = activeNode?.type === 'agent' && activeNode.key === agentKey
              const accent = AGENT_COLORS[agentKey] ?? '#dffbff'
              const accentRgb = hexToRgb(accent)
              const statusRaw = (agent?.health_status ?? agent?.presence?.status ?? agent?.status ?? 'offline').toLowerCase()
              const isUp = ['online','active','busy','registered'].some(k => statusRaw.includes(k))
              const modelLabel = agent?.model?.split('/').pop()?.slice(0, 18) ?? '—'
              const hermesNativeProfiles = (agent?.local_profiles ?? []).filter((profile) => profile.profile_kind === 'hermes-native')
              const hermesRunningProfiles = hermesNativeProfiles.filter((profile) => profile.running).length
              const hermesProfileSummary = hermesNativeProfiles.length > 0
                ? `${hermesRunningProfiles}/${hermesNativeProfiles.length}`
                : null
              const hermesLatestTitle = agentKey === 'hermes'
                ? hermesNativeProfiles.find((profile) => profile.session_overview?.latest_title)?.session_overview?.latest_title
                : null
              const hermesBackgroundCount = agentKey === 'hermes'
                ? ((hermesStatus?.background_tasks ?? []).filter((task) => task.running).length)
                : null

              const activityStatus = agent?.activity_status ?? null
              const activityLabel = !agent ? 'OFFLINE'
                : activityStatus === 'live' ? 'ACTIVE'
                : activityStatus === 'recent' ? 'RECENT'
                : activityStatus === 'idle' || activityStatus === 'stale' ? 'IDLE'
                : isUp ? 'ONLINE' : 'OFFLINE'
              const activityColor = activityLabel === 'ACTIVE' ? STATUS_COLORS.green
                : activityLabel === 'RECENT' ? STATUS_COLORS.amber
                : activityLabel === 'IDLE' || activityLabel === 'ONLINE' ? 'rgba(140,110,200,0.7)'
                : STATUS_COLORS.red
              const contextLine: string = (() => {
                if (agent?.task) return agent.task.slice(0, 60)
                if (agentKey === 'hermes' && hermesBackgroundCount != null && hermesBackgroundCount > 0) {
                  return `${hermesBackgroundCount} ${hermesBackgroundCount === 1 ? 'task' : 'tasks'} in background`
                }
                if (agentKey === 'hermes' && hermesLatestTitle) return hermesLatestTitle.slice(0, 60)
                return 'standby'
              })()

              return (
                <div
                  key={agentKey}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '13px 14px',
                    border: isFocused ? `2px solid rgba(${accentRgb},0.52)` : '1px solid rgba(160,100,255,0.1)',
                    background: isFocused ? `linear-gradient(180deg, rgba(${accentRgb},0.12), rgba(255,255,255,0.035))` : 'rgba(255,255,255,0.018)',
                    boxShadow: isFocused ? `0 0 30px rgba(${accentRgb},0.18), inset 0 0 0 1px rgba(${accentRgb},0.08)` : 'none',
                    opacity: isFocused ? 1 : 0.9,
                    transform: 'scale(1)',
                    position: 'relative',
                  }}
                >
                  {isFocused && (
                    <div
                      style={{
                        position: 'absolute',
                        inset: -1,
                        pointerEvents: 'none',
                        background: `linear-gradient(135deg, rgba(${accentRgb},0.14), transparent 30%, transparent 70%, rgba(${accentRgb},0.08))`,
                        mixBlendMode: 'screen',
                      }}
                    />
                  )}
                  <div style={{ height: 1, background: isFocused ? `linear-gradient(90deg, rgba(${accentRgb},1), rgba(${accentRgb},0.18))` : `linear-gradient(90deg, rgba(${accentRgb},0.35), rgba(${accentRgb},0.05))`, marginBottom: 10 }} />

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                    <span style={{ fontSize: 9, color: 'rgba(180,140,255,0.45)', letterSpacing: '0.18em', textTransform: 'uppercase' }}>
                      {AGENT_ROLES[agentKey] ?? agentKey}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <div style={{ width: 6, height: 6, borderRadius: '50%', background: activityColor, boxShadow: activityLabel === 'ACTIVE' ? `0 0 6px ${activityColor}` : 'none' }} />
                      <span style={{ fontSize: 9, color: activityColor, letterSpacing: '0.12em' }}>{activityLabel}</span>
                    </div>
                  </div>

                  <div style={{ fontSize: 16, color: accent, fontWeight: 700, letterSpacing: '0.06em', lineHeight: 1.1, marginBottom: 6, textShadow: isFocused ? `0 0 20px rgba(${accentRgb},0.4)` : 'none' }}>
                    {AGENT_LABELS[agentKey] ?? agentKey}
                  </div>

                  <div style={{ fontSize: 11, color: isFocused ? 'rgba(220,200,255,0.7)' : 'rgba(160,130,210,0.55)', lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {contextLine}
                  </div>

                  {isFocused && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ height: 1, background: `rgba(${accentRgb},0.15)`, marginBottom: 10 }} />
                      {modelLabel !== '—' && (
                        <div style={{ marginBottom: 8 }}>
                          <span style={{ fontSize: 9, color: 'rgba(180,160,220,0.65)', background: 'rgba(160,100,255,0.08)', padding: '3px 8px', border: '1px solid rgba(160,100,255,0.16)', letterSpacing: '0.1em', borderRadius: 2 }}>
                            {modelLabel}
                          </span>
                        </div>
                      )}
                      {agentKey === 'hermes' && hermesBackgroundCount != null && hermesBackgroundCount > 0 && (
                        <div style={{ fontSize: 11, color: 'rgba(200,180,255,0.75)', marginBottom: 4 }}>
                          {hermesBackgroundCount} background {hermesBackgroundCount === 1 ? 'task' : 'tasks'} running
                        </div>
                      )}
                      {agentKey === 'hermes' && hermesProfileSummary && (
                        <div style={{ fontSize: 11, color: 'rgba(180,160,220,0.6)', marginBottom: 4 }}>
                          {hermesProfileSummary} profiles active
                        </div>
                      )}
                      {agent?.task && agent.task.length > 60 && (
                        <div style={{ fontSize: 11, color: '#f2fbff', lineHeight: 1.55, marginTop: 6 }}>
                          {agent.task.slice(0, 120)}
                        </div>
                      )}
                      {agentKey === 'hermes' && hermesLatestTitle && !agent?.task && (
                        <div style={{ fontSize: 11, color: '#f2fbff', lineHeight: 1.55, marginTop: 6 }}>
                          {hermesLatestTitle}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {memorySummary && (
            <div
              style={{
                marginTop: 10,
                padding: '12px 13px',
                border: '1px solid rgba(100,210,255,0.12)',
                background: 'rgba(255,255,255,0.02)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 10, color: 'rgba(150,220,255,0.6)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>
                  Memory Route
                </span>
                <span style={{ fontSize: 12, color: memoryCauseColor, letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                  {memoryCause}
                </span>
              </div>

              <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'rgba(150,200,220,0.5)', letterSpacing:'0.12em', textTransform:'uppercase' }}>Gateway</div>
                  <div style={{ fontSize: 13, color: memorySummary.component_health?.gateway === 'up' ? STATUS_COLORS.green : STATUS_COLORS.red, marginTop: 4 }}>
                    {memorySummary.component_health?.gateway ?? 'unknown'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'rgba(150,200,220,0.5)', letterSpacing:'0.12em', textTransform:'uppercase' }}>Substrate</div>
                  <div style={{ fontSize: 13, color: memorySummary.component_health?.substrate === 'up' ? STATUS_COLORS.green : memorySummary.component_health?.substrate === 'down' ? STATUS_COLORS.red : STATUS_COLORS.amber, marginTop: 4 }}>
                    {memorySummary.component_health?.substrate ?? 'unknown'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'rgba(150,200,220,0.5)', letterSpacing:'0.12em', textTransform:'uppercase' }}>Impact</div>
                  <div style={{ fontSize: 13, color: '#dffbff', marginTop: 4 }}>
                    {routingSummary?.guidance?.memory_heavy ?? '—'}
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 9, padding: '9px 10px', border: '1px solid rgba(100,210,255,0.08)', background: 'rgba(255,255,255,0.02)' }}>
                <div style={{ fontSize: 10, color: 'rgba(150,220,255,0.56)', letterSpacing: '0.16em', textTransform: 'uppercase', marginBottom: 5 }}>
                  Primary Cause
                </div>
                <div style={{ fontSize: 12, color: 'rgba(220,242,250,0.86)', lineHeight: 1.55 }}>
                  {memoryCauseSummary}
                </div>
              </div>
            </div>
          )}

          {activeService && (() => {
        const statusRaw = (activeService?.status ?? '').toLowerCase()
        const isUp = ['online','active','busy','up','healthy','registered'].some(k => statusRaw.includes(k))
        const isDegraded = ['degraded','partial'].some(k => statusRaw.includes(k))
        const statusColor = isUp ? STATUS_COLORS.green : isDegraded ? STATUS_COLORS.amber : STATUS_COLORS.red
        const statusLabel = isUp ? 'ONLINE' : isDegraded ? 'DEGRADED' : statusRaw ? statusRaw.toUpperCase() : 'OFFLINE'
        const modelLabel = activeService?.active_model?.split('/').pop()?.slice(0, 18) ?? null
        const serviceSummary =
          activeService?.error?.slice(0, 88) ??
          (activeService?.models && activeService.models.length > 0 && !activeService.active_model ? activeService.models.slice(0, 2).join(' • ') : null)
        return (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(100,210,255,0.1)' }}>
              {/* header row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: 'rgba(150,220,255,0.6)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>
                  Service Detail
                </span>
                <span style={{ fontSize: 10, color: 'rgba(100,150,180,0.4)', letterSpacing: '0.12em' }}>{pinnedNode ? 'pinned' : 'preview'}</span>
              </div>
              {/* node name */}
              <div style={{ marginTop: 7, fontSize: 22, color: '#dffbff', letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 700, lineHeight: 1.35 }}>
                {activeNode?.label}
              </div>
              {/* status badge */}
              <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor, boxShadow: `0 0 6px ${statusColor}` }} />
                <span style={{ fontSize: 13, color: statusColor, letterSpacing: '0.16em' }}>{statusLabel}</span>
              </div>
              {modelLabel && (
                <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <span style={{ fontSize: 10, color: 'rgba(150,200,220,0.55)', letterSpacing:'0.1em', textTransform:'uppercase' }}>Model</span>
                  <span style={{ fontSize: 12, color: '#c8eaf8', textAlign: 'right' }}>{modelLabel}</span>
                </div>
              )}
              {/* divider */}
              <div style={{ margin: '8px 0', height: 1, background: 'rgba(100,210,255,0.1)' }} />
              {/* service details */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {activeService.status && (
                    <div style={{ display:'flex', justifyContent:'space-between' }}>
                      <span style={{ fontSize: 10, color: 'rgba(150,200,220,0.55)', letterSpacing:'0.1em', textTransform:'uppercase' }}>State</span>
                      <span style={{ fontSize: 12, color: '#c8eaf8' }}>{activeService.status}</span>
                    </div>
                  )}
                  {serviceSummary && (
                    <div style={{ marginTop: 5, padding: '10px 11px', border: '1px solid rgba(100,210,255,0.12)', background: 'rgba(255,255,255,0.03)' }}>
                      <div style={{ fontSize: 10, color: 'rgba(150,220,255,0.56)', letterSpacing: '0.18em', textTransform: 'uppercase', marginBottom: 5 }}>
                        {activeService.error ? 'Fault Detail' : 'Service Notes'}
                      </div>
                      <div style={{ fontSize: 12, color: activeService.error ? '#ff928a' : 'rgba(202,234,245,0.82)', lineHeight: 1.55 }}>{serviceSummary}</div>
                    </div>
                  )}
                </div>
          </div>
        )
      })()}
        </div>
      </div>
    </div>
  )
}
