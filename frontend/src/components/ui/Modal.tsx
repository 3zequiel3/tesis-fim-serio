import { X } from 'lucide-react'
import { useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useDialogBehavior } from '@/hooks/useDialogBehavior'

interface ModalProps {
  title: string
  onClose: () => void
  /** A mutation is in flight: Escape, outside click and the close button are ignored. */
  busy?: boolean
  children: ReactNode
  /** Tailwind max-width class of the panel. */
  widthClassName?: string
}

// Single accessible dialog (design D-3): role="dialog", aria-modal, labelled
// by its title, first control focused, focus trapped and returned to the
// opener, the rest of the document `inert`. Closing is blocked while `busy`.
export function Modal({ title, onClose, busy = false, children, widthClassName = 'max-w-lg' }: ModalProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const portalRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const state = useDialogBehavior({ panelRef, portalRef, initialFocusRef: bodyRef, onClose, busy })

  return createPortal(
    <div ref={portalRef} className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div
        className="absolute inset-0 bg-black/60"
        aria-hidden="true"
        onClick={() => {
          if (!state.current.busy) state.current.onClose()
        }}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`animate-enter relative flex max-h-[90vh] w-full flex-col overflow-y-auto rounded-t-modal border border-line bg-surface-raised shadow-modal focus:outline-none sm:rounded-modal ${widthClassName}`}
      >
        <div className="border-b border-line px-5 py-4 pr-14">
          <h2 id={titleId} className="text-lg font-semibold text-text">
            {title}
          </h2>
        </div>
        <div ref={bodyRef} className="px-5 py-4">
          {children}
        </div>
        {/* Last in DOM order so the first Tab stop is the first control of the content. */}
        <button
          type="button"
          aria-label="Cerrar"
          disabled={busy}
          onClick={onClose}
          className="absolute right-3 top-3 rounded-control p-1 text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40"
        >
          <X aria-hidden="true" size={18} />
        </button>
      </div>
    </div>,
    document.body,
  )
}
