#!/usr/bin/env bash
# Unified evaluation run on the candidate named by TAG (required, e.g. TAG=v5.0-tesis).
#
# Everything the thesis reports comes from this single candidate, so that the
# hardest question at a defence — "which version am I looking at?" — has a
# one-line answer. The backend image is rebuilt from the tag and its provenance
# verified by hashing the container's tree against the working tree, because a
# previous package was produced against an image built four days before its
# declared candidate and nothing in the logs showed it.
#
# The notification chain ends in a local SMTP sink (Mailpit). Gmail was verified
# to authenticate and deliver and stays as proof that the external channel works;
# a thousand notifications through an external provider are neither feasible nor
# measurable, since its rate limiting would be indistinguishable from the
# system's own latency.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
LAB=/home/ezequiel/fim-lab
# The candidate is a parameter with NO default: a code change invalidates the
# frozen candidate and forces a new tag, and a harness that hardcodes one tag
# silently measures the wrong tree (L-13).
TAG="${TAG:?ABORTA: TAG is required (e.g. TAG=v5.0-tesis)}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
# v5.0-tesis -> v5-eval-<ts>, the naming of the earlier packages (v2-eval-...).
OUT=$REPO/tesis/cierre/evidencia/${TAG%%.*}-eval-$TS
RES=$LAB/corrida_unificada.out
CERTS=$LAB/suites_certs
COMPOSE_FILES=(docker-compose.yml docker-compose.tls.yml "$LAB/docker-compose.mailpit.yml")
DC=(docker compose)
for f in "${COMPOSE_FILES[@]}"; do DC+=(-f "$f"); done
cd "$REPO" || exit 1
# shellcheck source=lib_arnes.sh
source "$LAB/lib_arnes.sh"
# L-13: provenance guard BEFORE anything is built or written. Aborts unless HEAD is
# the tag's commit and agent/backend/frontend/n8n are clean; writes env/procedencia.txt
# with tag= and commit=. The tag must therefore be CHECKED OUT in $REPO.
procedencia_exigir "$TAG" "$OUT/env" || exit 1
mkdir -p "$OUT"/{env,suites,latencia,control,notificacion,resiliencia,diagnostico,invalidos}
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }
mp() { curl -s "http://127.0.0.1:8025/api/v1/$1" 2>/dev/null; }
mp_count() { mp messages | python3 -c 'import json,sys; print(json.load(sys.stdin)["messages_count"])' 2>/dev/null || echo 0; }

say "=== corrida unificada — candidato $TAG commit=$COMMIT ==="

# ── procedencia ───────────────────────────────────────────────────────────────
# HEAD is the tag (checked by procedencia_exigir), so the working tree IS the tag:
# the old `git checkout $TAG -- .` is gone, it only masked a HEAD on another commit.
say "reconstruyendo el backend desde el tag"
"${DC[@]}" build -q backend >/dev/null 2>&1
# ── registro de migraciones (D84/RN-178) ─────────────────────────────────────
# Runs BEFORE the backend starts: the backend refuses to start against a registry
# that is behind its EXPECTED_SCHEMA_VERSION, so bringing it up first would leave
# it restarting in a loop and the provenance check below could not `exec` into it.
# See the "esquema" section below for why the registry alone is not enough.
"${DC[@]}" up -d --wait db >/dev/null 2>&1 \
  || { say "ABORTA: la base no levanto"; exit 1; }
MIGRAR=(python3 scripts/migrar.py -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.mailpit.yml")
MIG_OUT=$("${MIGRAR[@]}" 2>&1) \
  || { say "ABORTA: migrar.py no pudo aplicar las migraciones pendientes: $MIG_OUT"; exit 1; }
MIG_OUT=$("${MIGRAR[@]}" --verificar 2>&1) \
  || { say "ABORTA: el registro schema_migrations no llega a la version esperada: $MIG_OUT"; exit 1; }
# Bring up the SMTP sink alongside the backend. The harness used to assume it
# was already running from an earlier manual start: a run once measured the
# notification batteries with no sink at all, reported zero deliveries in all
# three scenarios, and nothing failed — the backend kept retrying against a
# hostname that resolved to nothing.
"${DC[@]}" --profile app up -d --force-recreate backend mailpit >/dev/null 2>&1
sleep 25
CONT=$("${DC[@]}" exec -T backend sh -c 'cd /app && find app -name "*.py" -exec sha256sum {} \;' | sort -k2 | sha256sum | cut -d' ' -f1)
ARBOL=$(fd -e py . backend/app -x sha256sum | sd 'backend/app/' 'app/' | sort -k2 | sha256sum | cut -d' ' -f1)
{
  echo "candidate_tag=$TAG"
  echo "candidate_commit=$(git rev-list -1 "$TAG")"
  echo "candidate_tree=$(git rev-parse "$TAG^{tree}")"
  echo "git_status_clean=$(git status --porcelain | wc -l | sed 's/^0$/yes/;s/^[1-9].*/no/')"
  echo "backend_tree_container=$CONT"
  echo "backend_tree_worktree=$ARBOL"
  echo "provenance_match=$([ "$CONT" = "$ARBOL" ] && echo yes || echo NO)"
  echo "agent_tree_matches=$(git diff --quiet "$TAG" -- agent/ && echo yes || echo no)"
  echo "notification_sink=mailpit (canal SMTP real, local)"
  echo "gmail_verified=yes (autenticacion y entrega comprobadas por separado)"
} >> "$OUT/env/procedencia.txt"
cat "$OUT/env/procedencia.txt" | tee -a "$RES"
[ "$CONT" = "$ARBOL" ] || { say "ABORTADO: la procedencia no coincide"; exit 1; }

# ── el esquema tiene que coincidir con el modelo ──────────────────────────────
# A candidate whose model carried a new column once ran against a table that did
# not have it: every INSERT on `alerts` failed and the notification batteries
# reported zero deliveries. The dangerous part is what it did to the other number
# — with no alerts created, the notification lane did no work at all and the
# ingest drain looked FASTER than the previous candidate. A defect that improves
# the headline figure is the one that gets published.
#
# Two independent checks (D84/RN-178). The `schema_migrations` registry proves
# WHICH scripts ran: `migrar.py` applies the pending ones and `--verificar` proves
# the registry reaches the candidate's tree. The column comparison below proves
# that the model HAS a script for every column: the registry cannot know about a
# column nobody wrote a migration for. This harness never runs `--marcar-hasta`:
# registering automatically would hide the very drift the guard exists to show.
# The registry part of the check ran earlier, before the backend started (see
# "registro de migraciones" above); only the column comparison runs here.
say "verificando que el modelo no declare columnas sin migracion"
FALTANTES=$("${DC[@]}" exec -T backend python - <<'PY' 2>/dev/null | tr -d '\r'
# Compara los campos que el modelo declara contra las columnas que la tabla
# tiene. No alcanza con correr las migraciones: hay que verificar el resultado.
import os, psycopg
from sqlmodel import SQLModel
import app.modules.alerts.models, app.modules.events.models, app.modules.agents.models  # noqa: F401
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
faltan = []
with psycopg.connect(url) as cn, cn.cursor() as cur:
    for tabla, modelo in SQLModel.metadata.tables.items():
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (tabla,),
        )
        reales = {r[0] for r in cur.fetchall()}
        if not reales:
            continue
        for col in modelo.columns:
            if col.name not in reales:
                faltan.append(f"{tabla}.{col.name}")
print(",".join(sorted(faltan)))
PY
)
[ -z "$FALTANTES" ] \
  && say "esquema al dia: toda columna del modelo existe en la base" \
  || { say "ABORTA: la base no tiene estas columnas del modelo: $FALTANTES"; exit 1; }

# ── el sumidero de notificación tiene que existir ─────────────────────────────
# Both channels failing is indistinguishable from a chain that is merely slow:
# the batteries report zero deliveries either way. Prove the sink answers before
# measuring anything that depends on it.
say "verificando el sumidero de notificacion"
"${DC[@]}" exec -T backend python -c "import socket; socket.gethostbyname('fim-mailpit')" >/dev/null 2>&1 \
  || { say "ABORTA: el backend no resuelve fim-mailpit"; exit 1; }
preflight_sumidero || { say "ABORTA: la API de mailpit no responde en /api/v1/info (8025)"; exit 1; }
say "sumidero operativo: mailpit resuelve y su API responde"

# ── convergencia de reloj antes de medir latencia ─────────────────────────────
# The latency battery subtracts a timestamp stamped by the agent on the guest
# from one stamped by the backend on the host, so the two clocks must agree to
# far better than the tens of milliseconds being measured.
#
# Do NOT try to measure the offset with `multipass exec ... date`: its round
# trip is ~300 ms and asymmetric, so it reports a skew of ~150 ms that does not
# exist. Both machines discipline themselves by NTP — the host to under a
# millisecond, the guest with jitter of about one — and the honest check is that
# each says it is synchronized, plus a settling wait.
#
# The symptom this prevents: a run produced 23 negative latencies, all of them
# inside the first 83 seconds of a 1796-second window and none afterwards. That
# is a clock converging, and waiting costs less than discarding the samples.
# `NTPSynchronized=yes` NO alcanza y no debe usarse como guarda. Una corrida
# entera midió con las dos máquinas declarándose sincronizadas y el reloj del
# huésped corrido decenas de milisegundos: systemd-timesyncd sondea hasta cada
# 34 minutos y corrige despacio, de modo que "sincronizado" convive con un error
# mayor que la magnitud medida. El resultado fueron 347 muestras negativas sobre
# 484, es decir latencias imposibles. Se exige chrony en las dos máquinas y se
# compara su desvío informado, en microsegundos, contra un techo explícito.
say "verificando el desvio de reloj de las dos maquinas"
# Se invoca con el comando completo como argumentos, no con un prefijo en una
# cadena: la división en palabras de una expansión sin comillas depende del
# shell y no es la misma en bash que en zsh.
desvio_us() {
  local salida
  salida=$("$@" 2>/dev/null | rg -N -o 'System time *: *[0-9.]+' | rg -N -o '[0-9.]+' | head -1)
  [ -n "$salida" ] || { echo ""; return; }
  "$LAB/.venv/bin/python" -c "print(int(float('$salida')*1_000_000))"
}
HOST_US=$(desvio_us chronyc tracking)
VM_US=$(desvio_us multipass exec fim-host -- chronyc tracking)
[ -n "$HOST_US" ] || { say "ABORTA: chronyc no responde en el anfitrion"; exit 1; }
[ -n "$VM_US" ] || { say "ABORTA: chronyc no responde en el huesped (instalar chrony)"; exit 1; }
if [ "$HOST_US" -gt "${CLOCK_MAX_US:-5000}" ] || [ "$VM_US" -gt "${CLOCK_MAX_US:-5000}" ]; then
  say "ABORTA: desvio de reloj excesivo — anfitrion ${HOST_US} us, huesped ${VM_US} us (techo ${CLOCK_MAX_US:-5000} us)"
  exit 1
fi
say "desvio de reloj: anfitrion ${HOST_US} us, huesped ${VM_US} us"
{
  echo "host_clock_offset_us=$HOST_US"
  echo "vm_clock_offset_us=$VM_US"
  echo "clock_max_us=${CLOCK_MAX_US:-5000}"
  echo "host_chrony=$(chronyc tracking 2>/dev/null | rg -N 'System time|RMS offset' | tr '\n' ' ')"
  echo "vm_chrony=$(multipass exec fim-host -- chronyc tracking 2>/dev/null | tr -d '\r' | rg -N 'System time|RMS offset' | tr '\n' ' ')"
} >> "$OUT/env/procedencia.txt"
say "relojes sincronizados; esperando ${CLOCK_SETTLE_S:-120}s de asentamiento antes de medir latencia"
sleep "${CLOCK_SETTLE_S:-120}"

# ── guardas de preflight (L-14) ───────────────────────────────────────────────
# Schema registry (re-checked: the candidate tree may have moved since the early
# migrar.py run), ingest limit == product defaults unless RATE_LIMIT_VARIANT is
# declared, and Valkey with AOF on. The clock and the sink were proven above and the
# baseline purge is checked by every reset (reset_lab). The observed values are
# recorded next to the provenance.
say "preflight: esquema, limite de ingesta, AOF"
preflight_esquema || { say "ABORTA: preflight del esquema"; exit 1; }
preflight_rate_limit || { say "ABORTA: el limite de ingesta no es el del producto"; exit 1; }
preflight_aof || { say "ABORTA: Valkey sin AOF (ver pasos de migracion arriba)"; exit 1; }
{
  echo "preflight=ok"
  echo "rate_limit=$RATE_LIMIT_OBSERVED variant=${RATE_LIMIT_VARIANT:-none}"
  echo "valkey_appendonly=yes"
} > "$OUT/env/preflight.txt"
say "preflight ok ($RATE_LIMIT_OBSERVED, appendonly=yes)"

say "capturando el entorno"
{ uname -a; echo "--- monitoreado:"; multipass exec fim-host -- uname -a; } > "$OUT/env/uname.txt" 2>&1
{ findmnt -no FSTYPE,SOURCE -T "$REPO" 2>/dev/null; echo "--- monitoreado /srv/fim-watch:"; multipass exec fim-host -- sudo findmnt -no FSTYPE,SOURCE -T /srv/fim-watch; } > "$OUT/env/fs.txt" 2>&1
{ docker --version; docker compose version; "${DC[@]}" exec -T backend python --version;
  "${DC[@]}" exec -T db psql --version; "${DC[@]}" exec -T n8n n8n --version 2>/dev/null | tail -1;
  multipass exec fim-host -- /usr/bin/python3.13 --version; } > "$OUT/env/versions.txt" 2>&1
docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}}' > "$OUT/env/images.txt" 2>&1
mkdir -p "$OUT/env/config"
for f in docker-compose.yml docker-compose.tls.yml; do cp "$f" "$OUT/env/config/"; done
cp "$LAB/docker-compose.mailpit.yml" "$OUT/env/config/" 2>/dev/null
multipass exec fim-host -- sudo cat /etc/fim-agent/config.yaml > "$OUT/env/config/agente.yaml" 2>&1
# The batteries run with the product's defaults (D85/RN-179); D38/RN-132 still requires
# declaring the effective limit next to every result.
"${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S RATE_LIMIT_INGEST_BURST > "$OUT/env/rate_limit_nominal.txt" 2>&1
# The removed variables are ignored by the backend; record whether the environment still sets them.
{ for v in RATE_LIMIT_INGEST_EVENTS RATE_LIMIT_INGEST_WINDOW_SECONDS; do
    val=$("${DC[@]}" exec -T backend printenv "$v" 2>/dev/null | tr -d '\r')
    echo "$v=${val:-<unset>}"
  done; } >> "$OUT/env/rate_limit_nominal.txt"

# ── helpers en la VM ──────────────────────────────────────────────────────────
# Transfer them on every run. They live in /tmp on the guest, and /tmp does not
# survive a reboot: the guest rebooted once between two runs and every later
# `sh /tmp/vm_reset.sh` would have failed silently, because those calls redirect
# stderr to /dev/null. A reset that does nothing looks exactly like a reset that
# worked.
say "transfiriendo los helpers a la VM"
for s in "$LAB"/vm_*.sh; do multipass transfer "$s" "fim-host:/tmp/$(basename "$s")" 2>/dev/null; done
for req in vm_reset.sh vm_trace_on.sh vm_trace_off.sh vm_trace_range.sh; do
  multipass exec fim-host -- test -f "/tmp/$req" \
    || { say "ABORTA: /tmp/$req no llego a la VM"; exit 1; }
done

# ── trazas del agente, activas para TODAS las baterías ────────────────────────
say "activando las trazas causales del agente"
multipass exec fim-host -- sudo sh /tmp/vm_trace_on.sh >/dev/null 2>&1
multipass exec fim-host -- sudo systemctl is-active fim-agent | tee -a "$RES"
# Assert the drop-in actually took effect. A previous package shipped three
# byte-identical "per-run" traces because tracing was off and the harness kept
# copying the same stale cumulative file without ever checking. Fail loudly.
TRACE_ENV=$(multipass exec fim-host -- sudo systemctl show fim-agent -p Environment 2>/dev/null | tr -d '\r')
case "$TRACE_ENV" in
  *FIM_EXPERIMENT_TRACE_FILE*) say "trazas activas: $TRACE_ENV" ;;
  *) say "ABORTA: las trazas no quedaron activas (Environment='$TRACE_ENV')"; exit 1 ;;
esac

# Measurement protocol (D85/RN-179, D-9): every measurement starts with the ingest token
# bucket of the VM's agent_id full. The bucket lives in the backend's memory, so the
# backend container is recreated at the END of reset_lab, after the database, the agent
# queue and the stream are empty, and the function returns only once the consumer is
# running again (bounded wait, not a fixed sleep).
# NEVER call this during a Valkey cut: recreating the backend there refills the bucket
# and restarts the consumer in the middle of the measurement.
recreate_backend() {  # $1 label  $2 evidence file
  local since id
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  "${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
  id=$("${DC[@]}" --profile app ps -q backend 2>/dev/null | tr -d '\r')
  say "backend recreated for $1 at $since id=$id"
  echo "label=$1 recreated_at=$since backend_container_id=$id" >> "$2"
  for _ in $(seq 1 60); do
    "${DC[@]}" logs --since "$since" backend 2>/dev/null | rg -q 'consumer\.started' && return 0
    sleep 2
  done
  say "ABORTA: el backend no volvio a consumir tras recrearlo ($1)"
  return 1
}

reset_lab() {  # $1 label  $2 evidence file
  # L-11: vm_reset.sh purges the agent (state.json, baseline, queue, discarded, journal,
  # quarantine, watch dir, trace) and exits non-zero unless baseline_entries_after_reset
  # is 0; reset_servidor TRUNCATEs events/alerts/rejected_events_audit (audit_log and
  # published_commands are kept) and XTRIMs the ingest stream to 0, which also covers
  # the events that survive a database wipe and a queue purge (they would be consumed
  # by the next repetition and shift max(received_at) - min(received_at)).
  # Any failure aborts the whole run: a repetition on a dirty lab is not a repetition.
  local rst
  rst=$(reset_laboratorio 2>> "$RES") \
    || { say "ABORTA: el reset del laboratorio fallo (${1:-reset_lab}); ver $RES"; exit 1; }
  say "reset ok (${1:-reset_lab}): ${rst:-sin salida}"
  sleep 18
  recreate_backend "${1:-reset_lab}" "${2:-$OUT/env/backend_recreations.txt}" || exit 1
}

# ── 1. suites ─────────────────────────────────────────────────────────────────
say "--- suites ---"
# Run the suites on THIS candidate and write them straight into this package.
# The script used to be pinned to 7a906c2 and to the September package's folder,
# and the harness then copied that folder in: every unified run overwrote the
# September artifacts and shipped them stamped v1.0-tesis, whatever candidate was
# being evaluated. Pass the candidate explicitly and check what came back.
CAND="$(git rev-list -1 "$TAG")" CAND_TAG="$TAG" SUITES_OUT="$OUT/suites" \
  bash "$REPO/scripts/correr_suites_candidato.sh" >/dev/null 2>&1
SUITES_TAG=$(rg -N -o 'candidate_tag=.*' "$OUT/suites/procedencia.txt" 2>/dev/null | sd 'candidate_tag=' '')
[ "$SUITES_TAG" = "$TAG" ] \
  && say "suites: corridas sobre $SUITES_TAG" \
  || say "ATENCION: las suites del paquete dicen '$SUITES_TAG' y el candidato es '$TAG'"
"$LAB/.venv/bin/python" - "$OUT/suites" >> "$RES" 2>&1 <<'PY'
import sys, pathlib, xml.etree.ElementTree as ET
out = pathlib.Path(sys.argv[1])
for name in ("agente.xml", "backend.xml", "frontend.xml"):
    f = out / name
    if not f.exists():
        print(f"  {name:14s} ausente"); continue
    root = ET.parse(f).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    g = lambda k: sum(int(s.get(k) or 0) for s in suites)
    print(f"  {name:14s} tests={g('tests'):5d} fallas={g('failures')} errores={g('errors')} omitidos={g('skipped')}")
PY

# ── 2. latencia + control, misma ventana, tres repeticiones (L-12) ─────────────
# Three repetitions, each with its own generator seed and its own control phase:
# the control scanner's 900 s grid used to start at the same offset every time, so
# its mean latency could not be told apart from the offset that happened to be
# chosen. fase_control_s = random.Random(SEED).randrange(900) is the delay between
# the baseline scan and the first `control_hashing.py --loop` scan. The generator
# rate is the original one (0.2778 ch/s, 500 changes, mix 20/70/10; vm_gen_b3.sh).
# Every run gets a FRESH control CSV (vm_control.sh removes it): never cumulative.
say "--- baterias de latencia y control (30 min, misma ventana, 3 repeticiones) ---"
SEEDS=(20261001 20261002 20261003)
for i in 1 2 3; do
  R=$(printf "run-%02d" "$i")
  SEED=${SEEDS[$((i-1))]}
  FASE=$(python3 -c 'import random, sys; print(random.Random(int(sys.argv[1])).randrange(900))' "$SEED")
  LD="$OUT/latencia/$R"; CD="$OUT/control/$R"
  mkdir -p "$LD" "$CD"
  say "latencia+control $R: seed=$SEED fase_control_s=$FASE"
  reset_lab "latencia/$R" "$LD/backend_recreation.txt"
  {
    echo "tag=$TAG"
    echo "commit=$COMMIT"
    echo "repeticion=$R"
    echo "seed=$SEED"
    echo "fase_control_s=$FASE"
    echo "generador=--rate 0.2778 --count 500 --mix 20/70/10 --critical-frac 0.2"
    echo "control=control_hashing.py --loop --interval 900 tras baseline inmediato y espera de fase_control_s"
    echo "csv_control=nuevo por corrida (vm_control.sh lo borra antes de empezar)"
    echo "inicio_utc=$(ts)"
  } > "$LD/condiciones.txt"
  cp "$LD/condiciones.txt" "$CD/condiciones.txt"
  nohup multipass exec fim-host -- sudo sh /tmp/vm_control.sh "$SEED" "$FASE" > "$CD/control.log" 2>&1 &
  CTRL=$!
  sleep 30
  multipass exec fim-host -- sudo sh /tmp/vm_gen_b3.sh "$SEED" >> "$LD/generador_stdout.log" 2>&1
  say "generador de latencia finalizado ($R); esperando el ultimo scan del control"
  wait $CTRL 2>/dev/null
  sleep 30
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id, path, detected_at, received_at, EXTRACT(EPOCH FROM (received_at-detected_at))*1000 AS latencia_ms FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$LD/eventos.csv" 2>/dev/null
  "$LAB/.venv/bin/python" "$LAB/latencia.py" "$LD/eventos.csv" > "$LD/resumen.txt" 2>&1
  say "latencia $R: $(tr '\n' ' ' < "$LD/resumen.txt")"
  # A negative latency means the guest stamped the detection after the host
  # stamped the reception, which is impossible and therefore measures the clocks,
  # not the system. Report where they fall: clustered at the start is a clock
  # still converging, spread across the window is a skew that invalidates the run.
  "$LAB/.venv/bin/python" - "$LD/eventos.csv" >> "$RES" 2>&1 <<'PY'
import csv, sys, datetime
rows = list(csv.DictReader(open(sys.argv[1])))
neg = [r for r in rows if float(r["latencia_ms"]) < 0]
if not neg:
    print("  negativos: 0 — reloj consistente en toda la ventana"); raise SystemExit
allts = sorted(datetime.datetime.fromisoformat(r["received_at"]) for r in rows)
ts = [datetime.datetime.fromisoformat(r["received_at"]) for r in neg]
span, full = (max(ts) - min(ts)).total_seconds(), (allts[-1] - allts[0]).total_seconds()
head = (min(ts) - allts[0]).total_seconds()
print(f"  ATENCION negativos: {len(neg)} de {len(rows)}, el peor {min(float(r['latencia_ms']) for r in neg):.1f} ms")
print(f"  se concentran en {span:.0f}s de una ventana de {full:.0f}s, desde +{head:.0f}s del inicio")
PY
  for f in bateria3_manifiesto.json bateria3_manifiesto.jsonl bateria3_generador.log; do
    multipass transfer "fim-host:/srv/evidencia/$f" "$LD/" 2>/dev/null; done
  for f in bateria7_control.csv control_estado.json; do
    multipass transfer "fim-host:/srv/evidencia/$f" "$CD/" 2>/dev/null; done
  echo "fin_utc=$(ts)" >> "$LD/condiciones.txt"; echo "fin_utc=$(ts)" >> "$CD/condiciones.txt"
  # Trace path is the unit's FIM_EXPERIMENT_TRACE_FILE (vm_trace_on.sh).
  multipass exec fim-host -- sudo cp /var/lib/fim-agent/traza_b3.jsonl "/srv/evidencia/traza_lat_$R.jsonl" 2>/dev/null
  multipass exec fim-host -- sudo chmod 644 "/srv/evidencia/traza_lat_$R.jsonl" 2>/dev/null
  multipass transfer "fim-host:/srv/evidencia/traza_lat_$R.jsonl" "$OUT/diagnostico/" 2>/dev/null
  say "traza causal $R: $(wc -l < "$OUT/diagnostico/traza_lat_$R.jsonl" 2>/dev/null || echo 0) registros"
done

# ── 3. notificacion, tres escenarios contra Mailpit ───────────────────────────
say "--- bateria de notificacion, tres escenarios ---"
# One reset for the whole battery: the three series are parts of the same battery, not
# repetitions, so the backend is NOT recreated between them (D85/RN-179, D-9). Together
# they publish 3,000 events under the same agent_id, within the 3,000 burst.
reset_lab notificacion "$OUT/notificacion/backend_recreation.txt"
"${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S RATE_LIMIT_INGEST_BURST > "$OUT/notificacion/rate_limit_usado.txt" 2>&1
RL_PREV=0
"${DC[@]}" cp "$LAB/bateria4_publicador.py" backend:/tmp/b4.py >/dev/null 2>&1
notif() {  # $1 label  $2 total  $3 concurrency
  say "escenario $1: $2 eventos, concurrencia $3"
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events;" >/dev/null 2>&1
  curl -s -X DELETE http://127.0.0.1:8025/api/v1/messages >/dev/null 2>&1
  sleep 3
  "${DC[@]}" exec -T backend sh -c "cd /app && PYTHONPATH=/app python /tmp/b4.py $1 $2 $3" >> "$RES" 2>&1
  prev=-1; est=0
  for _ in $(seq 1 180); do
    n=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM alerts WHERE delivered_at IS NOT NULL;" | tr -d ' \r')
    [ "$n" = "$prev" ] && est=$((est+1)) || est=0; prev=$n
    [ "$est" -ge 5 ] && break; sleep 5
  done
  # B-3: both intervals (ms_aceptacion = channel_accepted_at - received_at, the protocol's
  # interval; ms_entrega = delivered_at - received_at, written after the executor hop).
  exportar_notif_csv > "$OUT/notificacion/$1.csv"
  say "escenario $1: $(( $(wc -l < "$OUT/notificacion/$1.csv") - 1 )) muestras; correos en mailpit: $(mp_count)"
  # rate_limited rejections of THIS series (the audit table is cumulative since the reset).
  # A non-zero count is a result to report, not something to fix by recreating the backend.
  RL_TOTAL=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM rejected_events_audit WHERE reason = 'rate_limited';" 2>/dev/null | tr -d ' \r')
  echo "$1 rate_limited=$(( ${RL_TOTAL:-0} - RL_PREV ))" >> "$OUT/notificacion/rate_limited.txt"
  [ "$(( ${RL_TOTAL:-0} - RL_PREV ))" = "0" ] || say "ATENCION: escenario $1 tuvo $(( ${RL_TOTAL:-0} - RL_PREV )) rechazos rate_limited"
  RL_PREV=${RL_TOTAL:-0}
}
notif secuencial 1000 1
notif conc50 1000 50
notif conc100 1000 100
"$LAB/.venv/bin/python" - "$OUT/notificacion" <<'PY' > "$OUT/notificacion/resumen.txt" 2>&1
import sys, pathlib, pandas as pd
d = pathlib.Path(sys.argv[1])
for e in ("secuencial", "conc50", "conc100"):
    f = d / f"{e}.csv"
    if not f.exists() or f.stat().st_size < 20: print(f"{e}: sin muestras"); continue
    df = pd.read_csv(f)
    for col in ("ms_aceptacion", "ms_entrega"):
        s = df[col].dropna()
        print(f"{e:11s} {col:13s} n={len(s):5d} media={s.mean():9.3f} p50={s.quantile(.50):9.3f} p95={s.quantile(.95):9.3f} p99={s.quantile(.99):9.3f} max={s.max():9.3f}")
PY
cat "$OUT/notificacion/resumen.txt" | tee -a "$RES"

# ── 4. resiliencia, tres repeticiones ─────────────────────────────────────────
say "--- bateria de resiliencia, 3 repeticiones ---"
for i in 1 2 3; do
  R=$(printf "run-%02d" "$i"); mkdir -p "$OUT/resiliencia/$R"
  say "repeticion $R"
  # reset_lab recreates the backend (full bucket) and waits for the consumer.
  reset_lab "resiliencia/$R" "$OUT/resiliencia/$R/backend_recreation.txt"
  # Reference instant for this repetition: any trace record older than this one
  # was carried over from a previous run and the trace is not this run's.
  WIN_START=$(date -u +%Y-%m-%dT%H:%M:%S)
  # bateria5.sh gets exactly the compose file set the backend was brought up with.
  TAG="$TAG" DC_FILES="docker-compose.yml docker-compose.tls.yml $LAB/docker-compose.mailpit.yml" \
    bash "$LAB/bateria5.sh" "$OUT/resiliencia/$R" "$R" \
    || say "$R: REPETICION INVALIDA — el backend se recreo durante el corte"
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id, path, detected_at, received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$OUT/resiliencia/$R/eventos.csv" 2>/dev/null
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT json_build_object('eventos', count(*), 'unicos', count(DISTINCT event_id), 'ventana_s', round(EXTRACT(EPOCH FROM (max(received_at)-min(received_at)))::numeric,3)) FROM events;" > "$OUT/resiliencia/$R/counts.json" 2>/dev/null
  multipass exec fim-host -- sudo cp /var/lib/fim-agent/traza_b3.jsonl "/srv/evidencia/traza_$R.jsonl" 2>/dev/null
  multipass exec fim-host -- sudo chmod 644 "/srv/evidencia/traza_$R.jsonl" 2>/dev/null
  multipass transfer "fim-host:/srv/evidencia/traza_$R.jsonl" "$OUT/resiliencia/$R/" 2>/dev/null

  # The trace must belong to THIS repetition. Three checks, because the failure
  # mode was silent: a stale cumulative file copied three times passed every
  # check the harness had, and its seal verified perfectly.
  TR=$(multipass exec fim-host -- sudo sh /tmp/vm_trace_range.sh 2>/dev/null | tr -d '\r')
  TR_LINES=$(echo "$TR" | cut -d' ' -f1); TR_FIRST=$(echo "$TR" | cut -d' ' -f3)
  TR_HASH=$(sha256sum "$OUT/resiliencia/$R/traza_$R.jsonl" 2>/dev/null | cut -d' ' -f1)
  if [ "${TR_LINES:-0}" -eq 0 ]; then
    say "$R: TRAZA VACIA O AUSENTE — repeticion invalida"
  elif [ "$TR_HASH" = "${PREV_TRACE_HASH:-}" ]; then
    say "$R: TRAZA IDENTICA A LA ANTERIOR ($TR_LINES lineas) — no se trunco entre repeticiones"
  elif [ -n "$TR_FIRST" ] && [ "$TR_FIRST" != "-" ] && [ "$TR_FIRST" \< "$WIN_START" ]; then
    say "$R: TRAZA EMPIEZA ANTES DE LA REPETICION ($TR_FIRST < $WIN_START) — arrastra registros previos"
  else
    say "$R: traza propia, $TR_LINES registros desde $TR_FIRST"
  fi
  PREV_TRACE_HASH="$TR_HASH"

  # The battery log must open at events=0. A residual carried into the window
  # inflates the drain time, because the window is a difference of extremes.
  INIT=$(rg -N -o "initial: events=[0-9]+" "$OUT/resiliencia/$R/bateria5_$R.log" 2>/dev/null | head -1 | sd '.*=' '')
  [ "${INIT:-0}" = "0" ] && say "$R: arranca limpio (events=0)" \
                         || say "$R: ARRANCA CONTAMINADO (events=${INIT:-?}) — la ventana de drenaje queda inflada"

  say "$R: $(cat "$OUT/resiliencia/$R/counts.json" 2>/dev/null)"

  # A-2 (out-of-order arrivals) and A-3 (drain decomposition) -> metricas.json. This
  # runs INSIDE the loop, so every metricas.json exists before the package is sealed
  # (SHA256SUMS below): a file written after the seal would not be covered by it.
  RD="$OUT/resiliencia/$R"
  python3 "$REPO/scripts/fuera_de_orden.py" "$RD/eventos.csv" --json > "$RD/fuera_de_orden.json" 2>"$RD/fuera_de_orden.err"
  python3 "$REPO/scripts/descomponer_drenaje.py" --log "$RD/bateria5_$R.log" --traza "$RD/traza_$R.jsonl" \
    --eventos "$RD/eventos.csv" --backend-pre "$RD/backend_inspect_pre.txt" --backend-post "$RD/backend_inspect_post.txt" \
    --json > "$RD/descomposicion_drenaje.json" 2>"$RD/descomposicion_drenaje.err"
  python3 - "$RD" "$R" "$TAG" "$COMMIT" <<'PY'
import json, pathlib, sys
rd, run, tag, commit = pathlib.Path(sys.argv[1]), *sys.argv[2:5]
def load(name):
    f, err = rd / f"{name}.json", rd / f"{name}.err"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {"error": (err.read_text().strip() if err.exists() else "") or "sin salida"}
m = {"run": run, "tag": tag, "commit": commit,
     "fuera_de_orden": load("fuera_de_orden"), "drenaje": load("descomposicion_drenaje")}
(rd / "metricas.json").write_text(json.dumps(m, indent=2) + "\n")
print("metricas.json:", json.dumps(m))
PY
  say "$R: metricas.json escrito ($(wc -c < "$RD/metricas.json") bytes)"
done

# ── cierre ────────────────────────────────────────────────────────────────────
multipass exec fim-host -- sudo sh /tmp/vm_trace_off.sh >/dev/null 2>&1

say "sellando"
cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
say "sellado: $(wc -l < SHA256SUMS) archivos | $(sha256sum -c SHA256SUMS 2>/dev/null | grep -c ': OK$') OK"
say "=== corrida unificada completa: $OUT ==="
