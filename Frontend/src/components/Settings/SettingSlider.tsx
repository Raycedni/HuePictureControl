// quick-task 260704-iss: generalized version of BrightnessCutoffControl,
// parameterized by settingKey so it can render any /api/settings/{key}
// single-float slider (color_vibrancy, saturation_boost, ...). Same
// fetch-on-mount / PUT-on-change pattern; native <input type="range"> keeps
// the dependency surface at zero new packages per CLAUDE.md.

import { useCallback, useEffect, useState } from 'react'
import { getSetting, putSetting, SettingsApiError } from '@/api/settings'

const STEP = 0.01

interface Props {
  settingKey: string
  label: string
  description: string
  min?: number
  max?: number
}

export function SettingSlider({
  settingKey,
  label,
  description,
  min = 0.0,
  max = 1.0,
}: Props) {
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
        const r = await getSetting(settingKey)
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
  }, [settingKey])

  // Persist on every change. The backend is local + cheap; debounce would
  // add complexity for no measurable benefit at slider input rates.
  const persist = useCallback(
    async (next: number) => {
      setError(null)
      try {
        const r = await putSetting(settingKey, next)
        setValue(r.value)
      } catch (err) {
        setError(
          err instanceof SettingsApiError
            ? `Save failed (HTTP ${err.status})`
            : (err as Error).message,
        )
      }
    },
    [settingKey],
  )

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

  const sliderId = `setting-slider-${settingKey}`

  return (
    <section
      data-testid={`setting-panel-${settingKey}`}
      className="flex flex-col gap-2 p-3 border border-white/[0.08] rounded-md"
    >
      <div className="flex items-baseline justify-between">
        <label htmlFor={sliderId} className="text-sm font-semibold">
          {label}
        </label>
        <span
          data-testid={`setting-value-${settingKey}`}
          className="text-xs tabular-nums text-muted-foreground"
        >
          {value.toFixed(2)}
        </span>
      </div>
      <input
        id={sliderId}
        data-testid={`setting-slider-${settingKey}`}
        type="range"
        min={min}
        max={max}
        step={STEP}
        value={value}
        onChange={handleChange}
        disabled={!loaded}
      />
      <p className="text-xs text-muted-foreground">{description}</p>
      {error && (
        <p
          data-testid={`setting-error-${settingKey}`}
          className="text-xs text-red-400"
        >
          {error}
        </p>
      )}
    </section>
  )
}
