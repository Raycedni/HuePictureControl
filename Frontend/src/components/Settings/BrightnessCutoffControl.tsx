// quick-task 260516-kra: single slider for the global brightness-cutoff
// threshold. 0.00 = disabled (default; existing behavior unchanged). Above
// 0, lights whose region's mean Rec.709 luma falls below the threshold
// turn off (Hue sends bri=0; WLED writes (0,0,0) to those LEDs).
//
// Native <input type="range"> + a small numeric readout — keeps the
// dependency surface at zero new packages per CLAUDE.md. The Settings tab
// already mixes raw inputs with shadcn primitives in WledDevicesPanel, so
// this stays consistent with the surrounding visual language.

import { useCallback, useEffect, useState } from 'react'
import {
  getBrightnessCutoff,
  putBrightnessCutoff,
  SettingsApiError,
} from '@/api/settings'

const STEP = 0.01
const MIN = 0.0
const MAX = 1.0

export function BrightnessCutoffControl() {
  const [value, setValue] = useState<number>(0.0)
  const [loaded, setLoaded] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Load current value on mount. The cancelled flag protects against a
  // stale resolved fetch arriving after unmount (React strict-mode double
  // invoke + slow network).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await getBrightnessCutoff()
        if (!cancelled) {
          setValue(r.value)
          setLoaded(true)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof SettingsApiError
              ? `Load failed (HTTP ${err.status})`
              : (err as Error).message,
          )
          setLoaded(true)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Persist on every change. The backend is local + cheap; debounce would
  // add complexity for no measurable benefit at slider input rates.
  const persist = useCallback(async (next: number) => {
    setError(null)
    try {
      const r = await putBrightnessCutoff(next)
      setValue(r.value)
    } catch (err) {
      setError(
        err instanceof SettingsApiError
          ? `Save failed (HTTP ${err.status})`
          : (err as Error).message,
      )
    }
  }, [])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = Number(e.target.value)
      if (Number.isFinite(next)) {
        setValue(next)
        void persist(next)
      }
    },
    [persist],
  )

  return (
    <section
      data-testid="brightness-cutoff-control"
      className="flex flex-col gap-2 p-3 border border-white/[0.08] rounded-md"
    >
      <div className="flex items-baseline justify-between">
        <label
          htmlFor="brightness-cutoff-slider"
          className="text-sm font-semibold"
        >
          Brightness cutoff (0 = off)
        </label>
        <span
          data-testid="brightness-cutoff-value"
          className="text-xs tabular-nums text-muted-foreground"
        >
          {value.toFixed(2)}
        </span>
      </div>
      <input
        id="brightness-cutoff-slider"
        data-testid="brightness-cutoff-slider"
        type="range"
        min={MIN}
        max={MAX}
        step={STEP}
        value={value}
        onChange={handleChange}
        disabled={!loaded}
      />
      <p className="text-xs text-muted-foreground">
        Lights below this brightness will turn off.
      </p>
      {error && (
        <p
          data-testid="brightness-cutoff-error"
          className="text-xs text-red-400"
        >
          {error}
        </p>
      )}
    </section>
  )
}
