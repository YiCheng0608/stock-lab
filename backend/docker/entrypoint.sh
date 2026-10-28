#!/bin/sh
# Entrypoint of the api and the scheduler in compose (docker-compose.yml, #335), run by tini:
#
#   tini -- /app/backend/docker/entrypoint.sh <command>
#
# 1. WEB_PORT and API_PORT, when not empty, are the host ports compose publishes. The API's
#    write gate (docs/OPERATIONS.md §1.1) admits a Host only with its port and a browser on
#    port 80 sends none, so 80 is refused. WEB_PORT 8000 is refused too: the api listens on
#    8000 and would admit Host localhost:8000 without any allow list (#335, PR #349 review S2).
# 2. With STOCK_SEED_FIXTURE=1 (docker-compose.dev.yml) and no stock.db in STOCK_DATA_DIR, it
#    writes the verify fixture database there (tools/verify/fixture_db.py); an existing
#    stock.db is never touched.
#
# Then the command replaces it, so tini's signals reach the command itself. The image marks
# this file executable; the dev override bind mounts the checkout, where a Windows file has no
# execute bit, and calls it as `sh /app/backend/docker/entrypoint.sh` instead.
set -eu

refuse() {
    echo "entrypoint: $*" >&2
    exit 64
}

check_port() {
    case "$2" in
        '' | *[!0-9]* | 0*) refuse "$1=$2 is not a port: 1-65535, no leading 0" ;;
    esac
    [ "$2" -le 65535 ] || refuse "$1=$2 is not a port: 1-65535"
    [ "$2" -ne 80 ] || refuse "$1=80: a browser sends Host without a port on 80, and the API's write gate refuses that"
}

# Empty is unset: the scheduler gets the two only from the env file, where `WEB_PORT=` would
# otherwise stop it (#335 review S7).
if [ -n "${API_PORT:-}" ]; then check_port API_PORT "$API_PORT"; fi
if [ -n "${WEB_PORT:-}" ]; then
    check_port WEB_PORT "$WEB_PORT"
    [ "$WEB_PORT" -ne 8000 ] || refuse "WEB_PORT=8000 is the api's own port, which the write gate admits without an allow list; pick another"
    [ "${API_PORT:-}" != "$WEB_PORT" ] || refuse "WEB_PORT and API_PORT are both $WEB_PORT"
fi

if [ "${STOCK_SEED_FIXTURE:-}" = 1 ]; then
    data="${STOCK_DATA_DIR:?STOCK_DATA_DIR is not set}"
    if [ ! -e "$data/stock.db" ]; then
        echo "entrypoint: no $data/stock.db, writing the verify fixture database" >&2
        # Built aside and moved in, so a run stopped halfway leaves no partial stock.db.
        seed="$(mktemp -d "$data/.fixture.XXXXXX")"
        python -B /app/tools/verify/fixture_db.py --dest "$seed" >&2
        # Its WAL into the file, and the last connection's close removes the WAL, so the one
        # file moved holds everything.
        python -B -c 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()' "$seed/stock.db"
        [ ! -e "$seed/stock.db-wal" ] || refuse "$seed/stock.db-wal is still there after a checkpoint"
        mv "$seed/stock.db" "$data/stock.db"
        rm -r "$seed"
    fi
fi

exec "$@"
