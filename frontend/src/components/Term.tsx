import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { GLOSSARY } from '../glossary'

// In-place glossary term (UI_COPY_SPEC §7): a button that opens the definition, use, reading and limits.
// Mouse, touch, Enter／Space open it; Esc closes and returns focus. Never put it inside a link. The dialog is portalled
// to <body>, so a term in a table header or badge does not pass its nowrap, alignment or font to the definition.
export function Term({ id, children }: { id: string; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const term = GLOSSARY.find((item) => item.term_id === id)
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])
  if (!term) return <span>{children ?? id}</span>
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="term-button"
        data-term={id}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {children ?? term.name}
      </button>
      {open && createPortal(
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
          <section className="glossary-modal" role="dialog" aria-modal="true" aria-label={term.name} onMouseDown={(event) => event.stopPropagation()}>
            <div className="position-head"><strong>{term.name}</strong><button type="button" className="secondary-button" onClick={() => { setOpen(false); buttonRef.current?.focus() }}>關閉</button></div>
            <p><b>白話定義：</b>{term.plain_definition.replaceAll('外陸資', '外資')}</p>
            <p><b>用途：</b>{term.use}</p>
            <p><b>如何解讀：</b>{term.how_to_read}</p>
            <p><b>限制：</b>{term.limitations}</p>
          </section>
        </div>,
        document.body,
      )}
    </>
  )
}
