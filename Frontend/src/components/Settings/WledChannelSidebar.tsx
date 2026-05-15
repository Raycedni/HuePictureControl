// Phase 19.1 Plan 07: WledChannelSidebar is now a READ-ONLY metadata panel.
//
// Phase 19 had editable name/start/end input fields plus a Delete button —
// all removed per D-07. The sidebar now resolves the selected segment from
// the cached `listSegments(deviceId)` response and displays its metadata
// (name via segmentName(seg), seg_index, range, length) in a read-only DL.
// Selection is owned by the parent (SettingsPanel / SettingsPage) via the
// `selectedSeg: {device_id, seg_index} | null` prop.

import { useEffect, useState } from 'react'
import { listSegments, WledApiError } from '@/api/wled'
import type { WledSegment } from '@/utils/wled-segment'
import { segmentName } from '@/utils/wled-segment'

interface Props {
  selectedSeg: { device_id: string; seg_index: number } | null
  onClear?: () => void
}

export function WledChannelSidebar({ selectedSeg, onClear }: Props) {
  const [seg, setSeg] = useState<WledSegment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selectedSeg) {
      setSeg(null)
      setError(null)
      setLoading(false)
      return
    }
    let alive = true
    setError(null)
    setLoading(true)
    listSegments(selectedSeg.device_id)
      .then((resp) => {
        if (!alive) return
        const found = resp.segments.find(
          (s) => s.seg_index === selectedSeg.seg_index,
        )
        if (!found) {
          setSeg(null)
          setError('Segment not found in cache.')
        } else {
          setSeg(found)
          setError(null)
        }
        setLoading(false)
      })
      .catch((err) => {
        if (!alive) return
        console.error('Failed to load segment detail:', err)
        const msg =
          err instanceof WledApiError
            ? `Failed to load segment (HTTP ${err.status}).`
            : 'Failed to load segment.'
        setError(msg)
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selectedSeg?.device_id, selectedSeg?.seg_index])

  if (!selectedSeg) {
    return (
      <div
        className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-xs text-muted-foreground"
        data-testid="wled-channel-sidebar-empty"
      >
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Selected segment
        </h3>
        Select a zone on the strip to view it.
      </div>
    )
  }

  if (error) {
    return (
      <div
        className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-xs text-red-400"
        data-testid="wled-channel-sidebar-error"
      >
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Selected segment
        </h3>
        {error}
      </div>
    )
  }

  if (loading || !seg) {
    return (
      <div
        className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-xs text-muted-foreground"
        data-testid="wled-channel-sidebar-loading"
      >
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Selected segment
        </h3>
        Loading…
      </div>
    )
  }

  const length = seg.stop_led - seg.start_led + 1
  return (
    <div
      className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 flex flex-col gap-2"
      data-testid="wled-channel-sidebar"
    >
      <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
        Selected segment
      </h3>
      <dl className="text-xs space-y-1">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Name</dt>
          <dd className="font-medium truncate" data-testid="sidebar-seg-name">
            {segmentName(seg)}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Index</dt>
          <dd className="font-mono" data-testid="sidebar-seg-index">
            {seg.seg_index}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Range</dt>
          <dd className="font-mono" data-testid="sidebar-seg-range">
            {seg.start_led}–{seg.stop_led}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Length</dt>
          <dd className="font-mono" data-testid="sidebar-seg-length">
            {length} LEDs
          </dd>
        </div>
      </dl>
      {onClear && (
        <button
          type="button"
          onClick={onClear}
          className="mt-1 text-[11px] text-muted-foreground hover:text-foreground self-start"
          data-testid="wled-channel-sidebar-clear"
        >
          Clear selection
        </button>
      )}
    </div>
  )
}
