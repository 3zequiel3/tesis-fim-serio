## MODIFIED Requirements

### Requirement: AlertsBanner con conteo de alertas fallidas

El sistema SHALL tener `frontend/src/components/layout/AlertsBanner.tsx` que consulta `GET /alerts/failed/count` cada 30 s para conocer cuántas alertas de la DLQ están en fallo terminal (`delivered_at IS NULL AND failed_at IS NOT NULL`, US-29, US-05, RN-102, D6) — **sin** umbral de `retry_count`: una alerta agotada con `retry_count = 0` (n8n sin configurar) cuenta igual que una con `retry_count = 3`. La query MUST usar la key `['alerts', 'failed', 'count']`, para que las invalidaciones de reintento y descarte la refresquen. Si `count > 0`, MUST mostrar un banner amarillo con el texto "Notificaciones pendientes: N alertas no pudieron ser enviadas" (en singular, "1 alerta no pudo ser enviada") y un enlace a la vista de alertas fallidas `/alerts/failed`. El banner MUST desaparecer automáticamente cuando el conteo vuelve a 0.

#### Scenario: DLQ con alertas agotadas muestra banner amarillo
- **WHEN** `GET /alerts/failed/count` retorna `count = 4`
- **THEN** aparece un banner amarillo con el texto "Notificaciones pendientes: 4 alertas no pudieron ser enviadas"

#### Scenario: Singular con una sola alerta
- **WHEN** `GET /alerts/failed/count` retorna `count = 1`
- **THEN** el banner dice "Notificaciones pendientes: 1 alerta no pudo ser enviada"

#### Scenario: Alerta con retry_count = 0 igual muestra el banner
- **WHEN** la DLQ sólo contiene una alerta en fallo terminal con `retry_count = 0` (n8n sin configurar) y `GET /alerts/failed/count` retorna `count = 1`
- **THEN** se muestra el banner amarillo

#### Scenario: DLQ vacía — sin banner amarillo
- **WHEN** `GET /alerts/failed/count` retorna `count = 0`
- **THEN** no se muestra el banner amarillo

#### Scenario: El enlace abre la vista de alertas fallidas
- **WHEN** el banner está visible
- **THEN** contiene un enlace con `href="/alerts/failed"`

#### Scenario: Banner desaparece tras resolver alertas
- **WHEN** todas las alertas fallidas son reintentadas exitosamente y el siguiente fetch retorna `count = 0`
- **THEN** el banner amarillo desaparece sin recargar la página
