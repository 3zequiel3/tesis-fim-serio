import { useState } from 'react'
import type { Agent } from '@/api/agents'

interface AgentCardProps {
  agent: Agent
  onConfigSave: (id: string, paths: string[]) => void
  onRescan: (id: string) => void
  isSavingConfig?: boolean
  isRescanning?: boolean
}

const STATUS_STYLES: Record<Agent['status'], string> = {
  online: 'bg-green-700 text-green-200',
  offline: 'bg-gray-600 text-gray-300',
  draining: 'bg-yellow-700 text-yellow-200',
  dead: 'bg-red-800 text-red-200',
}

function formatLastSeen(iso: string): string {
  const d = new Date(iso)
  const diff = Math.floor((Date.now() - d.getTime()) / 1000)
  if (diff < 60) return `hace ${diff}s`
  if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`
  return `hace ${Math.floor(diff / 86400)}d`
}

export function AgentCard({
  agent,
  onConfigSave,
  onRescan,
  isSavingConfig,
  isRescanning,
}: AgentCardProps) {
  const isDraining = agent.status === 'draining'
  const [editingPaths, setEditingPaths] = useState(false)
  const [paths, setPaths] = useState<string[]>(agent.watch_paths)
  const [newPath, setNewPath] = useState('')

  const pressurePct = Math.round((agent.queue_pressure ?? 0) * 100)

  function handleAddPath() {
    const trimmed = newPath.trim()
    if (trimmed && !paths.includes(trimmed)) {
      setPaths([...paths, trimmed])
    }
    setNewPath('')
  }

  function handleRemovePath(path: string) {
    setPaths(paths.filter((p) => p !== path))
  }

  function handleSavePaths() {
    onConfigSave(agent.id, paths)
    setEditingPaths(false)
  }

  function handleCancelEdit() {
    setPaths(agent.watch_paths)
    setEditingPaths(false)
    setNewPath('')
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white">{agent.hostname}</p>
          <p className="text-xs text-gray-500 font-mono">{agent.id}</p>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[agent.status]}`}
        >
          {agent.status}
        </span>
      </div>

      {/* Queue pressure */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Queue pressure</span>
          <span className="text-xs text-gray-300 tabular-nums">{pressurePct}%</span>
        </div>
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              pressurePct > 80
                ? 'bg-red-500'
                : pressurePct > 50
                ? 'bg-yellow-500'
                : 'bg-green-500'
            }`}
            style={{ width: `${pressurePct}%` }}
          />
        </div>
      </div>

      {/* Last seen */}
      <p className="text-xs text-gray-500">
        Visto {formatLastSeen(agent.last_seen)}
        {agent.ruleset_version_applied != null && (
          <span className="ml-2">· ruleset v{agent.ruleset_version_applied}</span>
        )}
      </p>

      {/* Watch paths */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Watch paths</span>
          {!editingPaths && (
            <button
              onClick={() => setEditingPaths(true)}
              disabled={isDraining}
              title={isDraining ? 'El agente está en modo draining' : undefined}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Editar
            </button>
          )}
        </div>

        {editingPaths ? (
          <div className="space-y-2">
            <ul className="space-y-1">
              {paths.map((p) => (
                <li key={p} className="flex items-center gap-2">
                  <span className="flex-1 text-xs font-mono text-gray-300 truncate">{p}</span>
                  <button
                    onClick={() => handleRemovePath(p)}
                    className="text-xs text-red-400 hover:text-red-300 shrink-0"
                  >
                    Quitar
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input
                type="text"
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddPath()}
                placeholder="/ruta/nueva"
                className="flex-1 px-2 py-1 text-xs bg-gray-900 border border-gray-600 rounded text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={handleAddPath}
                className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded"
              >
                Agregar
              </button>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleSavePaths}
                disabled={isSavingConfig}
                className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-40"
              >
                {isSavingConfig ? 'Guardando...' : 'Guardar paths'}
              </button>
              <button
                onClick={handleCancelEdit}
                className="px-3 py-1 text-xs text-gray-400 hover:text-gray-200"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {agent.watch_paths.length === 0 ? (
              <li className="text-xs text-gray-600 italic">Sin paths configurados</li>
            ) : (
              agent.watch_paths.map((p) => (
                <li key={p} className="text-xs font-mono text-gray-400 truncate">
                  {p}
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onRescan(agent.id)}
          disabled={isDraining || isRescanning}
          title={isDraining ? 'El agente está en modo draining' : undefined}
          className="flex-1 px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded border border-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isRescanning ? 'Rescaneando...' : 'Rescan'}
        </button>
      </div>
    </div>
  )
}
