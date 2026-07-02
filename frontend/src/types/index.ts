// Shapes match what the backend actually sends

export interface Agent {
  id: string
  name: string
  label?: string
  avatar?: string
  status: string
  runtime_status?: string
  registration_status?: string
  orchestration_status?: string
  health_status?: string
  orchestration_reachable?: boolean
  status_reason?: string | null
  activity_status?: string
  activity_age_seconds?: number | null
  recently_active?: boolean
  availability_status?: string
  availability_reason?: string | null
  tier?: string
  routing_group?: string
  scarce?: boolean
  default_for?: string[]
  reserve_for?: string[]
  fallback_to?: string | null
  model?: string
  last_active?: string
  program?: string
  host?: string
  address?: string
  task?: string
  presence?: {
    kind: string
    status: string
    reason?: string | null
  }
  local_profiles?: {
    name: string
    display_name?: string
    model: string
    model_path?: string
    base_url?: string
    provider?: string
    purpose?: string
    mode?: string
    installed?: boolean
    running?: boolean
    startable?: boolean
    managed?: boolean
    port?: number
    pid?: number | null
    log_path?: string
    runtime?: string
    profile_kind?: string
    hermes_profile?: string
    profile_home?: string
    alias_path?: string | null
    alias_installed?: boolean
    gateway_status?: string
    quick_commands?: {
      name: string
      type: string
      command?: string | null
    }[]
    checkpoint_overview?: {
      enabled: boolean
      max_snapshots?: number | null
      snapshot_root?: string
      snapshot_count: number
      latest_snapshot_at?: string | null
      git_available?: boolean
      rollback_ready: boolean
      rollback_diff_hint?: string
      rollback_hint?: string
    }
    provider_overview?: {
      primary?: {
        provider?: string | null
        model?: string | null
        base_url?: string | null
      } | null
      fallbacks: {
        provider?: string | null
        model?: string | null
        base_url?: string | null
      }[]
      fallback_count: number
      smart_routing_enabled: boolean
      cheap_model?: {
        provider?: string | null
        model?: string | null
        base_url?: string | null
      } | null
      auxiliary: Record<string, {
        provider?: string | null
        model?: string | null
        base_url?: string | null
      }>
      auxiliary_count: number
      delegation?: {
        provider?: string | null
        model?: string | null
        base_url?: string | null
      } | null
      unique_endpoint_count: number
      unique_model_count: number
    }
    toolset_overview?: {
      toolsets: string[]
      toolset_count: number
      all_tools: boolean
      has_browser: boolean
      has_terminal: boolean
      has_memory: boolean
      has_delegation: boolean
    }
    skill_overview?: {
      local_dir: string
      local_exists: boolean
      local_skill_count: number
      local_sample_skills: string[]
      external_dirs: {
        path: string
        exists: boolean
        skill_count: number
        sample_skills: string[]
      }[]
      external_dir_count: number
      external_skill_count: number
      shared_skills_connected: boolean
    }
    memory_overview?: {
      memory_enabled: boolean
      user_profile_enabled: boolean
      memory_char_limit?: number | null
      user_char_limit?: number | null
      nudge_interval?: number | null
      flush_min_turns?: number | null
      memory_dir: string
      memory_file_exists: boolean
      user_file_exists: boolean
      memory_char_count: number
      user_char_count: number
      latest_update_at?: string | null
      external_provider_name?: string | null
      external_provider_active: boolean
      external_provider_available: boolean
      external_provider_endpoint?: string | null
      external_provider_candidates: string[]
      external_provider_hint: string
    }
    session_overview?: {
      profile: string
      session_count: number
      search_ready: boolean
      latest_session_id?: string | null
      latest_title?: string | null
      latest_source?: string | null
      latest_model?: string | null
      latest_started_at?: string | null
      latest_ended_at?: string | null
      latest_updated_at?: string | null
      latest_message_count?: number | null
      resume_target?: string | null
      resume_command?: string | null
    }
  }[]
}

export interface ServiceHealth {
  name: string
  status: string  // "up" | "down" | "degraded"
  url?: string
  error?: string
  detail?: unknown
  models?: string[]
  active_model?: string
}

export interface CronJob {
  id: string
  name: string
  schedule_display?: string
  last_run_at?: string | null
  next_run_at?: string | null
  next_run_in_seconds?: number | null
  last_status?: string | null
  enabled?: boolean
  state?: string
  interval_seconds?: number | null
  prompt_snippet?: string | null
}

export interface MemoryEntry {
  id?: string
  text?: string
  score?: number
  // legacy fields (if populated by old REST path)
  timestamp?: string
  agent?: string
  content?: string
  tags?: string[]
}

export interface MemorySummary {
  status: string
  gateway_status: string
  substrate_status: string
  recall_status: string
  recall_count: number
  average_score?: number | null
  top_score?: number | null
  freshness_seconds?: number | null
  last_event_at?: string | null
  last_success_at?: string | null
  last_error_at?: string | null
  recent_successes: number
  recent_errors: number
  pressure_events?: number
  component_health?: Record<string, string>
  primary_cause?: {
    kind: string
    severity: string
    summary: string
  }
  causes?: {
    kind: string
    severity: string
    summary: string
  }[]
  warnings: string[]
}

export interface MemoryEvent {
  ts?: string | null
  type: string
  status: string
  source?: string
  latency_ms?: number | null
  resource?: {
    free_mb?: number
    used_gb?: number
  } | null
  summary: string
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export interface SystemMetrics {
  cpu_pct: number
  ram_pct: number
  ram_used_gb: number
  ram_total_gb: number
  mlx_ram_pct: number
  mlx_ram_gb: number
  mlx_pid: number | null
  local_pct: number
  disk_pct: number
  disk_used_gb: number
  disk_total_gb: number
  uptime_seconds: number
  load_1m: number
}

export interface AmpMessage {
  id: string
  direction: 'inbox' | 'sent'
  from: string
  to: string
  subject: string
  body: string
  timestamp: string
  type: string
}

export interface HermesStatus {
  status: string
  session_id?: string
  model?: string
  task?: string
  created_at?: string
  modified?: number
  session_count?: number
  search_ready?: boolean
  resume_target?: string | null
  latest_title?: string | null
  latest_profile?: string | null
  latest_source?: string | null
  latest_updated_at?: string | null
  background_tasks?: {
    id: string
    profile: string
    title: string
    prompt?: string
    command?: string[]
    log_path?: string
    pid?: number
    status: string
    running: boolean
    mode?: string
    repo_path?: string | null
    worktree_path?: string | null
    worktree_branch?: string | null
    worktree_cleaned_at?: string | null
    started_at: string
    ended_at?: string | null
  }[]
  sessions?: {
    profiles: {
      profile: string
      session_count: number
      search_ready: boolean
      latest_session_id?: string | null
      latest_title?: string | null
      latest_source?: string | null
      latest_model?: string | null
      latest_started_at?: string | null
      latest_ended_at?: string | null
      latest_updated_at?: string | null
      latest_message_count?: number | null
      resume_target?: string | null
      resume_command?: string | null
    }[]
    profile_count: number
    active_profiles: number
    session_count: number
    search_ready: boolean
    latest_title?: string | null
    latest_profile?: string | null
    latest_source?: string | null
    latest_updated_at?: string | null
    resume_target?: string | null
    resume_command?: string | null
  }
}

export interface RoutingSummary {
  policy: string
  premium_pool: string[]
  premium_available: string[]
  premium_available_count: number
  premium_total_count: number
  local_default?: string
  specialized_agents: string[]
  memory_status?: string
  memory_ready?: boolean
  memory_mode?: string
  warnings?: string[]
  guidance?: Record<string, string>
  profile_guidance?: Record<string, string | null>
}

export interface PermissionAuditSummary {
  count: number
  decision_counts: Record<string, number>
  mode_counts: Record<string, number>
  last_event_at?: string | null
}

export interface PermissionAuditEntry {
  timestamp: string
  source: string
  agent?: string | null
  tool?: string | null
  decision: string
  mode: string
  reason?: string | null
  input_summary?: string | null
}

export interface GraphSelection {
  type: 'agent' | 'service'
  key: string
  label: string
}

export interface MeshLogs {
  mlx: string[]
  memory: string[]
}

export interface MeshInsight {
  timestamp: string
  severity: 'info' | 'warning' | 'critical'
  summary: string
  insights: string[]
  actions: string[]
}

export interface TrendingRepo {
  id: number
  name: string
  description: string
  stars: number
  language: string | null
  url: string
  created_at: string
  topics: string[]
}

export interface ServiceHistoryPoint {
  ts: string
  up: boolean
}

export interface SessionEntry {
  ts: string
  role: string
  content: string
}

export interface AgentMessage {
  id: string
  timestamp: string
  from: string
  to: string
  role: string
  task: string
  summary: string
  details: string
  files: string[]
}

export interface SignalWatcherState {
  last_run?: string | null
  next_run_at?: string | null
  next_run_in_seconds?: number | null
  findings_today: number
  top_finding?: string | null
  job_active: boolean
}

export interface SecurityServicePosture {
  name: string
  port: number
  localhost_only: boolean
}

export interface SecurityPosture {
  services: SecurityServicePosture[]
  tailscale_up: boolean
  xsearch_oauth: boolean
  all_localhost_bound: boolean
  score: number
  max_score: number
}

export interface StatusUpdate {
  type: 'status_update'
  timestamp?: string
  agents?: Agent[]
  services?: Record<string, ServiceHealth>
  service_history?: Record<string, ServiceHistoryPoint[]>
  cron_jobs?: CronJob[]
  memories?: MemoryEntry[]
  memory_summary?: MemorySummary
  memory_events?: MemoryEvent[]
  llm_active?: string | null
  voice_active?: boolean
  system?: SystemMetrics
  memory_monitor_log?: string[]
  logs?: MeshLogs
  amp_messages?: AmpMessage[]
  hermes_status?: HermesStatus
  routing_summary?: RoutingSummary
  permission_audit_summary?: PermissionAuditSummary
  trending_repos?: TrendingRepo[]
  insights?: MeshInsight[]
  agent_messages?: AgentMessage[]
  signal_watcher?: SignalWatcherState
  security_posture?: SecurityPosture
}

// ── Crew (real-time agent activity) ──────────────────────────────────────────

export type CrewStatus = 'idle' | 'thinking' | 'working' | 'talking' | 'waiting'

export interface CrewMember {
  name: string
  role: string
  model: string
  status: CrewStatus
  activity: string | null
  tool: string | null
  task: string | null
  tokens_in: number
  tokens_out: number
  events_today: number
  last_event_at: string | null
}

export interface CrewEvent {
  id: string
  ts: string
  agent: string
  kind: 'hook' | 'tool' | 'thought' | 'speech' | 'lifecycle'
  text: string
  tool: string | null
  meta: { from?: string; to?: string; subject?: string }
}

export interface CrewEventMessage {
  type: 'crew_event'
  timestamp: string
  event: CrewEvent | null
  crew: Record<string, CrewMember>
}
