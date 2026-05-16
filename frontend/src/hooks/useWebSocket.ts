import { useEffect, useRef } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { StatusUpdate, MeshInsight } from '../types'

const WS_URL = '/ws'

export const useWebSocket = () => {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectDelayRef = useRef(1000)
  const unmountedRef = useRef(false)
  // stable ref to connect so onclose can call it without stale closure issues
  const connectRef = useRef<() => void>(() => {})

  connectRef.current = () => {
    if (unmountedRef.current) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}${WS_URL}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (unmountedRef.current) return
      const { setConnected, setLastUpdate } = useDashboardStore.getState()
      setConnected(true)
      setLastUpdate(new Date())
      reconnectDelayRef.current = 1000
    }

    ws.onmessage = (event) => {
      if (unmountedRef.current) return
      try {
        const msg = JSON.parse(event.data)
        const { setAgents, setServices, setServiceHistory, setCronJobs, setMemories, setMemorySummary, setMemoryEvents, setLastUpdate, setLlmActive, setVoiceActive, setSystem, setMemoryMonitorLog, setLogs, setAmpMessages, setHermesStatus, setRoutingSummary, setPermissionAuditSummary, setTrendingRepos, addInsight, setInsights, setAgentMessages, setSignalWatcher, setSecurityPosture } =
          useDashboardStore.getState()
        setLastUpdate(new Date())

        if (msg.type === 'insight') {
          addInsight(msg.insight as MeshInsight)
          return
        }

        if (msg.type === 'status_update') {
          const su = msg as StatusUpdate
          if (su.agents) setAgents(su.agents)
          if (su.services) setServices(su.services)
          if (su.service_history) setServiceHistory(su.service_history)
          if (su.cron_jobs) setCronJobs(su.cron_jobs)
          if (su.memories) setMemories(su.memories)
          if (su.memory_summary) setMemorySummary(su.memory_summary)
          if (su.memory_events) setMemoryEvents(su.memory_events)
          if (su.llm_active !== undefined) setLlmActive(su.llm_active ?? null)
          if (su.voice_active !== undefined) setVoiceActive(su.voice_active)
          if (su.system) setSystem(su.system)
          if (su.memory_monitor_log) setMemoryMonitorLog(su.memory_monitor_log)
          if (su.logs) setLogs(su.logs)
          if (su.amp_messages) setAmpMessages(su.amp_messages)
          if (su.hermes_status) setHermesStatus(su.hermes_status)
          if (su.routing_summary) setRoutingSummary(su.routing_summary)
          if (su.permission_audit_summary) setPermissionAuditSummary(su.permission_audit_summary)
          if (su.trending_repos) setTrendingRepos(su.trending_repos)
          if (su.insights) setInsights(su.insights)
          if (su.agent_messages) setAgentMessages(su.agent_messages)
          if (su.signal_watcher) setSignalWatcher(su.signal_watcher)
          if (su.security_posture) setSecurityPosture(su.security_posture)
        }
      } catch {
        // malformed message — ignore
      }
    }

    ws.onerror = () => {
      // handled by onclose
    }

    ws.onclose = () => {
      if (unmountedRef.current) return
      useDashboardStore.getState().setConnected(false)

      const delay = Math.min(reconnectDelayRef.current, 30000)
      reconnectDelayRef.current = Math.min(delay * 2, 30000)

      reconnectTimeoutRef.current = setTimeout(() => {
        connectRef.current()
      }, delay)
    }
  }

  useEffect(() => {
    unmountedRef.current = false
    connectRef.current()

    return () => {
      unmountedRef.current = true
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close()
    }
  }, []) // intentionally empty — connect logic lives in connectRef

  const isConnected = useDashboardStore((s) => s.isConnected)
  const lastUpdate = useDashboardStore((s) => s.lastUpdate)

  return { isConnected, lastUpdate }
}
