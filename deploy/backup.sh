#!/bin/sh
# Atenea beta data backups (PR-BT4b).
#
# Exports BOTH SurrealDB databases the production stack uses -- OpenNotebook's
# own (SURREAL_DATABASE, default "open_notebook") and the tutor's
# (TUTOR_SURREAL_DATABASE, default "atenea"; same namespace, see
# tutor/db.py) -- to dated .surql files under a host-mounted directory, then
# rotates old dumps, keeping TUTOR_BACKUP_KEEP most recent per database.
#
# Two invocations of this SAME file (contract: "a separate file... runnable
# on demand"):
#   /backup.sh          -- one export+rotate pass, then exit. This is the
#                           on-demand path documented in
#                           docs/atenea/deploy_guide.md:
#                             docker compose -f docker-compose.yml \
#                               -f docker-compose.prod.yml exec backup /backup.sh
#   /backup.sh --loop   -- what the `backup` service's entrypoint runs in
#                           docker-compose.prod.yml: pass, sleep
#                           TUTOR_BACKUP_INTERVAL_HOURS, repeat forever.
#
# Written in plain POSIX sh (no bashisms: no arrays, no `local`, no `[[ ]]`)
# because the surrealdb/surrealdb image this container runs is a minimal
# CLI+server image not guaranteed to ship bash. The `surreal` CLI binary is
# invoked by its absolute path (/surreal) rather than relying on $PATH --
# the same path the image's own README documents for `docker exec ...
# /surreal sql ...` -- so this script only depends on /bin/sh existing to
# interpret it, not on any other userland tool. See docs/atenea/
# deploy_guide.md "Backups & restore" for the first-deploy verification
# step that catches it if that /bin/sh assumption is ever wrong on a given
# SurrealDB image tag, plus a host-cron fallback that does not need it.
set -eu

SURREAL_ENDPOINT="http://surrealdb:8000"
SURREAL_NAMESPACE="${SURREAL_NAMESPACE:-open_notebook}"
SURREAL_USER="${SURREAL_USER:-root}"
SURREAL_PASSWORD="${SURREAL_PASSWORD:-root}"
ON_DATABASE="${SURREAL_DATABASE:-open_notebook}"
TUTOR_DATABASE="${TUTOR_SURREAL_DATABASE:-atenea}"
BACKUP_DIR="${TUTOR_BACKUP_DIR:-/backups}"
BACKUP_KEEP="${TUTOR_BACKUP_KEEP:-14}"
BACKUP_INTERVAL_HOURS="${TUTOR_BACKUP_INTERVAL_HOURS:-24}"

do_export() {
    db="$1"
    ts="$(date -u +%Y%m%d-%H%M%S)"
    out="${BACKUP_DIR}/${db}-${ts}.surql"
    echo "[backup] exporting database '${db}' -> ${out}"
    /surreal export \
        --conn "${SURREAL_ENDPOINT}" \
        --user "${SURREAL_USER}" \
        --pass "${SURREAL_PASSWORD}" \
        --ns "${SURREAL_NAMESPACE}" \
        --db "${db}" \
        "${out}"
}

do_rotate() {
    db="$1"
    n=0
    for f in $(ls -1t "${BACKUP_DIR}/${db}"-*.surql 2>/dev/null); do
        n=$((n + 1))
        if [ "${n}" -gt "${BACKUP_KEEP}" ]; then
            echo "[backup] rotating out ${f}"
            rm -f "${f}"
        fi
    done
}

run_once() {
    mkdir -p "${BACKUP_DIR}"
    for db in "${ON_DATABASE}" "${TUTOR_DATABASE}"; do
        do_export "${db}"
        do_rotate "${db}"
    done
    echo "[backup] pass complete -- keeping ${BACKUP_KEEP} dump(s)/database in ${BACKUP_DIR}"
}

if [ "${1:-}" = "--loop" ]; then
    echo "[backup] looping every ${BACKUP_INTERVAL_HOURS}h, keeping ${BACKUP_KEEP} dump(s)/database"
    while true; do
        run_once
        sleep $((BACKUP_INTERVAL_HOURS * 3600))
    done
else
    run_once
fi
