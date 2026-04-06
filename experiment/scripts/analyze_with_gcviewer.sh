#!/bin/bash
# =============================================================================
# GCViewer Batch Analysis Script
# =============================================================================
# Runs GCViewer CLI on all GC log files in the results directory
# and exports CSV + summary reports to results/gcviewer_csv/
#
# GCViewer CLI usage:
#   java -jar gcviewer.jar <gc.log> <output.csv> [<output_chart.png>] [-t PLAIN_SUMMARY]
#
# This produces ~60 metrics per log file in CSV format.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
GCVIEWER_JAR="$BASE_DIR/tools/gcviewer-1.36.jar"
RESULTS_DIR="$BASE_DIR/results"
OUTPUT_DIR="$RESULTS_DIR/gcviewer_csv"

if [ ! -f "$GCVIEWER_JAR" ]; then
    echo "ERROR: GCViewer JAR not found at $GCVIEWER_JAR"
    exit 1
fi

echo "=============================================="
echo " GCViewer Batch Analysis"
echo " Date: $(date)"
echo "=============================================="

# Process all experiments
process_logs() {
    local src_dir="$1"
    local out_dir="$2"
    local exp_name="$3"
    
    if [ ! -d "$src_dir" ]; then
        echo "  SKIP: $src_dir does not exist"
        return
    fi
    
    echo ""
    echo "--- Processing $exp_name ---"
    
    find "$src_dir" -name "*.log" -type f | sort | while read -r log_file; do
        # Compute relative path for organized output
        rel_path="${log_file#$src_dir/}"
        out_csv="$out_dir/${rel_path%.log}.csv"
        out_summary="$out_dir/${rel_path%.log}_summary.txt"
        
        # Create output directory
        mkdir -p "$(dirname "$out_csv")"
        
        echo "  → Analyzing: $rel_path"
        
        # Run GCViewer CLI — SUMMARY format (aggregate metrics per log)
        java -jar "$GCVIEWER_JAR" "$log_file" "$out_csv" -t SUMMARY 2>/dev/null || {
            echo "    ⚠ GCViewer failed for $rel_path (may be unsupported log format)"
            continue
        }
        
        if [ -f "$out_csv" ]; then
            echo "    ✓ CSV: $(basename "$out_csv")"
        fi
    done
}

# Process each experiment directory
process_logs "$RESULTS_DIR/dacapo"     "$OUTPUT_DIR/dacapo"     "DaCapo Benchmarks"
process_logs "$RESULTS_DIR/renaissance" "$OUTPUT_DIR/renaissance" "Renaissance Benchmarks"
process_logs "$RESULTS_DIR/heap_vary"   "$OUTPUT_DIR/heap_vary"   "Heap-Varying Experiments"
process_logs "$RESULTS_DIR/epsilon"     "$OUTPUT_DIR/epsilon"     "Epsilon GC Baseline"

echo ""
echo "=============================================="
echo " GCViewer Analysis Complete!"
echo " CSV reports: $OUTPUT_DIR"
echo "=============================================="
