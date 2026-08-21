import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { getEvents } from './events'
import { installRequestCapture, type RequestCapture } from '@/test/captureRequest'

// Contrato de wire (capacidad api-contract-fixtures, D-6 del design de
// frontend-severity-triage): la query de severidad cruza la misma frontera
// que acababa de fallar en el bulk-reject, y un array repetible en una
// query string serializa de varias formas plausibles de las que sólo una
// es la que el backend acepta (`{severity:['critical','high']}` podría
// salir comma-joined o con notación de corchetes). Este archivo va separado
// de `events.test.ts` (que mockea `@/api/client` a nivel de módulo) porque
// el adaptador de captura necesita el cliente REAL.
const FIXTURE_PATH = path.resolve(process.cwd(), '..', 'contracts', 'events.list-severity.request.json')
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as { severity: string[] }

let capture: RequestCapture | undefined

afterEach(() => {
  capture?.restore()
  capture = undefined
})

describe('getEvents — contrato de wire de severidad contra contracts/events.list-severity.request.json (7.7)', () => {
  it('emite un parámetro `severity` repetido por valor, no comma-joined ni bracket notation', async () => {
    capture = installRequestCapture()

    await getEvents({ status: ['pending'], severity: fixture.severity })

    const config = capture.last()!
    expect(config.url).toBe('/events')

    // El cliente axios real normaliza un `paramsSerializer` en forma de
    // función a `{serialize: fn}` antes de llegar al adaptador (Axios.js) —
    // a diferencia del mock de módulo de `events.test.ts`, que expone la
    // función literal porque nunca pasa por el Axios real.
    const rawSerializer = config.paramsSerializer as unknown
    const serializer =
      typeof rawSerializer === 'function'
        ? (rawSerializer as (p: unknown) => string)
        : (rawSerializer as { serialize: (p: unknown) => string }).serialize
    const qs = serializer(config.params)
    const sp = new URLSearchParams(qs)

    expect(sp.getAll('severity')).toEqual(fixture.severity)
    // Ninguna forma alternativa de serializar el array debería colarse.
    expect(qs).not.toContain('severity[]')
    expect(qs).not.toContain(fixture.severity.join(','))
  })
})
