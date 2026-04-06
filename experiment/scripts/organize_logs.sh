#!/usr/bin/env bash
# organize_logs.sh
# Collects all related log/result files per experiment scenario into a single
# flat folder each, under experiment/organized_logs/.
#
# Output structure:
#   organized_logs/
#     dacapo/
#       g1gc/           ← avrora_g1gc.log, batik_g1gc.log, …  (.log only)
#       g1gc_pause50/   ← avrora_g1gc_pause50.log, …
#       g1gc_threads2/  ← avrora_g1gc_threads2.log, …
#       shenandoah/     ← avrora_shenandoah.log, …
#       zgc_gen/        ← avrora_zgc_gen.log, …
#       zgc_nogen/      ← avrora_zgc_nogen.log, …
#     renaissance/                ← raw logs from results/renaissance/*/
#     heap_vary_chi_square/       ← raw logs from results/heap_vary/chi-square/
#     heap_vary_movie_lens/       ← raw logs from results/heap_vary/movie-lens/
#     heap_vary_page_rank/        ← raw logs from results/heap_vary/page-rank/
#     energy_dacapo/              ← raw logs from results/energy/dacapo/*/
#     energy_renaissance/         ← raw logs from results/energy/renaissance/*/
#     gcviewer_dacapo/            ← GCViewer CSVs from results/gcviewer_csv/dacapo/*/
#     gcviewer_renaissance/       ← GCViewer CSVs from results/gcviewer_csv/renaissance/*/
#     gcviewer_heap_vary_*/       ← GCViewer CSVs from results/gcviewer_csv/heap_vary/*/
#     epsilon/                    ← GCViewer CSVs from results/gcviewer_csv/epsilon/*/
#
# Files from sub-benchmark folders are prefixed with the benchmark name so
# there are no filename clashes (e.g. avrora_g1gc.log, batik_g1gc.log).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$SCRIPT_DIR/../results"
OUTPUT_DIR="$SCRIPT_DIR/../organized_logs"

# ── helpers ──────────────────────────────────────────────────────────────────

# Known GC names, longest-first so prefix matching is unambiguous.
KNOWN_GCS=("g1gc_pause50" "g1gc_threads2" "zgc_nogen" "zgc_gen" "shenandoah" "epsilon" "g1gc" "zgc")

# extract_gc <basename_no_ext>
# Prints the GC name that is a prefix of the given string.
extract_gc() {
    local name="$1"
    for gc in "${KNOWN_GCS[@]}"; do
        if [[ "$name" == "$gc" || "$name" == "${gc}_"* ]]; then
            echo "$gc"
            return
        fi
    done
    echo "$name"   # fallback: use full name
}

# copy_by_gc <src_parent> <dest_parent>
# For every sub-directory (benchmark/workload) inside <src_parent>, copies
# only *.log files into <dest_parent>/{gc}/, prefixed with the sub-dir name.
#   e.g.  results/dacapo/avrora/g1gc_pause50.log
#         → organized_logs/dacapo/g1gc_pause50/avrora_g1gc_pause50.log
copy_by_gc() {
    local src_parent="$1"
    local dest_parent="$2"
    declare -A gc_counts
    for sub_dir in "$src_parent"/*/; do
        [ -d "$sub_dir" ] || continue
        local prefix
        prefix=$(basename "$sub_dir")
        for log_file in "$sub_dir"*.log; do
            [ -f "$log_file" ] || continue
            local log_name gc dest_dir
            log_name=$(basename "$log_file" .log)
            gc=$(extract_gc "$log_name")
            dest_dir="$dest_parent/$gc"
            mkdir -p "$dest_dir"
            cp "$log_file" "$dest_dir/${prefix}_${log_name}.log"
            gc_counts[$gc]=$(( ${gc_counts[$gc]:-0} + 1 ))
        done
    done
    for gc in $(printf '%s\n' "${!gc_counts[@]}" | sort); do
        echo "  [done] $(basename "$dest_parent")/$gc/ — ${gc_counts[$gc]} file(s)"
    done
}

# copy_by_gc_single <src_dir> <dest_parent> <prefix>
# Like copy_by_gc but operates on a single flat directory (no sub-dirs).
# Each .log file is placed into <dest_parent>/{gc}/, prefixed with <prefix>.
#   e.g.  results/heap_vary/chi-square/g1gc_500M.log
#         → organized_logs/heap_vary_chi_square/g1gc/chi_square_g1gc_500M.log
copy_by_gc_single() {
    local src_dir="$1"
    local dest_parent="$2"
    local prefix="$3"
    declare -A gc_counts
    for log_file in "$src_dir"*.log; do
        [ -f "$log_file" ] || continue
        local log_name gc dest_dir
        log_name=$(basename "$log_file" .log)
        gc=$(extract_gc "$log_name")
        dest_dir="$dest_parent/$gc"
        mkdir -p "$dest_dir"
        cp "$log_file" "$dest_dir/${prefix}_${log_name}.log"
        gc_counts[$gc]=$(( ${gc_counts[$gc]:-0} + 1 ))
    done
    for gc in $(printf '%s\n' "${!gc_counts[@]}" | sort); do
        echo "  [done] $(basename "$dest_parent")/$gc/ — ${gc_counts[$gc]} file(s)"
    done
}

# ── main ─────────────────────────────────────────────────────────────────────

echo "Organizing logs into: $OUTPUT_DIR"
echo ""

# 1. DaCapo raw logs – per-GC sub-folders, .log only
copy_by_gc "$RESULTS_DIR/dacapo" "$OUTPUT_DIR/dacapo"

# 2. Renaissance raw logs – per-GC sub-folders, .log only
copy_by_gc "$RESULTS_DIR/renaissance" "$OUTPUT_DIR/renaissance"

# 3. Heap-vary raw logs – per-workload/per-GC sub-folders, .log only
for workload_dir in "$RESULTS_DIR/heap_vary"/*/; do
    [ -d "$workload_dir" ] || continue
    workload=$(basename "$workload_dir")
    folder_name="heap_vary_$(echo "$workload" | tr '-' '_')"
    prefix=$(echo "$workload" | tr '-' '_')
    copy_by_gc_single "$workload_dir" "$OUTPUT_DIR/$folder_name" "$prefix"
done

# 4. Energy – DaCapo – per-GC sub-folders, .log only
copy_by_gc "$RESULTS_DIR/energy/dacapo" "$OUTPUT_DIR/energy_dacapo"

# 5. Energy – Renaissance – per-GC sub-folders, .log only
copy_by_gc "$RESULTS_DIR/energy/renaissance" "$OUTPUT_DIR/energy_renaissance"

# 6. GCViewer CSVs – DaCapo – per-GC sub-folders (.csv files, named after GC)
copy_by_gc_csv() {
    local src_parent="$1"
    local dest_parent="$2"
    declare -A gc_counts
    for sub_dir in "$src_parent"/*/; do
        [ -d "$sub_dir" ] || continue
        local prefix
        prefix=$(basename "$sub_dir")
        for csv_file in "$sub_dir"*.csv; do
            [ -f "$csv_file" ] || continue
            local csv_name gc dest_dir
            csv_name=$(basename "$csv_file" .csv)
            gc=$(extract_gc "$csv_name")
            dest_dir="$dest_parent/$gc"
            mkdir -p "$dest_dir"
            cp "$csv_file" "$dest_dir/${prefix}_${csv_name}.csv"
            gc_counts[$gc]=$(( ${gc_counts[$gc]:-0} + 1 ))
        done
    done
    for gc in $(printf '%s\n' "${!gc_counts[@]}" | sort); do
        echo "  [done] $(basename "$dest_parent")/$gc/ — ${gc_counts[$gc]} file(s)"
    done
}

copy_by_gc_csv_single() {
    local src_dir="$1"
    local dest_parent="$2"
    local prefix="$3"
    declare -A gc_counts
    for csv_file in "$src_dir"*.csv; do
        [ -f "$csv_file" ] || continue
        local csv_name gc dest_dir
        csv_name=$(basename "$csv_file" .csv)
        gc=$(extract_gc "$csv_name")
        dest_dir="$dest_parent/$gc"
        mkdir -p "$dest_dir"
        cp "$csv_file" "$dest_dir/${prefix}_${csv_name}.csv"
        gc_counts[$gc]=$(( ${gc_counts[$gc]:-0} + 1 ))
    done
    for gc in $(printf '%s\n' "${!gc_counts[@]}" | sort); do
        echo "  [done] $(basename "$dest_parent")/$gc/ — ${gc_counts[$gc]} file(s)"
    done
}

copy_by_gc_csv "$RESULTS_DIR/gcviewer_csv/dacapo" "$OUTPUT_DIR/gcviewer_dacapo"

# 7. GCViewer CSVs – Renaissance – per-GC sub-folders
copy_by_gc_csv "$RESULTS_DIR/gcviewer_csv/renaissance" "$OUTPUT_DIR/gcviewer_renaissance"

# 8. GCViewer CSVs – Heap-vary – per-workload/per-GC sub-folders
for workload_dir in "$RESULTS_DIR/gcviewer_csv/heap_vary"/*/; do
    [ -d "$workload_dir" ] || continue
    workload=$(basename "$workload_dir")
    folder_name="gcviewer_heap_vary_$(echo "$workload" | tr '-' '_')"
    prefix=$(echo "$workload" | tr '-' '_')
    copy_by_gc_csv_single "$workload_dir" "$OUTPUT_DIR/$folder_name" "$prefix"
done

# 9. Epsilon – per-GC sub-folders
copy_by_gc_csv "$RESULTS_DIR/gcviewer_csv/epsilon" "$OUTPUT_DIR/epsilon"

# ── zip children and remove original folders ─────────────────────────────────

echo ""
echo "Zipping GC sub-folders…"
zipped=0
for top_dir in "$OUTPUT_DIR"/*/; do
    [ -d "$top_dir" ] || continue
    for gc_dir in "$top_dir"*/; do
        [ -d "$gc_dir" ] || continue
        zip_name="${gc_dir%/}.zip"
        # -j: junk paths (store files flat inside the zip)
        zip -j -q "$zip_name" "$gc_dir"*
        rm -rf "$gc_dir"
        echo "  [zipped] ${zip_name#"$OUTPUT_DIR/"}"
        (( zipped++ )) || true
    done
done
echo "  $zipped zip archive(s) created."

# ── summary ──────────────────────────────────────────────────────────────────

echo ""
echo "Done. Summary:"
echo "─────────────────────────────────────────────────────"
for top_dir in "$OUTPUT_DIR"/*/; do
    [ -d "$top_dir" ] || continue
    top=$(basename "$top_dir")
    for zip_file in "$top_dir"*.zip; do
        [ -f "$zip_file" ] || continue
        count=$(zipinfo -1 "$zip_file" 2>/dev/null | wc -l)
        printf "  %-44s %4d file(s)\n" "$top/$(basename "$zip_file")" "$count"
    done
done
echo "─────────────────────────────────────────────────────"
total=$(find "$OUTPUT_DIR" -name "*.zip" | wc -l)
echo "  Total: $total zip archive(s)"
