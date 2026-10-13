import React, { useEffect, useState } from 'react'

// The quiet top strip. In the PWA there are no OS window controls — the
// browser (or the installed app's own chrome) draws those. So this is the
// brand mark, the version, and an "Install app" button when the browser
// offers one (beforeinstallprompt).
export default function TitleBar({ focus, onToggleFocus, onOpenSettings }) {
  const [installEvt, setInstallEvt] = useState(null)

  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault()
      setInstallEvt(e)
    }
    window.addEventListener('beforeinstallprompt', onPrompt)
    return () => window.removeEventListener('beforeinstallprompt', onPrompt)
  }, [])

  const install = async () => {
    if (!installEvt) return
    installEvt.prompt()
    await installEvt.userChoice
    setInstallEvt(null)
  }

  return (
    <div className="flex h-9 shrink-0 items-center justify-between border-b hairline bg-base px-3">
      <div className="flex items-center gap-2">
        <span className="text-gold text-[10px]">●</span>
        <span className="text-[11px] font-medium tracking-wide text-mute">Katha</span>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onOpenSettings}
          className="rounded-md border hairline px-2 py-0.5 text-[10.5px] text-mute hover:text-ink"
          title="Settings"
        >
          ⚙
        </button>
        <button
          onClick={onToggleFocus}
          className="rounded-md border hairline px-2 py-0.5 text-[10.5px] text-mute hover:text-ink"
          title={focus ? 'Exit focus mode (Ctrl+Shift+F)' : 'Focus mode (Ctrl+Shift+F)'}
        >
          {focus ? 'exit focus' : 'focus'}
        </button>
        {installEvt && (
          <button
            onClick={install}
            className="rounded-md border border-gold/40 px-2 py-0.5 text-[10.5px] font-medium text-gold hover:bg-gold/10"
            title="Install Katha as an app"
          >
            Install app
          </button>
        )}
        <span className="text-[11px] text-mute/70 select-none">v{__APP_VERSION__}</span>
      </div>
    </div>
  )
}
