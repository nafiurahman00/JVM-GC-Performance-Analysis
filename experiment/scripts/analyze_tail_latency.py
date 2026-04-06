#!/usr/bin/env python3
"""
Tail Latency Analysis for JVM GC Benchmarks
=============================================

Parses raw Java 21 GC logs (already collected in results/dacapo and
results/renaissance) to extract every individual STW pause duration.
Computes P50, P95, P99, P99.9 percentiles per benchmark × GC config and
generates four chart types:

    1. Percentile bar charts  — P50/P95/P99/P99.9 grouped by GC
    2. CDF plots              — one per benchmark, all GCs overlaid
    3. Box plots              — pause distribution shape per GC
    4. P99 heatmap            — benchmark × GC config

Output:
    results/csv/tail_latency_dacapo.csv
    results/csv/tail_latency_renaissance.csv
    graphs/tail_latency/...

Usage:
    cd experiment/
    python3 scripts/analyze_tail_latency.py

Dependencies:
    pip install matplotlib numpy scipy
"""

import re
import csv
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
GRAPHS_DIR = BASE_DIR / "graphs" / "tail_latency"
CSV_DIR = RESULTS_DIR / "csv"

SUITES = {
    "dacapo":      RESULTS_DIR / "dacapo",
    "renaissance": RESULTS_DIR / "renaissance",
}

GC_CONFIGS = ["g1gc", "shenandoah", "zgc_nogen", "zgc_gen",
              "g1gc_pause50", "g1gc_threads2"]

DACAPO_BENCHMARKS = ["avrora", "batik", "fop", "h2", "luindex",
                     "lusearch", "pmd", "sunflow", "tomcat", "xalan"]

RENAISSANCE_BENCHMARKS = ["chi-square", "dec-tree", "dotty", "finagle-http",
                           "movie-lens", "page-rank", "philosophers", "scala-kmeans"]

GC_STYLES = {
    "g1gc":          ("G1GC",               "#818cf8"),
    "shenandoah":    ("Shenandoah",         "#fb923c"),
    "zgc_nogen":     ("ZGC (Non-Gen)",      "#34d399"),
    "zgc_gen":       ("ZGC (Gen)",          "#f472b6"),
    "g1gc_pause50":  ("G1GC (Pause 50ms)",  "#60a5fa"),
    "g1gc_threads2": ("G1GC (2 Threads)",   "#a78bfa"),
}

GC_ORDER = ["g1gc", "shenandoah", "zgc_nogen", "zgc_gen",
            "g1gc_pause50", "g1gc_threads2"]

PERCENTILES = [50, 95, 99, 99.9]

# Light theme — matches generate_graphs.py
LIGHT_BG   = "#f8fafc"
CARD_BG    = "#ffffff"
TEXT_COLOR = "#0f172a"
GRID_COLOR = "#e2e8f0"
BAR_EDGE   = "#94a3b8"

# ---------------------------------------------------------------------------
# LOG PARSING
# ---------------------------------------------------------------------------

# G1GC / Shenandoah: final summary line with `[gc    ]` tag (not `[gc,start]`)
#   e.g. GC(0) Pause Young (Normal) ... 3.269ms
#        GC(0) Pause Init Mark ...     0.539ms
_RE_G1_SHENA = re.compile(
    r'\[gc\s+\].*GC\(\d+\)\s+Pause\s+.+?([\d.]+)ms\s*$'
)

# ZGC (gen + nogen): phases tag
#   e.g. GC(0) Pause Mark Start 0.017ms
#        GC(0) Y: Pause Mark End 0.021ms
#        GC(0) O: Pause Relocate Start 0.018ms
_RE_ZGC = re.compile(
    r'\[gc,phases\s*\].*GC\(\d+\)\s+(?:[YyOo]:\s*)?Pause\s+\S.*?([\d.]+)ms\s*$'
)


def parse_gc_log(log_path: Path) -> list[float]:
    """
    Extract every STW pause duration (ms) from a single GC log file.
    Works for G1GC, Shenandoah, ZGC (non-gen and gen).
    Returns a list of float values in milliseconds.
    """
    pauses = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = _RE_G1_SHENA.search(line) or _RE_ZGC.search(line)
                if m:
                    try:
                        pauses.append(float(m.group(1)))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return pauses


# ---------------------------------------------------------------------------
# DATA COLLECTION
# ---------------------------------------------------------------------------

def collect_pauses(suite_dir: Path, benchmarks: list[str]) -> dict:
    """
    Returns nested dict: data[benchmark][gc_config] = [pause_ms, ...]
    """
    data = defaultdict(lambda: defaultdict(list))
    for bm in benchmarks:
        bm_dir = suite_dir / bm
        if not bm_dir.is_dir():
            continue
        for gc in GC_CONFIGS:
            log_file = bm_dir / f"{gc}.log"
            pauses = parse_gc_log(log_file)
            if pauses:
                data[bm][gc] = pauses
                print(f"  {bm:20s} {gc:16s}  n={len(pauses):4d}  "
                      f"median={np.median(pauses):.3f}ms  "
                      f"p99={np.percentile(pauses, 99):.3f}ms")
            else:
                print(f"  {bm:20s} {gc:16s}  (no data)")
    return data


def compute_percentile_table(data: dict, benchmarks: list[str]) -> list[dict]:
    """
    Flatten data into rows for CSV output.
    Columns: suite, benchmark, gc_config, n_pauses, min, max,
             p50, p75, p90, p95, p99, p99_9, mean, std
    """
    rows = []
    for bm in benchmarks:
        for gc in GC_CONFIGS:
            pauses = data[bm].get(gc, [])
            if not pauses:
                continue
            arr = np.array(pauses)
            rows.append({
                "benchmark":  bm,
                "gc_config":  gc,
                "n_pauses":   len(arr),
                "min_ms":     round(float(arr.min()), 4),
                "mean_ms":    round(float(arr.mean()), 4),
                "std_ms":     round(float(arr.std()), 4),
                "p50_ms":     round(float(np.percentile(arr, 50)), 4),
                "p75_ms":     round(float(np.percentile(arr, 75)), 4),
                "p90_ms":     round(float(np.percentile(arr, 90)), 4),
                "p95_ms":     round(float(np.percentile(arr, 95)), 4),
                "p99_ms":     round(float(np.percentile(arr, 99)), 4),
                "p99_9_ms":   round(float(np.percentile(arr, 99.9)), 4),
                "max_ms":     round(float(arr.max()), 4),
            })
    return rows


def save_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        print(f"  WARNING: no rows to write to {out_path}")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  Saved {len(rows)} rows → {out_path}")


# ---------------------------------------------------------------------------
# CHART HELPERS
# ---------------------------------------------------------------------------

def _base_fig(w=14, h=6):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=LIGHT_BG)
    ax.set_facecolor(CARD_BG)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    ax.grid(axis="y", color=GRID_COLOR, linewidth=0.6, linestyle="--", alpha=0.4)
    return fig, ax


def _save(fig, path: Path, tight=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {path.name}")


# ---------------------------------------------------------------------------
# CHART 1: Percentile grouped bar chart (per suite, all benchmarks aggregated)
# ---------------------------------------------------------------------------

def plot_percentile_bars_aggregated(data: dict, benchmarks: list[str],
                                    suite: str, out_dir: Path):
    """
    For each GC config, aggregate all pause durations across all benchmarks
    and plot P50/P95/P99/P99.9 as a grouped bar chart.
    """
    pct_labels = ["P50", "P95", "P99", "P99.9"]
    pct_values = [50, 95, 99, 99.9]

    gcs_present = [gc for gc in GC_ORDER
                   if any(data[bm].get(gc) for bm in benchmarks)]

    n_gc = len(gcs_present)
    n_pct = len(pct_labels)
    x = np.arange(n_pct)
    bar_w = 0.8 / n_gc

    fig, ax = _base_fig(w=12, h=6)

    for i, gc in enumerate(gcs_present):
        label, color = GC_STYLES[gc]
        all_pauses = []
        for bm in benchmarks:
            all_pauses.extend(data[bm].get(gc, []))
        if not all_pauses:
            continue
        arr = np.array(all_pauses)
        values = [np.percentile(arr, p) for p in pct_values]
        offset = (i - n_gc / 2 + 0.5) * bar_w
        bars = ax.bar(x + offset, values, bar_w * 0.85,
                      label=label, color=color, edgecolor=BAR_EDGE,
                      linewidth=0.6, alpha=0.88)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.02,
                    f"{val:.2f}", ha="center", va="bottom",
                    fontsize=6.5, color=TEXT_COLOR, rotation=45)

    ax.set_xticks(x)
    ax.set_xticklabels(pct_labels, fontsize=11)
    ax.set_xlabel("Percentile", fontsize=11)
    ax.set_ylabel("Pause Time (ms)", fontsize=11)
    ax.set_title(f"GC Pause Tail Latency — {suite.title()} Suite (All Benchmarks)",
                 fontsize=13, fontweight="bold")
    leg = ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
                    labelcolor=TEXT_COLOR, loc="upper left")
    _save(fig, out_dir / f"{suite}_tail_latency_aggregated.png")


# ---------------------------------------------------------------------------
# CHART 2: Per-benchmark P99 and P99.9 grouped bars
# ---------------------------------------------------------------------------

def plot_per_benchmark_percentile(data: dict, benchmarks: list[str],
                                  suite: str, out_dir: Path, pct: float = 99):
    """
    One bar per benchmark showing Pct value for each GC config.
    """
    gcs_present = [gc for gc in GC_ORDER
                   if any(data[bm].get(gc) for bm in benchmarks)]
    n_gc = len(gcs_present)
    n_bm = len(benchmarks)
    x = np.arange(n_bm)
    bar_w = 0.8 / n_gc
    pct_label = f"P{pct:g}"

    fig, ax = _base_fig(w=max(14, n_bm * 1.4), h=6)

    for i, gc in enumerate(gcs_present):
        label, color = GC_STYLES[gc]
        values = []
        for bm in benchmarks:
            pauses = data[bm].get(gc, [])
            values.append(np.percentile(pauses, pct) if pauses else np.nan)
        offset = (i - n_gc / 2 + 0.5) * bar_w
        ax.bar(x + offset, values, bar_w * 0.85,
               label=label, color=color, edgecolor=BAR_EDGE,
               linewidth=0.6, alpha=0.88)

    ax.set_xticks(x)
    ax.set_xticklabels([b.replace("-", "\n") for b in benchmarks],
                       fontsize=9, rotation=0)
    ax.set_xlabel("Benchmark", fontsize=11)
    ax.set_ylabel(f"{pct_label} Pause Time (ms)", fontsize=11)
    ax.set_title(f"{pct_label} GC Pause Latency per Benchmark — {suite.title()} Suite",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR)
    _save(fig, out_dir / f"{suite}_tail_latency_{pct_label.lower()}_per_benchmark.png")


# ---------------------------------------------------------------------------
# CHART 3: CDF plots (one per benchmark)
# ---------------------------------------------------------------------------

def plot_cdfs(data: dict, benchmarks: list[str], suite: str, out_dir: Path):
    """
    For each benchmark, plot the empirical CDF of pause times for each GC config.
    """
    cdf_dir = out_dir / "cdf"
    cdf_dir.mkdir(parents=True, exist_ok=True)

    for bm in benchmarks:
        gcs_with_data = [(gc, data[bm][gc]) for gc in GC_ORDER
                         if data[bm].get(gc)]
        if not gcs_with_data:
            continue

        fig, ax = _base_fig(w=9, h=5)
        for gc, pauses in gcs_with_data:
            label, color = GC_STYLES[gc]
            arr = np.sort(np.array(pauses))
            cdf = np.arange(1, len(arr) + 1) / len(arr)
            ax.plot(arr, cdf, label=label, color=color, linewidth=1.8)

        # Mark P99 line
        ax.axhline(0.99, color=TEXT_COLOR, linewidth=0.8, linestyle=":",
                   alpha=0.6, label="P99 threshold")

        ax.set_xlabel("Pause Time (ms)", fontsize=11)
        ax.set_ylabel("Cumulative Probability", fontsize=11)
        ax.set_title(f"GC Pause CDF — {suite.title()}/{bm}",
                     fontsize=13, fontweight="bold")
        ax.set_ylim(0, 1.02)
        ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
                  labelcolor=TEXT_COLOR)
        _save(fig, cdf_dir / f"{suite}_{bm}_cdf.png")


# ---------------------------------------------------------------------------
# CHART 4: P99 Heatmap (benchmark × GC config)
# ---------------------------------------------------------------------------

def plot_p99_heatmap(data: dict, benchmarks: list[str], suite: str,
                     out_dir: Path, pct: float = 99):
    """
    Heatmap where rows = benchmarks, columns = GC configs, cells = Pct pause.
    """
    gcs_present = [gc for gc in GC_ORDER
                   if any(data[bm].get(gc) for bm in benchmarks)]
    pct_label = f"P{pct:g}"

    matrix = np.full((len(benchmarks), len(gcs_present)), np.nan)
    for i, bm in enumerate(benchmarks):
        for j, gc in enumerate(gcs_present):
            pauses = data[bm].get(gc, [])
            if pauses:
                matrix[i, j] = np.percentile(pauses, pct)

    fig, ax = plt.subplots(figsize=(max(8, len(gcs_present) * 1.6),
                                    max(5, len(benchmarks) * 0.65)),
                           facecolor=LIGHT_BG)
    ax.set_facecolor(CARD_BG)

    # Mask NaN for display
    masked = np.ma.array(matrix, mask=np.isnan(matrix))
    im = ax.imshow(masked, aspect="auto", cmap="YlOrRd")

    # Add text annotations
    for i in range(len(benchmarks)):
        for j in range(len(gcs_present)):
            val = matrix[i, j]
            if not np.isnan(val):
                text_color = "black" if val < np.nanmax(matrix) * 0.6 else "white"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=8, color=text_color)

    ax.set_xticks(range(len(gcs_present)))
    ax.set_xticklabels([GC_STYLES[gc][0] for gc in gcs_present],
                       fontsize=9, rotation=25, ha="right", color=TEXT_COLOR)
    ax.set_yticks(range(len(benchmarks)))
    ax.set_yticklabels(benchmarks, fontsize=9, color=TEXT_COLOR)
    ax.set_title(f"{pct_label} Pause Time Heatmap (ms) — {suite.title()} Suite",
                 fontsize=13, fontweight="bold", color=TEXT_COLOR)

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    cbar.set_label(f"{pct_label} Pause (ms)", color=TEXT_COLOR, fontsize=9)

    _save(fig, out_dir / f"{suite}_p99_heatmap.png")


# ---------------------------------------------------------------------------
# CHART 5: Box plots per GC config (aggregated across benchmarks)
# ---------------------------------------------------------------------------

def plot_boxplots(data: dict, benchmarks: list[str], suite: str, out_dir: Path):
    """
    Side-by-side box plots showing pause distribution for each GC config.
    Uses log scale on Y-axis to handle wide spread.
    """
    gcs_present = [gc for gc in GC_ORDER
                   if any(data[bm].get(gc) for bm in benchmarks)]

    all_data = []
    labels = []
    colors = []
    for gc in gcs_present:
        pauses = []
        for bm in benchmarks:
            pauses.extend(data[bm].get(gc, []))
        if pauses:
            all_data.append(pauses)
            labels.append(GC_STYLES[gc][0])
            colors.append(GC_STYLES[gc][1])

    if not all_data:
        return

    fig, ax = _base_fig(w=11, h=6)
    bp = ax.boxplot(all_data, patch_artist=True, notch=False,
                    medianprops={"color": "#0f172a", "linewidth": 2},
                    whiskerprops={"color": GRID_COLOR},
                    capprops={"color": GRID_COLOR},
                    flierprops={"marker": "o", "markersize": 2,
                                "alpha": 0.4, "markeredgecolor": "none"})
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)
        patch.set_edgecolor(BAR_EDGE)

    # Color outlier markers per GC
    for flier, color in zip(bp["fliers"], colors):
        flier.set_markerfacecolor(color)

    ax.set_yscale("log")
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, fontsize=10, rotation=15, ha="right")
    ax.set_ylabel("Pause Time (ms) — log scale", fontsize=11)
    ax.set_title(f"GC Pause Distribution — {suite.title()} Suite (All Benchmarks)",
                 fontsize=13, fontweight="bold")
    ax.yaxis.set_minor_formatter(ticker.NullFormatter())
    _save(fig, out_dir / f"{suite}_pause_boxplot.png")


# ---------------------------------------------------------------------------
# CHART 6: P50 vs P99 scatter per GC (mean across benchmarks)
# ---------------------------------------------------------------------------

def plot_p50_vs_p99_scatter(data: dict, benchmarks: list[str],
                             suite: str, out_dir: Path):
    """
    Scatter: X=median pause (P50), Y=P99 pause. Each point is a benchmark,
    color-coded by GC. Shows 'tail bloat' — how much worse P99 is vs median.
    """
    fig, ax = _base_fig(w=9, h=7)

    for gc in GC_ORDER:
        label, color = GC_STYLES[gc]
        p50s, p99s, bm_labels = [], [], []
        for bm in benchmarks:
            pauses = data[bm].get(gc, [])
            if len(pauses) >= 3:
                arr = np.array(pauses)
                p50s.append(np.percentile(arr, 50))
                p99s.append(np.percentile(arr, 99))
                bm_labels.append(bm)
        if p50s:
            ax.scatter(p50s, p99s, color=color, label=label, s=80,
                       edgecolors=BAR_EDGE, linewidths=0.5, alpha=0.85, zorder=3)
            for x, y, lbl in zip(p50s, p99s, bm_labels):
                ax.annotate(lbl[:5], (x, y), fontsize=6, color=TEXT_COLOR,
                            xytext=(3, 3), textcoords="offset points")

    # Reference line P99 = P50 (perfect = no tail)
    lim = ax.get_xlim()
    xs = np.linspace(0, max(lim[1], 1), 100)
    ax.plot(xs, xs, color=GRID_COLOR, linewidth=1, linestyle="--",
            label="P99 = P50 (no tail)", alpha=0.7)

    ax.set_xlabel("P50 Pause Time (ms)", fontsize=11)
    ax.set_ylabel("P99 Pause Time (ms)", fontsize=11)
    ax.set_title(f"Tail Bloat: P50 vs P99 — {suite.title()} Suite",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR)
    _save(fig, out_dir / f"{suite}_p50_vs_p99_scatter.png")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def run_suite(suite_name: str, suite_dir: Path, benchmarks: list[str],
              out_dir: Path):
    print(f"\n{'='*60}")
    print(f"  Suite: {suite_name.upper()}")
    print(f"{'='*60}")

    data = collect_pauses(suite_dir, benchmarks)

    rows = compute_percentile_table(data, benchmarks)
    save_csv(rows, CSV_DIR / f"tail_latency_{suite_name}.csv")

    print(f"\n  Generating charts → {out_dir}/")
    plot_percentile_bars_aggregated(data, benchmarks, suite_name, out_dir)
    plot_per_benchmark_percentile(data, benchmarks, suite_name, out_dir, pct=99)
    plot_per_benchmark_percentile(data, benchmarks, suite_name, out_dir, pct=99.9)
    plot_cdfs(data, benchmarks, suite_name, out_dir)
    plot_p99_heatmap(data, benchmarks, suite_name, out_dir, pct=99)
    plot_p99_heatmap(data, benchmarks, suite_name, out_dir, pct=99.9)
    plot_boxplots(data, benchmarks, suite_name, out_dir)
    plot_p50_vs_p99_scatter(data, benchmarks, suite_name, out_dir)

    return data, rows


def main():
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    run_suite("dacapo",      SUITES["dacapo"],      DACAPO_BENCHMARKS,      GRAPHS_DIR)
    run_suite("renaissance", SUITES["renaissance"], RENAISSANCE_BENCHMARKS, GRAPHS_DIR)

    print("\nDone. All tail latency outputs written.")


if __name__ == "__main__":
    main()
