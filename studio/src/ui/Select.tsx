// #7 Select: a native `<select>` — the four Board filters and the Playbook picker. `options` is
// the plain list; `roster` is the Settings people list, shown as "Name (@handle)" so a reviewer
// reads a person, not a handle. `onChange` yields the value, not the event. Unlike Input it is
// NOT full-width by default: a select's natural width is its longest option, and four of them
// on a wrapping filter row each took a whole line when they inherited `w-full` (observatory v2
// critique, shot 8). Pass `className="w-full"` where a form wants it to fill.
import { forwardRef, useId, type ForwardedRef } from 'react'
import type { ControlSize, SelectProps } from './contract'
import { cn } from './cn'
import { useFieldControl } from './Field'
import { INPUT_BASE } from './Input'
import { DisabledReason, disabledReasonProps } from './VisuallyHidden'

const SIZE: Record<ControlSize, string> = {
  sm: 'h-7 px-2.5 text-xs',
  md: 'h-8 px-3 text-sm',
}

// The native chevron breaks the type, so it is replaced by an inline `data:` SVG (allowed by the
// CSP's `img-src 'self' data:`). Light stroke is ink-3 (#6B625A), dark is the dark ink-3
// (#A69D94). `color-scheme` already follows the theme for the popup list.
const CHEVRON =
  'appearance-none pr-7 bg-no-repeat bg-[right_8px_center] bg-[length:12px_12px] ' +
  'bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 12 12\'%3E%3Cpath d=\'M3 4.5l3 3 3-3\' fill=\'none\' stroke=\'%236B625A\' stroke-width=\'1.5\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/svg%3E")] ' +
  'dark:bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 12 12\'%3E%3Cpath d=\'M3 4.5l3 3 3-3\' fill=\'none\' stroke=\'%23A69D94\' stroke-width=\'1.5\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/svg%3E")]'

function SelectInner<V extends string>(
  { size = 'md', value, onChange, options, roster, invalid, disabled, disabledReason, className, id, required, ...rest }: SelectProps<V>,
  ref: ForwardedRef<HTMLSelectElement>,
) {
  // A disabled select is DESCRIBED by its reason (aria-describedby → the hidden sibling), joined
  // with whatever the Field already describes it with; the title keeps the pointer's tooltip.
  const reasonId = useId()
  const reasonDescribes = disabled && disabledReason ? reasonId : undefined
  const ownDescribedBy = [rest['aria-describedby'], reasonDescribes].filter(Boolean).join(' ') || undefined
  const field = useFieldControl({ id, required, 'aria-describedby': ownDescribedBy, 'aria-invalid': invalid })
  return (
    <>
      <select
        ref={ref}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value as V)}
        {...disabledReasonProps(disabledReason, disabled)}
        className={cn(INPUT_BASE, 'w-auto', SIZE[size], CHEVRON, className)}
        {...rest}
        {...field}
      >
        {options?.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
        {roster?.map((p) => (
          <option key={p.handle} value={p.handle}>
            {p.name} ({p.handle})
          </option>
        ))}
      </select>
      <DisabledReason reason={disabledReason} disabled={disabled} id={reasonId} />
    </>
  )
}

export const Select = forwardRef(SelectInner) as <V extends string = string>(
  props: SelectProps<V> & { ref?: ForwardedRef<HTMLSelectElement> },
) => ReturnType<typeof SelectInner>
