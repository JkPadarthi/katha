import React from 'react'

// Buttons (4.0). Sizes are touch-sized on purpose: `sm` is the dense in-panel size,
// `md` the default, `lg` what a phone's primary action uses.
const SIZES = {
  sm: 'h-8 px-2.5 text-[12.5px] gap-1.5',
  md: 'h-9 px-3 text-[13.5px] gap-2',
  lg: 'h-11 px-4 text-[15px] gap-2'
}

const VARIANTS = {
  primary: 'bg-accent text-onaccent font-medium hover:brightness-110',
  accent: 'bg-accent/10 text-accent font-medium hover:bg-accent/15',
  ghost: 'border hairline bg-panel text-ink hover:bg-panel-2',
  quiet: 'text-mute hover:bg-panel-2 hover:text-ink',
  danger: 'border border-err/40 text-err hover:bg-err/10'
}

export function Button({ variant = 'ghost', size = 'md', className = '', ...props }) {
  return (
    <button
      {...props}
      className={
        'inline-flex shrink-0 items-center justify-center rounded-lg transition-colors disabled:cursor-default disabled:opacity-40 ' +
        (SIZES[size] || SIZES.md) + ' ' + (VARIANTS[variant] || VARIANTS.ghost) + ' ' + className
      }
    />
  )
}

// A square icon-only button. Always pass `aria-label` (and usually `title`).
export function IconButton({ className = '', size = 'md', ...props }) {
  const box = size === 'sm' ? 'h-8 w-8' : size === 'lg' ? 'h-11 w-11' : 'h-9 w-9'
  return (
    <button
      {...props}
      className={
        'inline-flex shrink-0 items-center justify-center rounded-lg text-mute transition-colors hover:bg-panel-2 hover:text-ink disabled:opacity-40 ' +
        box + ' ' + className
      }
    />
  )
}
