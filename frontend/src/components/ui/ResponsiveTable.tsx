import type { ReactNode } from 'react'
import { useMediaQuery } from '@/hooks/useMediaQuery'

export interface Column<T> {
  key: string
  header: string
  cell: (row: T) => ReactNode
  /** Classes for the cell (table) — e.g. width or alignment. */
  className?: string
  /** In card mode this column is the card title, rendered without its label. */
  primary?: boolean
  /** Header rendered visually hidden (e.g. a checkbox or action column). */
  hideHeader?: boolean
}

interface ResponsiveTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  getRowKey: (row: T) => string | number
  /** Accessible name of the table / list. */
  caption: string
  /** Extra classes for a row (severity band, selection). */
  rowClassName?: (row: T) => string
  /** Per-row data-testid. */
  rowTestId?: (row: T) => string | undefined
}

// One column definition, two renderings (design D-3): a real table from 640 px
// (Tailwind `sm`), a list of cards below it. Mounting only one keeps the DOM
// free of duplicates for assistive tech and tests.
export function ResponsiveTable<T>({
  columns,
  rows,
  getRowKey,
  caption,
  rowClassName,
  rowTestId,
}: ResponsiveTableProps<T>) {
  const isTable = useMediaQuery('(min-width: 640px)')

  if (isTable) {
    return (
      <div className="overflow-x-auto rounded-panel border border-line bg-surface-raised">
        <table className="w-full border-collapse text-left">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-line bg-surface">
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className="sticky top-0 whitespace-nowrap px-3 py-2 text-xs font-semibold text-text-muted"
                >
                  {c.hideHeader ? <span className="sr-only">{c.header}</span> : c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={getRowKey(row)}
                data-testid={rowTestId?.(row)}
                className={`border-b border-line last:border-b-0 hover:bg-surface-hover ${rowClassName?.(row) ?? ''}`}
              >
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-2 align-top ${c.className ?? ''}`}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const primary = columns.find((c) => c.primary)
  const rest = columns.filter((c) => c !== primary)
  return (
    <ul aria-label={caption} className="space-y-3">
      {rows.map((row) => (
        <li
          key={getRowKey(row)}
          data-testid={rowTestId?.(row)}
          className={`rounded-panel border border-line bg-surface-raised p-3 ${rowClassName?.(row) ?? ''}`}
        >
          {primary && <div className="mb-2 min-w-0">{primary.cell(row)}</div>}
          <dl className="space-y-1.5">
            {rest.map((c) => (
              <div key={c.key} className="flex min-w-0 items-baseline gap-3">
                {!c.hideHeader && <dt className="w-24 shrink-0 text-xs text-text-muted">{c.header}</dt>}
                <dd className="min-w-0 flex-1">{c.cell(row)}</dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ul>
  )
}
