#!/bin/bash
# =============================================================================
# Experiment 4: DaCapo Epsilon GC Baseline
# =============================================================================
# Runs DaCapo benchmarks with Epsilon (no-op) GC to establish a pure baseline.
# Uses 4GB heap to give maximum headroom since Epsilon never collects.
# Gracefully handles OOM crashes.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DACAPO_JAR="$BASE_DIR/benchmarks/dacapo_chopin/dacapo-23.11-MR2-chopin.jar"
RESULTS_DIR="$BASE_DIR/results/epsilon"

# All DaCapo benchmarks — some may OOM
BENCHMARKS=(lusearch luindex pmd fop avrora batik sunflow xalan tomcat h2)

echo "=============================================="
echo " DaCapo Epsilon GC Baseline (Java 21)"
echo " Date: $(date)"
echo " Java: $(java -version 2>&1 | head -1)"
echo " Heap: 4GB (Epsilon never collects!)"
echo "=============================================="

if [ ! -f "$DACAPO_JAR" ]; then
    echo "ERROR: DaCapo JAR not found at $DACAPO_JAR"
    exit 1
fi

# Get valid benchmarks
AVAILABLE=$(java -jar "$DACAPO_JAR" --list-benchmarks 2>/dev/null || java -jar "$DACAPO_JAR" -l 2>/dev/null || echo "")
VALID_BENCHMARKS=()
for bm in "${BENCHMARKS[@]}"; do
    if echo "$AVAILABLE" | grep -qw "$bm"; then
        VALID_BENCHMARKS+=("$bm")
    fi
done

echo "Will run: ${VALID_BENCHMARKS[*]}"

TOTAL=${#VALID_BENCHMARKS[@]}
COUNT=0
SUCCEEDED=0
FAILED=0

for benchmark in "${VALID_BENCHMARKS[@]}"; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "======== [$COUNT/$TOTAL] Benchmark: $benchmark (Epsilon) ========"

    mkdir -p "$RESULTS_DIR/$benchmark"

    log_file="$RESULTS_DIR/$benchmark/epsilon.log"
    time_file="$RESULTS_DIR/$benchmark/epsilon_time.txt"
    status_file="$RESULTS_DIR/$benchmark/epsilon_status.txt"

    START_TIME=$(date +%s%N)
    java -XX:+UnlockExperimentalVMOptions \
         -XX:+UseEpsilonGC \
         -Xmx64G \
         "-Xlog:gc*:file=$log_file:time,uptime,level,tags" \
         -jar "$DACAPO_JAR" "$benchmark" \
         > "$RESULTS_DIR/$benchmark/epsilon_stdout.txt" 2>&1
    EXIT_CODE=$?
    END_TIME=$(date +%s%N)

    ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))

    if [ $EXIT_CODE -eq 0 ]; then
        echo "$ELAPSED_MS" > "$time_file"
        echo "SUCCESS" > "$status_file"
        echo "  ✓ Completed in ${ELAPSED_MS}ms (no GC overhead!)"
        SUCCEEDED=$((SUCCEEDED + 1))
    else
        echo "$ELAPSED_MS" > "$time_file"
        echo "OOM_OR_FAILED (exit=$EXIT_CODE)" > "$status_file"
        echo "  ✗ Failed/OOM in ${ELAPSED_MS}ms (exit code: $EXIT_CODE)"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=============================================="
echo " Epsilon Baseline Complete!"
echo " Succeeded: $SUCCEEDED / $TOTAL"
echo " Failed/OOM: $FAILED / $TOTAL"
echo " Results: $RESULTS_DIR"
echo "=============================================="
