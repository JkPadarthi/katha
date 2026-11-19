import React from 'react'

const SIZES = {
  sm: 'px-2 py-0.5 text-[10.5px]',
  md: 'px-2.5 py-1 text-[11px]'
}

const VARIANTS = {
  primary: 'bg-accent text-onaccent font-semibold hover:brightness-110',
  accent: 'border border-accent/40 text-accent hover:bg-accent/10',
  ghost: 'border hairline text-mute hover:text-ink'
}

export function Button({ variant = 'ghost', size = 'md', className = '', ...props }) {
  return (
    <button
      {...props}
      className={
        'rounded-md transition-colors disabled:cursor-default disabled:opacity-40 ' +
        (SIZES[size] || SIZES.md) + ' ' + (VARIANTS[variant] || VARIANTS.ghost) + ' ' + className
      }
    />
  )
}

// A square, icon-only button for dense chrome (title bar, panel corners).
export function IconButton({ className = '', ...props }) {
  return (
    <button
      {...props}
      className={
        'flex h-6 items-center justify-center rounded px-1.5 text-mute hover:bg-panel-2 hover:text-ink ' +
        className
      }
    />
  )
}
