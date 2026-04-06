#!/usr/bin/env python3
"""
Graph Generation Script for Extended JVM GC Performance Study
==============================================================

Reads pre-aggregated CSVs from results/csv/ for DaCapo and Renaissance
benchmarks, and GCViewer CSVs for heap-varying experiments. Generates
publication-quality comparison charts with a light theme.

Usage:
    cd experiment/
    python3 scripts/generate_graphs.py

Output:
    graphs/dacapo/              — DaCapo benchmark metric charts (core 4 GCs)
    graphs/dacapo/zgc_comparison/   — ZGC Gen vs Non-Gen
    graphs/dacapo/g1gc_tuning/      — G1GC tuning variants
    graphs/renaissance/         — Renaissance benchmark metric charts
    graphs/renaissance/zgc_comparison/
    graphs/renaissance/g1gc_tuning/
    graphs/heap_vary/{chi-square,movie-lens,page-rank}/  — Heap-varying line charts

Dependencies:
    pip install matplotlib numpy pandas
"""

import re
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import os

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
GCVIEWER_DIR = BASE_DIR / "results" / "gcviewer_csv"
GRAPHS_DIR = BASE_DIR / "graphs"
CSV_DIR = BASE_DIR / "results" / "csv"

# GC display configuration: internal name -> (display label, color)
GC_STYLES = {
    "g1gc":          ("G1GC",               "#818cf8"),   # indigo
    "shenandoah":    ("Shenandoah",         "#fb923c"),   # orange
    "zgc_nogen":     ("ZGC (Non-Gen)",      "#34d399"),   # emerald
    "zgc_gen":       ("ZGC (Gen)",          "#f472b6"),   # pink
    "g1gc_pause50":  ("G1GC (Pause 50ms)",  "#60a5fa"),   # blue
    "g1gc_threads2": ("G1GC (2 Threads)",   "#a78bfa"),   # violet
}

GC_ORDER = ["g1gc", "shenandoah", "zgc_nogen", "zgc_gen",
            "g1gc_pause50", "g1gc_threads2"]

CORE_GCS = ["g1gc", "shenandoah", "zgc_nogen", "zgc_gen"]
ZGC_GCS = ["zgc_nogen", "zgc_gen"]
G1_TUNING_GCS = ["g1gc", "g1gc_pause50", "g1gc_threads2"]

# Primary metrics to chart from the aggregate CSVs
# Key: CSV column -> (display label, unit, convert_fn or None)
METRICS = {
    "totalHeapAllocMax":  ("JVM Heap Size Allocation",  "MB",    None),
    "totalHeapUsedMax":   ("Peak Heap Used",            "MB",    None),
    "throughput":         ("Throughput",                 "%",     None),
    "avgPause":           ("Avg Pause Time",            "ms",    lambda s: s * 1000),
    "maxPause":           ("Max Pause Time",            "ms",    lambda s: s * 1000),
    "gcPerformance":      ("GC Performance",            "MB/s",  None),
    "wallTimeSec":        ("Execution Time",            "s",     None),
    "freedMemoryPerMin":  ("Allocation Rate",           "MB/min", None),
    "pauseCount":         ("GC Pause Count",            "",      None),
    "accumPause":         ("Total Pause Time",          "ms",    lambda s: s * 1000),
    "freedMemory":        ("Total Freed Memory",        "MB",    None),
    "footprint":          ("Memory Footprint",          "MB",    None),
}

# Subset used for heap-vary line charts (GCViewer metrics)
HEAP_VARY_METRICS = {
    "throughput":        ("Throughput",         "%",    None),
    "avgPause":          ("Avg Pause Time",     "ms",   lambda s: s * 1000),
    "maxPause":          ("Max Pause Time",     "ms",   lambda s: s * 1000),
    "totalHeapUsedMax":  ("Peak Heap Used",     "MB",   None),
    "totalHeapAllocMax": ("Heap Allocated",     "MB",   None),
    "gcPerformance":     ("GC Performance",     "MB/s", None),
    "pauseCount":        ("GC Pause Count",     "",     None),
    "wallTimeSec":       ("Execution Time",     "s",    None),
}

# Light theme colors
LIGHT_BG     = "#f8fafc"
CARD_BG      = "#ffffff"
TEXT_COLOR   = "#0f172a"
GRID_COLOR   = "#e2e8f0"
BAR_EDGE     = "#94a3b8"


# ---------------------------------------------------------------------------
# THEME
# ---------------------------------------------------------------------------

def setup_light_theme():
    """Configure matplotlib for a clean light theme matching the study style."""
    plt.rcParams.update({
        "figure.facecolor":  LIGHT_BG,
        "axes.facecolor":    CARD_BG,
        "axes.edgecolor":    GRID_COLOR,
        "axes.labelcolor":   TEXT_COLOR,
        "axes.titlesize":    14,
        "axes.labelsize":    11,
        "text.color":        TEXT_COLOR,
        "xtick.color":       TEXT_COLOR,
        "ytick.color":       TEXT_COLOR,
        "xtick.labelsize":   9,
        "ytick.labelsize":   9,
        "grid.color":        GRID_COLOR,
        "grid.alpha":        0.6,
        "legend.facecolor":  CARD_BG,
        "legend.edgecolor":  GRID_COLOR,
        "legend.fontsize":   9,
        "figure.dpi":        150,
        "savefig.dpi":       300,
        "savefig.facecolor": LIGHT_BG,
        "savefig.edgecolor": LIGHT_BG,
        "font.family":       "sans-serif",
        "font.sans-serif":   ["DejaVu Sans", "Helvetica", "Arial"],
    })


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------

def load_csv_data(csv_path, gc_filter=None):
    """
    Load a pre-aggregated metrics CSV into a nested dict:
        {benchmark: {gc_config: {metric: value, ...}}}
    """
    data = {}
    if not os.path.exists(csv_path):
        print(f"  [SKIP] {csv_path} not found")
        return data

    df = pd.read_csv(csv_path)

    if gc_filter:
        df = df[df["gc_config"].isin(gc_filter)]

    for _, row in df.iterrows():
        bench = row["benchmark"]
        gc = row["gc_config"]
        if bench not in data:
            data[bench] = {}
        metrics = {}
        for col in df.columns:
            if col in ("benchmark", "gc_config"):
                continue
            val = row[col]
            if pd.notna(val):
                try:
                    metrics[col] = float(val)
                except (ValueError, TypeError):
                    pass
        data[bench][gc] = metrics

    return data


def parse_gcviewer_summary(csv_path):
    """
    Parse a GCViewer SUMMARY CSV file (semicolon-separated: name; value; unit).
    Returns a dict of {metric_name: float_value}.
    """
    metrics = {}
    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(";")]
                if len(parts) < 2:
                    continue
                name = parts[0]
                raw_val = parts[1].replace(",", "")
                try:
                    metrics[name] = float(raw_val)
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return metrics


def parse_time_file(time_path):
    """Read a wall-clock timing file (milliseconds or FAILED)."""
    try:
        with open(time_path, "r") as f:
            content = f.read().strip()
            if content == "FAILED":
                return None
            return float(content)
    except (FileNotFoundError, ValueError):
        return None


def load_heap_vary_data(exp_dir, gcviewer_dir):
    """
    Load heap-varying experiment data from raw log/time files + GCViewer CSVs.
    Returns: {benchmark: {heap_size_mb: {gc_name: {metric: value, ...}}}}
    """
    exp_dir = Path(exp_dir)
    gcviewer_dir = Path(gcviewer_dir)
    data = {}
    if not os.path.exists(exp_dir):
        print(f"  [SKIP] {exp_dir} does not exist")
        return data

    for bench_dir in sorted(os.listdir(exp_dir)):
        bench_dir = exp_dir / bench_dir
        if not os.path.isdir(bench_dir):
            continue
        bench_name = os.path.basename(bench_dir)
        data[bench_name] = {}

        for log_file in sorted(os.listdir(bench_dir)):
            log_file = os.path.join(bench_dir, log_file)
            if not log_file.endswith(".log"):
                continue
            m = re.match(r"^(.+?)_(\d+)M\.log$", os.path.basename(log_file))
            if not m:
                continue
            gc_name = m.group(1)
            heap_size = int(m.group(2))

            if heap_size not in data[bench_name]:
                data[bench_name][heap_size] = {}

            gcv_csv = gcviewer_dir / "heap_vary" / bench_name / f"{gc_name}_{heap_size}M.csv"
            metrics = parse_gcviewer_summary(gcv_csv)

            time_file = bench_dir / f"{gc_name}_{heap_size}M_time.txt"
            wall_time = parse_time_file(time_file)
            if wall_time is not None:
                metrics["wallTimeMs"] = wall_time
                metrics["wallTimeSec"] = wall_time / 1000.0

            if metrics:
                data[bench_name][heap_size][gc_name] = metrics

    return data


def load_experiment_data(exp_name, exp_dir, gcviewer_dir):
    """
    Load all data for a standard experiment (dacapo or renaissance) from
    GCViewer CSVs and wall-clock timing files.
    Returns: {benchmark: {gc_name: {metric: value, ...}}}
    """
    exp_dir = Path(exp_dir)
    gcviewer_dir = Path(gcviewer_dir)
    data = {}
    if not os.path.exists(exp_dir):
        print(f"  [SKIP] {exp_dir} does not exist")
        return data

    for bench_dir in sorted(exp_dir.iterdir()):
        if not bench_dir.is_dir():
            continue
        bench_name = bench_dir.name
        data[bench_name] = {}

        for gc_name in GC_ORDER:
            gcv_csv = gcviewer_dir / exp_name / bench_name / f"{gc_name}.csv"
            metrics = parse_gcviewer_summary(gcv_csv)

            time_file = bench_dir / f"{gc_name}_time.txt"
            wall_time = parse_time_file(time_file)
            if wall_time is not None:
                metrics["wallTimeMs"] = wall_time
                metrics["wallTimeSec"] = wall_time / 1000.0

            if metrics:
                data[bench_name][gc_name] = metrics

    return data


def generate_aggregate_csv(data, output_path):
    """
    Write an aggregate CSV combining all metrics for an experiment.
    One row per (benchmark, gc_name) pair.
    """
    if not data:
        return

    all_keys = set()
    for bench in data:
        for gc in data[bench]:
            all_keys.update(data[bench][gc].keys())

    sorted_keys = sorted(all_keys)
    headers = ["benchmark", "gc_config"] + sorted_keys

    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for bench in sorted(data.keys()):
            for gc_name in GC_ORDER:
                if gc_name not in data[bench]:
                    continue
                metrics = data[bench][gc_name]
                row = [bench, gc_name]
                for key in sorted_keys:
                    row.append(metrics.get(key, ""))
                writer.writerow(row)

    print(f"  [CSV] {output_path.name} ({sum(len(data[b]) for b in data)} rows)")


# ---------------------------------------------------------------------------
# CHART GENERATORS
# ---------------------------------------------------------------------------

def _fmt_value(val):
    """Format a bar value label."""
    if val >= 10000:
        return f"{val:,.0f}"
    elif val >= 100:
        return f"{val:.0f}"
    elif val >= 10:
        return f"{val:.1f}"
    elif val >= 1:
        return f"{val:.2f}"
    elif val >= 0.01:
        return f"{val:.3f}"
    else:
        return f"{val:.4f}"


def plot_grouped_bar(data, metric_key, y_label, title, output_path,
                     gc_list=None, convert_fn=None):
    """
    Grouped bar chart: benchmarks on x-axis, one bar per GC.
    """
    setup_light_theme()

    benchmarks = sorted(data.keys())
    if not benchmarks:
        print(f"  [SKIP] No data for {title}")
        return

    if gc_list is None:
        gc_set = set()
        for bench in benchmarks:
            gc_set.update(data[bench].keys())
        gc_list = [g for g in GC_ORDER if g in gc_set]

    if not gc_list:
        print(f"  [SKIP] No GC data for {title}")
        return

    n_bench = len(benchmarks)
    n_gc = len(gc_list)

    fig, ax = plt.subplots(figsize=(max(10, n_bench * 1.8), 6))

    x = np.arange(n_bench)
    bar_width = 0.8 / n_gc
    offsets = np.linspace(-(n_gc - 1) * bar_width / 2,
                           (n_gc - 1) * bar_width / 2, n_gc)

    for i, gc_name in enumerate(gc_list):
        label, color = GC_STYLES.get(gc_name, (gc_name, "#94a3b8"))
        values = []
        for bench in benchmarks:
            val = data.get(bench, {}).get(gc_name, {}).get(metric_key, 0)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                val = 0
            if convert_fn:
                val = convert_fn(val)
            values.append(val)

        bars = ax.bar(x + offsets[i], values, bar_width * 0.9,
                      label=label, color=color,
                      edgecolor=BAR_EDGE, linewidth=0.5,
                      alpha=0.9, zorder=3)

        # Value labels on top of each bar
        for bar, val in zip(bars, values):
            if val > 0:
                fontsize = 6 if n_bench > 6 else 7
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height(),
                        _fmt_value(val),
                        ha="center", va="bottom",
                        fontsize=fontsize, color=TEXT_COLOR,
                        fontweight="bold", rotation=45)

    ax.set_xlabel("Benchmark", fontsize=12, fontweight="bold")
    ax.set_ylabel(y_label, fontsize=12, fontweight="bold")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(benchmarks, rotation=30, ha="right", fontsize=9)
    ax.legend(title="group", loc="upper right", framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)

    os.makedirs(output_path.parent, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.2)
    plt.close()
    print(f"  [OK] {output_path.name}")


def plot_heap_vary_lines(heap_data, metric_key, y_label,
                         base_output_dir, convert_fn=None,
                         gc_filter=None):
    """
    Line charts: one per benchmark saved in per-benchmark subdirectories.
    Heap size on x-axis, one line per GC.
    """
    setup_light_theme()

    for bench_name, size_data in sorted(heap_data.items()):
        if not size_data:
            continue

        heap_sizes = sorted(size_data.keys())

        gc_set = set()
        for hs in heap_sizes:
            gc_set.update(size_data[hs].keys())

        if gc_filter:
            gc_list = [g for g in gc_filter if g in gc_set]
        else:
            gc_list = [g for g in GC_ORDER if g in gc_set]

        if not gc_list:
            continue

        fig, ax = plt.subplots(figsize=(9, 5.5))

        for gc_name in gc_list:
            label, color = GC_STYLES.get(gc_name, (gc_name, "#94a3b8"))

            xs, ys = [], []
            for hs in heap_sizes:
                val = size_data.get(hs, {}).get(gc_name, {}).get(metric_key)
                if val is not None:
                    if convert_fn:
                        val = convert_fn(val)
                    xs.append(hs)
                    ys.append(val)

            if not xs:
                continue

            ax.plot(xs, ys, "o-", label=label, color=color,
                    linewidth=2.5, markersize=7,
                    markeredgecolor="white", markeredgewidth=1,
                    alpha=0.95, zorder=3)
            # Subtle glow effect
            ax.plot(xs, ys, "-", color=color,
                    linewidth=6, alpha=0.12, zorder=2)

        ax.set_xlabel("JVM Heap Size (MB)", fontsize=12, fontweight="bold")
        ax.set_ylabel(y_label, fontsize=12, fontweight="bold")
        ax.set_title(f"{bench_name} — {y_label}",
                     fontsize=14, fontweight="bold", pad=15)
        ax.legend(title="group", loc="best", framealpha=0.9)
        ax.grid(True, alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)

        out_dir = base_output_dir / bench_name
        os.makedirs(out_dir, exist_ok=True)
        out_file = out_dir / f"heap_vary_{metric_key}.png"
        plt.tight_layout()
        plt.savefig(out_file, bbox_inches="tight", pad_inches=0.2)
        plt.close()
        print(f"  [OK] {bench_name}/{out_file.name}")


def plot_heap_vary_cross_benchmark(heap_data, heap_size, metric_key,
                                   y_label, title, output_path,
                                   convert_fn=None, gc_filter=None):
    """
    Grouped bar chart comparing all heap-vary benchmarks at a fixed heap size.
    """
    bar_data = {}
    for bench_name, size_data in sorted(heap_data.items()):
        if heap_size not in size_data:
            continue
        bar_data[bench_name] = size_data[heap_size]

    if not bar_data:
        print(f"  [SKIP] No data for heap size {heap_size}MB")
        return

    plot_grouped_bar(bar_data, metric_key, y_label, title, output_path,
                     gc_list=gc_filter or CORE_GCS, convert_fn=convert_fn)


# ---------------------------------------------------------------------------
# SUITE CHART GENERATION
# ---------------------------------------------------------------------------

def generate_suite_charts(data, suite_name, output_dir, gc_list, tag=""):
    """
    Generate all primary metric charts for a benchmark suite.
    """
    os.makedirs(output_dir, exist_ok=True)

    for metric_key, (label, unit, convert_fn) in METRICS.items():
        y_label = f"{label} ({unit})" if unit else label
        title = f"{suite_name}: {label}"
        fname = f"{suite_name.lower().replace(' ', '_')}_{metric_key}{tag}.png"

        plot_grouped_bar(
            data, metric_key, y_label, title,
            output_dir / fname,
            gc_list=gc_list,
            convert_fn=convert_fn,
        )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  Graph Generation for Extended JVM GC Performance Study")
    print("=" * 70)

    # --- Directory setup ---
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    dacapo_dir = BASE_DIR / "graphs" / "dacapo"
    renaissance_dir = BASE_DIR / "graphs" / "renaissance"
    heap_vary_dir = BASE_DIR / "graphs" / "heap_vary"

    os.makedirs(dacapo_dir, exist_ok=True)
    os.makedirs(renaissance_dir, exist_ok=True)
    os.makedirs(heap_vary_dir, exist_ok=True)

    # =====================================================================
    # PHASE 1: DaCapo and Renaissance from pre-aggregated CSVs
    # =====================================================================

    print("\n[1/3] Loading data from GCViewer + CSVs...")

    dacapo_csv = BASE_DIR / "results" / "csv" / "dacapo_all_metrics.csv"
    renaissance_csv = BASE_DIR / "results" / "csv" / "renaissance_all_metrics.csv"

    # Only generate aggregate CSVs if they don't already exist.
    # If they exist, they may have been cleaned by fix_results_csvs.py —
    # regenerating from raw GCViewer data would reintroduce broken values.
    if not dacapo_csv.exists():
        dacapo_raw = load_experiment_data("dacapo", BASE_DIR / "results" / "dacapo", GCVIEWER_DIR)
        if dacapo_raw:
            generate_aggregate_csv(dacapo_raw, dacapo_csv)
    if not renaissance_csv.exists():
        renaissance_raw = load_experiment_data("renaissance", BASE_DIR / "results" / "renaissance", GCVIEWER_DIR)
        if renaissance_raw:
            generate_aggregate_csv(renaissance_raw, renaissance_csv)

    dacapo_core = load_csv_data(dacapo_csv, gc_filter=CORE_GCS)
    print(f"  DaCapo: {len(dacapo_core)} benchmarks loaded")

    renaissance_core = load_csv_data(renaissance_csv, gc_filter=CORE_GCS)
    print(f"  Renaissance: {len(renaissance_core)} benchmarks loaded")

    # --- DaCapo: core 4 GCs ---
    print("\n[2/3] Generating DaCapo & Renaissance charts...")

    if dacapo_core:
        print("  DaCapo — Core GCs (G1GC, Shenandoah, ZGC Non-Gen, ZGC Gen):")
        generate_suite_charts(dacapo_core, "DaCapo", dacapo_dir, CORE_GCS)

    # --- DaCapo: ZGC comparison ---
    dacapo_zgc = load_csv_data(dacapo_csv, gc_filter=ZGC_GCS)
    if dacapo_zgc:
        print("  DaCapo — ZGC Gen vs Non-Gen comparison:")
        generate_suite_charts(
            dacapo_zgc, "DaCapo ZGC Comparison",
            dacapo_dir / "zgc_comparison", ZGC_GCS, "_zgc"
        )

    # --- DaCapo: G1GC tuning ---
    dacapo_g1 = load_csv_data(dacapo_csv, gc_filter=G1_TUNING_GCS)
    if dacapo_g1:
        print("  DaCapo — G1GC tuning comparison:")
        generate_suite_charts(
            dacapo_g1, "DaCapo G1GC Tuning",
            dacapo_dir / "g1gc_tuning", G1_TUNING_GCS, "_g1tuning"
        )

    # --- Renaissance: core 4 GCs ---
    if renaissance_core:
        print("  Renaissance — Core GCs:")
        generate_suite_charts(
            renaissance_core, "Renaissance", renaissance_dir, CORE_GCS
        )

    # --- Renaissance: ZGC comparison ---
    renaissance_zgc = load_csv_data(renaissance_csv, gc_filter=ZGC_GCS)
    if renaissance_zgc:
        print("  Renaissance — ZGC Gen vs Non-Gen comparison:")
        generate_suite_charts(
            renaissance_zgc, "Renaissance ZGC Comparison",
            renaissance_dir / "zgc_comparison", ZGC_GCS, "_zgc"
        )

    # --- Renaissance: G1GC tuning ---
    renaissance_g1 = load_csv_data(renaissance_csv, gc_filter=G1_TUNING_GCS)
    if renaissance_g1:
        print("  Renaissance — G1GC tuning comparison:")
        generate_suite_charts(
            renaissance_g1, "Renaissance G1GC Tuning",
            renaissance_dir / "g1gc_tuning", G1_TUNING_GCS, "_g1tuning"
        )

    # =====================================================================
    # PHASE 2: Heap-Varying experiments
    # =====================================================================

    print("\n[3/3] Generating Heap-Varying charts...")

    heap_vary_data = load_heap_vary_data(
        BASE_DIR / "results" / "heap_vary", GCVIEWER_DIR
    )
    print(f"  Heap-Vary: {len(heap_vary_data)} benchmarks loaded")

    if heap_vary_data:
        # Per-benchmark line charts (saved in per-benchmark subdirectories)
        for metric_key, (label, unit, convert_fn) in HEAP_VARY_METRICS.items():
            y_label = f"{label} ({unit})" if unit else label
            plot_heap_vary_lines(
                heap_vary_data, metric_key, y_label,
                heap_vary_dir, convert_fn=convert_fn,
                gc_filter=CORE_GCS,
            )

        # Cross-benchmark comparison at fixed heap sizes
        for heap_size in [1000, 1500]:
            cross_dir = heap_vary_dir / f"cross_benchmark_{heap_size}M"
            os.makedirs(cross_dir, exist_ok=True)
            for metric_key, (label, unit, convert_fn) in HEAP_VARY_METRICS.items():
                y_label = f"{label} ({unit})" if unit else label
                plot_heap_vary_cross_benchmark(
                    heap_vary_data, heap_size, metric_key, y_label,
                    f"Heap Vary {heap_size}MB: {label}",
                    cross_dir / f"cross_{metric_key}_{heap_size}M.png",
                    convert_fn=convert_fn,
                    gc_filter=CORE_GCS,
                )

    # --- Summary ---
    total_graphs = sum(1 for _ in GRAPHS_DIR.rglob("*.png"))
    print()
    print("=" * 70)
    print(f"  Generation complete!")
    print(f"  Graphs: {total_graphs} PNG files in graphs/")
    print("=" * 70)


if __name__ == "__main__":
    main()
