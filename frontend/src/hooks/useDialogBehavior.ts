import { useEffect, useRef, type RefObject } from 'react'

export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface DialogBehaviorOptions {
  /** The dialog panel (receives the focus trap). */
  panelRef: RefObject<HTMLElement | null>
  /** The wrapper that must stay interactive; everything else in <body> becomes inert. */
  portalRef: RefObject<HTMLElement | null>
  /** Preferred element for the initial focus (first control of the content). */
  initialFocusRef?: RefObject<HTMLElement | null>
  onClose: () => void
  /** A mutation is in flight: Escape is ignored. */
  busy?: boolean
}

/**
 * Shared behavior of every modal surface (Modal and the mobile menu drawer):
 * initial focus, focus trap, Escape, inert background and focus return to the
 * opener (design D-3). Latest props are read through a ref so a parent
 * re-render never re-runs the effect and steals the focus.
 */
export function useDialogBehavior({ panelRef, portalRef, initialFocusRef, onClose, busy = false }: DialogBehaviorOptions) {
  const stateRef = useRef({ onClose, busy })
  useEffect(() => {
    stateRef.current = { onClose, busy }
  })

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const portal = portalRef.current
    const first =
      initialFocusRef?.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR) ??
      panel?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    ;(first ?? panel)?.focus()

    const inerted: Element[] = []
    for (const el of Array.from(document.body.children)) {
      if (el === portal || (portal && el.contains(portal)) || el.hasAttribute('inert')) continue
      el.setAttribute('inert', '')
      inerted.push(el)
    }

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        if (!stateRef.current.busy) stateRef.current.onClose()
        return
      }
      if (e.key !== 'Tab' || !panel) return
      const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusables.length === 0) {
        e.preventDefault()
        return
      }
      const firstEl = focusables[0]
      const lastEl = focusables[focusables.length - 1]
      const active = document.activeElement
      if (e.shiftKey) {
        if (active === firstEl || active === panel) {
          e.preventDefault()
          lastEl.focus()
        }
      } else if (active === lastEl || !panel.contains(active)) {
        e.preventDefault()
        firstEl.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      inerted.forEach((el) => el.removeAttribute('inert'))
      opener?.focus()
    }
    // Refs are stable; the effect must run once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return stateRef
}
