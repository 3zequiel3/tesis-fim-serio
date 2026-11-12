/**
 * Un estado del sistema escrito como lo lee una persona, con su valor
 * canónico al lado.
 *
 * Mismo criterio que `StatusBadge` (D93/RN-187): el nombre es para leer, el
 * valor canónico es para reconocer, y ninguno reemplaza al otro. RN-71 rige
 * la persistencia, las APIs, los streams, los logs y la documentación
 * técnica — no la etiqueta de una celda.
 *
 * El separador es un nodo de texto suelto a propósito. El algoritmo de
 * nombre accesible recorta cada hijo que es un elemento pero concatena los
 * nodos de texto tal cual, así que un espacio dentro del `<span>` se pierde
 * y el nombre queda pegado («Entregadadelivered»).
 */
export function CanonicalLabel({
  name,
  value,
  className = '',
}: {
  /** El nombre legible. Si es `undefined`, se muestra sólo el valor crudo. */
  name: string | undefined
  /** El valor canónico tal como viaja por la API. */
  value: string
  className?: string
}) {
  if (name === undefined) return <span className={className}>{value}</span>
  return (
    <span className={className}>
      {name}
      {' '}
      <span className="font-mono text-[0.6875rem] font-normal opacity-70">{value}</span>
    </span>
  )
}
