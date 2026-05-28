import { useState, useEffect } from 'react'

interface HealthData {
  k3s_available: boolean
  mqtt_available: boolean
  namespace: string
  hub_port: number
  dry_run: boolean
}

interface RedisResult {
  key: string
  type?: string
  value?: any
  note?: string
  error?: string
}

export default function Config() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [redisKey, setRedisKey] = useState('robot:3JKCK5L003093S:status')
  const [redisResult, setRedisResult] = useState<RedisResult | null>(null)
  const [redisLoading, setRedisLoading] = useState(false)

  // 헬스 조회
  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json())
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  async function queryRedis() {
    if (!redisKey.trim()) return
    setRedisLoading(true)
    try {
      const r = await fetch(`/api/redis?key=${encodeURIComponent(redisKey)}`)
      setRedisResult(await r.json())
    } catch (e) {
      setRedisResult({ key: redisKey, error: String(e) })
    } finally {
      setRedisLoading(false)
    }
  }

  // 자주 쓰는 Redis 키 프리셋
  const PRESETS = [
    { label: 'robot:{SN}:status', value: 'robot:3JKCK5L003093S:status' },
    { label: 'robot:{SN}:online', value: 'robot:3JKCK5L003093S:online' },
    { label: 'fleet:cache:{SN}', value: 'fleet:cache:3JKCK5L003093S' },
    { label: 'handover:{SN}', value: 'handover:3JKCK5L003093S' },
    { label: 'rssi:station-a:{SN}', value: 'rssi:station-a:3JKCK5L003093S' },
    { label: 'rssi:station-b:{SN}', value: 'rssi:station-b:3JKCK5L003093S' },
  ]

  const deploySteps = [
    'bash scripts/00_check_prereqs.sh',
    'bash scripts/05_build_images.sh',
    'bash scripts/06_push_images.sh',
    'kubectl -n default rollout restart deployment/central-hub',
    'kubectl -n default rollout status deployment/central-hub --timeout=120s',
    'curl -v http://localhost:30005/api/health',
    'curl -v http://localhost:30005/api/dashboard',
  ]

  function Card({ title, children }: { title: string; children: React.ReactNode }) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 mb-4 shadow-[0_12px_40px_rgba(0,0,0,0.18)]">
        <h3 className="text-sm font-semibold text-white mb-3">{title}</h3>
        {children}
      </div>
    )
  }

  function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
    return (
      <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${
        ok ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
           : 'bg-rose-500/10 border-rose-500/20 text-rose-300'
      }`}>
        <span className="text-lg">{ok ? '●' : '○'}</span>
        <span className="text-sm font-medium">{label}</span>
      </div>
    )
  }

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <div className="mb-4">
        <div className="text-xs uppercase tracking-[0.24em] text-[#9aa2b8]">Tab 4 · Config</div>
        <h1 className="text-2xl font-black tracking-tight mt-1">설정 및 디버그</h1>
      </div>

      {/* 시스템 상태 */}
      <Card title="⚙️ 시스템 상태">
        {health ? (
          <div className="grid grid-cols-3 gap-3">
            <StatusBadge ok={health.k3s_available}  label="k3s 연결" />
            <StatusBadge ok={health.mqtt_available} label="MQTT 연결" />
            <StatusBadge ok={!health.dry_run}       label="실제 배포 모드" />
          </div>
        ) : (
          <p className="text-[#9aa2b8] text-sm">Hub 연결 불가</p>
        )}
        {health && (
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[#9aa2b8]">
            <div>Namespace: <span className="text-white">{health.namespace}</span></div>
            <div>Hub Port: <span className="text-white">{health.hub_port}</span></div>
          </div>
        )}
      </Card>

      {/* Redis 직접 조회 */}
      <Card title="🗄 Redis 직접 조회">
        {/* 프리셋 */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {PRESETS.map(({ label, value }) => (
            <button key={label}
              onClick={() => setRedisKey(value)}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                redisKey === value
                  ? 'bg-[#7c6ff7] border-[#7c6ff7] text-white'
                  : 'bg-white/5 border-white/10 text-[#b7bfd0] hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>

        {/* 입력 */}
        <div className="flex gap-2 mb-3">
          <input
            value={redisKey}
            onChange={e => setRedisKey(e.target.value)}
            placeholder="Redis 키 입력..."
            className="flex-1 bg-[#0f1117] border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder-[#9aa2b8]"
            onKeyDown={e => e.key === 'Enter' && queryRedis()}
          />
          <button
            onClick={queryRedis}
            disabled={redisLoading}
            className="bg-[#7c6ff7] hover:bg-[#6a5fe0] text-white px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-50">
            {redisLoading ? '조회 중...' : '조회'}
          </button>
        </div>

        {/* 결과 */}
        {redisResult && (
          <div className="bg-[#0f1117] border border-white/10 rounded-2xl p-3">
            <div className="text-xs text-[#9aa2b8] mb-2">
              키: <span className="text-purple-300 font-mono">{redisResult.key}</span>
              {redisResult.type && <span className="ml-2 text-blue-300">({redisResult.type})</span>}
            </div>
            {redisResult.error ? (
              <div className="text-red-400 text-xs">{redisResult.error}</div>
            ) : redisResult.value === null ? (
              <div className="text-[#9aa2b8] text-xs italic">{redisResult.note || '키 없음'}</div>
            ) : (
              <pre className="text-xs font-mono text-emerald-300 whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                {JSON.stringify(redisResult.value, null, 2)}
              </pre>
            )}
          </div>
        )}
      </Card>

      {/* 실행 순서 가이드 */}
      <Card title="📋 배포 순서">
        <ol className="space-y-2 text-sm text-[#b7bfd0]">
          {deploySteps.map((cmd, i) => (
            <li key={i} className="flex gap-3">
              <span className="text-[#7c6ff7] font-mono text-xs w-5 flex-shrink-0">{i+1}.</span>
              <code className="font-mono text-xs text-white bg-[#0f1117] px-2 py-1 rounded flex-1 break-all">
                {cmd}
              </code>
            </li>
          ))}
        </ol>
      </Card>

    </div>
  )
}
