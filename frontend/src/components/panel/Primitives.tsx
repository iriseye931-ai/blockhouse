import { useState, type ReactNode } from 'react'

type Tab = 'logs' | 'amp' | 'hermes' | 'rag'
type HermesView = 'overview' | 'agents' | 'audit'

export const TAB_LABELS: { id: Tab; label: string }[] = [
  { id: 'logs', label: 'Logs' },
  { id: 'amp', label: 'AMP' },
  { id: 'hermes', label: 'Hermes' },
  { id: 'rag', label: 'RAG' },
]

export const C = {
  panel: '#0d0919',
  panel2: '#160e2a',
  panel3: '#0d0619',
  border: '#2a1a45',
  borderHi: '#5a3585',
  text: '#f4eeff',
  textSoft: '#9b85c8',
  textDim: '#6a4d8c',
  cyan: '#b580ff',
  teal: '#8f5fcf',
  amber: '#f3b55e',
  green: '#8fe6b8',
  red: '#ff6f6a',
  violet: '#b580ff',
}

export function panelSurface(emphasis: 'base' | 'raised' = 'base') {
  return {
    border: `1px solid ${emphasis === 'raised' ? C.borderHi : C.border}`,
    background: emphasis === 'raised'
      ? 'linear-gradient(180deg, rgba(24,10,45,0.96), rgba(11,5,22,0.98))'
      : 'linear-gradient(180deg, rgba(17,8,32,0.94), rgba(9,4,18,0.98))',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06), 0 14px 28px rgba(0,0,0,0.18)',
  } as const
}

export function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <div
      className="flex shrink-0"
      style={{
        borderBottom: `1px solid ${C.border}`,
        padding: '12px 14px 10px',
        gap: 6,
        flexWrap: 'wrap',
        background: 'linear-gradient(180deg, rgba(20,10,38,0.92), rgba(10,5,22,0.9))',
      }}
    >
      {TAB_LABELS.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          style={{
            padding: '8px 14px',
            fontSize: 9,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            fontFamily: 'inherit',
            borderRadius: 999,
            border: `1px solid ${active === id ? (id === 'rag' ? '#7f6ab0' : C.borderHi) : C.border}`,
            background: active === id ? (id === 'rag' ? 'linear-gradient(180deg, rgba(65,41,101,0.96), rgba(26,17,47,0.98))' : 'linear-gradient(180deg, rgba(40,15,70,0.96), rgba(15,8,30,0.98))') : 'rgba(11,6,22,0.92)',
            color: active === id ? (id === 'rag' ? C.violet : C.cyan) : C.textSoft,
            cursor: 'pointer',
            boxShadow: active === id ? '0 12px 22px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.05)' : 'none',
          }}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function SectionTitle({ children }: { children: string }) {
  return (
    <p style={{ fontSize: 8, color: C.textDim, letterSpacing: '0.2em', textTransform: 'uppercase', marginBottom: 10 }}>
      {children}
    </p>
  )
}

export function PanelCard({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div
      style={{
        padding: compact ? '8px 9px' : '10px 11px',
        borderRadius: 14,
        ...panelSurface(compact ? 'base' : 'raised'),
      }}
    >
      {children}
    </div>
  )
}

export function MiniStat({ label, value, tone = '#9485a8' }: { label: string; value: string | number; tone?: string }) {
  return (
    <div
      style={{
        padding: '9px 10px',
        borderRadius: 14,
        ...panelSurface(),
      }}
    >
      <div style={{ fontSize: 8, color: C.textDim, textTransform: 'uppercase', letterSpacing: '0.16em' }}>
        {label}
      </div>
      <div style={{ marginTop: 5, fontSize: 14, color: tone, fontFamily: 'monospace', lineHeight: 1 }}>
        {value}
      </div>
    </div>
  )
}

export function ViewTabs({ active, onChange }: { active: HermesView; onChange: (value: HermesView) => void }) {
  const views: HermesView[] = ['overview', 'agents', 'audit']
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {views.map((view) => (
        <button
          key={view}
          type="button"
          onClick={() => onChange(view)}
          style={{
            padding: '5px 9px',
            borderRadius: 999,
            border: `1px solid ${active === view ? C.borderHi : C.border}`,
            background: active === view ? 'linear-gradient(180deg, rgba(40,15,70,0.96), rgba(15,8,30,0.98))' : 'rgba(11,6,22,0.92)',
            color: active === view ? C.cyan : C.textSoft,
            cursor: 'pointer',
            fontSize: 8,
            textTransform: 'uppercase',
            letterSpacing: '0.14em',
          }}
        >
          {view}
        </button>
      ))}
    </div>
  )
}
