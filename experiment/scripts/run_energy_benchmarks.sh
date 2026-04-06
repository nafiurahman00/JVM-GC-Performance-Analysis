#!/bin/bash
# =============================================================================
# Green Computing: Energy-Aware GC Benchmark Runner
# =============================================================================
# Measures energy consumption (Joules) alongside wall-clock time for each
# combination of Garbage Collector and Benchmark.
#
# Energy Source: Intel RAPL (Running Average Power Limit)
#   - Primary:   /sys/class/powercap/intel-rapl (sysfs — no root needed on
#                 many kernels)
#   - Fallback:  perf stat -e power/energy-pkg/ (requires perf_event access)
#
# GCs tested:  G1GC, Shenandoah, ZGC
# Suites:      DaCapo (Chopin) and Renaissance
#
# Output (per run):
#   results/energy/<suite>/<benchmark>/<gc>_energy.txt
#     → energy_pkg_joules=<value>
#       energy_cores_joules=<value>
#       energy_uncore_joules=<value>
#       wall_time_ms=<value>
#
# Usage:
#   chmod +x scripts/run_energy_benchmarks.sh
#   bash scripts/run_energy_benchmarks.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
DACAPO_JAR="$BASE_DIR/benchmarks/dacapo_chopin/dacapo-23.11-MR2-chopin.jar"
RENAISSANCE_JAR="$BASE_DIR/benchmarks/renaissance-gpl-0.16.1.jar"
RESULTS_DIR="$BASE_DIR/results/energy"

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# GC configurations: name|flags
# Extended to cover all 7 configs from the main performance study,
# enabling complete energy × performance Pareto analysis.
declare -A GC_CONFIGS
GC_CONFIGS=(
    ["g1gc"]="-XX:+UseG1GC"
    ["shenandoah"]="-XX:+UseShenandoahGC"
    ["zgc_nogen"]="-XX:+UseZGC -XX:-ZGenerational"
    ["zgc_gen"]="-XX:+UseZGC -XX:+ZGenerational"
    ["g1gc_pause50"]="-XX:+UseG1GC -XX:MaxGCPauseMillis=50"
    ["g1gc_threads2"]="-XX:+UseG1GC -XX:ConcGCThreads=2"
    
)

# DaCapo benchmarks (subset used in the study)
DACAPO_BENCHMARKS=(h2 lusearch luindex pmd fop avrora batik sunflow xalan tomcat)

# Renaissance benchmarks (subset used in the study)
RENAISSANCE_BENCHMARKS=(chi-square dec-tree dotty finagle-http movie-lens page-rank philosophers scala-kmeans)

RENAISSANCE_REPETITIONS=3

# RAPL sysfs paths
RAPL_BASE="/sys/class/powercap/intel-rapl"
RAPL_PKG="$RAPL_BASE/intel-rapl:0"
RAPL_CORE="$RAPL_BASE/intel-rapl:0/intel-rapl:0:0"
RAPL_UNCORE="$RAPL_BASE/intel-rapl:0/intel-rapl:0:1"

# ---------------------------------------------------------------------------
# ENERGY MEASUREMENT ENGINE
# ---------------------------------------------------------------------------

ENERGY_METHOD="none"

detect_energy_method() {
    # Method 1: RAPL sysfs (preferred — no root needed on many distros)
    if [ -r "$RAPL_PKG/energy_uj" ]; then
        ENERGY_METHOD="rapl_sysfs"
        echo "[✓] Energy method: Intel RAPL via sysfs"
        echo "    Package domain:  $RAPL_PKG"
        [ -r "$RAPL_CORE/energy_uj" ]   && echo "    Core domain:     $RAPL_CORE"
        [ -r "$RAPL_UNCORE/energy_uj" ] && echo "    Uncore domain:   $RAPL_UNCORE"
        return 0
    fi

    # Method 2: perf stat (requires perf_event_paranoid ≤ 0 or CAP_PERFMON)
    if command -v perf &>/dev/null; then
        if perf stat -e power/energy-pkg/ -- sleep 0.1 &>/dev/null; then
            ENERGY_METHOD="perf_stat"
            echo "[✓] Energy method: perf stat (power/energy-pkg/)"
            return 0
        fi
    fi

    echo "[✗] WARNING: No energy measurement method available."
    echo "    To enable RAPL sysfs:  sudo chmod a+r /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
    echo "    To enable perf stat:   sudo sysctl -w kernel.perf_event_paranoid=-1"
    echo ""
    echo "    The script will still run benchmarks and record wall-clock times,"
    echo "    but energy columns will show 0.0 Joules."
    ENERGY_METHOD="none"
    return 0
}

# Read a RAPL energy counter (returns microjoules, or 0 if unreadable)
read_rapl_uj() {
    local path="$1/energy_uj"
    if [ -r "$path" ]; then
        cat "$path"
    else
        echo "0"
    fi
}

# ---------------------------------------------------------------------------
# Run a single benchmark, measure energy
# ---------------------------------------------------------------------------
# Arguments:
#   $1 = suite name (dacapo / renaissance)
#   $2 = benchmark name
#   $3 = gc_name
#   $4 = gc_flags
#   $5 = full java command (without GC / logging flags)
# ---------------------------------------------------------------------------
run_with_energy() {
    local suite="$1"
    local benchmark="$2"
    local gc_name="$3"
    local gc_flags="$4"
    shift 4
    local java_args=("$@")

    local out_dir="$RESULTS_DIR/$suite/$benchmark"
    mkdir -p "$out_dir"

    local energy_file="$out_dir/${gc_name}_energy.txt"
    local gc_log="$out_dir/${gc_name}_gc.log"
    local stdout_log="$out_dir/${gc_name}_stdout.txt"

    echo "  → $benchmark / $gc_name ($gc_flags)"

    # ── RAPL sysfs method ────────────────────────────────────────────────
    if [ "$ENERGY_METHOD" = "rapl_sysfs" ]; then
        local pkg_before core_before uncore_before
        pkg_before=$(read_rapl_uj "$RAPL_PKG")
        core_before=$(read_rapl_uj "$RAPL_CORE")
        uncore_before=$(read_rapl_uj "$RAPL_UNCORE")

        local start_ns
        start_ns=$(date +%s%N)

        java -XX:+UnlockExperimentalVMOptions \
             $gc_flags \
             "-Xlog:gc*:file=$gc_log:time,uptime,level,tags" \
             "${java_args[@]}" \
             > "$stdout_log" 2>&1 || {
            echo "    ✗ FAILED (exit $?)"
            echo "status=FAILED" > "$energy_file"
            return 1
        }

        local end_ns
        end_ns=$(date +%s%N)

        local pkg_after core_after uncore_after
        pkg_after=$(read_rapl_uj "$RAPL_PKG")
        core_after=$(read_rapl_uj "$RAPL_CORE")
        uncore_after=$(read_rapl_uj "$RAPL_UNCORE")

        # Handle counter wrap-around (32-bit counters wrap at max_energy_range_uj)
        local max_range
        max_range=$(cat "$RAPL_PKG/max_energy_range_uj" 2>/dev/null || echo "0")

        local pkg_delta core_delta uncore_delta
        pkg_delta=$((pkg_after - pkg_before))
        core_delta=$((core_after - core_before))
        uncore_delta=$((uncore_after - uncore_before))

        # Fix wrap-around
        if [ "$max_range" -gt 0 ]; then
            [ "$pkg_delta" -lt 0 ]    && pkg_delta=$((pkg_delta + max_range))
            [ "$core_delta" -lt 0 ]   && core_delta=$((core_delta + max_range))
            [ "$uncore_delta" -lt 0 ] && uncore_delta=$((uncore_delta + max_range))
        fi

        local wall_ms=$(( (end_ns - start_ns) / 1000000 ))

        # Convert microjoules → joules (6 decimal places)
        local pkg_j core_j uncore_j
        pkg_j=$(awk "BEGIN {printf \"%.6f\", $pkg_delta / 1000000.0}")
        core_j=$(awk "BEGIN {printf \"%.6f\", $core_delta / 1000000.0}")
        uncore_j=$(awk "BEGIN {printf \"%.6f\", $uncore_delta / 1000000.0}")

        cat > "$energy_file" <<EOF
status=SUCCESS
method=rapl_sysfs
energy_pkg_joules=$pkg_j
energy_cores_joules=$core_j
energy_uncore_joules=$uncore_j
wall_time_ms=$wall_ms
gc_name=$gc_name
benchmark=$benchmark
suite=$suite
EOF

        echo "    ✓ ${wall_ms}ms | Pkg: ${pkg_j}J  Core: ${core_j}J  Uncore: ${uncore_j}J"
        return 0
    fi

    # ── perf stat method ─────────────────────────────────────────────────
    if [ "$ENERGY_METHOD" = "perf_stat" ]; then
        local perf_output="$out_dir/${gc_name}_perf.txt"

        local start_ns
        start_ns=$(date +%s%N)

        perf stat -e power/energy-pkg/,power/energy-cores/ \
             -o "$perf_output" \
             -- java -XX:+UnlockExperimentalVMOptions \
                     $gc_flags \
                     "-Xlog:gc*:file=$gc_log:time,uptime,level,tags" \
                     "${java_args[@]}" \
             > "$stdout_log" 2>&1 || {
            echo "    ✗ FAILED (exit $?)"
            echo "status=FAILED" > "$energy_file"
            return 1
        }

        local end_ns
        end_ns=$(date +%s%N)
        local wall_ms=$(( (end_ns - start_ns) / 1000000 ))

        # Parse perf stat output.  Sample line:
        #       12.34 Joules power/energy-pkg/
        local pkg_j core_j
        pkg_j=$(grep -i "energy-pkg" "$perf_output" \
                | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]/) {print $i; exit}}' \
                || echo "0.0")
        core_j=$(grep -i "energy-cores" "$perf_output" \
                 | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]/) {print $i; exit}}' \
                 || echo "0.0")

        # Remove commas from locale-formatted numbers
        pkg_j="${pkg_j//,/}"
        core_j="${core_j//,/}"

        cat > "$energy_file" <<EOF
status=SUCCESS
method=perf_stat
energy_pkg_joules=${pkg_j:-0.0}
energy_cores_joules=${core_j:-0.0}
energy_uncore_joules=0.0
wall_time_ms=$wall_ms
gc_name=$gc_name
benchmark=$benchmark
suite=$suite
EOF

        echo "    ✓ ${wall_ms}ms | Pkg: ${pkg_j}J  Core: ${core_j}J"
        return 0
    fi

    # ── No energy method — wall-clock only ───────────────────────────────
    local start_ns
    start_ns=$(date +%s%N)

    java -XX:+UnlockExperimentalVMOptions \
         $gc_flags \
         "-Xlog:gc*:file=$gc_log:time,uptime,level,tags" \
         "${java_args[@]}" \
         > "$stdout_log" 2>&1 || {
        echo "    ✗ FAILED (exit $?)"
        echo "status=FAILED" > "$energy_file"
        return 1
    }

    local end_ns
    end_ns=$(date +%s%N)
    local wall_ms=$(( (end_ns - start_ns) / 1000000 ))

    cat > "$energy_file" <<EOF
status=SUCCESS
method=none
energy_pkg_joules=0.0
energy_cores_joules=0.0
energy_uncore_joules=0.0
wall_time_ms=$wall_ms
gc_name=$gc_name
benchmark=$benchmark
suite=$suite
EOF

    echo "    ✓ ${wall_ms}ms | Energy: N/A (no measurement method available)"
    return 0
}


# ==========================================================================
# MAIN
# ==========================================================================

echo "=================================================================="
echo "  Green Computing: Energy-Aware GC Benchmarks"
echo "  Date:  $(date)"
echo "  Java:  $(java -version 2>&1 | head -1)"
echo "  CPU:   $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
echo "=================================================================="

# Detect energy measurement method
echo ""
detect_energy_method
echo ""

# ─── DaCapo Suite ────────────────────────────────────────────────────────

if [ -f "$DACAPO_JAR" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  DaCapo Suite (Energy Profiling)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Validate available benchmarks
    AVAILABLE=$(java -jar "$DACAPO_JAR" --list-benchmarks 2>/dev/null \
                || java -jar "$DACAPO_JAR" -l 2>/dev/null \
                || echo "")

    VALID_DACAPO=()
    for bm in "${DACAPO_BENCHMARKS[@]}"; do
        if echo "$AVAILABLE" | grep -qw "$bm"; then
            VALID_DACAPO+=("$bm")
        else
            echo "  [SKIP] DaCapo benchmark '$bm' not available"
        fi
    done

    echo "  Benchmarks: ${VALID_DACAPO[*]}"
    echo "  GCs: ${!GC_CONFIGS[*]}"
    echo ""

    TOTAL_DACAPO=${#VALID_DACAPO[@]}
    DC_COUNT=0

    for benchmark in "${VALID_DACAPO[@]}"; do
        DC_COUNT=$((DC_COUNT + 1))
        echo "──── [$DC_COUNT/$TOTAL_DACAPO] DaCapo: $benchmark ────"

        for gc_name in "${!GC_CONFIGS[@]}"; do
            gc_flags="${GC_CONFIGS[$gc_name]}"
            run_with_energy "dacapo" "$benchmark" "$gc_name" "$gc_flags" \
                -jar "$DACAPO_JAR" "$benchmark" \
                || true
        done
        echo ""
    done
else
    echo "[SKIP] DaCapo JAR not found at $DACAPO_JAR"
fi

# ─── Renaissance Suite ───────────────────────────────────────────────────

if [ -f "$RENAISSANCE_JAR" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Renaissance Suite (Energy Profiling)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Benchmarks: ${RENAISSANCE_BENCHMARKS[*]}"
    echo "  GCs: ${!GC_CONFIGS[*]}"
    echo "  Repetitions: $RENAISSANCE_REPETITIONS"
    echo ""

    TOTAL_REN=${#RENAISSANCE_BENCHMARKS[@]}
    REN_COUNT=0

    for benchmark in "${RENAISSANCE_BENCHMARKS[@]}"; do
        REN_COUNT=$((REN_COUNT + 1))
        echo "──── [$REN_COUNT/$TOTAL_REN] Renaissance: $benchmark ────"

        for gc_name in "${!GC_CONFIGS[@]}"; do
            gc_flags="${GC_CONFIGS[$gc_name]}"
            local_csv="$RESULTS_DIR/renaissance/$benchmark/${gc_name}_results.csv"
            run_with_energy "renaissance" "$benchmark" "$gc_name" "$gc_flags" \
                -jar "$RENAISSANCE_JAR" "$benchmark" \
                -r "$RENAISSANCE_REPETITIONS" \
                --csv "$local_csv" \
                || true
        done
        echo ""
    done
else
    echo "[SKIP] Renaissance JAR not found at $RENAISSANCE_JAR"
fi

# ─── Summary ─────────────────────────────────────────────────────────────

TOTAL_FILES=$(find "$RESULTS_DIR" -name '*_energy.txt' 2>/dev/null | wc -l)
SUCCESS_FILES=$(grep -rl 'status=SUCCESS' "$RESULTS_DIR" 2>/dev/null | wc -l)
FAILED_FILES=$(grep -rl 'status=FAILED' "$RESULTS_DIR" 2>/dev/null | wc -l)

echo ""
echo "=================================================================="
echo "  Energy Benchmarks Complete!"
echo "  Method:     $ENERGY_METHOD"
echo "  Total runs: $TOTAL_FILES  (success: $SUCCESS_FILES, failed: $FAILED_FILES)"
echo "  Results:    $RESULTS_DIR"
echo ""
echo "  Next step:  python3 scripts/analyze_energy.py"
echo "=================================================================="
