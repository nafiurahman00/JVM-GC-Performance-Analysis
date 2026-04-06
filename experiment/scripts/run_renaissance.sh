#!/bin/bash
# =============================================================================
# Experiment 2: Renaissance Benchmark — All GCs on Java 21
# =============================================================================
# Runs each Renaissance benchmark with 6 GC configurations (no Epsilon).
# Uses 3 repetitions for statistical robustness.
# Logs are saved to: results/renaissance/<benchmark>/<gc_name>.log
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RENAISSANCE_JAR="$BASE_DIR/benchmarks/renaissance-gpl-0.16.1.jar"
RESULTS_DIR="$BASE_DIR/results/renaissance"
REPETITIONS=3

# Benchmarks matching the original study
BENCHMARKS=(chi-square dec-tree dotty finagle-http movie-lens page-rank philosophers scala-kmeans)

# GC configurations (no Epsilon — too memory-hungry for Renaissance)
declare -A GC_CONFIGS
GC_CONFIGS=(
    ["g1gc"]="-XX:+UseG1GC"
    ["shenandoah"]="-XX:+UseShenandoahGC"
    ["zgc_nogen"]="-XX:+UseZGC -XX:-ZGenerational"
    ["zgc_gen"]="-XX:+UseZGC -XX:+ZGenerational"
    ["g1gc_pause50"]="-XX:+UseG1GC -XX:MaxGCPauseMillis=50"
    ["g1gc_threads2"]="-XX:+UseG1GC -XX:ConcGCThreads=2"
)

echo "=============================================="
echo " Renaissance Benchmark Experiment (Java 21)"
echo " Date: $(date)"
echo " Java: $(java -version 2>&1 | head -1)"
echo " Repetitions: $REPETITIONS"
echo "=============================================="

# Verify JAR exists
if [ ! -f "$RENAISSANCE_JAR" ]; then
    echo "ERROR: Renaissance JAR not found at $RENAISSANCE_JAR"
    exit 1
fi

echo ""
echo "Available Renaissance benchmarks:"
java -jar "$RENAISSANCE_JAR" --list 2>/dev/null | head -40 || echo "(could not list)"
echo ""

TOTAL=${#BENCHMARKS[@]}
COUNT=0

for benchmark in "${BENCHMARKS[@]}"; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "======== [$COUNT/$TOTAL] Benchmark: $benchmark ========"

    mkdir -p "$RESULTS_DIR/$benchmark"

    for gc_name in "${!GC_CONFIGS[@]}"; do
        gc_flags="${GC_CONFIGS[$gc_name]}"
        log_file="$RESULTS_DIR/$benchmark/${gc_name}.log"
        time_file="$RESULTS_DIR/$benchmark/${gc_name}_time.txt"
        csv_file="$RESULTS_DIR/$benchmark/${gc_name}_results.csv"

        echo "  → Running $benchmark with $gc_name ($gc_flags) x${REPETITIONS}..."

        START_TIME=$(date +%s%N)
        java -XX:+UnlockExperimentalVMOptions \
             $gc_flags \
             "-Xlog:gc*:file=$log_file:time,uptime,level,tags" \
             -jar "$RENAISSANCE_JAR" "$benchmark" \
             -r "$REPETITIONS" \
             --csv "$csv_file" \
             > "$RESULTS_DIR/$benchmark/${gc_name}_stdout.txt" 2>&1 || {
            echo "    ✗ FAILED (exit code $?)"
            echo "FAILED" > "$time_file"
            continue
        }
        END_TIME=$(date +%s%N)

        ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
        echo "$ELAPSED_MS" > "$time_file"
        echo "    ✓ Completed in ${ELAPSED_MS}ms"
    done
done

echo ""
echo "=============================================="
echo " Renaissance Experiment Complete!"
echo " Results: $RESULTS_DIR"
echo "=============================================="
