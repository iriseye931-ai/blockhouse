import { useState, useRef, useEffect, type FormEvent, type ReactNode } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { GraphSelection, PermissionAuditEntry } from '../types'
import RAGSearch from './RAGSearch'
import AmpInbox from './AmpInbox'

type Tab = 'logs' | 'amp' | 'hermes' | 'rag'
type HermesView = 'overview' | 'agents' | 'audit'

const TAB_LABELS: { id: Tab; label: string }[] = [
  { id: 'logs', label: 'Logs' },
  { id: 'amp', label: 'AMP' },
  { id: 'hermes', label: 'Hermes' },
  { id: 'rag', label: 'RAG' },
]

const C = {
  panel: '#0f1929',
  panel2: '#15233a',
  panel3: '#0b1220',
  border: '#24374d',
  borderHi: '#4c6c8f',
  text: '#eaf4ff',
  textSoft: '#9db1c7',
  textDim: '#647992',
  cyan: '#74d8ff',
  teal: '#49c7cf',
  amber: '#f3b55e',
  green: '#8fe6b8',
  red: '#ff6f6a',
  violet: '#b399ff',
}

function panelSurface(emphasis: 'base' | 'raised' = 'base') {
  return {
    border: `1px solid ${emphasis === 'raised' ? C.borderHi : C.border}`,
    background: emphasis === 'raised'
      ? 'linear-gradient(180deg, rgba(24,40,65,0.96), rgba(11,18,31,0.98))'
      : 'linear-gradient(180deg, rgba(17,29,49,0.94), rgba(9,15,26,0.98))',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06), 0 14px 28px rgba(0,0,0,0.18)',
  } as const
}

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <div
      className="flex shrink-0"
      style={{
        borderBottom: `1px solid ${C.border}`,
        padding: '12px 14px 10px',
        gap: 6,
        flexWrap: 'wrap',
        background: 'linear-gradient(180deg, rgba(20,34,56,0.92), rgba(10,17,29,0.9))',
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
            background: active === id ? (id === 'rag' ? 'linear-gradient(180deg, rgba(65,41,101,0.96), rgba(26,17,47,0.98))' : 'linear-gradient(180deg, rgba(34,62,97,0.96), rgba(15,29,49,0.98))') : 'rgba(11,18,32,0.92)',
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

function SectionTitle({ children }: { children: string }) {
  return (
    <p style={{ fontSize: 8, color: C.textDim, letterSpacing: '0.2em', textTransform: 'uppercase', marginBottom: 10 }}>
      {children}
    </p>
  )
}

function PanelCard({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
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

function MiniStat({ label, value, tone = '#94a3b8' }: { label: string; value: string | number; tone?: string }) {
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

function ViewTabs({ active, onChange }: { active: HermesView; onChange: (value: HermesView) => void }) {
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
            background: active === view ? 'linear-gradient(180deg, rgba(34,62,97,0.96), rgba(15,29,49,0.98))' : 'rgba(11,18,32,0.92)',
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

function LogsTab() {
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
    return <p style={{ fontSize: 10, color: '#334155', padding: 12 }}>No log entries yet.</p>
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {combined.map(({ src, line }, i) => {
        const isWarn = line.includes('WARNING') || line.includes('WARN')
        const isErr = line.includes('ERROR') || line.includes('restart') || line.includes('OOM')
        const color = isErr ? '#ef4444' : isWarn ? '#f59e0b' : src === 'mlx' ? '#64748b' : '#475569'
        const badge = src === 'mlx' ? '#1e293b' : '#0f172a'
        return (
          <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start', padding: '4px 0', borderBottom: '1px solid rgba(15,23,42,0.45)' }}>
            <span style={{ fontSize: 8, color: '#475569', background: badge, padding: '2px 5px', borderRadius: 999, flexShrink: 0, marginTop: 1 }}>
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

function HermesTab({
  focus,
  onFocusChange,
}: {
  focus: GraphSelection | null
  onFocusChange?: (focus: GraphSelection | null) => void
}) {
  const status = useDashboardStore((s) => s.hermesStatus)
  const cronJobs = useDashboardStore((s) => s.cronJobs)
  const agents = useDashboardStore((s) => s.agents)
  const services = useDashboardStore((s) => s.services)
  const routingSummary = useDashboardStore((s) => s.routingSummary)
  const permissionAuditSummary = useDashboardStore((s) => s.permissionAuditSummary)
  const premiumPool = agents.filter((agent) => agent.routing_group === 'premium-pool')
  const localDefault = agents.find((agent) => agent.routing_group === 'local-default')

  const [view, setView] = useState<HermesView>('overview')
  const [taskText, setTaskText] = useState('')
  const [dispatchTask, setDispatchTask] = useState(false)
  const [submittingTask, setSubmittingTask] = useState(false)
  const [taskResult, setTaskResult] = useState<string | null>(null)
  const [availabilityBusy, setAvailabilityBusy] = useState<string | null>(null)
  const [profileBusy, setProfileBusy] = useState<string | null>(null)
  const [backgroundPrompt, setBackgroundPrompt] = useState('')
  const [backgroundProfile, setBackgroundProfile] = useState('default')
  const [backgroundWorktree, setBackgroundWorktree] = useState(false)
  const [backgroundBusy, setBackgroundBusy] = useState(false)
  const [backgroundStopBusy, setBackgroundStopBusy] = useState<string | null>(null)
  const [backgroundCleanupBusy, setBackgroundCleanupBusy] = useState<string | null>(null)
  const [backgroundPollBusy, setBackgroundPollBusy] = useState<string | null>(null)
  const [backgroundLogBusy, setBackgroundLogBusy] = useState<string | null>(null)
  const [backgroundLogs, setBackgroundLogs] = useState<Record<string, string>>({})
  const [quickCommandBusy, setQuickCommandBusy] = useState<string | null>(null)
  const [auditEntries, setAuditEntries] = useState<PermissionAuditEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [expandedAgents, setExpandedAgents] = useState<Record<string, boolean>>({})
  const agentRowRefs = useRef<Record<string, HTMLDetailsElement | null>>({})

  const nextJob = cronJobs
    .filter((j) => j.enabled !== false && j.next_run_in_seconds != null)
    .sort((a, b) => (a.next_run_in_seconds ?? Infinity) - (b.next_run_in_seconds ?? Infinity))[0]

  function fmtIn(secs: number | null | undefined) {
    if (secs == null) return '—'
    if (secs < 60) return `${secs}s`
    if (secs < 3600) return `${Math.floor(secs / 60)}m`
    return `${Math.floor(secs / 3600)}h`
  }

  function fmtAgo(secs: number | null | undefined) {
    if (secs == null) return 'unknown'
    if (secs < 60) return `${secs}s ago`
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
    return `${Math.floor(secs / 86400)}d ago`
  }

  async function loadAudit() {
    setAuditLoading(true)
    try {
      const res = await fetch('/api/permissions/audit?last=12')
      const data = await res.json()
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setAuditEntries(Array.isArray(data.entries) ? data.entries.slice().reverse() : [])
    } catch {
      setAuditEntries([])
    } finally {
      setAuditLoading(false)
    }
  }

  useEffect(() => {
    void loadAudit()
  }, [])

  useEffect(() => {
    if (!focus) return
    if (focus.type === 'agent') {
      setView('agents')
      const match = agents.find((agent) => (agent.name ?? '').toLowerCase().replace(/\s+/g, '-') === focus.key)
      if (match) {
        setExpandedAgents((current) => ({ ...current, [match.id]: true }))
        requestAnimationFrame(() => {
          agentRowRefs.current[match.id]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        })
      }
      return
    }
    setView('overview')
  }, [focus, agents])

  const showSession = status && status.status !== 'unavailable' && status.status !== 'no sessions'
  const sessionProfiles = status?.sessions?.profiles ?? []
  const hermesAgent = agents.find((agent) => agent.name === 'hermes')
  const hermesNativeProfiles = (hermesAgent?.local_profiles ?? []).filter((profile) => profile.profile_kind === 'hermes-native')
  const backgroundTasks = status?.background_tasks ?? []
  const activeProfileMeta = hermesNativeProfiles.find((profile) => (profile.hermes_profile ?? profile.display_name ?? profile.name) === backgroundProfile) ?? hermesNativeProfiles[0]
  const quickCommands = activeProfileMeta?.quick_commands ?? []
  const hermesProfileMeta = Object.fromEntries(
    hermesNativeProfiles.map((profile) => [profile.hermes_profile ?? profile.display_name ?? profile.name, profile]),
  )
  const checkpointReadyProfiles = hermesNativeProfiles.filter((profile) => profile.checkpoint_overview?.rollback_ready).length
  const providerReadyProfiles = hermesNativeProfiles.filter((profile) => profile.provider_overview?.primary?.provider).length
  const smartRoutingProfiles = hermesNativeProfiles.filter((profile) => profile.provider_overview?.smart_routing_enabled).length
  const fallbackProfiles = hermesNativeProfiles.filter((profile) => (profile.provider_overview?.fallback_count ?? 0) > 0).length
  const sharedSkillProfiles = hermesNativeProfiles.filter((profile) => profile.skill_overview?.shared_skills_connected).length
  const memoryEnabledProfiles = hermesNativeProfiles.filter((profile) => profile.memory_overview?.memory_enabled).length
  const memoryFileProfiles = hermesNativeProfiles.filter((profile) => profile.memory_overview?.memory_file_exists || profile.memory_overview?.user_file_exists).length
  const memoryExternalActiveProfiles = hermesNativeProfiles.filter((profile) => profile.memory_overview?.external_provider_active).length
  const memoryExternalReadyProfiles = hermesNativeProfiles.filter((profile) => profile.memory_overview?.external_provider_available).length
  const focusedAgent = focus?.type === 'agent'
    ? agents.find((agent) => (agent.name ?? '').toLowerCase().replace(/\s+/g, '-') === focus.key)
    : null
  const focusedService = focus?.type === 'service' ? services[focus.key] : null

  const fields: [string, string | number | undefined | null][] = showSession ? [
    ['Status', status?.status],
    ['Session', status?.session_id],
    ['Resume', status?.resume_target],
    ['Title', status?.latest_title],
    ['Profile', status?.latest_profile],
    ['Source', status?.latest_source],
    ['Model', status?.model],
    ['Task', status?.task],
    ['Created', status?.created_at ? new Date(status.created_at).toLocaleString() : undefined],
    ['Modified', status?.modified ? new Date(status.modified * 1000).toLocaleString() : undefined],
  ] : []

  async function submitTask(e: FormEvent) {
    e.preventDefault()
    if (!taskText.trim()) return
    setSubmittingTask(true)
    setTaskResult(null)
    try {
      const res = await fetch('/api/tasks/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskText, dispatch: dispatchTask }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setTaskResult(`${data.status}: ${data.task_class} -> ${data.recommended_agent}${(data.recommended_profile_display ?? data.recommended_profile) ? ` [${data.recommended_profile_display ?? data.recommended_profile}]` : ''}${data.fallback_agent ? ` (fallback ${data.fallback_agent})` : ''}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Task routing failed')
    } finally {
      setSubmittingTask(false)
      if (dispatchTask) void loadAudit()
    }
  }

  async function updateAvailability(agentName: string, availability: string) {
    setAvailabilityBusy(agentName)
    try {
      const note = availability === 'rate_limited' ? 'Anthropic usage limit reached' : null
      const res = await fetch('/api/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: agentName, availability, note }),
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setTaskResult(`availability updated: ${agentName} -> ${availability}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Availability update failed')
    } finally {
      setAvailabilityBusy(null)
      void loadAudit()
    }
  }

  async function runProfileAction(agentName: string, profileName: string, action: 'start' | 'stop') {
    setProfileBusy(`${agentName}:${profileName}:${action}`)
    try {
      const res = await fetch('/api/local-profiles/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: agentName, profile: profileName, action }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setTaskResult(`profile ${action}: ${profileName} -> ${data.status}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : `Profile ${action} failed`)
    } finally {
      setProfileBusy(null)
      void loadAudit()
    }
  }

  async function launchBackgroundTask(e: FormEvent) {
    e.preventDefault()
    if (!backgroundPrompt.trim()) return
    setBackgroundBusy(true)
    try {
      const res = await fetch('/api/hermes/background', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile: backgroundProfile,
          prompt: backgroundPrompt,
          use_worktree: backgroundWorktree,
          repo_path: backgroundWorktree ? '/Users/iris/Projects/mission-control-dashboard' : undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setTaskResult(`background launched: ${data.task.title} -> ${data.task.profile}`)
      setBackgroundPrompt('')
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Background launch failed')
    } finally {
      setBackgroundBusy(false)
    }
  }

  async function runQuickCommand(profile: string, commandName: string) {
    setQuickCommandBusy(`${profile}:${commandName}`)
    try {
      const res = await fetch('/api/hermes/quick-command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, command_name: commandName }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      const output = (data.stdout || data.stderr || '').trim()
      setTaskResult(`quick ${commandName}: ${data.status}${output ? ` · ${output.slice(0, 120)}` : ''}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Quick command failed')
    } finally {
      setQuickCommandBusy(null)
    }
  }

  async function stopBackgroundTask(taskId: string) {
    setBackgroundStopBusy(taskId)
    try {
      const res = await fetch(`/api/hermes/background/${taskId}/stop`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setTaskResult(`background stopped: ${data.task.title}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Background stop failed')
    } finally {
      setBackgroundStopBusy(null)
    }
  }

  async function cleanupBackgroundTask(taskId: string) {
    setBackgroundCleanupBusy(taskId)
    try {
      const res = await fetch(`/api/hermes/background/${taskId}/cleanup`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setTaskResult(`worktree cleaned: ${data.task.worktree_path ?? data.task.title}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Worktree cleanup failed')
    } finally {
      setBackgroundCleanupBusy(null)
    }
  }

  async function pollBackgroundTask(taskId: string) {
    setBackgroundPollBusy(taskId)
    try {
      const res = await fetch(`/api/hermes/background/${taskId}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setTaskResult(`background ${data.task.status}: ${data.task.title}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Background poll failed')
    } finally {
      setBackgroundPollBusy(null)
    }
  }

  async function loadBackgroundLog(taskId: string) {
    setBackgroundLogBusy(taskId)
    try {
      const res = await fetch(`/api/hermes/background/${taskId}/log?lines=40`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? `Server error: ${res.status}`)
      setBackgroundLogs((current) => ({ ...current, [taskId]: data.log || 'no log output yet' }))
      setTaskResult(`background log loaded: ${taskId}`)
    } catch (err) {
      setTaskResult(err instanceof Error ? err.message : 'Background log failed')
    } finally {
      setBackgroundLogBusy(null)
    }
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <ViewTabs active={view} onChange={setView} />

      {view === 'overview' && (
        <>
          {focus && (
            <PanelCard>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.14em' }}>
                    graph focus
                  </div>
                  <div style={{ marginTop: 5, fontSize: 11, color: '#e2e8f0', fontFamily: 'monospace' }}>
                    {focus.label}
                  </div>
                </div>
                <div style={{ fontSize: 8, color: '#67e8f9', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                  {focus.type}
                </div>
              </div>
              {focusedService && (
                <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
                  <MiniStat label="status" value={focusedService.status} tone={focusedService.status === 'up' || focusedService.status === 'healthy' ? '#10b981' : '#f59e0b'} />
                  <MiniStat label="models" value={focusedService.models?.length ?? 0} tone="#a78bfa" />
                </div>
              )}
              {focusedService?.models && focusedService.models.length > 0 && (
                <div style={{ marginTop: 8, fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                  models: {focusedService.models.join(', ')}
                </div>
              )}
              {focusedService?.error && (
                <div style={{ marginTop: 6, fontSize: 8, color: '#ef4444', fontFamily: 'monospace', lineHeight: 1.5 }}>
                  {focusedService.error}
                </div>
              )}
              {focusedAgent && (
                <div style={{ marginTop: 8, fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                  focused agent details are expanded in the agents view
                </div>
              )}
            </PanelCard>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8 }}>
            <MiniStat label="premium" value={`${routingSummary?.premium_available_count ?? 0}/${routingSummary?.premium_total_count ?? 0}`} tone="#f59e0b" />
            <MiniStat label="audit" value={permissionAuditSummary?.count ?? 0} tone="#06b6d4" />
            <MiniStat label="next cron" value={nextJob ? fmtIn(nextJob.next_run_in_seconds) : '—'} tone="#a78bfa" />
            <MiniStat label="hermes" value={showSession ? status?.status ?? 'live' : 'idle'} tone={showSession ? '#10b981' : '#94a3b8'} />
          </div>

          {(premiumPool.length > 0 || localDefault) && (
            <div>
              <SectionTitle>Routing Policy</SectionTitle>
              <div style={{ display: 'grid', gap: 8 }}>
                {premiumPool.length > 0 && (
                  <PanelCard compact>
                    <div style={{ fontSize: 9, color: '#e2e8f0', fontFamily: 'monospace' }}>
                      premium pool: {premiumPool.map((agent) => agent.label ?? agent.name).join(' + ')}
                    </div>
                    {routingSummary && (
                      <div style={{ marginTop: 4, fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                        available now: {routingSummary.premium_available_count}/{routingSummary.premium_total_count} ({routingSummary.premium_available.join(', ') || 'none'})
                      </div>
                    )}
                    <div style={{ marginTop: 4, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      reserve for planning, tricky refactors, ambiguous debugging, and final review
                    </div>
                  </PanelCard>
                )}
                {localDefault && (
                  <PanelCard compact>
                    <div style={{ fontSize: 9, color: '#e2e8f0', fontFamily: 'monospace' }}>
                      local default: {localDefault.label ?? localDefault.name}
                    </div>
                    <div style={{ marginTop: 4, fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      use for cron, summaries, memory consolidation, repo scans, and routine execution
                    </div>
                    {routingSummary?.guidance && (
                      <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                        router: routine → {routingSummary.guidance.routine}, specialized → {routingSummary.guidance.specialized}, premium → {routingSummary.guidance.premium}
                      </div>
                    )}
                  </PanelCard>
                )}
              </div>
            </div>
          )}

          <div>
            <SectionTitle>Task Router</SectionTitle>
            <form onSubmit={submitTask} style={{ padding: '10px 11px', border: '1px solid #182033', borderRadius: 10, background: 'linear-gradient(180deg, rgba(13,16,32,0.92), rgba(10,12,22,0.92))', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <textarea
                value={taskText}
                onChange={(e) => setTaskText(e.target.value)}
                rows={3}
                placeholder="Describe the task to see where the mesh will route it..."
                style={{
                  background: '#090b13',
                  border: '1px solid #182033',
                  color: '#e2e8f0',
                  borderRadius: 8,
                  padding: '9px 10px',
                  fontSize: 10,
                  fontFamily: 'monospace',
                  resize: 'vertical',
                }}
              />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="submit"
                  disabled={submittingTask || !taskText.trim()}
                  style={{
                    fontSize: 10,
                    padding: '6px 10px',
                    borderRadius: 8,
                    border: 'none',
                    background: submittingTask ? '#06b6d466' : '#06b6d4',
                    color: '#0a0a0f',
                    cursor: submittingTask ? 'not-allowed' : 'pointer',
                    fontFamily: 'monospace',
                    opacity: taskText.trim() ? 1 : 0.4,
                  }}
                >
                  {submittingTask ? 'Routing…' : 'Route Task'}
                </button>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                  <input
                    type="checkbox"
                    checked={dispatchTask}
                    onChange={(e) => setDispatchTask(e.target.checked)}
                  />
                  dispatch
                </label>
                {taskResult && (
                  <span style={{ fontSize: 8, color: '#94a3b8', fontFamily: 'monospace' }}>
                    {taskResult}
                  </span>
                )}
              </div>
            </form>
          </div>

          {cronJobs.length > 0 && (
            <div>
              <SectionTitle>Cron</SectionTitle>
              <PanelCard compact>
                {nextJob && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0 0 6px', borderBottom: '1px solid #0f172a' }}>
                    <span style={{ fontSize: 9, color: '#94a3b8', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                      {nextJob.name}
                    </span>
                    <span style={{ fontSize: 9, color: '#06b6d4', fontFamily: 'monospace', flexShrink: 0 }}>
                      in {fmtIn(nextJob.next_run_in_seconds)}
                    </span>
                  </div>
                )}
                {cronJobs.slice(0, 4).map((job) => (
                  <div key={job.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid rgba(15,23,42,0.45)' }}>
                    <span style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                      {job.name}
                    </span>
                    <span style={{ fontSize: 8, color: job.last_status === 'success' ? '#10b981' : job.last_status ? '#f59e0b' : '#334155', fontFamily: 'monospace', flexShrink: 0 }}>
                      {job.last_status ?? '—'}
                    </span>
                  </div>
                ))}
              </PanelCard>
            </div>
          )}

          <div>
            <SectionTitle>Session</SectionTitle>
            {(showSession || sessionProfiles.length > 0) ? (
              <PanelCard compact>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
                  <MiniStat label="sessions" value={status?.session_count ?? 0} tone="#67e8f9" />
                  <MiniStat label="profiles" value={`${status?.sessions?.active_profiles ?? 0}/${status?.sessions?.profile_count ?? 0}`} tone="#a78bfa" />
                  <MiniStat label="search" value={status?.search_ready ? 'ready' : 'idle'} tone={status?.search_ready ? '#10b981' : '#94a3b8'} />
                </div>
                {showSession && (
                  <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
                  {fields.filter(([, v]) => v != null && v !== '').map(([label, value]) => (
                    <div key={label}>
                      <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase' }}>
                        {label}
                      </div>
                      <div style={{ marginTop: 3, fontSize: 9, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-word', lineHeight: 1.4 }}>
                        {String(value)}
                      </div>
                    </div>
                  ))}
                  </div>
                )}
                {sessionProfiles.length > 0 && (
                  <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
                      profile sessions
                    </div>
                    {sessionProfiles.map((profile) => (
                      <div key={profile.profile} style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.7fr 1fr', gap: 8, alignItems: 'start', padding: '7px 0', borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                        <div>
                          <div style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>{profile.profile}</div>
                          <div style={{ marginTop: 3, fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            {profile.latest_title ?? profile.resume_target ?? 'no sessions yet'}
                          </div>
                          {profile.resume_command && (
                            <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              {profile.resume_command}
                            </div>
                          )}
                        </div>
                        <div style={{ fontSize: 8, color: '#94a3b8', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          {profile.session_count} sess
                          <br />
                          {profile.search_ready ? 'fts ready' : 'no fts'}
                        </div>
                        <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          {profile.latest_updated_at ? new Date(profile.latest_updated_at).toLocaleString() : 'idle'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {hermesNativeProfiles.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                      memory
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
                      <MiniStat label="built-in" value={`${memoryEnabledProfiles}/${hermesNativeProfiles.length}`} tone={memoryEnabledProfiles > 0 ? '#10b981' : '#94a3b8'} />
                      <MiniStat label="files" value={`${memoryFileProfiles}/${hermesNativeProfiles.length}`} tone={memoryFileProfiles > 0 ? '#67e8f9' : '#94a3b8'} />
                      <MiniStat label="ext" value={`${memoryExternalActiveProfiles > 0 ? memoryExternalActiveProfiles : memoryExternalReadyProfiles}/${hermesNativeProfiles.length}`} tone={(memoryExternalActiveProfiles > 0 || memoryExternalReadyProfiles > 0) ? '#a78bfa' : '#94a3b8'} />
                    </div>
                    {activeProfileMeta?.memory_overview && (
                      <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                        <div style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {(activeProfileMeta.display_name ?? activeProfileMeta.hermes_profile ?? activeProfileMeta.name)} · {activeProfileMeta.memory_overview.memory_enabled ? 'built-in memory enabled' : 'built-in memory disabled'}
                        </div>
                        <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          memory file: {activeProfileMeta.memory_overview.memory_file_exists ? `${activeProfileMeta.memory_overview.memory_char_count} chars` : 'missing'} · user file: {activeProfileMeta.memory_overview.user_file_exists ? `${activeProfileMeta.memory_overview.user_char_count} chars` : 'missing'}
                        </div>
                        <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          limits: {activeProfileMeta.memory_overview.memory_char_limit ?? '—'} / {activeProfileMeta.memory_overview.user_char_limit ?? '—'} · flush {activeProfileMeta.memory_overview.flush_min_turns ?? '—'} turns
                        </div>
                        <div style={{ fontSize: 8, color: activeProfileMeta.memory_overview.external_provider_active ? '#10b981' : activeProfileMeta.memory_overview.external_provider_available ? '#94a3b8' : '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          external: {activeProfileMeta.memory_overview.external_provider_hint}
                          {activeProfileMeta.memory_overview.external_provider_endpoint ? ` · ${activeProfileMeta.memory_overview.external_provider_endpoint}` : ''}
                        </div>
                        {activeProfileMeta.memory_overview.external_provider_candidates.length > 0 && (
                          <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            candidates: {activeProfileMeta.memory_overview.external_provider_candidates.join(', ')}
                          </div>
                        )}
                        {activeProfileMeta.session_overview && (
                          <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            session search: {activeProfileMeta.session_overview.search_ready ? 'ready' : 'not ready'}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
                {hermesNativeProfiles.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                      skills
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
                      <MiniStat label="shared" value={`${sharedSkillProfiles}/${hermesNativeProfiles.length}`} tone={sharedSkillProfiles > 0 ? '#10b981' : '#94a3b8'} />
                      <MiniStat label="local" value={activeProfileMeta?.skill_overview?.local_skill_count ?? 0} tone="#67e8f9" />
                      <MiniStat label="external" value={activeProfileMeta?.skill_overview?.external_skill_count ?? 0} tone="#a78bfa" />
                    </div>
                    {activeProfileMeta?.skill_overview && (
                      <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                        <div style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {(activeProfileMeta.display_name ?? activeProfileMeta.hermes_profile ?? activeProfileMeta.name)} · {activeProfileMeta.skill_overview.shared_skills_connected ? 'shared skills connected' : 'local skills only'}
                        </div>
                        <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          local dir: {activeProfileMeta.skill_overview.local_dir}
                        </div>
                        {activeProfileMeta.skill_overview.local_sample_skills.length > 0 && (
                          <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            local sample: {activeProfileMeta.skill_overview.local_sample_skills.join(', ')}
                          </div>
                        )}
                        {activeProfileMeta.skill_overview.external_dirs.map((dir) => (
                          <div key={dir.path} style={{ fontSize: 8, color: dir.exists ? '#475569' : '#7f1d1d', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            external: {dir.path} · {dir.skill_count} skills{dir.sample_skills.length > 0 ? ` · ${dir.sample_skills.join(', ')}` : ''}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {hermesNativeProfiles.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                      provider graph
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
                      <MiniStat label="profiles" value={`${providerReadyProfiles}/${hermesNativeProfiles.length}`} tone={providerReadyProfiles > 0 ? '#10b981' : '#94a3b8'} />
                      <MiniStat label="fallback" value={`${fallbackProfiles}/${hermesNativeProfiles.length}`} tone={fallbackProfiles > 0 ? '#f59e0b' : '#94a3b8'} />
                      <MiniStat label="smart" value={`${smartRoutingProfiles}/${hermesNativeProfiles.length}`} tone={smartRoutingProfiles > 0 ? '#67e8f9' : '#94a3b8'} />
                    </div>
                    {activeProfileMeta?.provider_overview && (
                      <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                        <div style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {(activeProfileMeta.display_name ?? activeProfileMeta.hermes_profile ?? activeProfileMeta.name)} · {activeProfileMeta.provider_overview.primary?.provider ?? 'unconfigured'}
                        </div>
                        {activeProfileMeta.provider_overview.primary?.model && (
                          <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            primary: {activeProfileMeta.provider_overview.primary.model}
                          </div>
                        )}
                        {activeProfileMeta.provider_overview.cheap_model?.model && (
                          <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            cheap route: {activeProfileMeta.provider_overview.cheap_model.model}
                          </div>
                        )}
                        {(activeProfileMeta.provider_overview.fallback_count ?? 0) > 0 && (
                          <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            fallback: {activeProfileMeta.provider_overview.fallbacks.map((fallback) => fallback.model ?? fallback.provider ?? 'fallback').join(' · ')}
                          </div>
                        )}
                        {(activeProfileMeta.provider_overview.auxiliary_count ?? 0) > 0 && (
                          <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            auxiliary: {Object.keys(activeProfileMeta.provider_overview.auxiliary).join(', ')}
                          </div>
                        )}
                        {activeProfileMeta.provider_overview.delegation?.model && (
                          <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            delegation: {activeProfileMeta.provider_overview.delegation.model}
                          </div>
                        )}
                        <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          endpoints: {activeProfileMeta.provider_overview.unique_endpoint_count} · models: {activeProfileMeta.provider_overview.unique_model_count}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {hermesNativeProfiles.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                      checkpoints
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8 }}>
                      <MiniStat label="ready" value={`${checkpointReadyProfiles}/${hermesNativeProfiles.length}`} tone={checkpointReadyProfiles > 0 ? '#10b981' : '#94a3b8'} />
                      <MiniStat label="snapshots" value={activeProfileMeta?.checkpoint_overview?.snapshot_count ?? 0} tone="#67e8f9" />
                      <MiniStat label="max" value={activeProfileMeta?.checkpoint_overview?.max_snapshots ?? '—'} tone="#a78bfa" />
                    </div>
                    {activeProfileMeta?.checkpoint_overview && (
                      <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                        <div style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {(activeProfileMeta.display_name ?? activeProfileMeta.hermes_profile ?? activeProfileMeta.name)} · {activeProfileMeta.checkpoint_overview.rollback_ready ? 'rollback ready' : activeProfileMeta.checkpoint_overview.enabled ? 'checkpointing enabled' : 'checkpointing off'}
                        </div>
                        {activeProfileMeta.checkpoint_overview.latest_snapshot_at && (
                          <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            latest snapshot: {new Date(activeProfileMeta.checkpoint_overview.latest_snapshot_at).toLocaleString()}
                          </div>
                        )}
                        <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          {activeProfileMeta.checkpoint_overview.rollback_diff_hint}
                        </div>
                        <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                          {activeProfileMeta.checkpoint_overview.rollback_hint}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                  <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                    background work
                  </div>
                  <form onSubmit={launchBackgroundTask} style={{ display: 'grid', gap: 8 }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                      <select
                        value={backgroundProfile}
                        onChange={(e) => setBackgroundProfile(e.target.value)}
                        style={{ background: '#090b13', border: '1px solid #182033', color: '#e2e8f0', borderRadius: 8, padding: '7px 9px', fontSize: 10, fontFamily: 'monospace' }}
                      >
                        {hermesNativeProfiles.map((profile) => (
                          <option key={profile.name} value={profile.hermes_profile ?? profile.display_name ?? profile.name}>
                            {profile.display_name ?? profile.hermes_profile ?? profile.name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="submit"
                        disabled={backgroundBusy || !backgroundPrompt.trim()}
                        style={{
                          fontSize: 10,
                          padding: '6px 10px',
                          borderRadius: 8,
                          border: 'none',
                          background: backgroundBusy ? '#06b6d466' : '#06b6d4',
                          color: '#0a0a0f',
                          cursor: backgroundBusy ? 'not-allowed' : 'pointer',
                          fontFamily: 'monospace',
                          opacity: backgroundPrompt.trim() ? 1 : 0.4,
                        }}
                      >
                        {backgroundBusy ? 'Launching…' : 'Launch background'}
                      </button>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                        <input
                          type="checkbox"
                          checked={backgroundWorktree}
                          onChange={(e) => setBackgroundWorktree(e.target.checked)}
                        />
                        worktree
                      </label>
                    </div>
                    <textarea
                      value={backgroundPrompt}
                      onChange={(e) => setBackgroundPrompt(e.target.value)}
                      rows={2}
                      placeholder="Run a deeper Hermes task without blocking the active session..."
                      style={{ background: '#090b13', border: '1px solid #182033', color: '#e2e8f0', borderRadius: 8, padding: '9px 10px', fontSize: 10, fontFamily: 'monospace', resize: 'vertical' }}
                    />
                  </form>
                  {backgroundTasks.length > 0 && (
                    <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                      {backgroundTasks.slice(0, 4).map((task) => (
                        <div key={task.id} style={{ padding: '7px 0', borderTop: '1px solid rgba(15,23,42,0.45)', display: 'grid', gap: 4 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                            <span style={{ fontSize: 9, color: '#cbd5e1', fontFamily: 'monospace' }}>{task.title}</span>
                            <span style={{ fontSize: 8, color: task.running ? '#10b981' : '#94a3b8', fontFamily: 'monospace', textTransform: 'uppercase' }}>{task.status}</span>
                          </div>
                          <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            {task.profile} · {new Date(task.started_at).toLocaleString()}
                          </div>
                          {task.worktree_path && (
                            <div style={{ fontSize: 8, color: '#94a3b8', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              {task.worktree_path}
                            </div>
                          )}
                          {task.worktree_branch && (
                            <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              {task.worktree_branch}
                            </div>
                          )}
                          {task.mode === 'worktree' && hermesProfileMeta[task.profile]?.checkpoint_overview && (
                            <div style={{ fontSize: 8, color: hermesProfileMeta[task.profile]?.checkpoint_overview?.rollback_ready ? '#94a3b8' : '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              {hermesProfileMeta[task.profile]?.checkpoint_overview?.rollback_ready
                                ? `${hermesProfileMeta[task.profile]?.checkpoint_overview?.rollback_diff_hint} inside the worktree session`
                                : 'worktree rollback not ready yet'}
                            </div>
                          )}
                          <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                            {task.prompt}
                          </div>
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                            {task.log_path && <span style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace' }}>{task.log_path}</span>}
                            {task.mode === 'worktree' && task.repo_path && <span style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace' }}>{task.repo_path}</span>}
                            <button
                              type="button"
                              onClick={() => pollBackgroundTask(task.id)}
                              disabled={backgroundPollBusy === task.id}
                              style={{ fontSize: 8, padding: '3px 6px', borderRadius: 6, border: '1px solid #1e293b', background: '#0a0a0f', color: backgroundPollBusy === task.id ? '#475569' : '#94a3b8', cursor: backgroundPollBusy === task.id ? 'not-allowed' : 'pointer', fontFamily: 'monospace' }}
                            >
                              {backgroundPollBusy === task.id ? 'polling' : 'poll'}
                            </button>
                            <button
                              type="button"
                              onClick={() => loadBackgroundLog(task.id)}
                              disabled={backgroundLogBusy === task.id}
                              style={{ fontSize: 8, padding: '3px 6px', borderRadius: 6, border: '1px solid #1e293b', background: '#0a0a0f', color: backgroundLogBusy === task.id ? '#475569' : '#94a3b8', cursor: backgroundLogBusy === task.id ? 'not-allowed' : 'pointer', fontFamily: 'monospace' }}
                            >
                              {backgroundLogBusy === task.id ? 'loading' : 'log'}
                            </button>
                            {task.running && (
                              <button
                                type="button"
                                onClick={() => stopBackgroundTask(task.id)}
                                disabled={backgroundStopBusy === task.id}
                                style={{ fontSize: 8, padding: '3px 6px', borderRadius: 6, border: '1px solid #7f1d1d', background: backgroundStopBusy === task.id ? '#3f1d1d' : '#7f1d1d', color: '#fecaca', cursor: backgroundStopBusy === task.id ? 'not-allowed' : 'pointer', fontFamily: 'monospace' }}
                              >
                                {backgroundStopBusy === task.id ? 'stopping' : 'stop'}
                              </button>
                            )}
                            {!task.running && task.mode === 'worktree' && task.worktree_path && task.status !== 'cleaned' && (
                              <button
                                type="button"
                                onClick={() => cleanupBackgroundTask(task.id)}
                                disabled={backgroundCleanupBusy === task.id}
                                style={{ fontSize: 8, padding: '3px 6px', borderRadius: 6, border: '1px solid #1e40af', background: backgroundCleanupBusy === task.id ? '#1e3a8a' : '#0f2b66', color: '#bfdbfe', cursor: backgroundCleanupBusy === task.id ? 'not-allowed' : 'pointer', fontFamily: 'monospace' }}
                              >
                                {backgroundCleanupBusy === task.id ? 'cleaning' : 'cleanup'}
                              </button>
                            )}
                          </div>
                          {backgroundLogs[task.id] && (
                            <pre style={{ margin: 0, padding: '8px 9px', borderRadius: 8, border: '1px solid #182033', background: '#090b13', color: '#94a3b8', fontSize: 8, fontFamily: 'monospace', lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                              {backgroundLogs[task.id]}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {quickCommands.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(15,23,42,0.45)' }}>
                    <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8 }}>
                      quick commands
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {quickCommands.map((command) => {
                        const busyKey = `${backgroundProfile}:${command.name}`
                        return (
                          <button
                            key={command.name}
                            type="button"
                            onClick={() => runQuickCommand(backgroundProfile, command.name)}
                            disabled={quickCommandBusy === busyKey}
                            style={{
                              fontSize: 8,
                              padding: '5px 8px',
                              borderRadius: 999,
                              border: '1px solid #1e293b',
                              background: quickCommandBusy === busyKey ? '#1f2937' : '#0a0a0f',
                              color: quickCommandBusy === busyKey ? '#475569' : '#94a3b8',
                              cursor: quickCommandBusy === busyKey ? 'not-allowed' : 'pointer',
                              fontFamily: 'monospace',
                            }}
                          >
                            /{command.name}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
              </PanelCard>
            ) : (
              <p style={{ fontSize: 10, color: '#334155' }}>No active Hermes session</p>
            )}
          </div>
        </>
      )}

      {view === 'audit' && (
        <>
          <div>
            <SectionTitle>Permission Audit</SectionTitle>
            <PanelCard>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 8 }}>
                <MiniStat label="total" value={permissionAuditSummary?.count ?? 0} />
                <MiniStat label="allow" value={permissionAuditSummary?.decision_counts?.allow ?? 0} tone="#10b981" />
                <MiniStat label="deny" value={permissionAuditSummary?.decision_counts?.deny ?? 0} tone="#ef4444" />
                <MiniStat label="ask" value={permissionAuditSummary?.decision_counts?.ask ?? 0} tone="#f59e0b" />
                <MiniStat label="bypass" value={permissionAuditSummary?.decision_counts?.bypass ?? 0} tone="#06b6d4" />
              </div>
              {permissionAuditSummary?.last_event_at && (
                <div style={{ marginTop: 8, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                  last event: {new Date(permissionAuditSummary.last_event_at).toLocaleString()}
                </div>
              )}
              <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace' }}>
                  recent control-plane decisions
                </div>
                <button
                  type="button"
                  onClick={() => void loadAudit()}
                  disabled={auditLoading}
                  style={{
                    fontSize: 8,
                    padding: '3px 6px',
                    borderRadius: 4,
                    border: '1px solid #1e293b',
                    background: '#0a0a0f',
                    color: auditLoading ? '#475569' : '#94a3b8',
                    cursor: auditLoading ? 'not-allowed' : 'pointer',
                    fontFamily: 'monospace',
                  }}
                >
                  {auditLoading ? 'refreshing' : 'refresh'}
                </button>
              </div>
            </PanelCard>
          </div>

          {auditEntries.length === 0 ? (
            <PanelCard compact>
              <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                no audit entries yet
              </div>
            </PanelCard>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {auditEntries.map((entry, index) => (
                <details key={`${entry.timestamp}-${index}`} style={{ border: '1px solid #182033', borderRadius: 10, background: 'linear-gradient(180deg, rgba(13,16,32,0.92), rgba(10,12,22,0.92))' }}>
                  <summary style={{ cursor: 'pointer', padding: '9px 10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                      <span style={{ fontSize: 8, color: '#cbd5e1', fontFamily: 'monospace' }}>
                        {entry.tool ?? 'unknown-tool'}
                        {entry.agent ? ` -> ${entry.agent}` : ''}
                      </span>
                      <span style={{ fontSize: 8, color: entry.decision === 'allow' ? '#10b981' : entry.decision === 'deny' ? '#ef4444' : entry.decision === 'ask' ? '#f59e0b' : '#06b6d4', fontFamily: 'monospace', textTransform: 'uppercase' }}>
                        {entry.decision}
                      </span>
                    </div>
                    <div style={{ marginTop: 3, fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      {new Date(entry.timestamp).toLocaleString()} · source {entry.source} · mode {entry.mode}
                    </div>
                  </summary>
                  <div style={{ padding: '0 10px 10px' }}>
                    {entry.reason && (
                      <div style={{ marginTop: 3, fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                        {entry.reason}
                      </div>
                    )}
                    {entry.input_summary && (
                      <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                        input: {entry.input_summary}
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          )}
        </>
      )}

      {view === 'agents' && (
        <div>
          <SectionTitle>Mesh State</SectionTitle>
          {focusedAgent && (
            <div style={{ marginBottom: 8, fontSize: 8, color: '#67e8f9', fontFamily: 'monospace', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              focused agent: {focusedAgent.label ?? focusedAgent.name}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {agents.map((agent) => (
              <details
                key={agent.id}
                ref={(node) => {
                  agentRowRefs.current[agent.id] = node
                }}
                open={Boolean(expandedAgents[agent.id] || focusedAgent?.id === agent.id)}
                onToggle={(e) => {
                  const nextOpen = (e.currentTarget as HTMLDetailsElement).open
                  setExpandedAgents((current) => ({ ...current, [agent.id]: nextOpen }))
                }}
                style={{
                  border: `1px solid ${focusedAgent?.id === agent.id ? '#0ea5e955' : '#182033'}`,
                  borderRadius: 10,
                  background: 'linear-gradient(180deg, rgba(13,16,32,0.92), rgba(10,12,22,0.92))',
                  boxShadow: focusedAgent?.id === agent.id ? '0 0 0 1px rgba(6,182,212,0.18)' : 'none',
                }}
              >
                <summary
                  style={{ cursor: 'pointer', padding: '9px 10px' }}
                  onClick={() => onFocusChange?.({
                    type: 'agent',
                    key: (agent.name ?? '').toLowerCase().replace(/\s+/g, '-'),
                    label: agent.label ?? agent.name ?? 'Unknown agent',
                  })}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                    <span style={{ fontSize: 10, color: '#e2e8f0', fontFamily: 'monospace' }}>
                      {agent.label ?? agent.name}
                    </span>
                    <span style={{ fontSize: 8, color: agent.health_status === 'healthy' ? '#10b981' : agent.health_status === 'degraded' ? '#f59e0b' : '#475569', fontFamily: 'monospace', textTransform: 'uppercase' }}>
                      {agent.health_status ?? agent.status}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 5 }}>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      runtime: <span style={{ color: '#94a3b8' }}>{agent.runtime_status ?? agent.status}</span>
                    </span>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      presence: <span style={{ color: agent.presence?.status === 'online' ? '#10b981' : agent.presence?.status === 'registered' ? '#06b6d4' : '#ef4444' }}>{agent.presence?.status ?? 'unknown'}</span>
                    </span>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      tier: <span style={{ color: agent.tier === 'premium' ? '#f59e0b' : agent.tier === 'local-default' ? '#a855f7' : '#94a3b8' }}>{agent.tier ?? 'unknown'}</span>
                    </span>
                  </div>
                </summary>
                <div style={{ padding: '0 10px 10px' }}>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 5 }}>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      maestro: <span style={{ color: '#94a3b8' }}>{agent.registration_status === 'registered' ? (agent.orchestration_status ?? 'unknown') : 'not registered'}</span>
                    </span>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      activity: <span style={{ color: agent.activity_status === 'live' ? '#10b981' : agent.activity_status === 'recent' ? '#06b6d4' : agent.activity_status === 'idle' ? '#f59e0b' : agent.activity_status === 'stale' ? '#ef4444' : '#94a3b8' }}>{agent.activity_status ?? 'unknown'}</span>
                    </span>
                    <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                      availability: <span style={{ color: agent.availability_status === 'available' ? '#10b981' : agent.availability_status === 'rate_limited' ? '#f59e0b' : '#ef4444' }}>{agent.availability_status ?? 'available'}</span>
                    </span>
                  </div>
                  {agent.last_active && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#475569', fontFamily: 'monospace' }}>
                      last active: {new Date(agent.last_active).toLocaleString()} ({fmtAgo(agent.activity_age_seconds)})
                    </div>
                  )}
                  {agent.status_reason && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      {agent.status_reason}
                    </div>
                  )}
                  {agent.presence?.reason && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      presence: {agent.presence.reason}
                    </div>
                  )}
                  {agent.availability_reason && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      availability note: {agent.availability_reason}
                    </div>
                  )}
                  {agent.routing_group === 'premium-pool' && (
                    <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>set:</span>
                      <select
                        value={agent.availability_status ?? 'available'}
                        onChange={(e) => updateAvailability(agent.name, e.target.value)}
                        disabled={availabilityBusy === agent.name}
                        style={{
                          background: '#0a0a0f',
                          border: '1px solid #1e293b',
                          color: '#94a3b8',
                          borderRadius: 4,
                          padding: '2px 6px',
                          fontSize: 8,
                          fontFamily: 'monospace',
                        }}
                      >
                        <option value="available">available</option>
                        <option value="rate_limited">rate_limited</option>
                        <option value="offline">offline</option>
                      </select>
                    </div>
                  )}
                  {(agent.reserve_for && agent.reserve_for.length > 0) && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      reserve: {agent.reserve_for.join(', ')}
                    </div>
                  )}
                  {(agent.local_profiles && agent.local_profiles.length > 0) && (
                    <div style={{ marginTop: 5, display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace', textTransform: 'uppercase' }}>
                        local profiles
                      </div>
                      {agent.local_profiles.map((profile) => (
                        <div
                          key={profile.name}
                          style={{
                            padding: '5px 6px',
                            border: '1px solid #182033',
                            borderRadius: 8,
                            background: '#090b13',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 2,
                          }}
                        >
                          <div style={{ fontSize: 8, color: '#cbd5e1', fontFamily: 'monospace' }}>
                            {(profile.display_name ?? profile.name)}: {profile.model.split('/').pop() ?? profile.model}
                          </div>
                          {(profile.profile_kind || profile.runtime) && (
                            <div style={{ fontSize: 8, color: '#38bdf8', fontFamily: 'monospace' }}>
                              kind: {profile.profile_kind === 'hermes-native' ? 'hermes-profile' : (profile.runtime ?? profile.profile_kind)}
                            </div>
                          )}
                          {profile.mode && (
                            <div style={{ fontSize: 8, color: profile.mode === 'active' ? '#10b981' : '#f59e0b', fontFamily: 'monospace' }}>
                              mode: {profile.mode}
                            </div>
                          )}
                          <div style={{ fontSize: 8, color: '#64748b', fontFamily: 'monospace' }}>
                            state: <span style={{ color: profile.running ? '#10b981' : profile.installed ? '#94a3b8' : '#ef4444' }}>
                              {profile.running ? 'running' : profile.installed ? 'installed' : 'missing'}
                            </span>
                          </div>
                          {profile.hermes_profile && (
                            <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              hermes profile: {profile.hermes_profile}
                            </div>
                          )}
                          {profile.purpose && (
                            <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              {profile.purpose}
                            </div>
                          )}
                          {profile.provider && (
                            <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              provider: {profile.provider}
                            </div>
                          )}
                          {profile.provider_overview && (
                            <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              provider graph: {profile.provider_overview.smart_routing_enabled ? 'smart' : 'fixed'} · {profile.provider_overview.fallback_count} fallback · {profile.provider_overview.auxiliary_count} aux
                            </div>
                          )}
                          {profile.toolset_overview && (
                            <>
                              <div style={{ fontSize: 8, color: '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                toolsets: {profile.toolset_overview.all_tools ? 'all' : profile.toolset_overview.toolsets.join(', ')}
                              </div>
                              <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                tools: {profile.toolset_overview.has_terminal ? 'terminal ' : ''}{profile.toolset_overview.has_memory ? 'memory ' : ''}{profile.toolset_overview.has_delegation ? 'delegation ' : ''}{profile.toolset_overview.has_browser ? 'browser' : ''}
                              </div>
                            </>
                          )}
                          {profile.skill_overview && (
                            <div style={{ fontSize: 8, color: profile.skill_overview.shared_skills_connected ? '#10b981' : '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              skills: {profile.skill_overview.local_skill_count} local · {profile.skill_overview.external_skill_count} external
                            </div>
                          )}
                          {profile.memory_overview && (
                            <>
                              <div style={{ fontSize: 8, color: profile.memory_overview.memory_enabled ? '#10b981' : '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                memory: {profile.memory_overview.memory_enabled ? 'built-in on' : 'built-in off'} · {profile.memory_overview.external_provider_hint}
                              </div>
                              <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                files: M {profile.memory_overview.memory_char_count}c · U {profile.memory_overview.user_char_count}c
                              </div>
                            </>
                          )}
                          {profile.base_url && (
                            <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              endpoint: {profile.base_url}
                            </div>
                          )}
                          {profile.alias_path && (
                            <div style={{ fontSize: 8, color: profile.alias_installed ? '#64748b' : '#ef4444', fontFamily: 'monospace', lineHeight: 1.5 }}>
                              alias: {profile.alias_installed ? profile.alias_path : 'missing'}
                            </div>
                          )}
                          {profile.checkpoint_overview && (
                            <>
                              <div style={{ fontSize: 8, color: profile.checkpoint_overview.rollback_ready ? '#10b981' : '#475569', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                checkpoints: {profile.checkpoint_overview.enabled ? `${profile.checkpoint_overview.snapshot_count} ready` : 'disabled'}
                              </div>
                              <div style={{ fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                                {profile.checkpoint_overview.rollback_diff_hint}
                              </div>
                            </>
                          )}
                          {(profile.mode === 'on-demand' || profile.profile_kind === 'hermes-native') && (
                            <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
                              <button
                                type="button"
                                disabled={!profile.installed || profile.running || profileBusy === `${agent.name}:${profile.name}:start`}
                                onClick={() => runProfileAction(agent.name, profile.name, 'start')}
                                style={{
                                  fontSize: 8,
                                  padding: '3px 6px',
                                  borderRadius: 4,
                                  border: 'none',
                                  background: !profile.installed || profile.running ? '#1f2937' : '#10b981',
                                  color: !profile.installed || profile.running ? '#64748b' : '#0a0a0f',
                                  cursor: !profile.installed || profile.running ? 'not-allowed' : 'pointer',
                                  fontFamily: 'monospace',
                                }}
                              >
                                start
                              </button>
                              <button
                                type="button"
                                disabled={!profile.running || profileBusy === `${agent.name}:${profile.name}:stop`}
                                onClick={() => runProfileAction(agent.name, profile.name, 'stop')}
                                style={{
                                  fontSize: 8,
                                  padding: '3px 6px',
                                  borderRadius: 4,
                                  border: 'none',
                                  background: profile.running ? '#ef4444' : '#1f2937',
                                  color: profile.running ? '#0a0a0f' : '#64748b',
                                  cursor: profile.running ? 'pointer' : 'not-allowed',
                                  fontFamily: 'monospace',
                                }}
                              >
                                stop
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {agent.fallback_to && (
                    <div style={{ marginTop: 3, fontSize: 8, color: '#334155', fontFamily: 'monospace', lineHeight: 1.5 }}>
                      failover: {agent.fallback_to}
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function MeshPanel({
  focus = null,
  onFocusChange,
}: {
  focus?: GraphSelection | null
  onFocusChange?: (focus: GraphSelection | null) => void
}) {
  const [activeTab, setActiveTab] = useState<Tab>('hermes')

  useEffect(() => {
    if (focus) setActiveTab('hermes')
  }, [focus])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'linear-gradient(180deg, rgba(14,24,40,0.98), rgba(7,11,19,0.99))' }}>
      <TabBar active={activeTab} onChange={setActiveTab} />
      {activeTab === 'logs' && <LogsTab />}
      {activeTab === 'amp' && <AmpInbox />}
      {activeTab === 'hermes' && <HermesTab focus={focus} onFocusChange={onFocusChange} />}
      {activeTab === 'rag' && (
        <div style={{ flex: 1, padding: '8px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <RAGSearch />
        </div>
      )}
    </div>
  )
}
