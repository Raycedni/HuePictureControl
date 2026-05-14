import type { WledOrientation } from '@/api/wled'

interface Props {
  value: WledOrientation
  onChange: (next: WledOrientation) => void
  disabled?: boolean
}

interface Option {
  value: WledOrientation
  label: string
}

const OPTIONS: Option[] = [
  { value: 'auto', label: 'auto' },
  { value: 'horizontal-LTR', label: '→' },
  { value: 'horizontal-RTL', label: '←' },
  { value: 'vertical-TTB', label: '↓' },
  { value: 'vertical-BTT', label: '↑' },
]

export function OrientationSegmentedControl({ value, onChange, disabled }: Props) {
  return (
    <div
      className="flex gap-0.5 bg-black/30 border border-white/[0.08] rounded p-0.5"
      data-testid="orientation-segmented-control"
    >
      {OPTIONS.map((opt) => {
        const isActive = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            disabled={disabled}
            aria-pressed={isActive}
            aria-label={`Orientation ${opt.label}`}
            onClick={() => {
              if (!isActive && !disabled) onChange(opt.value)
            }}
            className={
              'flex-1 py-1 rounded font-mono text-[11px] leading-none transition-colors disabled:opacity-50 ' +
              (isActive
                ? 'text-[var(--accent)] bg-[var(--accent-bg)] shadow-[inset_0_0_0_1px_var(--accent-border)]'
                : 'text-white/55 hover:text-foreground hover:bg-white/[0.04] bg-transparent')
            }
            data-testid={`orientation-btn-${opt.value}`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
