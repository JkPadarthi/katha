import React, { useEffect, useState } from 'react'
import { Button, IconButton } from '../ui/Button.jsx'
import ThemePicker from './ThemePicker.jsx'

// The quiet top strip: brand, theme picker, settings, focus (desktop only), an
// "Install app" button when the browser offers one, and the version.
export default function TitleBar({ focus, onToggleFocus, onOpenSettings, theme, onChooseTheme }) {
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
        <span className="text-[10px] text-accent">●</span>
        <span className="text-[11px] font-medium tracking-wide text-mute">Katha</span>
      </div>

      <div className="flex items-center gap-1.5">
        <ThemePicker theme={theme} onChoose={onChooseTheme} />
        <button
          onClick={onToggleFocus}
          className="hidden rounded-md border hairline px-2 py-0.5 text-[10.5px] text-mute hover:text-ink md:block"
          title={focus ? 'Exit focus mode (Ctrl+Shift+F)' : 'Focus mode (Ctrl+Shift+F)'}
        >
          {focus ? 'exit focus' : 'focus'}
        </button>
        <IconButton onClick={onOpenSettings} title="Settings">⚙</IconButton>
        {installEvt && (
          <Button variant="accent" size="sm" onClick={install} title="Install Katha as an app">
            Install app
          </Button>
        )}
        <span className="select-none text-[11px] text-mute/70">v{__APP_VERSION__}</span>
      </div>
    </div>
  )
}
