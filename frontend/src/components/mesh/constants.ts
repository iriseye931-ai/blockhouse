// Point cloud data, color maps, and type definitions for MeshGraph.
// Keep this pure — no React, no DOM.

// Canonical status colors — keep in sync with App.tsx C.green / C.amber / C.red
export const STATUS_COLORS = { green: '#79ff98', amber: '#f0c040', red: '#ff7060' } as const

export const AGENT_COLORS: Record<string, string> = {
  atlas: '#ffe49a',
  hermes: '#8fe7ff',
  iriseye: '#c6b7ff',
  claude: '#a8ffd4',
}

export const SERVICE_COLORS: Record<string, string> = {
  openviking: '#eedeff',
  mlx_server: '#f0eaff',
  memory_mcp: '#e5d8ff',
  openclaw_mcp: '#d8c8ff',
  ollama: '#dcd0ff',
  screenpipe: '#d0f0e8',
}

export const SERVICE_LABELS: Record<string, string> = {
  openviking: 'Gateway',
  mlx_server: 'Inference',
  memory_mcp: 'Memory',
  openclaw_mcp: 'Automation',
  ollama: 'Models',
  screenpipe: 'Capture',
}

export const AGENT_LABELS: Record<string, string> = {
  atlas: 'Lead',
  hermes: 'Hermes',
  iriseye: 'IrisEye',
  claude: 'Claude',
}

export const AGENT_ROLES: Record<string, string> = {
  atlas: 'Lead',
  hermes: 'Automation',
  iriseye: 'Operator',
  claude: 'Cloud',
}

export const WATCH_AGENTS = ['atlas', 'hermes', 'iriseye', 'claude'] as const

export type Vec3 = { x: number; y: number; z: number }

export type PanelDatum = {
  title: string
  rows: Array<[string, string]>
  bars: number[]
  kind?: 'default' | 'agents'
  agents?: Array<{ label: string; status: string; live: boolean }>
}

export type GraphNodeMeta =
  | { type: 'agent'; key: string; label: string; x: number; y: number; radius: number }
  | { type: 'service'; key: string; label: string; x: number; y: number; radius: number }

export const AGENT_POINTS: Record<string, Vec3> = {
  atlas: { x: 0, y: 0.16, z: 0.95 },
  hermes: { x: -0.62, y: -0.18, z: 0.48 },
  iriseye: { x: 0.6, y: -0.22, z: 0.44 },
  claude: { x: 0.22, y: 0.58, z: 0.72 },
}

export const SERVICE_POINTS: Record<string, Vec3> = {
  openviking: { x: -0.12, y: 0.72, z: 0.42 },
  mlx_server: { x: 0.72, y: 0.18, z: 0.34 },
  openclaw_mcp: { x: 0.54, y: -0.52, z: 0.28 },
  ollama: { x: -0.04, y: -0.76, z: 0.22 },
  memory_mcp: { x: -0.76, y: -0.18, z: 0.26 },
  screenpipe: { x: -0.56, y: 0.42, z: 0.18 },
}

export const STAR_POINTS: Vec3[] = Array.from({ length: 600 }, (_, index) => {
  const theta = (index * 2.399963229728653) % (Math.PI * 2)
  const v = -1 + ((index + 0.5) / 600) * 2
  const phi = Math.acos(v)
  const radius = 0.72 + ((index * 37) % 24) / 100
  return {
    x: Math.sin(phi) * Math.cos(theta) * radius,
    y: Math.cos(phi) * radius,
    z: Math.sin(phi) * Math.sin(theta) * radius,
  }
})

export const SHELL_POINTS: Vec3[] = Array.from({ length: 280 }, (_, index) => {
  const theta = (index * 1.61803398875) % (Math.PI * 2)
  const band = -1 + ((index + 0.5) / 280) * 2
  const phi = Math.acos(band)
  const radius = 0.9 + ((index * 13) % 10) / 100
  return {
    x: Math.sin(phi) * Math.cos(theta) * radius,
    y: Math.cos(phi) * radius,
    z: Math.sin(phi) * Math.sin(theta) * radius,
  }
})

export const POLY_LINES: Array<[Vec3, Vec3]> = [
  [SERVICE_POINTS.openviking, AGENT_POINTS.atlas],
  [SERVICE_POINTS.mlx_server, AGENT_POINTS.atlas],
  [SERVICE_POINTS.memory_mcp, AGENT_POINTS.atlas],
  [SERVICE_POINTS.openclaw_mcp, AGENT_POINTS.hermes],
  [SERVICE_POINTS.ollama, AGENT_POINTS.hermes],
  [SERVICE_POINTS.screenpipe, AGENT_POINTS.atlas],
  [SERVICE_POINTS.screenpipe, AGENT_POINTS.hermes],
  [SERVICE_POINTS.memory_mcp, AGENT_POINTS.iriseye],
  [SERVICE_POINTS.openviking, SERVICE_POINTS.mlx_server],
  [SERVICE_POINTS.mlx_server, SERVICE_POINTS.openclaw_mcp],
  [SERVICE_POINTS.openclaw_mcp, SERVICE_POINTS.ollama],
  [SERVICE_POINTS.ollama, SERVICE_POINTS.memory_mcp],
  [SERVICE_POINTS.memory_mcp, SERVICE_POINTS.screenpipe],
  [SERVICE_POINTS.screenpipe, SERVICE_POINTS.openviking],
  // Additional cross-connections for richer lattice
  [SERVICE_POINTS.openviking, SERVICE_POINTS.openclaw_mcp],
  [SERVICE_POINTS.mlx_server, SERVICE_POINTS.screenpipe],
  [SERVICE_POINTS.mlx_server, SERVICE_POINTS.memory_mcp],
  [SERVICE_POINTS.ollama, SERVICE_POINTS.openviking],
  [AGENT_POINTS.hermes, AGENT_POINTS.iriseye],
  [AGENT_POINTS.hermes, AGENT_POINTS.atlas],
  [AGENT_POINTS.iriseye, AGENT_POINTS.atlas],
  [AGENT_POINTS.claude, AGENT_POINTS.atlas],
  [AGENT_POINTS.claude, SERVICE_POINTS.openviking],
]

