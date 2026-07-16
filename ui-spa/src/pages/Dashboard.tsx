import { useMemo } from 'react'
import { useDashboard } from '../store'

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-white/10 bg-white/5 shadow-[0_12px_40px_rgba(0,0,0,0.18)] backdrop-blur-sm ${className}`}>
      {children}
    </div>
  )
}

function MetricCard({ label, value, hint, tone = 'neutral' }: {
  label: string
  value: string
  hint?: string
  tone?: 'neutral' | 'good' | 'warn' | 'bad'
}) {
  const tones = {
    neutral: 'text-white',
    good: 'text-emerald-300',
    warn: 'text-amber-300',
    bad: 'text-rose-300',
  }
  return (
    <Card className="p-4 min-h-[108px]">
      <div className="text-xs uppercase tracking-[0.22em] text-[#9aa2b8]">{label}</div>
      <div className={`mt-3 text-3xl font-extrabold tracking-tight ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-2 text-xs text-[#9aa2b8]">{hint}</div>}
    </Card>
  )
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      {subtitle && <p className="text-xs text-[#9aa2b8] mt-1">{subtitle}</p>}
    </div>
  )
}

function statusDot(ready: boolean) {
  return ready ? 'bg-emerald-400 shadow-[0_0_0_4px_rgba(16,185,129,0.16)]' : 'bg-rose-400 shadow-[0_0_0_4px_rgba(244,63,94,0.14)]'
}

function signalTone(value: number) {
  if (value > -65) return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
  if (value > -75) return 'bg-amber-500/20 text-amber-300 border-amber-500/30'
  return 'bg-rose-500/20 text-rose-300 border-rose-500/30'
}

export default function Dashboard() {
  const { robots, nodes, rssi, handovers, recent_missions, mqtt_ok } = useDashboard()

  const edgeNodes = nodes.filter((n: any) => n.role === 'edge')
  const robotNodes = nodes.filter((n: any) => n.role === 'robot')
  const onlineRobots = robots.filter((r) => r.online)
  const activeMissions = robots.filter((r) => r.current_mission)

  const stationNames = useMemo(() => Array.from(new Set(rssi.map((s) => s.station))).sort(), [rssi])
  const robotIds = useMemo(() => Array.from(new Set(rssi.map((s) => s.sn))).sort(), [rssi])

  const rssiMatrix = useMemo(() => {
    return stationNames.map((station) => ({
      station,
      cells: robotIds.map((sn) => rssi.find((entry) => entry.station === station && entry.sn === sn) || null),
    }))
  }, [rssi, robotIds, stationNames])

  return (
    <div className="p-4 space-y-4 max-w-[1700px] mx-auto">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-[0.3em] text-[#9aa2b8]">Tab 1 · Dashboard</div>
          <h1 className="text-2xl font-black tracking-tight mt-1">실시간 Fleet 모니터링</h1>
        </div>
        <div className={`px-3 py-1.5 rounded-full border text-xs font-medium ${mqtt_ok ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
          MQTT {mqtt_ok ? 'Connected' : 'Disconnected'}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <MetricCard label="기지국 노드 수" value={`${edgeNodes.filter((n: any) => n.ready).length}/${edgeNodes.length}`} hint="edge role" tone={edgeNodes.every((n: any) => n.ready) ? 'good' : 'warn'} />
        <MetricCard label="제어 노드 수" value={`${robotNodes.filter((n: any) => n.ready).length}/${robotNodes.length}`} hint="robot role" tone={robotNodes.every((n: any) => n.ready) ? 'good' : 'warn'} />
        <MetricCard label="로봇 온라인 수" value={`${onlineRobots.length}/${robots.length}`} hint="link_proxy 연결 로봇 기준" tone={onlineRobots.length > 0 ? 'good' : 'bad'} />
        <MetricCard label="진행 미션 수" value={`${activeMissions.length}`} hint="현재 미션 진행 중 로봇" tone={activeMissions.length > 0 ? 'warn' : 'neutral'} />
        <MetricCard label="MQTT 상태" value={mqtt_ok ? 'ON' : 'OFF'} hint="/ws/mqtt 스트림 연결" tone={mqtt_ok ? 'good' : 'bad'} />
      </div>

      <div className="grid xl:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionTitle title="노드 카드" subtitle="기지국 RPi(edge role) / 제어용 RPi(robot role)" />
          <div className="grid md:grid-cols-2 gap-3">
            <div className="space-y-3">
              <div className="text-xs uppercase tracking-[0.22em] text-[#9aa2b8]">기지국 RPi</div>
              {edgeNodes.length === 0 && <div className="text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">표시할 기지국 노드가 없습니다.</div>}
              {edgeNodes.map((node: any) => (
                <div key={node.name} className="rounded-xl border border-white/10 bg-[#121521] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`h-2.5 w-2.5 rounded-full ${statusDot(node.ready)}`} />
                        <div className="font-semibold">{node.name}</div>
                      </div>
                      <div className="text-xs text-[#9aa2b8] mt-1">{node.ready ? 'Ready' : 'NotReady'} · {node.age || '-'}</div>
                    </div>
                    <span className="text-[11px] px-2 py-1 rounded-full bg-white/5 border border-white/10 text-[#b7bfd0]">edge role</span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(node.pods || []).map((pod: any) => (
                      <span key={pod.name} className={`text-xs px-2 py-1 rounded-full border ${pod.phase === 'Running' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                        {pod.app || pod.name} · {pod.phase}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="space-y-3">
              <div className="text-xs uppercase tracking-[0.22em] text-[#9aa2b8]">제어용 RPi</div>
              {robotNodes.length === 0 && <div className="text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">표시할 제어 노드가 없습니다.</div>}
              {robotNodes.map((node: any) => (
                <div key={node.name} className="rounded-xl border border-white/10 bg-[#121521] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`h-2.5 w-2.5 rounded-full ${statusDot(node.ready)}`} />
                        <div className="font-semibold">{node.name}</div>
                      </div>
                      <div className="text-xs text-[#9aa2b8] mt-1">{node.ready ? 'Ready' : 'NotReady'}</div>
                    </div>
                    <span className="text-[11px] px-2 py-1 rounded-full bg-white/5 border border-white/10 text-[#b7bfd0]">robot role</span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(node.pods || []).map((pod: any) => (
                      <span key={pod.name} className={`text-xs px-2 py-1 rounded-full border ${pod.phase === 'Running' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                        {pod.app || pod.name} · {pod.phase}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle title="로봇 카드" subtitle="link_proxy가 연결한 로봇마다 1개씩 표시" />
          <div className="grid sm:grid-cols-2 gap-3">
            {robots.length === 0 && <div className="col-span-full text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">연결된 로봇이 없습니다.</div>}
            {robots.map((robot) => {
              const battery = robot.battery?.soc ?? 0
              const batteryBarTone = battery > 50 ? 'from-emerald-400 to-emerald-500' : battery > 20 ? 'from-amber-400 to-amber-500' : 'from-rose-400 to-rose-500'
              return (
                <div key={robot.robot_id} className={`rounded-2xl border p-4 ${robot.online ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-white/10 bg-[#121521]'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs text-[#9aa2b8] uppercase tracking-[0.18em]">SN</div>
                      <div className="mt-1 font-mono text-sm font-semibold break-all">{robot.robot_id}</div>
                    </div>
                    <span className={`text-xs px-2 py-1 rounded-full border ${robot.online ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                      {robot.online ? 'ONLINE' : 'OFFLINE'}
                    </span>
                  </div>

                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs text-[#9aa2b8] mb-1">
                      <span>배터리</span>
                      <span>{battery}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-black/20 overflow-hidden border border-white/10">
                      <div className={`h-full rounded-full bg-gradient-to-r ${batteryBarTone}`} style={{ width: `${Math.max(0, Math.min(100, battery))}%` }} />
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[#d7dbec]">
                    <div className="rounded-lg bg-white/5 p-2">x: <span className="font-mono">{robot.position?.x?.toFixed(2) ?? '-'}</span></div>
                    <div className="rounded-lg bg-white/5 p-2">y: <span className="font-mono">{robot.position?.y?.toFixed(2) ?? '-'}</span></div>
                    <div className="rounded-lg bg-white/5 p-2 col-span-2">속도: <span className="font-mono">{robot.speed?.speed !== undefined ? `${robot.speed.speed.toFixed(2)} m/s` : '-'}</span></div>
                  </div>

                  {robot.armor?.id ? (
                    <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200 font-medium">
                      장갑 타격 경고 · {robot.armor.position ?? '-'} (id={robot.armor.id})
                    </div>
                  ) : null}

                  {robot.current_mission ? (
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs text-[#9aa2b8] mb-1">
                        <span>현재 미션</span>
                        <span className="font-mono">{robot.current_mission.mission_id ?? '-'}</span>
                      </div>
                      <div className="h-2 rounded-full bg-black/20 overflow-hidden border border-white/10">
                        <div className="h-full rounded-full bg-gradient-to-r from-[#7c6ff7] to-[#a89dff]" style={{ width: `${robot.current_mission.progress_pct ?? 0}%` }} />
                      </div>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-4 xl:col-span-2">
          <SectionTitle title="RSSI 히트맵 (Phase 2)" subtitle="기지국 × 로봇 신호 강도 카드 · -65 / -75 기준 색상 변경" />
          {rssiMatrix.length === 0 ? (
            <div className="text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">RSSI 데이터가 없습니다.</div>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[640px] space-y-3">
                <div className="grid gap-2" style={{ gridTemplateColumns: `160px repeat(${Math.max(1, robotIds.length)}, minmax(0, 1fr))` }}>
                  <div className="text-xs text-[#9aa2b8] uppercase tracking-[0.2em]">station / robot</div>
                  {robotIds.map((sn) => <div key={sn} className="text-xs text-[#9aa2b8] uppercase tracking-[0.2em] truncate">{sn}</div>)}
                </div>
                {rssiMatrix.map((row) => (
                  <div key={row.station} className="grid gap-2 items-stretch" style={{ gridTemplateColumns: `160px repeat(${Math.max(1, robotIds.length)}, minmax(0, 1fr))` }}>
                    <div className="rounded-xl border border-white/10 bg-[#121521] p-3">
                      <div className="text-xs text-[#9aa2b8]">{row.station}</div>
                    </div>
                    {row.cells.map((cell, index) => (
                      <div key={index} className="rounded-xl border border-white/10 bg-[#121521] p-3 min-h-[96px]">
                        {cell ? (
                          <>
                            <div className="text-[11px] text-[#9aa2b8] uppercase tracking-[0.18em] truncate">{cell.ssid}</div>
                            <div className={`mt-2 inline-flex items-center px-2 py-1 rounded-full border text-sm font-semibold ${signalTone(cell.ewma)}`}>{cell.ewma.toFixed(1)} dBm</div>
                            <div className="mt-2 text-xs text-[#9aa2b8]">raw: {cell.rssi} dBm</div>
                          </>
                        ) : (
                          <div className="text-xs text-[#9aa2b8] opacity-50">-</div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card className="p-4">
            <SectionTitle title="핸드오버 이벤트 (Phase 2)" subtitle="robot_sn · from_station → to_station · 발생 시각" />
            <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
              {handovers.length === 0 ? <div className="text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">핸드오버 이벤트가 없습니다.</div> : handovers.map((handover, index) => (
                <div key={index} className="rounded-xl border border-white/10 bg-[#121521] p-3">
                  <div className="font-mono text-sm text-white">{handover.robot_sn}</div>
                  <div className="mt-1 text-sm text-[#d7dbec]">{handover.from_station} → {handover.to_station}</div>
                  <div className="mt-1 text-xs text-[#9aa2b8]">{new Date(handover.ts * 1000).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-4">
            <SectionTitle title="미션 이력" subtitle="미션ID | 로봇 | accept/reject | 이유 | 시각" />
            <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
              {recent_missions.length === 0 ? <div className="text-sm text-[#9aa2b8] bg-white/5 rounded-xl p-4">미션 이력이 없습니다.</div> : recent_missions.slice(0, 10).map((mission, index) => (
                <div key={index} className="rounded-xl border border-white/10 bg-[#121521] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-mono text-sm text-white truncate">{mission.mission_id}</div>
                    <span className={`text-xs px-2 py-1 rounded-full border ${mission.decision === 'accept' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-rose-500/10 border-rose-500/20 text-rose-300'}`}>
                      {mission.decision}
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-[#9aa2b8]">
                    <div>로봇: <span className="text-white font-mono">{mission.robot_id}</span></div>
                    <div>이유: <span className="text-white">{mission.reason || '-'}</span></div>
                  </div>
                  <div className="mt-1 text-xs text-[#9aa2b8]">{new Date(mission.ts * 1000).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
