import { create } from 'zustand'

export interface RobotState {
  robot_id: string
  online: boolean
  battery: { soc?: number }
  position: { x?: number; y?: number }
  speed: { speed?: number }
  armor: { id?: number; position?: string; ts?: number }
  current_mission?: { mission_id?: string; progress_pct?: number } | null
}

export interface RssiState {
  station: string
  sn: string
  ssid: string
  rssi: number
  ewma: number
  ts: number
}

export interface HandoverState {
  robot_sn: string
  from_station: string
  to_station: string
  ts: number
}

export interface MqttEntry {
  topic: string
  payload: string
  ts: number
}

interface DashboardStore {
  robots: RobotState[]
  nodes: any[]
  rssi: RssiState[]
  handovers: HandoverState[]
  recent_missions: any[]
  mqtt_ok: boolean
  mqtt_log: MqttEntry[]
  setDashboard: (d: any) => void
  addMqttEntry: (e: MqttEntry) => void
}

export const useDashboard = create<DashboardStore>((set) => ({
  robots: [], nodes: [], rssi: [], handovers: [],
  recent_missions: [], mqtt_ok: false, mqtt_log: [],
  setDashboard: (d) => set({
    robots: d.robots || [],
    nodes:  d.nodes  || [],
    rssi:   d.rssi   || [],
    handovers: d.handovers || [],
    recent_missions: d.recent_missions || [],
    mqtt_ok: d.mqtt_ok ?? false,
  }),
  addMqttEntry: (e) => set((s) => ({
    mqtt_log: [e, ...s.mqtt_log].slice(0, 200),
  })),
}))

// ── WebSocket 연결 (앱 시작 시 1회) ──────────────────────────────
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

function connectDashboardWS() {
  const ws = new WebSocket(`${WS_BASE}/ws/dashboard`)
  ws.onmessage = (e) => {
    try { useDashboard.getState().setDashboard(JSON.parse(e.data)) }
    catch {}
  }
  ws.onclose = () => setTimeout(connectDashboardWS, 2000)
}

function connectMqttWS() {
  const ws = new WebSocket(`${WS_BASE}/ws/mqtt`)
  ws.onmessage = (e) => {
    try { useDashboard.getState().addMqttEntry(JSON.parse(e.data)) }
    catch {}
  }
  ws.onclose = () => setTimeout(connectMqttWS, 2000)
}

connectDashboardWS()
connectMqttWS()
