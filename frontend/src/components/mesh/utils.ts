import type { Vec3, GraphNodeMeta } from './constants'
import type { GraphSelection } from '../../types'

export function hexToRgb(hex: string) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r},${g},${b}`
}

export function normKey(value: string | undefined) {
  return (value ?? '').toLowerCase().replace(/\s+/g, '-')
}

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max))
}

export function agentSignature(key: string) {
  switch (key) {
    case 'atlas':
      return {
        cadence: 0.9,
        orbitA: 1.04,
        orbitB: 0.72,
        halo: 0.22,
        shell: 'command' as const,
      }
    case 'hermes':
      return {
        cadence: 1.35,
        orbitA: 1.3,
        orbitB: 0.94,
        halo: 0.18,
        shell: 'relay' as const,
      }
    case 'iriseye':
      return {
        cadence: 1.08,
        orbitA: 0.86,
        orbitB: 1.22,
        halo: 0.2,
        shell: 'sensor' as const,
      }
    default:
      return {
        cadence: 1,
        orbitA: 1,
        orbitB: 1,
        halo: 0.18,
        shell: 'relay' as const,
      }
  }
}

export function panelPath(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, cut: number) {
  ctx.beginPath()
  ctx.moveTo(x + cut, y)
  ctx.lineTo(x + w - cut * 1.4, y)
  ctx.lineTo(x + w, y + cut * 0.72)
  ctx.lineTo(x + w, y + h - cut)
  ctx.lineTo(x + w - cut, y + h)
  ctx.lineTo(x + cut * 0.9, y + h)
  ctx.lineTo(x, y + h - cut * 0.8)
  ctx.lineTo(x, y + cut)
  ctx.closePath()
}

export function rotateY(point: Vec3, angle: number): Vec3 {
  return {
    x: point.x * Math.cos(angle) - point.z * Math.sin(angle),
    y: point.y,
    z: point.x * Math.sin(angle) + point.z * Math.cos(angle),
  }
}

export function rotateX(point: Vec3, angle: number): Vec3 {
  return {
    x: point.x,
    y: point.y * Math.cos(angle) - point.z * Math.sin(angle),
    z: point.y * Math.sin(angle) + point.z * Math.cos(angle),
  }
}

export function project(point: Vec3, cx: number, cy: number, radius: number) {
  const perspective = 0.7 + (point.z + 1) * 0.22
  return {
    x: cx + point.x * radius * perspective,
    y: cy + point.y * radius * perspective,
    scale: perspective,
    z: point.z,
  }
}

export function selectionMeta(selection: GraphSelection | null): GraphNodeMeta | null {
  if (!selection) return null
  return { type: selection.type, key: selection.key, label: selection.label, x: 0, y: 0, radius: 0 }
}

