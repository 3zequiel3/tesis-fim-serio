import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { bulkReject, type BulkRejectItem } from './actions'
import { installRequestCapture, type RequestCapture } from '@/test/captureRequest'

// Contrato de wire (capacidad api-contract-fixtures, D-5 del design de
// frontend-severity-triage): `bulkReject` se llama SIN mockear `@/api/client`
// — se captura el cuerpo que el cliente axios real emite, DESPUÉS de
// transformRequest, y se compara contra el fixture compartido con el
// backend. Ver contracts/README.md.
//
// Resuelto desde process.cwd(), nunca relativo a este archivo (7.13):
// `pnpm --dir frontend test` corre con cwd=frontend/, así que la raíz del
// repo es un nivel arriba. pytest, del otro lado, resuelve el mismo
// archivo desde su propio directorio de trabajo (backend/).
const FIXTURE_PATH = path.resolve(process.cwd(), '..', 'contracts', 'actions.bulk-reject.request.json')
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as {
  items: BulkRejectItem[]
}

let capture: RequestCapture | undefined

afterEach(() => {
  capture?.restore()
  capture = undefined
})

describe('bulkReject — contrato de wire contra contracts/actions.bulk-reject.request.json (7.6)', () => {
  it('el cuerpo serializado que emite el cliente real es igual al fixture', async () => {
    capture = installRequestCapture()

    await bulkReject(fixture.items)

    expect(capture.requests).toHaveLength(1)
    const config = capture.last()!
    expect(config.url).toBe('/actions/bulk-reject')

    // Comparación contra el cuerpo SERIALIZADO (JSON.parse(config.data)), no
    // contra el objeto de JavaScript que lo precede: el fixture es JSON
    // porque el backend lo lee con Python, y comparar contra el objeto
    // esconde justo la clase de diferencias que sólo aparecen al serializar.
    const body = JSON.parse(config.data as string)
    expect(body).toEqual(fixture)
  })

  it('la acción viaja dentro de cada ítem, y no hay `action` al nivel superior del cuerpo', async () => {
    capture = installRequestCapture()

    await bulkReject(fixture.items)

    const body = JSON.parse(capture.last()!.data as string)
    expect(body.action).toBeUndefined()
    for (const item of body.items) {
      expect(item.action).toBeDefined()
    }
  })

  // Caso negativo obligatorio (7.8): sin esto no hay evidencia de que la
  // aserción de arriba sepa distinguir las dos formas — una aserción que
  // nunca se vio fallar no es evidencia de nada.
  it('caso negativo: el cuerpo real NO es igual a la forma vieja (acción al nivel superior)', async () => {
    capture = installRequestCapture()

    await bulkReject(fixture.items)

    const body = JSON.parse(capture.last()!.data as string)
    const oldShapeBody = {
      items: (body.items as Array<{ event_id: number; version: number; action: string }>).map(
        ({ event_id, version }) => ({ event_id, version })
      ),
      action: body.items[0].action,
    }

    expect(body).not.toEqual(oldShapeBody)
  })
})
