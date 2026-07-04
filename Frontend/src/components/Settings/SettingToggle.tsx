// quick-task 260704-w88: reusable boolean toggle bound to /api/settings/{key}
// (0.0 off / 1.0 on), mirroring SettingSlider.tsx's fetch-on-mount /
// PUT-on-change pattern. Native <input type="checkbox" role="switch"> keeps
// the dependency surface at zero new packages per CLAUDE.md (same rationale
// SettingSlider uses for its native <input type="range">).

import { useCallback, useEffect, useState } from 'react'
import { getSetting, putSetting, SettingsApiError } from '@/api/settings'

interface Props {
  settingKey: string
  label: string
  description: string
}

export function SettingToggle({ settingKey, label, description }: Props) {
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
      const next = e.target.checked ? 1.0 : 0.0
      setValue(next)
      void persist(next)
    },
    [persist],
  )

  const toggleId = `setting-toggle-${settingKey}`
  const checked = value >= 0.5

  return (
    <section
      data-testid={`setting-toggle-panel-${settingKey}`}
      className="flex flex-col gap-2 p-3 border border-white/[0.08] rounded-md"
    >
      <div className="flex items-baseline justify-between">
        <label htmlFor={toggleId} className="text-sm font-semibold">
          {label}
        </label>
        <input
          id={toggleId}
          data-testid={toggleId}
          type="checkbox"
          role="switch"
          checked={checked}
          onChange={handleChange}
          disabled={!loaded}
        />
      </div>
      <p className="text-xs text-muted-foreground">{description}</p>
      {error && (
        <p
          data-testid={`setting-toggle-error-${settingKey}`}
          className="text-xs text-red-400"
        >
          {error}
        </p>
      )}
    </section>
  )
}
