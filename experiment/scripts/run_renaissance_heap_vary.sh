#!/bin/bash
# =============================================================================
# Experiment 3: Renaissance Heap-Varying Experiment
# =============================================================================
# Runs select Renaissance benchmarks across varying heap sizes.
# Tests 4 GC configs: G1GC, Shenandoah, ZGC-gen, ZGC-nogen
# Heap sizes: 500, 750, 1000, 1250, 1500, 1750, 2000 MB
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
RENAISSANCE_JAR="$BASE_DIR/benchmarks/renaissance-gpl-0.16.1.jar"
RESULTS_DIR="$BASE_DIR/results/heap_vary"
REPETITIONS=3

# Benchmarks for heap-varying (matching original study)
BENCHMARKS=(chi-square movie-lens page-rank)

# Heap sizes in MB
HEAP_SIZES=(500 750 1000 1250 1500 1750 2000)

# GC configurations for heap-varying
declare -A GC_CONFIGS
GC_CONFIGS=(
    ["g1gc"]="-XX:+UseG1GC"
    ["shenandoah"]="-XX:+UseShenandoahGC"
    ["zgc_nogen"]="-XX:+UseZGC -XX:-ZGenerational"
    ["zgc_gen"]="-XX:+UseZGC -XX:+ZGenerational"
)

echo "=============================================="
echo " Renaissance Heap-Varying Experiment (Java 21)"
echo " Date: $(date)"
echo " Java: $(java -version 2>&1 | head -1)"
echo " Heap sizes: ${HEAP_SIZES[*]} MB"
echo " Repetitions: $REPETITIONS"
echo "=============================================="

if [ ! -f "$RENAISSANCE_JAR" ]; then
    echo "ERROR: Renaissance JAR not found at $RENAISSANCE_JAR"
    exit 1
fi

TOTAL=${#BENCHMARKS[@]}
COUNT=0

for benchmark in "${BENCHMARKS[@]}"; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "======== [$COUNT/$TOTAL] Benchmark: $benchmark ========"

    mkdir -p "$RESULTS_DIR/$benchmark"

    for size in "${HEAP_SIZES[@]}"; do
        echo "  --- Heap size: ${size}M ---"

        for gc_name in "${!GC_CONFIGS[@]}"; do
            gc_flags="${GC_CONFIGS[$gc_name]}"
            log_file="$RESULTS_DIR/$benchmark/${gc_name}_${size}M.log"
            time_file="$RESULTS_DIR/$benchmark/${gc_name}_${size}M_time.txt"

            echo "    → $gc_name with -Xmx${size}M..."

            START_TIME=$(date +%s%N)
            java -XX:+UnlockExperimentalVMOptions \
                 $gc_flags \
                 -Xmx${size}M \
                 "-Xlog:gc*:file=$log_file:time,uptime,level,tags" \
                 -jar "$RENAISSANCE_JAR" "$benchmark" \
                 -r "$REPETITIONS" \
                 > "$RESULTS_DIR/$benchmark/${gc_name}_${size}M_stdout.txt" 2>&1 || {
                echo "      ✗ FAILED (exit code $?)"
                echo "FAILED" > "$time_file"
                continue
            }
            END_TIME=$(date +%s%N)

            ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
            echo "$ELAPSED_MS" > "$time_file"
            echo "      ✓ Completed in ${ELAPSED_MS}ms"
        done
    done
done

echo ""
echo "=============================================="
echo " Heap-Varying Experiment Complete!"
echo " Results: $RESULTS_DIR"
echo "=============================================="
