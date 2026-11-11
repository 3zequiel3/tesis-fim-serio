import { useState, type FormEvent } from 'react'
import { inputClassName } from '@/components/ui/Field'

interface PaginationProps {
  currentPage: number
  totalPages: number
  onPageChange: (page: number) => void
}

// US-26: ventana de números centrada en la página actual, acotada a
// [1, totalPages]. Tope de 7 botones numerados para no desbordar la UI con
// miles de páginas.
const WINDOW_SIZE = 7

function computePageWindow(current: number, total: number): number[] {
  if (total <= WINDOW_SIZE) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }
  const half = Math.floor(WINDOW_SIZE / 2)
  let start = Math.max(1, current - half)
  const end = Math.min(total, start + WINDOW_SIZE - 1)
  start = Math.max(1, end - WINDOW_SIZE + 1)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
}

export function Pagination({ currentPage, totalPages, onPageChange }: PaginationProps) {
  const [goToPageInput, setGoToPageInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  function handleGoToPage(e: FormEvent) {
    e.preventDefault()
    const parsed = Number(goToPageInput)
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > totalPages) {
      setError(`Ingresá un número de página entre 1 y ${totalPages}`)
      return
    }
    setError(null)
    setGoToPageInput('')
    onPageChange(parsed)
  }

  const pageNumbers = computePageWindow(currentPage, totalPages)
  const buttonClass =
    'rounded-control border border-line-strong bg-surface-raised px-3 py-1.5 text-text hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <div className="flex flex-wrap items-center gap-2 text-text">
      <button
        type="button"
        onClick={() => onPageChange(1)}
        disabled={currentPage <= 1}
        className={buttonClass}
      >
        Primera
      </button>
      <button
        type="button"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
        className={buttonClass}
      >
        Anterior
      </button>

      {pageNumbers.map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onPageChange(n)}
          aria-current={n === currentPage ? 'page' : undefined}
          className={`${buttonClass} tabular-nums ${
            n === currentPage ? '!border-accent !bg-accent !text-on-accent' : ''
          }`}
        >
          {n}
        </button>
      ))}

      <button
        type="button"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
        className={buttonClass}
      >
        Siguiente
      </button>
      <button
        type="button"
        onClick={() => onPageChange(totalPages)}
        disabled={currentPage >= totalPages}
        className={buttonClass}
      >
        Última
      </button>

      {/*
        noValidate: sin esto, el input `min/max` dispara la validación
        nativa del navegador ANTES de que nuestro onSubmit corra, y un valor
        fuera de rango nunca llega a `handleGoToPage` — el mensaje de error
        propio (con el rango exacto) nunca se muestra.
      */}
      <form onSubmit={handleGoToPage} noValidate className="flex items-center gap-1.5">
        <label htmlFor="go-to-page-input" className="text-xs text-text-muted">
          Ir a página
        </label>
        <input
          id="go-to-page-input"
          type="number"
          min={1}
          max={totalPages}
          value={goToPageInput}
          onChange={(e) => setGoToPageInput(e.target.value)}
          className={`${inputClassName} !w-20 !py-1`}
        />
        <button type="submit" className={buttonClass}>
          Ir
        </button>
      </form>

      {error && (
        <span role="alert" className="text-xs text-danger-fg">
          {error}
        </span>
      )}
    </div>
  )
}
