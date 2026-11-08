#!/usr/bin/env bash
# Generate the train, tune and test populations with Synthea, in Docker.
#
# Run this yourself. It detaches and returns at once, so closing the terminal or
# Claude Code does not stop it. Allow roughly 40 minutes of running time per
# population, and keep the host machine awake, because the VM freezes when it
# sleeps. Progress goes to ~/synthea/run.log.
#
# Safe to run again after any interruption, including a reboot. A population only
# counts as finished once Synthea has exited cleanly and left a .complete marker.
# Anything without that marker is partial, so it is deleted and regenerated.
set -euo pipefail

BASE="${SYNTHEA_BASE:-$HOME/synthea}"
JAR="$BASE/jar/synthea-with-dependencies.jar"
LOG="$BASE/run.log"
LOCK="$BASE/.generate.lock"

if [[ ! -f "$JAR" ]]; then
    echo "Synthea not found at $JAR. Download it first (see data/README.md)." >&2
    exit 1
fi

# Only one copy may run, because two would delete each other's output.
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "Already running. Progress is in $LOG" >&2
    exit 1
fi

if [[ -z "${SYNTHEA_DETACHED:-}" ]]; then
    flock -u 9
    SYNTHEA_DETACHED=1 setsid nohup bash "$0" >>"$LOG" 2>&1 </dev/null &
    echo "Started in the background (PID $!). Progress is in $LOG"
    exit 0
fi

log() { echo "$*  [$(date '+%F %T')]" >>"$LOG"; }

log "run: started"
for entry in train:101 tune:202 test:303; do
    name="${entry%:*}"
    seed="${entry#*:}"
    out="$BASE/$name"
    container="synthea-$name"

    if [[ -f "$out/.complete" ]]; then
        log "$name: already complete, skipping"
        continue
    fi

    # We hold the lock, so any container or output found here is left over from
    # an interrupted run.
    docker rm -f "$container" >/dev/null 2>&1 || true
    rm -rf "$out"
    mkdir -p "$out"

    log "$name: started"
    if ! docker run --rm --name "$container" \
        --user "$(id -u):$(id -g)" --memory 3g \
        -v "$BASE/jar:/jar:ro" -v "$out:/out" -w /tmp \
        eclipse-temurin:21-jre \
        java -Xmx2500m -jar /jar/synthea-with-dependencies.jar \
        -p 10000 -s "$seed" -cs "$seed" -r 20261101 \
        --exporter.baseDirectory=/out/ \
        --exporter.csv.export=true \
        --exporter.csv.included_files=patients.csv \
        --exporter.fhir.export=false \
        --exporter.hospital.fhir.export=false \
        --exporter.practitioner.fhir.export=false \
        Massachusetts >>"$LOG" 2>&1; then
        log "$name: FAILED, see the output above"
        exit 1
    fi

    if [[ ! -s "$out/csv/patients.csv" ]]; then
        log "$name: FAILED, Synthea exited cleanly but wrote no patients.csv"
        exit 1
    fi

    touch "$out/.complete"
    log "$name: finished"
done
log "run: all populations are ready"
