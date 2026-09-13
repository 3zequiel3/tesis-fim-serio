#!/bin/sh
# 40-fim-console-tls.sh — selecciona el modo TLS de la consola (D55/RN-149).
#
# Corre dentro de /docker-entrypoint.d/ de la imagen oficial de nginx, ANTES
# de que nginx arranque. Un exit distinto de 0 acá aborta el contenedor
# (verificado empíricamente contra nginx:alpine, ver design.md §Risks del
# change 52): nginx NUNCA degrada en silencio a HTTP por un problema acá.
#
# CONSOLE_TLS_MODE (D55/RN-149):
#   off         — instala console-http.conf tal cual, sin HSTS. Advierte que
#                 credenciales y tokens viajan en claro.
#   self_signed — certificado que emite `certs-init` (change 52, D53/RN-147),
#                 montado en $FIM_SELF_SIGNED_DIR. HSTS corto sin
#                 includeSubDomains (D60/RN-154) para no volver no-omisible
#                 el error de certificado autofirmado del navegador.
#   provided    — certificado del operador, montado en $FIM_PROVIDED_DIR
#                 (CONSOLE_TLS_DIR), con las rutas relativas
#                 CONSOLE_TLS_CERT_FILE / CONSOLE_TLS_KEY_FILE. Soporta un
#                 directorio estilo /etc/letsencrypt (enlaces relativos
#                 live/ -> archive/) porque se monta el directorio completo,
#                 nunca los archivos sueltos. HSTS largo con includeSubDomains.
set -e

TEMPLATES_DIR="${FIM_CONSOLE_TEMPLATES_DIR:-/etc/nginx/fim-console}"
SELF_SIGNED_DIR="${FIM_SELF_SIGNED_DIR:-/run/fim-console-tls/self-signed}"
PROVIDED_DIR="${FIM_PROVIDED_DIR:-/run/fim-console-tls/provided}"
DEFAULT_CONF="/etc/nginx/conf.d/default.conf"

MODE="${CONSOLE_TLS_MODE:-off}"

entrypoint_log() {
    echo "40-fim-console-tls.sh: $*"
}

die() {
    echo "40-fim-console-tls.sh: ERROR: $*" >&2
    exit 1
}

require_file() {
    path="$1"
    label="$2"
    if [ ! -f "$path" ]; then
        die "$label not found: $path"
    fi
}

case "$MODE" in
    off)
        entrypoint_log "CONSOLE_TLS_MODE=off — installing HTTP-only config"
        entrypoint_log "WARNING: credentials and tokens travel unencrypted (CONSOLE_TLS_MODE=off)"
        cp "$TEMPLATES_DIR/console-http.conf" "$DEFAULT_CONF"
        ;;
    self_signed)
        entrypoint_log "CONSOLE_TLS_MODE=self_signed — installing HTTPS config with the certs-init certificate"
        cert_path="$SELF_SIGNED_DIR/console.pem"
        key_path="$SELF_SIGNED_DIR/console-key.pem"
        require_file "$cert_path" "self-signed console certificate"
        require_file "$key_path" "self-signed console private key"
        FIM_CONSOLE_TLS_CERT="$cert_path" \
        FIM_CONSOLE_TLS_KEY="$key_path" \
        FIM_CONSOLE_HSTS_VALUE="max-age=300" \
            envsubst '$FIM_CONSOLE_TLS_CERT $FIM_CONSOLE_TLS_KEY $FIM_CONSOLE_HSTS_VALUE' \
            < "$TEMPLATES_DIR/console-https.conf" > "$DEFAULT_CONF"
        ;;
    provided)
        entrypoint_log "CONSOLE_TLS_MODE=provided — installing HTTPS config with the operator-provided certificate"
        cert_file="${CONSOLE_TLS_CERT_FILE:-fullchain.pem}"
        key_file="${CONSOLE_TLS_KEY_FILE:-privkey.pem}"
        cert_path="$PROVIDED_DIR/$cert_file"
        key_path="$PROVIDED_DIR/$key_file"
        require_file "$cert_path" "provided console certificate (CONSOLE_TLS_CERT_FILE)"
        require_file "$key_path" "provided console private key (CONSOLE_TLS_KEY_FILE)"
        FIM_CONSOLE_TLS_CERT="$cert_path" \
        FIM_CONSOLE_TLS_KEY="$key_path" \
        FIM_CONSOLE_HSTS_VALUE="max-age=63072000; includeSubDomains" \
            envsubst '$FIM_CONSOLE_TLS_CERT $FIM_CONSOLE_TLS_KEY $FIM_CONSOLE_HSTS_VALUE' \
            < "$TEMPLATES_DIR/console-https.conf" > "$DEFAULT_CONF"
        ;;
    *)
        die "unknown CONSOLE_TLS_MODE: '$MODE' (expected off, self_signed or provided)"
        ;;
esac

entrypoint_log "console configured in mode '$MODE'"
