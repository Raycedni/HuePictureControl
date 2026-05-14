import { useEffect, useState } from 'react'
import {
  listWledChannels,
  updateWledChannel,
  deleteWledChannel,
  type WledChannel,
  WledApiError,
} from '@/api/wled'

interface Props {
  selectedChannelId: string | null
  selectedDeviceId: string | null
  onChange: () => Promise<void> | void
  onClear: () => void
}

export function WledChannelSidebar({
  selectedChannelId,
  selectedDeviceId,
  onChange,
  onClear,
}: Props) {
  const [channel, setChannel] = useState<WledChannel | null>(null)
  const [nameDraft, setNameDraft] = useState('')
  const [startDraft, setStartDraft] = useState('')
  const [endDraft, setEndDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedChannelId || !selectedDeviceId) {
      setChannel(null)
      setError(null)
      return
    }
    let alive = true
    setError(null)
    listWledChannels(selectedDeviceId)
      .then((resp) => {
        if (!alive) return
        const found = resp.channels.find((c) => c.id === selectedChannelId)
        if (!found) {
          setChannel(null)
          return
        }
        setChannel(found)
        setNameDraft(found.name)
        setStartDraft(String(found.start_led))
        setEndDraft(String(found.end_led))
      })
      .catch((err) => {
        if (!alive) return
        console.error('Failed to load channel detail:', err)
        setError('Failed to load channel.')
      })
    return () => {
      alive = false
    }
  }, [selectedChannelId, selectedDeviceId])

  if (!selectedChannelId || !channel) {
    return (
      <div
        className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-xs text-muted-foreground"
        data-testid="wled-channel-sidebar-empty"
      >
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Selected channel
        </h3>
        Select a zone on the strip to edit it.
      </div>
    )
  }

  async function saveField(patch: Partial<{ name: string; start_led: number; end_led: number }>) {
    if (!selectedDeviceId || !channel) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateWledChannel(selectedDeviceId, channel.id, patch)
      setChannel(updated)
      await onChange()
    } catch (err) {
      const msg =
        err instanceof WledApiError
          ? `Save failed. HTTP ${err.status}`
          : 'Save failed.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  async function handleNameBlur() {
    if (channel && nameDraft !== channel.name && nameDraft.trim()) {
      await saveField({ name: nameDraft.trim() })
    }
  }

  async function handleStartBlur() {
    if (!channel) return
    const n = Number(startDraft)
    if (!Number.isFinite(n) || n < 0) {
      setStartDraft(String(channel.start_led))
      return
    }
    if (n !== channel.start_led) await saveField({ start_led: Math.floor(n) })
  }

  async function handleEndBlur() {
    if (!channel) return
    const n = Number(endDraft)
    if (!Number.isFinite(n) || n < 0) {
      setEndDraft(String(channel.end_led))
      return
    }
    if (n !== channel.end_led) await saveField({ end_led: Math.floor(n) })
  }

  async function handleDelete() {
    if (!selectedDeviceId || !channel) return
    setSaving(true)
    setError(null)
    try {
      await deleteWledChannel(selectedDeviceId, channel.id)
      setToast('Channel deleted.')
      onClear()
      await onChange()
      setTimeout(() => setToast(null), 3000)
    } catch (err) {
      const msg =
        err instanceof WledApiError
          ? `Delete failed. HTTP ${err.status}`
          : 'Delete failed.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 flex flex-col gap-2"
      data-testid="wled-channel-sidebar"
    >
      <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
        Selected channel
      </h3>

      <label className="flex flex-col gap-1 text-xs">
        <span className="sr-only">Channel name</span>
        <input
          type="text"
          aria-label="Channel name"
          placeholder="Channel N"
          value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          onBlur={handleNameBlur}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
          className="h-7 text-xs rounded-lg px-2.5"
          disabled={saving}
          data-testid="wled-channel-name-input"
        />
      </label>

      <div className="flex gap-2">
        <label className="flex flex-col gap-1 text-xs flex-1">
          <span className="sr-only">Start LED</span>
          <input
            type="number"
            aria-label="Start LED"
            placeholder="0"
            value={startDraft}
            onChange={(e) => setStartDraft(e.target.value)}
            onBlur={handleStartBlur}
            className="h-7 text-xs rounded-lg px-2.5 font-mono"
            disabled={saving}
            data-testid="wled-channel-start-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs flex-1">
          <span className="sr-only">End LED</span>
          <input
            type="number"
            aria-label="End LED"
            placeholder="0"
            value={endDraft}
            onChange={(e) => setEndDraft(e.target.value)}
            onBlur={handleEndBlur}
            className="h-7 text-xs rounded-lg px-2.5 font-mono"
            disabled={saving}
            data-testid="wled-channel-end-input"
          />
        </label>
      </div>

      <button
        type="button"
        onClick={handleDelete}
        disabled={saving}
        className="h-7 text-[11px] rounded-lg px-2.5 bg-destructive/10 text-red-400 hover:bg-destructive/20 border border-destructive/30 disabled:opacity-50"
        data-testid="wled-channel-delete-button"
      >
        Delete channel
      </button>

      {error && (
        <p className="text-[11px] text-red-400" data-testid="wled-channel-sidebar-error">
          {error}
        </p>
      )}
      {toast && (
        <p
          className="text-[11px] text-muted-foreground"
          data-testid="wled-channel-sidebar-toast"
        >
          {toast}
        </p>
      )}
    </div>
  )
}
