import { useRef, useEffect } from 'react'
import { useDashboardStore } from '../../store/dashboardStore'
import { C, SectionTitle } from './Primitives'

export default function LogsTab() {
  const logs = useDashboardStore((s) => s.logs)
  const bottomRef = useRef<HTMLDivElement>(null)

  const combined = [
    ...logs.memory.map((l) => ({ src: 'mem', line: l })),
    ...logs.mlx.map((l) => ({ src: 'mlx', line: l })),
  ].sort((a, b) => {
    const ta = a.line.match(/\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}/)?.[0] ?? ''
    const tb = b.line.match(/\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}/)?.[0] ?? ''
    return ta < tb ? -1 : ta > tb ? 1 : 0
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [combined.length])

  if (combined.length === 0) {
    return <p style={{ fontSize: 10, color: '#2e1e50', padding: 12 }}>No log entries yet.</p>
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {combined.map(({ src, line }, i) => {
        const isWarn = line.includes('WARNING') || line.includes('WARN')
        const isErr = line.includes('ERROR') || line.includes('restart') || line.includes('OOM')
        const color = isErr ? '#ef4444' : isWarn ? '#f59e0b' : src === 'mlx' ? '#5e4a78' : '#42326a'
        const badge = src === 'mlx' ? '#1e1035' : '#0f0821'
        return (
          <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start', padding: '4px 0', borderBottom: '1px solid rgba(15,8,30,0.45)' }}>
            <span style={{ fontSize: 8, color: '#42326a', background: badge, padding: '2px 5px', borderRadius: 999, flexShrink: 0, marginTop: 1 }}>
              {src}
            </span>
            <span style={{ fontSize: 9, color, fontFamily: 'monospace', lineHeight: 1.5, wordBreak: 'break-all' }}>
              {line}
            </span>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

