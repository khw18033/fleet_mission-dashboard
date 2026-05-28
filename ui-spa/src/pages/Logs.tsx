import { useDashboard } from '../store'

export default function Logs() {
  const { mqtt_log } = useDashboard()

  const TOPIC_COLORS: Record<string, string> = {
    'fleet/mission/deploy':    'text-sky-400',
    'fleet/mission/broadcast': 'text-emerald-400',
    'fleet/mission/accept/':   'text-amber-300',
    'fleet/mission/accepted':  'text-yellow-200',
    'fleet/mission/cache/':    'text-violet-300',
    'fleet/handover/':         'text-orange-300',
    'fleet/ping':              'text-[#9aa2b8]',
  }

  function topicColor(topic: string): string {
    for (const [prefix, color] of Object.entries(TOPIC_COLORS)) {
      if (topic.startsWith(prefix)) return color
    }
    return 'text-[#9896a8]'
  }

  return (
    <div className="p-4 h-full flex flex-col max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-[#9aa2b8]">Tab 3 · MQTT Log</div>
          <h2 className="text-xl font-black tracking-tight mt-1">실시간 fleet 토픽 스트림</h2>
        </div>
        <span className="text-xs text-[#9aa2b8] px-3 py-1.5 rounded-full border border-white/10 bg-white/5">{mqtt_log.length}건 · 최근 200건 유지</span>
      </div>

      {/* 범례 */}
      <div className="flex gap-3 mb-3 flex-wrap px-1">
        {Object.entries(TOPIC_COLORS).map(([prefix, color]) => (
          <span key={prefix} className={`text-xs ${color}`}>
            ● {prefix.replace('fleet/', '')}
          </span>
        ))}
      </div>

      {/* 로그 목록 */}
      <div className="flex-1 overflow-y-auto bg-white/5 border border-white/10 rounded-2xl p-2 font-mono text-xs space-y-0.5 shadow-[0_12px_40px_rgba(0,0,0,0.18)]">
        {mqtt_log.length === 0 && (
          <div className="text-[#9aa2b8] text-center py-8">
            MQTT 메시지 대기 중...
          </div>
        )}
        {mqtt_log.map((entry, i) => {
          const ts = new Date(entry.ts * 1000).toLocaleTimeString('ko-KR', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 1
          })
          let payloadPreview = entry.payload
          try {
            const parsed = JSON.parse(entry.payload)
            // mission_id 줄임
            if (parsed.mission_id) parsed.mission_id = '...' + String(parsed.mission_id).slice(-8)
            payloadPreview = JSON.stringify(parsed)
          } catch {}

          return (
            <div key={i} className="grid grid-cols-[128px_280px_minmax(0,1fr)] gap-3 py-2 px-3 border-b border-white/5 hover:bg-white/5 rounded-xl items-start">
              <span className="text-[#9aa2b8] flex-shrink-0">{ts}</span>
              <span className={`flex-shrink-0 truncate ${topicColor(entry.topic)}`}>{entry.topic}</span>
              <span className="text-[#d7dbec] truncate min-w-0">{payloadPreview.slice(0, 200)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
