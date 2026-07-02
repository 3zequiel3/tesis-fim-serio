import { useEffect, useRef, type ReactNode } from 'react'

interface ModalDialogProps {
  /** id del elemento (h2) que titula el diálogo, para aria-labelledby */
  labelledBy: string
  onClose: () => void
  children: ReactNode
  /** Clases del panel (tamaño/spacing); el overlay y el posicionamiento los pone el wrapper */
  panelClassName?: string
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Wrapper accesible para modales (C38): role="dialog", aria-modal,
 * cierre con Esc, focus trap con Tab/Shift+Tab y restauración del foco
 * al elemento que abrió el modal. No altera la lógica del contenido.
 */
export function ModalDialog({ labelledBy, onClose, children, panelClassName }: ModalDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  // Ref para leer siempre el onClose más reciente sin re-ejecutar el efecto
  // (re-montarlo robaría el foco en cada render del padre).
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    panelRef.current?.focus()

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab') return

      const panel = panelRef.current
      if (!panel) return
      const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusables.length === 0) {
        e.preventDefault()
        return
      }
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement

      if (e.shiftKey) {
        if (active === first || active === panel) {
          e.preventDefault()
          last.focus()
        }
      } else if (active === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previouslyFocused?.focus()
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={() => onCloseRef.current()} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={`relative bg-gray-800 border border-gray-700 rounded-lg shadow-xl focus:outline-none ${panelClassName ?? ''}`}
      >
        {children}
      </div>
    </div>
  )
}
