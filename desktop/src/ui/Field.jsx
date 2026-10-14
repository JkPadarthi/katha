import React from 'react'

const INPUT =
  'w-full rounded-md border hairline bg-base px-2.5 py-1.5 text-[12.5px] text-ink ' +
  'placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-accent/50'

export function TextInput({ className = '', ...props }) {
  return <input {...props} className={INPUT + ' ' + className} />
}

export function TextArea({ className = '', ...props }) {
  return <textarea {...props} className={INPUT + ' resize-none ' + className} />
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-[11px] text-mute">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-[10px] text-mute/60">{hint}</span>}
    </label>
  )
}
