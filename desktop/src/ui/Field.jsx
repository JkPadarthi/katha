import React from 'react'

const INPUT =
  'w-full rounded-lg border hairline bg-base px-3 py-2 text-[14px] text-ink ' +
  'placeholder:text-mute/60 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20'

export const TextInput = React.forwardRef(function TextInput({ className = '', ...props }, ref) {
  return <input ref={ref} {...props} className={INPUT + ' ' + className} />
})

export function TextArea({ className = '', ...props }) {
  return <textarea {...props} className={INPUT + ' resize-none ' + className} />
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium text-ink">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1.5 block text-[12px] leading-snug text-mute">{hint}</span>}
    </label>
  )
}
