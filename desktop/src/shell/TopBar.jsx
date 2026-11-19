import React, { useEffect, useState } from 'react'
import Icon from '../ui/Icon.jsx'
import Popover, { MenuItem, MenuLabel, MenuDivider } from '../ui/Popover.jsx'
import RitualsCard from '../components/RitualsCard.jsx'
import { signOut } from '../lib/api.js'
import { THEMES, oppositeOf } from '../lib/useTheme.js'
import { MEASURES } from '../lib/useMeasure.js'

// THE TOP BAR (4.0, D63). The rail and the title bar are gone: where you are is one
// breadcrumb ("Harbour / 01 · The Debt"), and it opens the book — chapters, bible,
// rituals, every book action. Everything else is ⌘K or the menu on the right.

const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform) ? '⌘K' : 'Ctrl K'

const chapterNo = (id) => (id === 'ch-00' ? '0' : (id || '').replace(/^ch-?/, ''))

function BookMenu({ archive, series, book, chapter, onClose, a, stats }) {
  const [books, setBooks] = useState(false)
  const run = (fn) => () => { onClose(); fn() }
  const all = archive.flatMap((s) => (s.books || []).map((b) => ({ s, b })))
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5">
        <button
          onClick={() => setBooks((v) => !v)}
          aria-expanded={books}
          className="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-left hover:bg-panel-2"
        >
          <Icon name="book" className="text-mute" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12px] text-mute">{series?.title || series?.name}</span>
            <span className="block truncate text-[14.5px] font-medium text-ink">{book?.title}</span>
          </span>
          <span className="text-[12px] text-mute">{books ? 'Close' : all.length > 1 ? 'Switch' : 'New book'}</span>
        </button>
        {books && (
          <div className="mb-1 ml-3 border-l hairline pl-2">
            {all.map(({ s, b }) => (
              <MenuItem
                key={`${s.name}/${b.id}`}
                active={b.id === book?.id && s.name === series?.name}
                onClick={run(() => a.selectBook(s.name, b.id))}
                hint={s.title || s.name}
              >
                {b.title}
              </MenuItem>
            ))}
            <MenuItem icon={<Icon name="plus" size={16} className="text-mute" />} onClick={run(a.newBook)}>New book or series</MenuItem>
          </div>
        )}

        <MenuLabel>Chapters</MenuLabel>
        <ul>
          {(book?.chapters || []).map((c) => (
            <li key={c.id} className="group flex items-center">
              <button
                onClick={run(() => a.jump(c.id))}
                aria-current={c.id === chapter?.id ? 'page' : undefined}
                className={
                  'flex min-h-10 min-w-0 flex-1 items-center gap-3 rounded-lg px-3 text-left text-[14px] max-md:min-h-12 ' +
                  (c.id === chapter?.id ? 'bg-accent/10 text-ink' : 'text-ink hover:bg-panel-2')
                }
              >
                <span className={'w-6 shrink-0 text-right tabular-nums ' + (c.id === chapter?.id ? 'text-accent' : 'text-mute')}>
                  {chapterNo(c.id)}
                </span>
                <span className="min-w-0 flex-1 truncate">{c.title || 'Untitled'}</span>
                <span className="shrink-0 text-[12px] text-mute">{c.words} w</span>
              </button>
              <button
                onClick={run(() => a.deleteChapter(c))}
                aria-label={`Delete ${c.title || c.id}`}
                title="Delete — moves it to the trash"
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-mute opacity-0 hover:bg-err/10 hover:text-err focus:opacity-100 group-hover:opacity-100 max-md:opacity-60"
              >
                <Icon name="trash" size={16} />
              </button>
            </li>
          ))}
        </ul>
        <MenuItem icon={<Icon name="plus" size={16} className="text-accent" />} onClick={run(() => a.newChapter('chapter'))}>
          New chapter
        </MenuItem>
        {book && !book.chapters.some((c) => c.id === 'ch-00') && (
          <MenuItem icon={<Icon name="plus" size={16} className="text-mute" />} onClick={run(() => a.newChapter('prologue'))}>
            Prologue <span className="text-mute">— chapter 0</span>
          </MenuItem>
        )}

        <MenuDivider />
        <MenuItem icon={<Icon name="read" size={16} className="text-mute" />} onClick={run(() => a.openBible(''))}
                  hint={`${book?.bible?.length || 0} files`}>
          Bible
        </MenuItem>
        <MenuItem icon={<Icon name="flag" size={16} className="text-mute" />} onClick={run(a.sweep)}>Canon sweep</MenuItem>
        <MenuItem icon={<Icon name="pen" size={16} className="text-mute" />} onClick={run(a.editBook)}>Title, author & cover</MenuItem>
        <MenuItem icon={<Icon name="download" size={16} className="text-mute" />} onClick={run(a.exportEpub)}>Export EPUB</MenuItem>
        <MenuItem icon={<Icon name="trash" size={16} />} danger onClick={run(a.deleteBook)}>Delete this book</MenuItem>
      </div>
      {stats && (
        <div className="shrink-0 border-t hairline">
          <RitualsCard stats={stats} />
        </div>
      )}
    </div>
  )
}

function AppMenu({ onClose, a, theme, focus }) {
  const [installEvt, setInstallEvt] = useState(() => window.__kathaInstall || null)
  const run = (fn) => () => { onClose(); fn() }
  const other = THEMES.find((t) => t.id === oppositeOf(theme))
  useEffect(() => {
    const onPrompt = (e) => { e.preventDefault(); window.__kathaInstall = e; setInstallEvt(e) }
    window.addEventListener('beforeinstallprompt', onPrompt)
    return () => window.removeEventListener('beforeinstallprompt', onPrompt)
  }, [])
  return (
    <div className="p-1.5">
      <MenuItem
        icon={<Icon name={other.scheme === 'dark' ? 'moon' : 'sun'} size={16} className="text-mute" />}
        onClick={() => a.chooseTheme(other.id)}
      >
        {other.scheme === 'dark' ? 'Dark mode' : 'Light mode'}
      </MenuItem>
      <div className="flex items-center gap-3 px-3 py-1.5">
        <span className="flex-1 text-[14px] text-ink">Page width</span>
        <div role="group" aria-label="Page width" className="flex rounded-lg border hairline p-0.5">
          {MEASURES.map((m) => (
            <button
              key={m.id}
              onClick={() => a.setMeasure(m.id)}
              aria-pressed={a.measure === m.id}
              className={
                'h-8 rounded-md px-2.5 text-[12.5px] transition-colors ' +
                (a.measure === m.id ? 'bg-accent/12 font-medium text-accent' : 'text-mute hover:text-ink')
              }
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <MenuItem icon={<Icon name="focus" size={16} className="text-mute" />} onClick={run(a.toggleFocus)} hint="Ctrl ⇧ F">
        {focus ? 'Leave focus mode' : 'Focus mode'}
      </MenuItem>
      <MenuDivider />
      <MenuItem icon={<Icon name="settings" size={16} className="text-mute" />} onClick={run(a.settings)}>Settings</MenuItem>
      <MenuItem icon={<Icon name="key" size={16} className="text-mute" />} onClick={run(a.security)}>Muse & security</MenuItem>
      {installEvt && (
        <MenuItem
          icon={<Icon name="download" size={16} className="text-mute" />}
          onClick={run(async () => { installEvt.prompt(); await installEvt.userChoice; window.__kathaInstall = null; setInstallEvt(null) })}
        >
          Install Katha as an app
        </MenuItem>
      )}
      <MenuItem icon={<Icon name="lock" size={16} className="text-mute" />} onClick={run(signOut)}>Lock</MenuItem>
      <div className="px-3 pb-1 pt-2 text-[12px] text-mute">Katha v{__APP_VERSION__}</div>
    </div>
  )
}

export default function TopBar({ archive, series, book, chapter, stats, theme, focus, a }) {
  const [open, setOpen] = useState(null)   // 'book' | 'app' | null
  const close = () => setOpen(null)
  const s = archive?.find((x) => x.name === series?.series)

  return (
    <header
      className="relative z-40 flex min-h-14 shrink-0 items-center gap-1 px-2 md:gap-2 md:px-4"
      style={{ paddingTop: 'env(safe-area-inset-top)' }}
    >
      <img src="/logo.svg" alt="Katha" width="28" height="28" className="ml-1 h-7 w-7 rounded-[7px] max-md:hidden" />

      <div className="relative min-w-0">
        <button
          data-popover-anchor
          onClick={() => (book ? setOpen(open === 'book' ? null : 'book') : a.newBook())}
          aria-expanded={open === 'book'}
          aria-haspopup="dialog"
          className="flex h-10 min-w-0 max-w-full items-center gap-2 rounded-lg px-2.5 text-[14.5px] hover:bg-panel-2"
          title="Chapters, bible and the book"
        >
          {book && <span className="truncate text-mute max-md:hidden">{book.title}</span>}
          {book && <span className="text-mute/60 max-md:hidden" aria-hidden="true">/</span>}
          <span className="truncate font-medium text-ink">
            {chapter ? `${chapterNo(chapter.id)} · ${chapter.title || 'Untitled'}` : book ? book.title : 'Katha'}
          </span>
          <Icon name="chevronDown" size={16} className="text-mute" />
        </button>
        {archive && (
          <Popover open={open === 'book'} onClose={close} width={360} label="The book">
            <BookMenu archive={archive} series={s} book={book} chapter={chapter} onClose={close} a={a} stats={stats} />
          </Popover>
        )}
      </div>

      <div className="flex-1" />

      {stats && (
        <span className="mr-1 text-[13px] text-mute max-md:hidden" title={`${stats.streak}-day streak`}>
          {stats.today} / {stats.goal} today
        </span>
      )}

      <button
        onClick={a.palette}
        className="flex h-10 items-center gap-2.5 rounded-lg text-[13.5px] text-mute hover:text-ink max-md:w-10 max-md:justify-center md:min-w-[250px] md:border md:hairline md:bg-panel md:px-3"
        aria-label="Search, jump, or run a command"
        title={`Search, jump, or run a command (${MOD})`}
      >
        <Icon name="search" size={17} />
        <span className="flex-1 text-left max-md:hidden">Search or run a command</span>
        <kbd className="font-sans text-[12px] max-md:hidden">{MOD}</kbd>
      </button>

      <div className="relative">
        <button
          data-popover-anchor
          onClick={() => setOpen(open === 'app' ? null : 'app')}
          aria-expanded={open === 'app'}
          aria-label="Menu"
          title="Theme, settings, lock"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-mute hover:bg-panel-2 hover:text-ink"
        >
          <Icon name="more" size={20} />
        </button>
        <Popover open={open === 'app'} onClose={close} align="right" width={320} label="Menu">
          <AppMenu onClose={close} a={a} theme={theme} focus={focus} />
        </Popover>
      </div>
    </header>
  )
}
