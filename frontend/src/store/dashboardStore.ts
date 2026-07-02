import { create } from 'zustand'
import { Agent, ServiceHealth, ServiceHistoryPoint, CronJob, MemoryEntry, MemorySummary, MemoryEvent, Message, SystemMetrics, AmpMessage, HermesStatus, MeshLogs, TrendingRepo, MeshInsight, RoutingSummary, PermissionAuditSummary, AgentMessage, SignalWatcherState, SecurityPosture, CrewMember, CrewEvent } from '../types'

interface DashboardState {
  // Connection
  isConnected: boolean
  lastUpdate: Date | null

  // Data
  agents: Agent[]
  services: Record<string, ServiceHealth>
  cronJobs: CronJob[]
  memories: MemoryEntry[]
  memorySummary: MemorySummary | null
  memoryEvents: MemoryEvent[]
  system: SystemMetrics | null
  memoryMonitorLog: string[]
  logs: MeshLogs
  ampMessages: AmpMessage[]
  hermesStatus: HermesStatus | null
  routingSummary: RoutingSummary | null
  permissionAuditSummary: PermissionAuditSummary | null
  agentMessages: AgentMessage[]

  // LLM / Voice
  llmActive: string | null
  voiceActive: boolean

  // Service sparkline history
  serviceHistory: Record<string, ServiceHistoryPoint[]>

  // Trending
  trendingRepos: TrendingRepo[]

  // Subconscious insights
  insights: MeshInsight[]

  // Chat
  chatHistory: Message[]
  isChatLoading: boolean

  // Brief
  brief: string | null
  briefGeneratedAt: string | null

  // Signal Watcher + Security Posture
  signalWatcher: SignalWatcherState | null
  securityPosture: SecurityPosture | null

  // Crew (real-time agent activity)
  crew: Record<string, CrewMember>
  crewEvents: CrewEvent[]

  // Actions
  setAgents: (agents: Agent[]) => void
  setServices: (services: Record<string, ServiceHealth>) => void
  setCronJobs: (jobs: CronJob[]) => void
  addMemory: (memory: MemoryEntry) => void
  setMemories: (memories: MemoryEntry[]) => void
  setMemorySummary: (summary: MemorySummary | null) => void
  setMemoryEvents: (events: MemoryEvent[]) => void
  addChatMessage: (msg: Message) => void
  appendChatToken: (token: string) => void
  setChatLoading: (loading: boolean) => void
  setBrief: (text: string, generatedAt: string | null) => void
  setConnected: (connected: boolean) => void
  setLastUpdate: (date: Date) => void
  setLlmActive: (llmActive: string | null) => void
  setVoiceActive: (voiceActive: boolean) => void
  setSystem: (system: SystemMetrics) => void
  setMemoryMonitorLog: (lines: string[]) => void
  setLogs: (logs: MeshLogs) => void
  setAmpMessages: (messages: AmpMessage[]) => void
  setHermesStatus: (status: HermesStatus) => void
  setRoutingSummary: (summary: RoutingSummary) => void
  setPermissionAuditSummary: (summary: PermissionAuditSummary | null) => void
  setAgentMessages: (messages: AgentMessage[]) => void
  setServiceHistory: (history: Record<string, ServiceHistoryPoint[]>) => void
  setTrendingRepos: (repos: TrendingRepo[]) => void
  addInsight: (insight: MeshInsight) => void
  setInsights: (insights: MeshInsight[]) => void
  setSignalWatcher: (state: SignalWatcherState | null) => void
  setSecurityPosture: (posture: SecurityPosture | null) => void
  setCrew: (crew: Record<string, CrewMember>) => void
  addCrewEvent: (event: CrewEvent) => void
  setCrewEvents: (events: CrewEvent[]) => void
}

export const useDashboardStore = create<DashboardState>((set) => ({
  isConnected: false,
  lastUpdate: null,

  agents: [],
  services: {},
  cronJobs: [],
  memories: [],
  memorySummary: null,
  memoryEvents: [],
  system: null,
  memoryMonitorLog: [],
  logs: { mlx: [], memory: [] },
  ampMessages: [],
  hermesStatus: null,
  routingSummary: null,
  permissionAuditSummary: null,
  agentMessages: [],

  llmActive: null,
  voiceActive: false,

  serviceHistory: {},
  trendingRepos: [],
  insights: [],

  chatHistory: [],
  isChatLoading: false,

  brief: null,
  briefGeneratedAt: null,

  signalWatcher: null,
  securityPosture: null,

  crew: {},
  crewEvents: [],

  setAgents: (agents) => set({ agents }),
  setServices: (services) => set({ services }),
  setCronJobs: (cronJobs) => set({ cronJobs }),
  addMemory: (memory) =>
    set((state) => ({
      memories: [memory, ...state.memories].slice(0, 100),
    })),
  setMemories: (memories) => set({ memories }),
  setMemorySummary: (memorySummary) => set({ memorySummary }),
  setMemoryEvents: (memoryEvents) => set({ memoryEvents }),
  addChatMessage: (msg) =>
    set((state) => ({ chatHistory: [...state.chatHistory, msg] })),
  appendChatToken: (token) =>
    set((state) => {
      const history = [...state.chatHistory]
      if (history.length === 0) return {}
      const last = history[history.length - 1]
      if (last.role !== 'assistant') return {}
      history[history.length - 1] = { ...last, content: last.content + token }
      return { chatHistory: history }
    }),
  setChatLoading: (isChatLoading) => set({ isChatLoading }),
  setBrief: (text, generatedAt) => set({ brief: text, briefGeneratedAt: generatedAt }),
  setConnected: (isConnected) => set({ isConnected }),
  setLastUpdate: (lastUpdate) => set({ lastUpdate }),
  setLlmActive: (llmActive) => set({ llmActive }),
  setVoiceActive: (voiceActive) => set({ voiceActive }),
  setSystem: (system) => set({ system }),
  setMemoryMonitorLog: (memoryMonitorLog) => set({ memoryMonitorLog }),
  setLogs: (logs) => set({ logs }),
  setAmpMessages: (ampMessages) => set({ ampMessages }),
  setHermesStatus: (hermesStatus) => set({ hermesStatus }),
  setRoutingSummary: (routingSummary) => set({ routingSummary }),
  setPermissionAuditSummary: (permissionAuditSummary) => set({ permissionAuditSummary }),
  setAgentMessages: (agentMessages) => set({ agentMessages }),
  setServiceHistory: (serviceHistory) => set({ serviceHistory }),
  setTrendingRepos: (trendingRepos) => set({ trendingRepos }),
  addInsight: (insight) => set((state) => ({ insights: [insight, ...state.insights].slice(0, 20) })),
  setInsights: (insights) => set({ insights }),
  setSignalWatcher: (signalWatcher) => set({ signalWatcher }),
  setSecurityPosture: (securityPosture) => set({ securityPosture }),
  setCrew: (crew) => set({ crew }),
  addCrewEvent: (event) =>
    set((state) => ({ crewEvents: [event, ...state.crewEvents].slice(0, 200) })),
  setCrewEvents: (crewEvents) => set({ crewEvents: crewEvents.slice(0, 200) }),
}))
