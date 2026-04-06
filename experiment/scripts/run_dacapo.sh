#!/bin/bash
# =============================================================================
# Experiment 1: DaCapo Benchmark — All GCs on Java 21
# =============================================================================
# Runs each DaCapo benchmark with all 7 GC configurations.
# Logs are saved to: results/dacapo/<benchmark>/<gc_name>.log
# Timing is saved to: results/dacapo/<benchmark>/<gc_name>_time.txt
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DACAPO_JAR="$BASE_DIR/benchmarks/dacapo_chopin/dacapo-23.11-MR2-chopin.jar"
RESULTS_DIR="$BASE_DIR/results/dacapo"

# Benchmarks to run (will be validated against available list)
# Benchmarks matching the original study + Chopin additions
BENCHMARKS=(h2 lusearch luindex pmd fop avrora batik sunflow xalan tomcat)

# GC configurations: name|flags
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
echo " DaCapo Benchmark Experiment (Java 21)"
echo " Date: $(date)"
echo " Java: $(java -version 2>&1 | head -1)"
echo "=============================================="

# Verify JAR exists
if [ ! -f "$DACAPO_JAR" ]; then
    echo "ERROR: DaCapo JAR not found at $DACAPO_JAR"
    exit 1
fi

# List available benchmarks
echo ""
echo "Available DaCapo benchmarks:"
java -jar "$DACAPO_JAR" --list-benchmarks 2>/dev/null || java -jar "$DACAPO_JAR" -l 2>/dev/null || echo "(could not list)"
echo ""

# Filter to only benchmarks that exist
VALID_BENCHMARKS=()
AVAILABLE=$(java -jar "$DACAPO_JAR" --list-benchmarks 2>/dev/null || java -jar "$DACAPO_JAR" -l 2>/dev/null || echo "")
for bm in "${BENCHMARKS[@]}"; do
    if echo "$AVAILABLE" | grep -qw "$bm"; then
        VALID_BENCHMARKS+=("$bm")
    else
        echo "SKIP: Benchmark '$bm' not available in this DaCapo version"
    fi
done

echo ""
echo "Will run: ${VALID_BENCHMARKS[*]}"
echo "GC configs: ${!GC_CONFIGS[*]}"
echo "=============================================="

TOTAL=${#VALID_BENCHMARKS[@]}
COUNT=0

for benchmark in "${VALID_BENCHMARKS[@]}"; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "======== [$COUNT/$TOTAL] Benchmark: $benchmark ========"

    # Create output directory
    mkdir -p "$RESULTS_DIR/$benchmark"

    for gc_name in "${!GC_CONFIGS[@]}"; do
        gc_flags="${GC_CONFIGS[$gc_name]}"
        log_file="$RESULTS_DIR/$benchmark/${gc_name}.log"
        time_file="$RESULTS_DIR/$benchmark/${gc_name}_time.txt"

        echo "  → Running $benchmark with $gc_name ($gc_flags)..."

        # Run benchmark with timing
        START_TIME=$(date +%s%N)
        java -XX:+UnlockExperimentalVMOptions \
             $gc_flags \
             "-Xlog:gc*:file=$log_file:time,uptime,level,tags" \
             -jar "$DACAPO_JAR" "$benchmark" \
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
echo " DaCapo Experiment Complete!"
echo " Results: $RESULTS_DIR"
echo "=============================================="
