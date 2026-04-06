#!/usr/bin/env python3
"""
Generational ZGC Deep Analysis
================================

Compares ZGC (Generational) vs ZGC (Non-Generational) and all GC configs
across all key metrics from the existing GCViewer CSV data. Applies
Wilcoxon signed-rank tests for statistical significance, computes effect
sizes (Cohen's d / rank-biserial r), and generates publication-quality
charts.

Research Questions addressed:
  RQ1: Does Generational ZGC improve throughput, pause latency, and heap
       efficiency compared to Non-Generational ZGC on Java 21 workloads?
  RQ2: For what workload characteristics does ZGCGen underperform?
  RQ3: How does ZGCGen compare to G1GC and Shenandoah on each benchmark?

Output:
    results/csv/zgc_gen_analysis.csv         — per-benchmark metric comparisons
    results/csv/zgc_gen_statistical_tests.csv — Wilcoxon test results
    graphs/zgc_gen/...

Usage:
    cd experiment/
    python3 scripts/analyze_zgc_gen.py

Dependencies:
    pip install matplotlib numpy pandas scipy
"""

import sys
import warnings
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
CSV_DIR = RESULTS_DIR / "csv"
GRAPHS_DIR = BASE_DIR / "graphs" / "zgc_gen"

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

# Metrics for analysis: (column name, display name, unit, higher_is_better)
ANALYSIS_METRICS = [
    ("throughput",        "Throughput",           "%",    True),
    ("avgPause",          "Avg Pause Time",        "s",    False),
    ("maxPause",          "Max Pause Time",        "s",    False),
    ("pauseCount",        "GC Pause Count",        "",     False),
    ("gcPerformance",     "GC Throughput",         "MB/s", True),
    ("totalHeapUsedMax",  "Peak Heap Used",        "MB",   False),
    ("totalHeapAllocMax", "Heap Allocated",        "MB",   False),
    ("wallTimeSec",       "Wall-Clock Time",       "s",    False),
    ("freedMemoryByGC",   "Memory Freed by GC",   "MB",   True),
    ("footprint",         "Memory Footprint",      "MB",   False),
]

# Key metrics for the primary ZGC gen vs nogen comparison
ZGC_KEY_METRICS = ["throughput", "avgPause", "maxPause",
                   "pauseCount", "gcPerformance", "totalHeapUsedMax", "wallTimeSec"]

DARK_BG    = "#0f172a"
CARD_BG    = "#1e293b"
TEXT_COLOR = "#e2e8f0"
GRID_COLOR = "#334155"
BAR_EDGE   = "#475569"
POSITIVE_COLOR = "#4ade80"   # green  = improvement
NEGATIVE_COLOR = "#f87171"   # red    = regression


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------

def load_suite(suite_name: str) -> pd.DataFrame:
    csv_path = CSV_DIR / f"{suite_name}_all_metrics.csv"
    df = pd.read_csv(csv_path)
    # Sanitize: replace sentinel -2199023255552.0 with NaN
    df.replace(-2199023255552.0, np.nan, inplace=True)
    df["suite"] = suite_name
    return df


# ---------------------------------------------------------------------------
# STATISTICAL TESTS
# ---------------------------------------------------------------------------

def cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d effect size between two samples."""
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    pooled_std = np.sqrt((a.std(ddof=1)**2 + b.std(ddof=1)**2) / 2)
    if pooled_std == 0:
        return 0.0
    return (a.mean() - b.mean()) / pooled_std


def rank_biserial_r(a: np.ndarray, b: np.ndarray) -> float:
    """
    Rank-biserial correlation (non-parametric effect size for Wilcoxon).
    r = 1 - (2 * W) / (n1 * n2)  approximation.
    """
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    try:
        result = stats.mannwhitneyu(a, b, alternative="two-sided")
        r = 1 - (2 * result.statistic) / (len(a) * len(b))
        return r
    except Exception:
        return np.nan


def pairwise_wilcoxon(df: pd.DataFrame, gc_a: str, gc_b: str,
                      metric: str) -> dict:
    """
    Run Wilcoxon signed-rank test on paired benchmark observations
    for gc_a vs gc_b on a given metric.
    Returns dict with statistic, p_value, effect_size, direction.
    """
    sub_a = df[df["gc_config"] == gc_a][["benchmark", metric]].dropna()
    sub_b = df[df["gc_config"] == gc_b][["benchmark", metric]].dropna()
    merged = sub_a.merge(sub_b, on="benchmark", suffixes=("_a", "_b"))

    if len(merged) < 3:
        return {"statistic": np.nan, "p_value": np.nan,
                "effect_r": np.nan, "n_pairs": len(merged),
                "mean_a": np.nan, "mean_b": np.nan, "pct_change": np.nan}

    col_a = merged[f"{metric}_a"].values
    col_b = merged[f"{metric}_b"].values
    try:
        stat, p_val = stats.wilcoxon(col_a, col_b, alternative="two-sided",
                                     zero_method="pratt")
    except Exception:
        stat, p_val = np.nan, np.nan

    mean_a = np.nanmean(col_a)
    mean_b = np.nanmean(col_b)
    pct_change = ((mean_b - mean_a) / abs(mean_a) * 100) if mean_a != 0 else np.nan

    return {
        "statistic":  stat,
        "p_value":    p_val,
        "effect_r":   rank_biserial_r(col_a, col_b),
        "n_pairs":    len(merged),
        "mean_a":     mean_a,
        "mean_b":     mean_b,
        "pct_change": pct_change,
    }


def run_all_statistical_tests(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run pairwise Wilcoxon tests for key comparisons:
      - zgc_gen vs zgc_nogen (primary)
      - zgc_gen vs g1gc
      - zgc_gen vs shenandoah
      - zgc_nogen vs g1gc
    for all analysis metrics.
    """
    comparisons = [
        ("zgc_gen",   "zgc_nogen"),
        ("zgc_gen",   "g1gc"),
        ("zgc_gen",   "shenandoah"),
        ("zgc_nogen", "g1gc"),
        ("zgc_nogen", "shenandoah"),
        ("g1gc",      "shenandoah"),
    ]
    rows = []
    for gc_a, gc_b in comparisons:
        for col, display, unit, higher_better in ANALYSIS_METRICS:
            if col not in df.columns:
                continue
            r = pairwise_wilcoxon(df, gc_a, gc_b, col)
            significance = "**" if r["p_value"] < 0.01 else \
                           "*"  if r["p_value"] < 0.05 else \
                           "ns"
            rows.append({
                "gc_a":       gc_a,
                "gc_b":       gc_b,
                "metric":     col,
                "metric_display": display,
                "unit":       unit,
                "higher_is_better": higher_better,
                "n_pairs":    r["n_pairs"],
                "mean_a":     round(r["mean_a"], 4) if not np.isnan(r["mean_a"]) else "",
                "mean_b":     round(r["mean_b"], 4) if not np.isnan(r["mean_b"]) else "",
                "pct_change": round(r["pct_change"], 2) if not np.isnan(r["pct_change"]) else "",
                "wilcoxon_stat": r["statistic"],
                "p_value":    round(r["p_value"], 4) if not np.isnan(r["p_value"]) else "",
                "effect_r":   round(r["effect_r"], 3) if not np.isnan(r["effect_r"]) else "",
                "significance": significance,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CHART HELPERS
# ---------------------------------------------------------------------------

def _base_fig(w=14, h=6):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=DARK_BG)
    ax.set_facecolor(CARD_BG)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    ax.grid(axis="y", color=GRID_COLOR, linewidth=0.6, linestyle="--", alpha=0.6)
    return fig, ax


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {path.name}")


# ---------------------------------------------------------------------------
# CHART 1: ZGCGen vs ZGCNonGen side-by-side per metric, per benchmark
# ---------------------------------------------------------------------------

def plot_zgc_gen_vs_nogen(df: pd.DataFrame, suite: str, out_dir: Path):
    """
    For each key metric: grouped bar chart, one group per benchmark,
    bars = zgc_gen and zgc_nogen side by side.
    """
    benchmarks = sorted(df["benchmark"].unique())

    for col, display, unit, higher_better in ANALYSIS_METRICS:
        if col not in df.columns:
            continue
        sub = df[df["gc_config"].isin(["zgc_gen", "zgc_nogen"])][
            ["benchmark", "gc_config", col]].copy()
        sub = sub.dropna(subset=[col])
        if sub.empty:
            continue

        pivot = sub.pivot(index="benchmark", columns="gc_config", values=col)
        present_gcs = [gc for gc in ["zgc_nogen", "zgc_gen"] if gc in pivot.columns]
        if not present_gcs:
            continue

        bms = pivot.index.tolist()
        x = np.arange(len(bms))
        bar_w = 0.35

        fig, ax = _base_fig(w=max(11, len(bms) * 1.3), h=6)

        for i, gc in enumerate(present_gcs):
            label, color = GC_STYLES[gc]
            vals = pivot[gc].values if gc in pivot.columns else [np.nan] * len(bms)
            offset = (i - len(present_gcs) / 2 + 0.5) * bar_w
            ax.bar(x + offset, vals, bar_w * 0.9, label=label,
                   color=color, edgecolor=BAR_EDGE, linewidth=0.6, alpha=0.88)

        ax.set_xticks(x)
        ax.set_xticklabels([b.replace("-", "\n") for b in bms], fontsize=9)
        ax.set_xlabel("Benchmark", fontsize=11)
        ylabel = f"{display} ({unit})" if unit else display
        ax.set_ylabel(ylabel, fontsize=11)
        direction = "↑ better" if higher_better else "↓ better"
        ax.set_title(f"ZGC Gen vs Non-Gen: {display} [{direction}]\n"
                     f"{suite.title()} Suite", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9, facecolor=CARD_BG, edgecolor=GRID_COLOR,
                  labelcolor=TEXT_COLOR)
        fname = f"{suite}_zgcgen_vs_nogen_{col}.png"
        _save(fig, out_dir / "gen_vs_nogen" / fname)


# ---------------------------------------------------------------------------
# CHART 2: All-GC comparison on key metrics (heatmap style)
# ---------------------------------------------------------------------------

def plot_all_gc_metric_heatmap(df: pd.DataFrame, suite: str, out_dir: Path):
    """
    Heatmap: rows=GC configs, columns=key metrics.
    Values are normalized per metric (0=worst, 1=best) accounting for
    direction (higher_is_better).
    """
    gcs = [gc for gc in GC_ORDER if gc in df["gc_config"].unique()]
    metrics_info = [(c, n, u, h) for c, n, u, h in ANALYSIS_METRICS
                    if c in df.columns and c != "wallTimeSec"]

    # Compute mean per GC across all benchmarks
    agg = df.groupby("gc_config")[[m[0] for m in metrics_info]].mean()

    # Normalize each column 0→1 (best=1, worst=0)
    norm_matrix = np.zeros((len(gcs), len(metrics_info)))
    for j, (col, _, _, higher_better) in enumerate(metrics_info):
        if col not in agg.columns:
            continue
        vals = agg.loc[[g for g in gcs if g in agg.index], col].values.astype(float)
        valid = vals[~np.isnan(vals)]
        if len(valid) == 0 or valid.max() == valid.min():
            continue
        if higher_better:
            norm = (vals - np.nanmin(vals)) / (np.nanmax(vals) - np.nanmin(vals))
        else:
            norm = (np.nanmax(vals) - vals) / (np.nanmax(vals) - np.nanmin(vals))
        gc_indices = [i for i, gc in enumerate(gcs) if gc in agg.index]
        for idx, gi in enumerate(gc_indices):
            norm_matrix[gi, j] = norm[idx] if not np.isnan(norm[idx]) else 0

    fig, ax = plt.subplots(
        figsize=(max(10, len(metrics_info) * 1.4), max(4, len(gcs) * 0.75)),
        facecolor=DARK_BG)
    ax.set_facecolor(CARD_BG)

    im = ax.imshow(norm_matrix, aspect="auto", cmap="RdYlGn",
                   vmin=0, vmax=1)

    for i, gc in enumerate(gcs):
        for j, (col, _, _, _) in enumerate(metrics_info):
            val = norm_matrix[i, j]
            text_color = "black" if 0.3 < val < 0.8 else "white"
            if col in agg.columns and gc in agg.index:
                raw = agg.loc[gc, col]
                if not np.isnan(raw):
                    ax.text(j, i, f"{raw:.2g}", ha="center", va="center",
                            fontsize=7, color=text_color)

    ax.set_xticks(range(len(metrics_info)))
    ax.set_xticklabels([m[1] for m in metrics_info],
                       fontsize=8, rotation=30, ha="right", color=TEXT_COLOR)
    ax.set_yticks(range(len(gcs)))
    ax.set_yticklabels([GC_STYLES[gc][0] for gc in gcs],
                       fontsize=9, color=TEXT_COLOR)
    ax.set_title(f"GC Config Performance Heatmap — {suite.title()} Suite\n"
                 f"(Color: normalized score, 1=best per metric, raw values shown)",
                 fontsize=12, fontweight="bold", color=TEXT_COLOR)

    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.04)
    cbar.ax.tick_params(colors=TEXT_COLOR)
    cbar.set_label("Normalized Score (1=best)", color=TEXT_COLOR, fontsize=8)

    _save(fig, out_dir / f"{suite}_all_gc_heatmap.png")


# ---------------------------------------------------------------------------
# CHART 3: Percent change matrix (ZGCGen vs others)
# ---------------------------------------------------------------------------

def plot_pct_change_matrix(df: pd.DataFrame, suite: str, out_dir: Path):
    """
    For each metric, show pct change from baseline (g1gc) to each other GC.
    Bars are colored green (improvement) or red (regression).
    """
    key_metrics = [m for m in ANALYSIS_METRICS if m[0] in ZGC_KEY_METRICS
                   and m[0] in df.columns]
    baseline = "g1gc"
    comparators = [gc for gc in GC_ORDER
                   if gc != baseline and gc in df["gc_config"].unique()]

    if not comparators:
        return

    # Compute means
    agg = df.groupby("gc_config")[[m[0] for m in key_metrics]].mean()

    n_metrics = len(key_metrics)
    n_gc = len(comparators)
    x = np.arange(n_metrics)
    bar_w = 0.8 / n_gc

    fig, ax = _base_fig(w=max(14, n_metrics * 1.6), h=7)
    ax.axhline(0, color=TEXT_COLOR, linewidth=0.8, linestyle="--", alpha=0.5)

    for i, gc in enumerate(comparators):
        label, color = GC_STYLES[gc]
        pct_changes = []
        for col, _, _, higher_better in key_metrics:
            if col not in agg.columns or baseline not in agg.index or gc not in agg.index:
                pct_changes.append(np.nan)
                continue
            base_val = agg.loc[baseline, col]
            gc_val = agg.loc[gc, col]
            if base_val == 0 or np.isnan(base_val) or np.isnan(gc_val):
                pct_changes.append(np.nan)
                continue
            raw_pct = (gc_val - base_val) / abs(base_val) * 100
            # Flip sign for "lower is better" metrics so positive always = improvement
            if not higher_better:
                raw_pct = -raw_pct
            pct_changes.append(raw_pct)

        offset = (i - n_gc / 2 + 0.5) * bar_w
        bar_colors = [POSITIVE_COLOR if (v is not None and not np.isnan(v) and v > 0)
                      else NEGATIVE_COLOR for v in pct_changes]
        bars = ax.bar(x + offset, pct_changes, bar_w * 0.85,
                      label=label, color=bar_colors, edgecolor=BAR_EDGE,
                      linewidth=0.6, alpha=0.85)
        # Override bar edge color with GC color for identification
        for bar in bars:
            bar.set_edgecolor(color)
            bar.set_linewidth(1.5)

    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in key_metrics],
                       fontsize=9, rotation=25, ha="right")
    ax.set_xlabel("Metric", fontsize=11)
    ax.set_ylabel("% Change vs G1GC (positive = improvement)", fontsize=10)
    ax.set_title(f"Performance Delta vs G1GC Baseline — {suite.title()} Suite\n"
                 f"Green=better than G1GC, Red=worse (pause/size metrics: lower=better)",
                 fontsize=11, fontweight="bold")
    leg = ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
                    labelcolor=TEXT_COLOR)
    _save(fig, out_dir / f"{suite}_pct_change_vs_g1gc.png")


# ---------------------------------------------------------------------------
# CHART 4: Throughput vs Max Pause scatter (Pareto frontier)
# ---------------------------------------------------------------------------

def plot_throughput_vs_maxpause(df: pd.DataFrame, suite: str, out_dir: Path):
    """
    Scatter: X = avgPause (ms), Y = throughput (%).
    Each point = one benchmark × GC config combination.
    Ideal: top-left corner (high throughput, low pause).
    """
    if "avgPause" not in df.columns or "throughput" not in df.columns:
        return

    sub = df[["benchmark", "gc_config", "avgPause", "throughput"]].dropna()

    fig, ax = _base_fig(w=10, h=7)

    gcs_present = [gc for gc in GC_ORDER if gc in sub["gc_config"].unique()]
    for gc in gcs_present:
        label, color = GC_STYLES[gc]
        gcdf = sub[sub["gc_config"] == gc]
        # Convert avgPause from seconds to ms
        xs = gcdf["avgPause"].values * 1000
        ys = gcdf["throughput"].values
        ax.scatter(xs, ys, color=color, label=label, s=70,
                   edgecolors=BAR_EDGE, linewidths=0.5, alpha=0.85, zorder=3)
        # Label each point with benchmark name
        for _, row in gcdf.iterrows():
            ax.annotate(row["benchmark"][:4],
                        (row["avgPause"] * 1000, row["throughput"]),
                        fontsize=5.5, color=color, alpha=0.8,
                        xytext=(2, 2), textcoords="offset points")

    ax.set_xlabel("Avg GC Pause Time (ms) — lower is better", fontsize=11)
    ax.set_ylabel("Throughput (%) — higher is better", fontsize=11)
    ax.set_title(f"Throughput vs Pause Latency Trade-off — {suite.title()} Suite\n"
                 f"Ideal region: top-left corner",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR)
    _save(fig, out_dir / f"{suite}_throughput_vs_pause_scatter.png")


# ---------------------------------------------------------------------------
# CHART 5: Statistical test significance matrix
# ---------------------------------------------------------------------------

def plot_significance_matrix(test_df: pd.DataFrame, suite: str, out_dir: Path):
    """
    Heatmap showing p-values (or significance markers) for pairwise Wilcoxon
    tests across key metrics.
    Primary focus: zgc_gen vs others.
    """
    focus = test_df[test_df["gc_a"] == "zgc_gen"].copy()
    if focus.empty:
        return

    metrics_display = {row["metric"]: row["metric_display"]
                       for _, row in focus.iterrows()}
    comparisons = sorted(focus["gc_b"].unique())
    metric_cols = [c for c, _, _, _ in ANALYSIS_METRICS if c in metrics_display]

    matrix_p = np.ones((len(comparisons), len(metric_cols)))
    matrix_r = np.zeros((len(comparisons), len(metric_cols)))

    for i, gc_b in enumerate(comparisons):
        for j, col in enumerate(metric_cols):
            row = focus[(focus["gc_b"] == gc_b) & (focus["metric"] == col)]
            if not row.empty:
                pval = row["p_value"].values[0]
                eff = row["effect_r"].values[0]
                if pval != "" and pval is not None:
                    try:
                        matrix_p[i, j] = float(pval)
                        matrix_r[i, j] = float(eff) if eff != "" else 0
                    except (ValueError, TypeError):
                        pass

    fig, ax = plt.subplots(
        figsize=(max(10, len(metric_cols) * 1.3), max(4, len(comparisons) * 0.9)),
        facecolor=DARK_BG)
    ax.set_facecolor(CARD_BG)

    # Show -log10(p) for visual impact (higher = more significant)
    log_p = -np.log10(np.clip(matrix_p, 1e-10, 1.0))
    im = ax.imshow(log_p, aspect="auto", cmap="Blues", vmin=0, vmax=4)

    for i in range(len(comparisons)):
        for j in range(len(metric_cols)):
            pv = matrix_p[i, j]
            sig = "**" if pv < 0.01 else "*" if pv < 0.05 else "ns"
            r_val = matrix_r[i, j]
            cell_text = f"{sig}\nr={r_val:.2f}" if sig != "ns" else "ns"
            ax.text(j, i, cell_text, ha="center", va="center",
                    fontsize=7, color=TEXT_COLOR)

    ax.set_xticks(range(len(metric_cols)))
    ax.set_xticklabels([metrics_display.get(c, c) for c in metric_cols],
                       fontsize=8, rotation=30, ha="right", color=TEXT_COLOR)
    ax.set_yticks(range(len(comparisons)))
    ax.set_yticklabels([f"ZGCGen vs {GC_STYLES.get(gc, (gc, ''))[0]}"
                        for gc in comparisons],
                       fontsize=8, color=TEXT_COLOR)
    ax.set_title(f"Statistical Significance: ZGC (Gen) vs Others — {suite.title()}\n"
                 f"Color = -log₁₀(p-value), ** p<0.01, * p<0.05, ns = not significant",
                 fontsize=11, fontweight="bold", color=TEXT_COLOR)

    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.04)
    cbar.ax.tick_params(colors=TEXT_COLOR)
    cbar.set_label("-log₁₀(p-value)", color=TEXT_COLOR, fontsize=8)
    _save(fig, out_dir / f"{suite}_zgcgen_significance_matrix.png")


# ---------------------------------------------------------------------------
# CHART 6: Radar / spider chart — GC profile per benchmark
# ---------------------------------------------------------------------------

def plot_radar_profile(df: pd.DataFrame, suite: str, out_dir: Path):
    """
    Radar chart: for each GC config, plot normalized scores on 5 axes
    (throughput, low pause, low heap, GC performance, speed).
    Shows the 'GC profile' shape at a glance.
    """
    radar_metrics = [
        ("throughput",        "Throughput",    True),
        ("avgPause",          "Low Pause",     False),
        ("totalHeapUsedMax",  "Low Heap",      False),
        ("gcPerformance",     "GC Perf",       True),
        ("wallTimeSec",       "Speed",         False),
    ]
    radar_metrics = [(c, n, h) for c, n, h in radar_metrics if c in df.columns]
    if len(radar_metrics) < 3:
        return

    N = len(radar_metrics)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # close polygon

    agg = df.groupby("gc_config")[[m[0] for m in radar_metrics]].mean()
    gcs_present = [gc for gc in GC_ORDER if gc in agg.index]

    # Normalize each metric 0→1 (1=best)
    norm = {}
    for col, _, higher in radar_metrics:
        vals = agg[col].values.astype(float)
        vmin, vmax = np.nanmin(vals), np.nanmax(vals)
        if vmax == vmin:
            norm[col] = {gc: 0.5 for gc in gcs_present}
        else:
            for gc in gcs_present:
                v = agg.loc[gc, col]
                n_val = (v - vmin) / (vmax - vmin) if higher else (vmax - v) / (vmax - vmin)
                norm.setdefault(col, {})[gc] = float(n_val) if not np.isnan(n_val) else 0

    fig, ax = plt.subplots(1, 1, figsize=(8, 8), facecolor=DARK_BG,
                           subplot_kw={"polar": True})
    ax.set_facecolor(CARD_BG)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([m[1] for m in radar_metrics],
                       fontsize=10, color=TEXT_COLOR)
    ax.tick_params(colors=TEXT_COLOR)
    ax.spines["polar"].set_color(GRID_COLOR)
    ax.yaxis.set_tick_params(colors=GRID_COLOR)

    for gc in gcs_present:
        label, color = GC_STYLES[gc]
        values = [norm[col][gc] for col, _, _ in radar_metrics]
        values += values[:1]
        ax.plot(angles, values, color=color, linewidth=2, label=label)
        ax.fill(angles, values, color=color, alpha=0.13)

    ax.set_title(f"GC Performance Profile — {suite.title()} Suite\n"
                 f"(Normalized, outer = better)",
                 fontsize=12, fontweight="bold", color=TEXT_COLOR, pad=20)
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR, loc="upper right",
              bbox_to_anchor=(1.35, 1.1))
    _save(fig, out_dir / f"{suite}_gc_radar_profile.png")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def run_suite(df: pd.DataFrame, suite_name: str, out_dir: Path):
    print(f"\n{'='*60}")
    print(f"  Suite: {suite_name.upper()}  — {len(df)} rows, "
          f"{df['benchmark'].nunique()} benchmarks, "
          f"{df['gc_config'].nunique()} GC configs")
    print(f"{'='*60}")

    # Run statistical tests
    print("  Running pairwise Wilcoxon tests...")
    test_df = run_all_statistical_tests(df)
    test_out = CSV_DIR / f"zgc_gen_statistical_tests_{suite_name}.csv"
    test_df.to_csv(test_out, index=False)
    print(f"  Saved → {test_out.name}")

    # Print summary of key findings
    zgc_vs_nogen = test_df[(test_df["gc_a"] == "zgc_gen") &
                            (test_df["gc_b"] == "zgc_nogen")]
    print(f"\n  ZGCGen vs ZGCNonGen key results:")
    for _, row in zgc_vs_nogen.iterrows():
        if row["metric"] in ZGC_KEY_METRICS:
            print(f"    {row['metric']:22s}  "
                  f"gen_mean={row['mean_a']!s:>12}  "
                  f"nogen_mean={row['mean_b']!s:>12}  "
                  f"Δ={row['pct_change']!s:>8}%  "
                  f"p={row['p_value']!s:>8}  {row['significance']}")

    # Generate charts
    print(f"\n  Generating charts → {out_dir}/")
    plot_zgc_gen_vs_nogen(df, suite_name, out_dir)
    plot_all_gc_metric_heatmap(df, suite_name, out_dir)
    plot_pct_change_matrix(df, suite_name, out_dir)
    plot_throughput_vs_maxpause(df, suite_name, out_dir)
    plot_significance_matrix(test_df, suite_name, out_dir)
    plot_radar_profile(df, suite_name, out_dir)


def main():
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading DaCapo data...")
    dacapo_df = load_suite("dacapo")

    print("Loading Renaissance data...")
    renaissance_df = load_suite("renaissance")

    # Combined dataset
    combined_df = pd.concat([dacapo_df, renaissance_df], ignore_index=True)

    run_suite(dacapo_df,      "dacapo",      GRAPHS_DIR)
    run_suite(renaissance_df, "renaissance", GRAPHS_DIR)
    run_suite(combined_df,    "combined",    GRAPHS_DIR)

    print("\nDone. All ZGC Gen analysis outputs written.")


if __name__ == "__main__":
    main()
