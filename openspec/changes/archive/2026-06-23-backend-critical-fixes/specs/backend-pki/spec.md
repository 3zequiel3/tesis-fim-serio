## MODIFIED Requirements

### Requirement: mTLS listener on port 8443

El backend SHALL exponer un listener adicional en el puerto 8443 configurado con `ssl_cert_reqs=CERT_REQUIRED` y `ssl_ca_certs` apuntando al `ca.pem` de la CA propia. Este listener MUST servir las mismas rutas de la app FastAPI pero requiriendo client certificate en todas las conexiones.

El listener mTLS MUST ejecutarse sobre el event loop principal de la aplicación como una task de lifespan gestionada, NO sobre un thread secundario (C10). En concreto:
- `start_mtls_server(...)` SHALL construir el `uvicorn.Server` con `config.install_signal_handlers = False` y retornar el server configurado (o `None` cuando los certificados no están disponibles), sin lanzar ningún `threading.Thread` ni llamar `asyncio.run`.
- El lifespan de `main.py` SHALL arrancar el server mediante `asyncio.create_task(mtls_server.serve())`, registrando la task junto a las demás tasks de lifespan (`consumer_task`, `heartbeat_task`, `retention_task_handle`), y SHALL cancelarla en shutdown incluyéndola en el `asyncio.gather(..., return_exceptions=True)` existente.

De esta forma el puerto 8443 arranca de forma confiable; el bug previo (llamar `signal.signal()` desde un non-main thread, que lanzaba `ValueError` y dejaba el server silenciosamente caído) queda eliminado. Un fallo de arranque del listener MUST ser visible en los logs en lugar de quedar silenciado.

#### Scenario: Conexión mTLS exitosa
- **WHEN** un agente con certificado válido emitido por la CA se conecta al puerto 8443
- **THEN** el handshake mTLS completa y la solicitud HTTP llega al handler de FastAPI

#### Scenario: Conexión sin certificado rechazada
- **WHEN** un cliente intenta conectar al puerto 8443 sin presentar certificado de cliente
- **THEN** el handshake TLS falla con `SSL_ERROR_NO_CERTIFICATE`

#### Scenario: El listener 8443 arranca como task de lifespan en el loop principal
- **WHEN** el backend completa su startup con certificados disponibles
- **THEN** el puerto 8443 queda escuchando
- **AND** el servidor mTLS corre como una `asyncio` task sobre el event loop principal (sin thread secundario)
- **AND** no se lanza `ValueError` por `signal.signal()` en un non-main thread

#### Scenario: El listener 8443 se cancela limpiamente en shutdown
- **WHEN** el backend recibe la señal de shutdown
- **THEN** la task del servidor mTLS se cancela junto a las demás tasks de lifespan
- **AND** el shutdown completa sin excepciones no controladas (gather con `return_exceptions=True`)

#### Scenario: Fallo de arranque del listener es visible
- **WHEN** el servidor mTLS no puede arrancar (por ejemplo, el puerto 8443 ya está en uso)
- **THEN** el error queda registrado en los logs
- **AND** el fallo no se silencia
