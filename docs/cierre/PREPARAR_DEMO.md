# Preparar la demo — laboratorio local

Acompaña a [GUION_DEMO.md](GUION_DEMO.md). Este archivo es la parte operativa: cómo dejar
el laboratorio en el estado inicial de la demo y cómo volver a ese estado después de cada
ensayo.

Topología: **agente en Docker** (perfil `lab`), vigilando `/watch`, que es un bind mount de
`./fim-watch` del repositorio. No es la instalación nativa con systemd.

---

## El comando de Compose

Todos los comandos de abajo usan el mismo juego de archivos. Conviene dejarlo en una
variable de la terminal:

```bash
cd ~/Facultad/tesis/tesis-fim-serio
alias dc='docker compose \
  -f docker-compose.yml \
  -f docker-compose.tls.yml \
  -f ~/fim-lab/docker-compose.mailpit.yml \
  -f ~/fim-lab/docker-compose.agent-tls.yml \
  --profile app --profile lab'
```

`~/fim-lab/docker-compose.agent-tls.yml` es obligatorio. Sin él el agente no publica nada:
`docker-compose.tls.yml` define `FIM_VALKEY_URL` para el servicio `agent`, pero el agente
**no lee esa variable** — sólo lee `/etc/fim-agent/config.yaml` (`agent/config.py:108`).
Con el overlay TLS activo, Valkey deja de escuchar en 6379 y el agente se queda mudo.

---

## Estado inicial de la demo

### Archivos vigilados

| Archivo | Contenido inicial |
|---|---|
| `fim-watch/revision/sshd_config` | `PermitRootLogin no` / `PasswordAuthentication no` / `Port 22` |
| `fim-watch/revision/app.conf` | `DB_HOST=db.interno` / `DB_PORT=5432` / `POOL=10` |
| `fim-watch/restaurar/hosts` | `127.0.0.1 localhost` / `10.0.0.5 backend.interno` |

El cambio de la escena 1 es `PermitRootLogin no` → `yes`: se lee de un vistazo y el jurado
entiende por qué importa sin explicación.

### Reglas

| id | Patrón | Severidad | Acción |
|---|---|---|---|
| 3 | `/watch/revision/*` | `high` | `manual_review` |
| 4 | `/watch/restaurar/*` | `critical` | `auto_restore` |

Las reglas 1 y 2 apuntan a `/srv/fim-watch/*` (de la topología nativa) y no coinciden con
nada en este laboratorio. **Gana la primera regla que coincide**; el default es
`alert_only` (RN-06, `agent/rules.py:61-72`).

### Operadores

`demo_ux` y `demo_op2`, ambos con rol `admin`. Los dos hacen falta: la escena 2 necesita
dos sesiones distintas. **Son usuarios descartables de laboratorio; borralos cuando
termines.**

La contraseña no se escribe en este archivo: es un repositorio y esto es una tesis sobre
integridad. Exportala en la terminal antes de correr lo que sigue, y usá una que no uses
en ningún otro lado.

```bash
read -rs -p 'Contraseña del laboratorio: ' DEMO_PASSWORD; export DEMO_PASSWORD; echo
```

### Consola

- Desarrollo: `http://127.0.0.1:4173`
- Imagen Docker: `http://localhost`

---

## Arrancar

```bash
dc up -d                      # stack completo, agente incluido
dc ps                         # todo Up / healthy
```

Verificar que el agente esté publicando antes de grabar:

```bash
docker compose exec -T db psql -U fim -d fim -c \
  "select agent_id,status,ruleset_version_applied,queue_size from agents where agent_id='docker-agent';"
```

Tiene que decir `online`, con `ruleset_version_applied` distinto de 0 y `queue_size` en 0.
Si `ruleset_version_applied` es 0 o el agente no tiene reglas, ver «El agente no recibe las
reglas» más abajo.

---

## Volver al estado inicial después de un ensayo

Los cuatro pasos van en este orden. El tercero es el que se olvida y rompe el ensayo
siguiente.

```bash
cd ~/Facultad/tesis/tesis-fim-serio

# 1. Archivos al contenido original y fuera los sobrantes de la escena 4
printf 'PermitRootLogin no\nPasswordAuthentication no\nPort 22\n' > fim-watch/revision/sshd_config
printf 'DB_HOST=db.interno\nDB_PORT=5432\nPOOL=10\n'              > fim-watch/revision/app.conf
printf '127.0.0.1 localhost\n10.0.0.5 backend.interno\n'          > fim-watch/restaurar/hosts
rm -f fim-watch/revision/seq_*.conf

# 2. Esperar a que el agente registre esos cambios (si no, reaparecen después)
sleep 20

# 3. Borrar los eventos del ensayo — SOLO los de docker-agent
docker compose exec -T db psql -U fim -d fim -c "
  delete from alerts where event_id in (select id from events where agent_id='docker-agent');
  update events set parent_event_id = null where agent_id='docker-agent';
  delete from events where agent_id='docker-agent';"

# 4. Resincronizar la línea base con el contenido actual de los archivos
TOKEN=$(curl -fsS -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"demo_ux\",\"password\":\"$DEMO_PASSWORD\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS -X POST http://localhost:8000/agents/docker-agent/rescan \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"force":true,"paths":["/watch"]}'
```

**Por qué el paso 4 no es opcional.** Al aprobar un evento, la línea base pasa a ser el
contenido aprobado. Después de la escena 1 la línea base de `sshd_config` dice
`PermitRootLogin yes`. Si restaurás el archivo a `no` sin resincronizar, en el ensayo
siguiente el cambio a `yes` **coincide con la línea base y no genera ningún evento**: la
demo arranca sin nada que mostrar.

El filtro por `agent_id='docker-agent'` es a propósito: los 100 eventos `alert_only` de
`fim-vm` son de corridas anteriores y no hay que tocarlos.

### Comprobar que quedó listo

```bash
docker compose exec -T db psql -U fim -d fim -At -c \
  "select count(*) from events where agent_id='docker-agent';"     # tiene que dar 0
```

Y la prueba de humo, que conviene hacer una vez antes de grabar:

```bash
printf 'PermitRootLogin yes\nPasswordAuthentication no\nPort 22\n' > fim-watch/revision/sshd_config
sleep 10
docker compose exec -T db psql -U fim -d fim -c \
  "select id,path,status,severity from events where agent_id='docker-agent';"
# Esperado: exactamente 1 fila, pending, high
```

Después de la prueba de humo, repetir los cuatro pasos de limpieza.

---

## Antes de grabar

- [ ] `dc ps` — todo `Up` / `healthy`
- [ ] Agente `online` con reglas aplicadas
- [ ] Cero eventos de `docker-agent`
- [ ] Los tres archivos vigilados en su contenido inicial
- [ ] Sesión de `demo_ux` abierta en un navegador y la de `demo_op2` en otro perfil o
      ventana privada
- [ ] Decidir qué hacer con el agente fantasma (abajo)

---

## Problemas conocidos

### El dashboard dice «1 agente caído»

Es `fim-vm`, de una corrida anterior, en estado `dead`. Aparece en la frase de apertura del
dashboard y en el panel de Agentes.

No se puede borrar sin borrar también sus 100 eventos `alert_only`, que están referenciados
por clave foránea. **La decisión es tuya**: si esos eventos no te sirven para nada, esto los
elimina junto con el agente.

```bash
# DESTRUCTIVO: borra los 100 eventos alert_only de fim-vm y el agente
docker compose exec -T db psql -U fim -d fim -c "
  delete from alerts where event_id in (select id from events where agent_id='fim-vm');
  delete from events where agent_id='fim-vm';
  delete from baseline_entries where agent_id='fim-vm';
  delete from agents where agent_id='fim-vm';"
```

Si preferís no borrarlos, la alternativa es mencionarlo al pasar: «este agente es de una
prueba anterior, está dado de baja». Queda más honesto que que el jurado lo note solo.

### El agente no recibe las reglas

`rule_sync` se encola **por agente existente**. Si creaste o modificaste reglas antes de
registrar el agente, esos cambios nunca le llegaron y todo cae al default `alert_only`.

Solución: tocar cualquier regla después de registrar el agente, para forzar la
sincronización.

```bash
curl -fsS -X PUT http://localhost:8000/rules/3 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"pattern":"/watch/revision/*","severity":"high","action":"manual_review"}'
```

Verificar que llegaron:

```bash
docker run --rm -v tesis-fim-serio_agent_state:/s alpine cat /s/state.json
# "rules" tiene que traer las cuatro
```

### El agente arranca y tarda más de 15 minutos en publicar

Pasa cuando arranca **sin checkpoint** (`state.json` borrado o volumen nuevo). El stream
`commands` tenía 265.422 entradas acumuladas de corridas anteriores, y `agent_heartbeat`
255.204; el agente las reprocesa una por una, fallando la firma en cada una
(`publisher.command_signature_invalid`).

Recortar los dos streams antes de arrancar un agente nuevo:

```bash
VC="docker exec tesis-fim-serio-valkey-1 valkey-cli --tls -p 6380 \
  --cert /certs/valkey.pem --key /certs/valkey-key.pem --cacert /certs/ca.pem --no-auth-warning"
$VC xlen commands
$VC xtrim commands MAXLEN 1000          # DESTRUCTIVO: descarta el historial viejo
$VC xtrim agent_heartbeat MAXLEN 1000
```

El stream `events` ya se recorta solo (estaba en 400); estos dos no.

---

## Limpieza final

Cuando termines con la demo:

```bash
dc stop agent

docker compose exec -T db psql -U fim -d fim -c "
  delete from users where username in ('demo_ux','demo_op2');"

rm -rf fim-watch/revision fim-watch/restaurar
```

Las reglas 3 y 4 se borran desde la pantalla **Reglas** de la consola, o con
`DELETE /rules/3` y `DELETE /rules/4`.

El estado del agente anterior a este laboratorio quedó guardado dentro del volumen, en
`/var/lib/fim-agent/.pre-demo-backup-20261112/`, por si hiciera falta recuperarlo.
