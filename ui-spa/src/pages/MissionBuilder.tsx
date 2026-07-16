import { useEffect, useMemo, useState, type ReactNode } from 'react'

// ── 블록 타입 정의 ────────────────────────────────────────────────
type BlockType = 'move' | 'rotate' | 'stop' | 'led' | 'gripper' | 'arm' | 'repeat' | 'if_' | 'wait'
type ChildList = 'children' | 'then_' | 'else_'

interface Block {
  id: string
  type: BlockType
  delay: number
  params?: Record<string, any>
  children?: Block[]
  then_?: Block[]
  else_?: Block[]
  condition?: { sensor: string; field: string; op: string; value: string }
  event?: string
  filter?: Record<string, string>
  timeout?: number
}

const COLORS: Record<BlockType, string> = {
  move: 'bg-sky-950 border-sky-700 text-sky-200',
  rotate: 'bg-emerald-950 border-emerald-700 text-emerald-200',
  stop: 'bg-rose-950 border-rose-700 text-rose-200',
  led: 'bg-pink-950 border-pink-700 text-pink-200',
  gripper: 'bg-orange-950 border-orange-700 text-orange-200',
  arm: 'bg-orange-950 border-orange-700 text-orange-200',
  repeat: 'bg-violet-950 border-violet-700 text-violet-200',
  if_: 'bg-amber-950 border-amber-700 text-amber-200',
  wait: 'bg-cyan-950 border-cyan-700 text-cyan-200',
}

const LABELS: Record<BlockType, string> = {
  move: '전진/후진',
  rotate: '회전',
  stop: '정지',
  led: 'LED',
  gripper: '그리퍼',
  arm: '로봇 암',
  repeat: '반복 (REPEAT)',
  if_: '조건 (IF)',
  wait: '이벤트 대기',
}

const DEFAULTS: Record<BlockType, Partial<Block>> = {
  move: { params: { x: 0.3, y: 0, speed: 0.3 }, delay: 3 },
  rotate: { params: { yaw: 90, v_speed: 45 }, delay: 2 },
  stop: { params: {}, delay: 0 },
  led: { params: { r: 0, g: 255, b: 0, eff: 'on' }, delay: 0.5 },
  gripper: { params: { grip: 50, open: false }, delay: 2 },
  arm: { params: { arm_x: 0, arm_y: 0 }, delay: 2 },
  repeat: { params: { times: 3 }, children: [], delay: 0 },
  if_: { condition: { sensor: 'armor', field: 'position', op: 'eq', value: 'front' }, then_: [], else_: [], delay: 0 },
  wait: { event: 'armor_hit', filter: { position: 'front' }, timeout: 10, children: [], delay: 0 },
}

const STATION_OPTIONS = ['station-a', 'station-b']

let nextId = 1
function makeBlock(type: BlockType): Block {
  return { id: String(nextId++), type, ...JSON.parse(JSON.stringify(DEFAULTS[type])) }
}

function toPayload(block: Block): any {
  if (block.type === 'move') return { target: 'chassis', action: 'MOVE', params: block.params, delay_sec: block.delay }
  if (block.type === 'rotate') return { target: 'chassis', action: 'ROTATE', params: block.params, delay_sec: block.delay }
  if (block.type === 'stop') return { target: 'chassis', action: 'STOP', params: {}, delay_sec: block.delay }
  if (block.type === 'led') return { target: 'led', action: 'SET', params: block.params, delay_sec: block.delay }
  if (block.type === 'gripper') return { target: 'actuator', action: 'GRIPPER', params: block.params, delay_sec: block.delay }
  if (block.type === 'arm') return { target: 'actuator', action: 'ARM_MOVE', params: block.params, delay_sec: block.delay }
  if (block.type === 'repeat') return { target: 'flow', action: 'REPEAT', params: { times: block.params?.times }, body: (block.children || []).map(toPayload), delay_sec: block.delay }
  if (block.type === 'wait') return { target: 'flow', action: 'WAIT_EVENT', event: block.event, params: block.filter || {}, timeout_sec: block.timeout, children: (block.children || []).map(toPayload), delay_sec: block.delay }
  if (block.type === 'if_') return { target: 'flow', action: 'IF', condition: block.condition, then: (block.then_ || []).map(toPayload), else: (block.else_ || []).map(toPayload), delay_sec: block.delay }
  return {}
}

function NumberField({ label, value, min, max, step = 0.1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (value: number) => void }) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-[#9aa2b8] w-14">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        className="w-18 bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1 text-white"
        onChange={e => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-[#9aa2b8]">{label}</span>
      <select
        value={value}
        className="bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1 text-white"
        onChange={e => onChange(e.target.value)}
      >
        {options.map(option => <option key={option} value={option}>{option || ' '}</option>)}
      </select>
    </label>
  )
}

function BlockView({
  block,
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDn,
  onDropInto,
}: {
  block: Block
  onUpdate: (block: Block) => void
  onDelete: () => void
  onMoveUp: () => void
  onMoveDn: () => void
  onDropInto?: (list: ChildList, child: Block) => void
}) {
  const [dragOver, setDragOver] = useState<ChildList | null>(null)
  const params = block.params || {}

  const updateParams = (key: string, value: any) => onUpdate({ ...block, params: { ...params, [key]: value } })

  function DropZone({ list, title }: { list: ChildList; title: string }) {
    return (
      <div
        onDragOver={event => {
          event.preventDefault()
          setDragOver(list)
        }}
        onDragLeave={() => setDragOver(null)}
        onDrop={event => {
          event.preventDefault()
          setDragOver(null)
          const type = event.dataTransfer.getData('blockType') as BlockType
          if (type && onDropInto) onDropInto(list, makeBlock(type))
        }}
        className={`min-h-[40px] rounded-xl border-2 border-dashed p-2 transition-colors ${dragOver === list ? 'border-[#7c6ff7] bg-[#7c6ff7]/10' : 'border-white/10 bg-white/5'}`}
      >
        <div className="text-[11px] text-[#9aa2b8] mb-2">{title}</div>
        {(block[list] as Block[] | undefined)?.length ? (
          <div className="space-y-2">
            {(block[list] as Block[]).map((child, index) => (
              <BlockView
                key={child.id}
                block={child}
                onUpdate={updated => {
                  const items = [...(block[list] as Block[])]
                  items[index] = updated
                  onUpdate({ ...block, [list]: items })
                }}
                onDelete={() => {
                  const items = (block[list] as Block[]).filter((_, childIndex) => childIndex !== index)
                  onUpdate({ ...block, [list]: items })
                }}
                onMoveUp={() => {
                  if (index === 0) return
                  const items = [...(block[list] as Block[])]
                  ;[items[index - 1], items[index]] = [items[index], items[index - 1]]
                  onUpdate({ ...block, [list]: items })
                }}
                onMoveDn={() => {
                  const items = [...(block[list] as Block[])]
                  if (index >= items.length - 1) return
                  ;[items[index + 1], items[index]] = [items[index], items[index + 1]]
                  onUpdate({ ...block, [list]: items })
                }}
                onDropInto={(nestedList, nestedChild) => {
                  const items = [...(block[list] as Block[])]
                  ;(items[index] as any)[nestedList] = [...(((items[index] as any)[nestedList]) || []), nestedChild]
                  onUpdate({ ...block, [list]: items })
                }}
              />
            ))}
          </div>
        ) : (
          <div className="text-xs text-[#9aa2b8] text-center py-2">블록을 드래그</div>
        )}
      </div>
    )
  }

  return (
    <div className={`mb-2 rounded-2xl border ${COLORS[block.type]} overflow-hidden`} draggable onDragStart={event => event.dataTransfer.setData('blockId', block.id)}>
      <div className="flex items-center gap-2 px-3 py-2 cursor-grab bg-black/10">
        <span className="text-base">⠿</span>
        <span className="flex-1 text-sm font-semibold">{LABELS[block.type]}</span>
        <button onClick={onMoveUp} className="text-xs opacity-60 hover:opacity-100">↑</button>
        <button onClick={onMoveDn} className="text-xs opacity-60 hover:opacity-100">↓</button>
        <button onClick={onDelete} className="text-xs opacity-60 hover:opacity-100 text-red-300">삭제</button>
      </div>

      <div className="px-3 pb-3 pt-2 flex flex-wrap gap-2">
        {block.type === 'move' && (
          <>
            <NumberField label="x(m)" value={params.x ?? 0} min={-5} max={5} onChange={value => updateParams('x', value)} />
            <NumberField label="y(m)" value={params.y ?? 0} min={-5} max={5} onChange={value => updateParams('y', value)} />
            <NumberField label="속도" value={params.speed ?? 0.3} min={0.1} max={3} onChange={value => updateParams('speed', value)} />
          </>
        )}
        {block.type === 'rotate' && (
          <>
            <NumberField label="각도" value={params.yaw ?? 0} min={-360} max={360} step={5} onChange={value => updateParams('yaw', value)} />
            <NumberField label="각속도" value={params.v_speed ?? 45} min={10} max={180} step={5} onChange={value => updateParams('v_speed', value)} />
          </>
        )}
        {block.type === 'led' && (
          <>
            <NumberField label="R" value={params.r ?? 0} min={0} max={255} step={1} onChange={value => updateParams('r', value)} />
            <NumberField label="G" value={params.g ?? 0} min={0} max={255} step={1} onChange={value => updateParams('g', value)} />
            <NumberField label="B" value={params.b ?? 0} min={0} max={255} step={1} onChange={value => updateParams('b', value)} />
            <SelectField label="효과" value={params.eff ?? 'on'} options={['on', 'off', 'flash']} onChange={value => updateParams('eff', value)} />
          </>
        )}
        {block.type === 'gripper' && (
          <>
            <NumberField label="파워" value={params.grip ?? 50} min={1} max={100} step={1} onChange={value => updateParams('grip', value)} />
            <SelectField label="동작" value={params.open ? '열기' : '닫기'} options={['닫기', '열기']} onChange={value => updateParams('open', value === '열기')} />
          </>
        )}
        {block.type === 'arm' && (
          <>
            <NumberField label="X(mm)" value={params.arm_x ?? 0} min={-200} max={200} step={10} onChange={value => updateParams('arm_x', value)} />
            <NumberField label="Y(mm)" value={params.arm_y ?? 0} min={-200} max={200} step={10} onChange={value => updateParams('arm_y', value)} />
          </>
        )}
        {block.type === 'repeat' && (
          <NumberField label="횟수" value={params.times ?? 3} min={1} max={99} step={1} onChange={value => updateParams('times', value)} />
        )}
        {block.type === 'wait' && (
          <>
            <SelectField label="이벤트" value={block.event ?? 'armor_hit'} options={['armor_hit', 'battery_low', 'speed_change', 'imu_change']} onChange={value => onUpdate({ ...block, event: value })} />
            <SelectField label="위치" value={block.filter?.position ?? ''} options={['', 'front', 'back', 'left', 'right']} onChange={value => onUpdate({ ...block, filter: { position: value } })} />
            <NumberField label="timeout" value={block.timeout ?? 10} min={1} max={300} step={1} onChange={value => onUpdate({ ...block, timeout: value })} />
          </>
        )}
        {block.type === 'if_' && (
          <>
            <SelectField label="센서" value={block.condition?.sensor ?? 'armor'} options={['armor', 'battery', 'speed', 'imu', 'position']} onChange={value => onUpdate({ ...block, condition: { ...(block.condition || DEFAULTS.if_!.condition!), sensor: value } })} />
            <label className="flex items-center gap-1 text-xs">
              <span className="text-[#9aa2b8]">필드</span>
              <input
                type="text"
                value={block.condition?.field ?? ''}
                className="w-20 bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1 text-white"
                onChange={e => onUpdate({ ...block, condition: { ...(block.condition || DEFAULTS.if_!.condition!), field: e.target.value } })}
              />
            </label>
            <SelectField label="op" value={block.condition?.op ?? 'eq'} options={['eq', 'ne', 'gt', 'lt', 'gte', 'lte']} onChange={value => onUpdate({ ...block, condition: { ...(block.condition || DEFAULTS.if_!.condition!), op: value } })} />
            <label className="flex items-center gap-1 text-xs">
              <span className="text-[#9aa2b8]">값</span>
              <input
                type="text"
                value={block.condition?.value ?? ''}
                className="w-20 bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1 text-white"
                onChange={e => onUpdate({ ...block, condition: { ...(block.condition || DEFAULTS.if_!.condition!), value: e.target.value } })}
              />
            </label>
          </>
        )}
        <label className="ml-auto flex items-center gap-1 text-xs text-[#9aa2b8]">
          <span>delay</span>
          <input
            type="number"
            value={block.delay}
            min={0}
            max={60}
            step={0.5}
            className="w-14 bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1 text-white"
            onChange={e => onUpdate({ ...block, delay: Number(e.target.value) || 0 })}
          />
          <span>s</span>
        </label>
      </div>

      {block.type === 'repeat' && <div className="px-3 pb-3"><DropZone list="children" title="반복할 블록" /></div>}
      {block.type === 'wait' && <div className="px-3 pb-3"><DropZone list="children" title="이벤트 발생 후 실행" /></div>}
      {block.type === 'if_' && (
        <div className="grid grid-cols-2 gap-2 px-3 pb-3">
          <DropZone list="then_" title="then" />
          <DropZone list="else_" title="else" />
        </div>
      )}
    </div>
  )
}

const PALETTE = [
  { group: '이동', types: ['move', 'rotate', 'stop'] as BlockType[] },
  { group: '장치', types: ['led', 'gripper', 'arm'] as BlockType[] },
  { group: '흐름제어', types: ['repeat', 'if_', 'wait'] as BlockType[] },
]

// 각 블록이 대응하는 프로토콜 (target, action). /api/mission-spec으로 받은
// 배포별 액션 문법과 대조해 실제 지원하는 블록만 팔레트에 노출한다.
const BLOCK_ACTION: Record<BlockType, { target: string; action: string }> = {
  move:   { target: 'chassis',  action: 'MOVE' },
  rotate: { target: 'chassis',  action: 'ROTATE' },
  stop:   { target: 'chassis',  action: 'STOP' },
  led:    { target: 'led',      action: 'SET' },
  gripper:{ target: 'actuator', action: 'GRIPPER' },
  arm:    { target: 'actuator', action: 'ARM_MOVE' },
  repeat: { target: 'flow',     action: 'REPEAT' },
  if_:    { target: 'flow',     action: 'IF' },
  wait:   { target: 'flow',     action: 'WAIT_EVENT' },
}

// mission_spec.targets 에서 지원하는 "target.action" 집합을 만든다.
function specActionSet(spec: any): Set<string> | null {
  const targets = spec?.targets
  if (!targets || typeof targets !== 'object') return null
  const set = new Set<string>()
  for (const [target, def] of Object.entries<any>(targets)) {
    for (const a of def?.actions || []) {
      if (a?.name) set.add(`${target}.${a.name}`)
    }
  }
  return set.size ? set : null
}

export default function MissionBuilder() {
  const [blocks, setBlocks] = useState<Block[]>([])
  const [missionName, setMissionName] = useState('mission-01')
  const [conditions, setConditions] = useState({ robot_type: 'ep01', robot_online: true, min_battery: 20, max_latency_ms: 9999 })
  const [targetStations, setTargetStations] = useState<string[]>([...STATION_OPTIONS])
  // 배포 상태: kind로 색상을 결정하므로 메시지 텍스트(이모지)에 의존하지 않는다.
  const [status, setStatus] = useState<{ kind: 'ok' | 'warn' | 'error'; text: string } | null>(null)
  const [deploying, setDeploying] = useState(false)
  const [canvasDragOver, setCanvasDragOver] = useState(false)
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle')
  // 배포된 로봇의 액션 문법 (허브 config의 mission_spec). 없으면 전체 팔레트 표시.
  const [actionSet, setActionSet] = useState<Set<string> | null>(null)

  useEffect(() => {
    fetch('/api/mission-spec')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setActionSet(specActionSet(data?.spec)))
      .catch(() => setActionSet(null))
  }, [])

  // 스펙을 못 받으면(standalone UI) 필터하지 않고 전체 노출.
  const palette = useMemo(() => {
    if (!actionSet) return PALETTE
    return PALETTE
      .map((grp) => ({
        ...grp,
        types: grp.types.filter((t) => {
          const a = BLOCK_ACTION[t]
          return actionSet.has(`${a.target}.${a.action}`)
        }),
      }))
      .filter((grp) => grp.types.length > 0)
  }, [actionSet])

  const payload = useMemo(() => ({
    mission_name: missionName,
    target_stations: targetStations,
    conditions,
    nodes: blocks.map(toPayload),
  }), [blocks, conditions, missionName, targetStations])

  const previewJson = useMemo(() => JSON.stringify(payload, null, 2), [payload])

  function updateBlock(index: number, block: Block) {
    setBlocks(prev => prev.map((item, itemIndex) => itemIndex === index ? block : item))
  }

  function deleteBlock(index: number) {
    setBlocks(prev => prev.filter((_, itemIndex) => itemIndex !== index))
  }

  async function deploy() {
    if (!blocks.length) {
      setStatus({ kind: 'warn', text: '노드를 추가하세요' })
      return
    }

    setDeploying(true)
    setStatus(null)
    try {
      const response = await fetch('/api/missions/broadcast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      setStatus(data.mqtt_sent
        ? { kind: 'ok', text: `배포 완료 — ${data.mission_id}` }
        : { kind: 'warn', text: `MQTT 미전송 (mission_id: ${data.mission_id})` })
    } catch (error) {
      setStatus({ kind: 'error', text: `배포 실패: ${error}` })
    } finally {
      setDeploying(false)
    }
  }

  async function copyJson() {
    try {
      await navigator.clipboard.writeText(previewJson)
      setCopyState('copied')
      window.setTimeout(() => setCopyState('idle'), 1200)
    } catch {
      setCopyState('idle')
    }
  }

  return (
    <div className="flex h-full min-h-0 text-[#f4f7fb]">
      <aside className="w-[160px] flex-shrink-0 bg-[#10131a]/90 border-r border-white/10 p-3 overflow-y-auto">
        <div className="text-[11px] font-semibold text-[#9aa2b8] uppercase tracking-[0.24em] mb-3">블록 팔레트</div>
        {palette.map(group => (
          <div key={group.group} className="mb-4">
            <div className="text-xs text-[#b7bfd0] mb-1.5">{group.group}</div>
            {group.types.map(type => (
              <div
                key={type}
                draggable
                onDragStart={event => event.dataTransfer.setData('blockType', type)}
                className={`${COLORS[type]} border rounded-lg px-2 py-2 mb-1.5 text-[11px] font-semibold cursor-grab hover:opacity-85 transition-all shadow-sm`}
              >
                {LABELS[type]}
              </div>
            ))}
          </div>
        ))}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 bg-[#10131a]/90 border-b border-white/10 flex-wrap">
          <div className="flex items-center gap-2 text-xs text-[#9aa2b8]">
            <span>미션 이름</span>
            <input
              value={missionName}
              onChange={e => setMissionName(e.target.value)}
              className="bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1.5 text-sm w-40 text-white"
              placeholder="mission-01"
            />
          </div>

          <div className="flex items-center gap-2 text-xs text-[#9aa2b8]">
            <span>로봇 타입</span>
            <input
              value={conditions.robot_type}
              onChange={e => setConditions({ ...conditions, robot_type: e.target.value })}
              className="bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1.5 w-20 text-white"
            />
          </div>

          <label className="flex items-center gap-2 text-xs text-[#9aa2b8] px-2 py-1.5 rounded-lg border border-white/10 bg-white/5">
            <input type="checkbox" checked={conditions.robot_online} onChange={e => setConditions({ ...conditions, robot_online: e.target.checked })} />
            온라인 필수
          </label>

          <label className="flex items-center gap-2 text-xs text-[#9aa2b8] px-2 py-1.5 rounded-lg border border-white/10 bg-white/5">
            <span>최소 배터리</span>
            <input
              type="number"
              value={conditions.min_battery}
              onChange={e => setConditions({ ...conditions, min_battery: Number(e.target.value) })}
              className="bg-[#0f1117] border border-white/10 rounded-lg px-2 py-1.5 w-16 text-white"
            />
            <span>%</span>
          </label>

          <div className="flex items-center gap-2 text-xs text-[#9aa2b8] flex-wrap">
            <span>기지국 선택</span>
            {STATION_OPTIONS.map(station => {
              const active = targetStations.includes(station)
              return (
                <button
                  key={station}
                  onClick={() => setTargetStations(prev => prev.includes(station) ? prev.filter(item => item !== station) : [...prev, station])}
                  className={`px-2 py-1.5 rounded-lg border text-xs ${active ? 'bg-[#7c6ff7] border-[#7c6ff7] text-white' : 'bg-white/5 border-white/10 text-[#b7bfd0]'}`}
                >
                  {station}
                </button>
              )
            })}
          </div>

          <button
            onClick={deploy}
            disabled={deploying}
            className="ml-auto bg-[#7c6ff7] hover:bg-[#6a5fe0] text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 shadow-[0_10px_24px_rgba(124,111,247,0.24)]"
          >
            {deploying ? '배포 중...' : '브로드캐스트 배포'}
          </button>

          <button
            onClick={() => setBlocks([])}
            className="bg-white/5 hover:bg-white/10 text-[#b7bfd0] px-3 py-2 rounded-lg text-sm border border-white/10"
          >
            초기화
          </button>
        </div>

        {status && (
          <div className={`px-4 py-2 text-sm border-b border-white/10 ${status.kind === 'ok' ? 'text-emerald-300' : status.kind === 'error' ? 'text-red-300' : 'text-amber-300'}`}>
            {status.text}
          </div>
        )}

        <div className="grid grid-cols-[minmax(0,1fr)_240px] flex-1 min-h-0 overflow-hidden">
          <div
            className="overflow-y-auto p-4"
            onDragOver={e => {
              e.preventDefault()
              setCanvasDragOver(true)
            }}
            onDragLeave={() => setCanvasDragOver(false)}
            onDrop={e => {
              e.preventDefault()
              setCanvasDragOver(false)
              const type = e.dataTransfer.getData('blockType') as BlockType
              if (type) setBlocks(prev => [...prev, makeBlock(type)])
            }}
          >
            {blocks.length === 0 && (
              <div className={`flex flex-col items-center justify-center h-56 rounded-2xl border-2 border-dashed transition-colors ${canvasDragOver ? 'border-[#7c6ff7] bg-[#7c6ff7]/10' : 'border-white/10 bg-white/5'}`}>
                <div className="text-3xl mb-2 opacity-30">⊞</div>
                <div className="text-[#d7dbec] text-sm">블록을 여기에 드래그하세요</div>
                <div className="text-[#9aa2b8] text-xs mt-1">REPEAT / IF / WAIT 안에 중첩 가능</div>
              </div>
            )}

            {blocks.map((block, index) => (
              <BlockView
                key={block.id}
                block={block}
                onUpdate={updated => updateBlock(index, updated)}
                onDelete={() => deleteBlock(index)}
                onMoveUp={() => {
                  if (index === 0) return
                  const items = [...blocks]
                  ;[items[index - 1], items[index]] = [items[index], items[index - 1]]
                  setBlocks(items)
                }}
                onMoveDn={() => {
                  if (index >= blocks.length - 1) return
                  const items = [...blocks]
                  ;[items[index + 1], items[index]] = [items[index], items[index + 1]]
                  setBlocks(items)
                }}
                onDropInto={(list, child) => {
                  const updated = { ...block, [list]: [...((block[list] as Block[] | undefined) || []), child] }
                  updateBlock(index, updated as Block)
                }}
              />
            ))}
          </div>

          <aside className="border-l border-white/10 bg-[#10131a]/90 p-4 overflow-y-auto min-h-0">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.24em] text-[#9aa2b8]">JSON 패널</div>
                <div className="text-sm font-semibold text-white mt-1">실시간 미리보기</div>
              </div>
              <button
                onClick={copyJson}
                className="text-xs px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[#d7dbec]"
              >
                {copyState === 'copied' ? '복사됨' : '복사'}
              </button>
            </div>
            <div className="rounded-2xl border border-white/10 bg-[#0b0d12] p-3 text-[11px] leading-5 font-mono text-[#d7dbec] overflow-x-auto whitespace-pre-wrap break-words min-h-[calc(100vh-210px)]">
              {previewJson}
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
