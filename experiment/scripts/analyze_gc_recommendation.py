#!/usr/bin/env python3
"""
GC Recommendation Framework via Workload Characterization
==========================================================

Answers: "Given *my workload*, which GC should I choose?"

Pipeline:
  1. Derive workload features from GCViewer + tail-latency CSVs:
       - gc_frequency   (GC events/sec) — how often GC fires
       - alloc_rate     (MB/s freed)    — allocation pressure
       - heap_pressure  (used/alloc)    — live-data density
       - tail_ratio     (p99/p50)       — how heavy the tails are
       - pause_overhead (accumPause/wallTime) — fraction in STW

  2. For each benchmark × GC pair, compute a weighted composite score
     across four workload priorities (four "user personas"):
       - Latency-critical  (weight: p99 pause)
       - Throughput-first  (weight: throughput %)
       - Memory-constrained (weight: heap footprint)
       - Balanced          (equal weights)

  3. Per benchmark, elect the BEST GC for each persona → build a
     recommendation matrix.

  4. Train a Decision Tree classifier: workload features → recommended GC
     (for the Latency-critical persona as primary target).

  5. Generate charts:
       - Recommendation heatmap (benchmark × persona → best GC)
       - Feature importance bar chart
       - Decision tree diagram
       - Workload cluster map (PCA 2D)
       - Per-persona win-rate bar chart

Output:
    results/csv/gc_recommendations.csv
    results/csv/gc_workload_features.csv
    graphs/recommendation/...

Usage:
    cd experiment/
    python3 scripts/analyze_gc_recommendation.py

Dependencies:
    pip install matplotlib numpy pandas scipy scikit-learn
"""

import warnings
import os
import sys
from pathlib import Path
from io import StringIO

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.tree import DecisionTreeClassifier, export_text, plot_tree
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
CSV_DIR = RESULTS_DIR / "csv"
GRAPHS_DIR = BASE_DIR / "graphs" / "recommendation"

GC_CONFIGS = ["g1gc", "shenandoah", "zgc_nogen", "zgc_gen",
              "g1gc_pause50", "g1gc_threads2"]

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

# Persona definitions: name → list of (metric_column, weight, lower_is_better)
# All metrics are normalized 0-1 before weighting; score = sum(weight * normalized)
# Higher final score = better GC for this persona
PERSONAS = {
    "Latency-Critical": [
        ("p99_ms",       0.40, True),
        ("p99_9_ms",     0.30, True),
        ("p50_ms",       0.15, True),
        ("throughput",   0.15, False),
    ],
    "Throughput-First": [
        ("throughput",   0.45, False),
        ("wallTimeSec",  0.30, True),
        ("p50_ms",       0.15, True),
        ("heap_pressure",0.10, True),
    ],
    "Memory-Constrained": [
        ("heap_pressure",0.35, True),
        ("footprint",    0.30, True),
        ("throughput",   0.20, False),
        ("p99_ms",       0.15, True),
    ],
    "Balanced": [
        ("throughput",   0.25, False),
        ("p99_ms",       0.25, True),
        ("wallTimeSec",  0.25, True),
        ("footprint",    0.25, True),
    ],
}

# Light theme — matches generate_graphs.py
LIGHT_BG   = "#f8fafc"
CARD_BG    = "#ffffff"
TEXT_COLOR = "#0f172a"
GRID_COLOR = "#e2e8f0"
BAR_EDGE   = "#94a3b8"

# ---------------------------------------------------------------------------
# DATA LOADING & FEATURE ENGINEERING
# ---------------------------------------------------------------------------

def load_and_merge() -> pd.DataFrame:
    """
    Merge GCViewer aggregate metrics with tail-latency percentiles.
    Returns one row per (benchmark, gc_config, suite).
    """
    frames = []
    for suite in ("dacapo", "renaissance"):
        gcv_path  = CSV_DIR / f"{suite}_all_metrics.csv"
        tail_path = CSV_DIR / f"tail_latency_{suite}.csv"

        if not os.path.exists(gcv_path):
            print(f"  [SKIP] {gcv_path.name} not found"); continue
        if not os.path.exists(tail_path):
            print(f"  [SKIP] {tail_path.name} not found"); continue

        gcv  = pd.read_csv(gcv_path)
        tail = pd.read_csv(tail_path)

        # Sanitize GCViewer sentinel
        gcv.replace(-2199023255552.0, np.nan, inplace=True)

        merged = gcv.merge(tail, on=["benchmark", "gc_config"], how="left")
        merged["suite"] = suite
        frames.append(merged)

    if not frames:
        print("[ERROR] No data found. Run the benchmark scripts first.")
        sys.exit(1)

    return pd.concat(frames, ignore_index=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive workload-characterization features from raw metrics.
    Added as new columns to df in-place; returns df.
    """
    eps = 1e-9  # avoid divide-by-zero

    # GC frequency: how many GC pauses per second of wall time
    df["gc_frequency"] = df["pauseCount"] / (df["wallTimeSec"] + eps)

    # Allocation rate proxy: MB freed per second (throughput of GC pipeline)
    df["alloc_rate"] = df["freedMemoryByGC"] / (df["wallTimeSec"] + eps)

    # Heap pressure: peak used / peak allocated (how full the heap is)
    df["heap_pressure"] = df["totalHeapUsedMax"] / (df["totalHeapAllocMax"] + eps)

    # Tail ratio: how much worse P99 is vs median (high = spiky pauses)
    df["tail_ratio"] = df["p99_ms"] / (df["p50_ms"] + eps)

    # Pause overhead: accumulated pause time as fraction of total wall time
    df["pause_overhead"] = df["accumPause"] / (df["wallTimeSec"] + eps)

    # footprint: use existing column; fill missing with totalHeapUsedMax
    if "footprint" not in df.columns or df["footprint"].isna().all():
        df["footprint"] = df["totalHeapUsedMax"]
    else:
        df["footprint"] = df["footprint"].fillna(df["totalHeapUsedMax"])

    # p50_ms from tail CSV (may already exist); ensure present
    for col in ("p50_ms", "p99_ms", "p99_9_ms"):
        if col not in df.columns:
            df[col] = np.nan

    return df


# ---------------------------------------------------------------------------
# WORKLOAD PROFILE: per-benchmark median features (across GC configs)
# ---------------------------------------------------------------------------

WORKLOAD_FEATURE_COLS = [
    "gc_frequency", "alloc_rate", "heap_pressure",
    "tail_ratio", "pause_overhead",
]


def compute_workload_profiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each benchmark, compute the median of workload features
    across all GC configs. This describes the workload itself,
    not any particular GC's response to it.
    """
    profile = (
        df.groupby("benchmark")[WORKLOAD_FEATURE_COLS]
        .median()
        .reset_index()
    )
    profile["suite"] = df.groupby("benchmark")["suite"].first().values
    return profile


# ---------------------------------------------------------------------------
# SCORING ENGINE
# ---------------------------------------------------------------------------

def normalize_col(series: pd.Series) -> pd.Series:
    """Min-max normalize to [0, 1]. NaNs stay NaN."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return series * 0 + 0.5
    return (series - mn) / (mx - mn)


def score_gcs(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each benchmark × GC pair compute a composite score for each persona.
    Returns df with added columns: score_<PersonaName>.
    """
    # Collect all metric columns used across personas; normalize within
    # each (benchmark, suite) group so that comparisons are local.
    all_metrics = set()
    for weights in PERSONAS.values():
        for col, _, _ in weights:
            all_metrics.add(col)

    df = df.copy()

    for metric in all_metrics:
        if metric not in df.columns:
            df[metric] = np.nan
        # Normalize per benchmark (so rankings are within a benchmark)
        df[f"_norm_{metric}"] = (
            df.groupby("benchmark")[metric]
              .transform(normalize_col)
        )

    for persona, weights in PERSONAS.items():
        score = pd.Series(0.0, index=df.index)
        for col, w, lower_better in weights:
            norm_col = f"_norm_{col}"
            if norm_col not in df.columns:
                continue
            contribution = df[norm_col].fillna(0.5)
            if lower_better:
                contribution = 1.0 - contribution  # invert: lower raw = higher score
            score += w * contribution
        df[f"score_{persona}"] = score

    return df


def elect_best_gc(scored: pd.DataFrame) -> pd.DataFrame:
    """
    For each (benchmark, persona) pick the GC config with the highest score.
    Returns a recommendation DataFrame:
        benchmark | persona | best_gc | best_score | runner_up | margin
    """
    rows = []
    for bm, grp in scored.groupby("benchmark"):
        for persona in PERSONAS:
            col = f"score_{persona}"
            if col not in grp.columns:
                continue
            sub = grp[["gc_config", col]].dropna().sort_values(col, ascending=False)
            if sub.empty:
                continue
            best = sub.iloc[0]
            runner = sub.iloc[1] if len(sub) > 1 else None
            rows.append({
                "benchmark": bm,
                "suite":     grp["suite"].iloc[0],
                "persona":   persona,
                "best_gc":   best["gc_config"],
                "best_score": round(best[col], 4),
                "runner_up": runner["gc_config"] if runner is not None else "",
                "margin":    round(best[col] - runner[col], 4)
                             if runner is not None else 1.0,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# DECISION TREE
# ---------------------------------------------------------------------------

def build_decision_tree(
        profiles: pd.DataFrame,
        recs: pd.DataFrame,
        persona: str = "Latency-Critical",
) -> tuple[DecisionTreeClassifier, LabelEncoder, list[str]]:
    """
    Train a shallow decision tree:
        Input:  workload features (gc_frequency, alloc_rate, …)
        Target: best GC for the given persona

    Returns (fitted clf, label_encoder, feature_names).
    """
    persona_recs = recs[recs["persona"] == persona][["benchmark", "best_gc"]]
    merged = profiles.merge(persona_recs, on="benchmark")
    merged = merged.dropna(subset=WORKLOAD_FEATURE_COLS)

    if len(merged) < 4:
        return None, None, WORKLOAD_FEATURE_COLS

    X = merged[WORKLOAD_FEATURE_COLS].values
    le = LabelEncoder()
    y = le.fit_transform(merged["best_gc"].values)

    clf = DecisionTreeClassifier(
        max_depth=3,          # shallow = interpretable
        min_samples_leaf=2,
        random_state=42,
    )
    clf.fit(X, y)

    acc = accuracy_score(y, clf.predict(X))
    print(f"  Decision tree ({persona}): "
          f"{len(merged)} samples, train accuracy={acc:.0%}, "
          f"depth={clf.get_depth()}, leaves={clf.get_n_leaves()}")

    # Print human-readable rules
    rules = export_text(clf, feature_names=WORKLOAD_FEATURE_COLS,
                        max_depth=3)
    print("  Decision Rules:")
    for line in rules.splitlines()[:30]:
        print("    " + line)

    return clf, le, WORKLOAD_FEATURE_COLS


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


def _save(fig, path: Path):
    os.makedirs(path.parent, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {path.name}")


# ---------------------------------------------------------------------------
# CHART 1: Recommendation Heatmap
# ---------------------------------------------------------------------------

def plot_recommendation_heatmap(recs: pd.DataFrame, out_dir: Path):
    """
    Heatmap: rows = benchmarks, columns = personas.
    Cell color = best GC for that benchmark × persona.
    Cell text = best GC label.
    """
    benchmarks = sorted(recs["benchmark"].unique())
    personas   = list(PERSONAS.keys())

    # Map GC → integer index for color
    gc_colormap = {gc: i for i, gc in enumerate(GC_ORDER)}
    n_colors = len(GC_ORDER)
    # Build a discrete colormap from GC_STYLES colors
    gc_colors_list = [GC_STYLES[gc][1] for gc in GC_ORDER]

    matrix    = np.full((len(benchmarks), len(personas)), np.nan)
    matrix_gc = [["" for _ in personas] for _ in benchmarks]

    for i, bm in enumerate(benchmarks):
        for j, persona in enumerate(personas):
            sub = recs[(recs["benchmark"] == bm) & (recs["persona"] == persona)]
            if not sub.empty:
                best = sub.iloc[0]["best_gc"]
                matrix[i, j] = gc_colormap.get(best, -1)
                matrix_gc[i][j] = best

    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap(gc_colors_list)
    bounds = np.arange(-0.5, n_colors + 0.5, 1)
    norm = BoundaryNorm(bounds, cmap.N)

    fig, ax = plt.subplots(
        figsize=(max(10, len(personas) * 2.5), max(6, len(benchmarks) * 0.55)),
        facecolor=LIGHT_BG)
    ax.set_facecolor(CARD_BG)

    im = ax.imshow(matrix, aspect="auto", cmap=cmap, norm=norm)

    for i in range(len(benchmarks)):
        for j in range(len(personas)):
            gc = matrix_gc[i][j]
            if gc:
                label = GC_STYLES.get(gc, (gc,))[0]
                # Short label
                short = label.replace("G1GC", "G1")  \
                              .replace("Shenandoah", "Shena")  \
                              .replace("ZGC", "ZGC") \
                              .replace("Non-Gen", "NG") \
                              .replace(" (", "\n(")
                ax.text(j, i, short, ha="center", va="center",
                        fontsize=7.5, color="white",
                        fontweight="bold")

    ax.set_xticks(range(len(personas)))
    ax.set_xticklabels(personas, fontsize=10, color=TEXT_COLOR, rotation=15)
    ax.set_yticks(range(len(benchmarks)))
    ax.set_yticklabels(benchmarks, fontsize=9, color=TEXT_COLOR)
    ax.set_title("GC Recommendation by Workload Priority\n"
                 "(Best GC per benchmark × deployment persona)",
                 fontsize=13, fontweight="bold", color=TEXT_COLOR)

    # Legend patches
    patches = [mpatches.Patch(color=GC_STYLES[gc][1], label=GC_STYLES[gc][0])
               for gc in GC_ORDER]
    ax.legend(handles=patches, fontsize=8, facecolor=CARD_BG,
              edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR,
              loc="lower right", bbox_to_anchor=(1.35, 0))

    _save(fig, out_dir / "recommendation_heatmap.png")


# ---------------------------------------------------------------------------
# CHART 2: Win-rate per GC per persona
# ---------------------------------------------------------------------------

def plot_win_rates(recs: pd.DataFrame, out_dir: Path):
    """
    Stacked / grouped bar: for each persona, how many benchmarks does each
    GC win? Shows dominance and coverage.
    """
    personas   = list(PERSONAS.keys())
    n_p = len(personas)
    x   = np.arange(n_p)
    bar_w = 0.8 / len(GC_ORDER)

    fig, ax = _base_fig(w=max(12, n_p * 2.5), h=6)

    for i, gc in enumerate(GC_ORDER):
        label, color = GC_STYLES[gc]
        counts = []
        for persona in personas:
            sub = recs[recs["persona"] == persona]
            counts.append((sub["best_gc"] == gc).sum())
        offset = (i - len(GC_ORDER) / 2 + 0.5) * bar_w
        bars = ax.bar(x + offset, counts, bar_w * 0.88,
                      label=label, color=color, edgecolor=BAR_EDGE,
                      linewidth=0.6, alpha=0.88)
        for bar, val in zip(bars, counts):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.05,
                        str(val), ha="center", va="bottom",
                        fontsize=8, color=TEXT_COLOR, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(personas, fontsize=10, rotation=10)
    ax.set_xlabel("Deployment Persona", fontsize=11)
    ax.set_ylabel("# Benchmarks Won", fontsize=11)
    ax.set_title("GC Win Count per Deployment Persona\n"
                 "(How many benchmarks each GC is recommended for)",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR, loc="upper right")
    _save(fig, out_dir / "win_rates_per_persona.png")


# ---------------------------------------------------------------------------
# CHART 3: Workload Feature heatmap (benchmark profiles)
# ---------------------------------------------------------------------------

def plot_workload_profiles(profiles: pd.DataFrame, out_dir: Path):
    """
    Heatmap: rows = benchmarks, cols = workload features.
    Normalized per column (0=min, 1=max) to show relative intensity.
    """
    feat_display = {
        "gc_frequency":   "GC Freq\n(evt/s)",
        "alloc_rate":     "Alloc Rate\n(MB/s)",
        "heap_pressure":  "Heap\nPressure",
        "tail_ratio":     "Tail Ratio\n(P99/P50)",
        "pause_overhead": "Pause\nOverhead",
    }
    features = [f for f in WORKLOAD_FEATURE_COLS if f in profiles.columns]
    bms = profiles["benchmark"].tolist()

    matrix = profiles[features].values.astype(float)
    # Normalize each column
    for j in range(matrix.shape[1]):
        col = matrix[:, j]
        valid = col[~np.isnan(col)]
        if len(valid) == 0 or valid.max() == valid.min():
            continue
        matrix[:, j] = (col - np.nanmin(col)) / (np.nanmax(col) - np.nanmin(col))

    fig, ax = plt.subplots(
        figsize=(max(8, len(features) * 1.8), max(5, len(bms) * 0.55)),
        facecolor=LIGHT_BG)
    ax.set_facecolor(CARD_BG)

    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1)

    for i in range(len(bms)):
        for j, feat in enumerate(features):
            raw_val = profiles[feat].values[i]
            if not np.isnan(raw_val):
                norm_v = matrix[i, j]
                txt_c = "black" if norm_v < 0.65 else "white"
                ax.text(j, i, f"{raw_val:.2g}", ha="center", va="center",
                        fontsize=7.5, color=txt_c)

    ax.set_xticks(range(len(features)))
    ax.set_xticklabels([feat_display.get(f, f) for f in features],
                       fontsize=9, color=TEXT_COLOR)
    ax.set_yticks(range(len(bms)))
    ax.set_yticklabels(bms, fontsize=9, color=TEXT_COLOR)
    ax.set_title("Workload Characterization Profile\n"
                 "(Normalized per feature; darker = higher intensity)",
                 fontsize=12, fontweight="bold", color=TEXT_COLOR)

    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.04)
    cbar.ax.tick_params(colors=TEXT_COLOR)
    cbar.set_label("Normalized intensity", color=TEXT_COLOR, fontsize=8)

    _save(fig, out_dir / "workload_profile_heatmap.png")


# ---------------------------------------------------------------------------
# CHART 4: PCA scatter of workloads, colored by best GC (Latency-Critical)
# ---------------------------------------------------------------------------

def plot_pca_cluster(profiles: pd.DataFrame, recs: pd.DataFrame,
                     out_dir: Path, persona: str = "Latency-Critical"):
    """
    PCA 2D projection of workload feature vectors.
    Each point = benchmark, color = recommended GC for `persona`.
    Reveals natural clusters and what GC fits each cluster.
    """
    feat_cols = [f for f in WORKLOAD_FEATURE_COLS if f in profiles.columns]
    sub = profiles.dropna(subset=feat_cols).copy()
    if len(sub) < 3:
        return

    persona_recs = recs[recs["persona"] == persona][["benchmark", "best_gc"]]
    sub = sub.merge(persona_recs, on="benchmark", how="left")

    X = sub[feat_cols].fillna(0).values
    X_scaled = StandardScaler().fit_transform(X)

    n_components = min(2, X_scaled.shape[1], X_scaled.shape[0] - 1)
    pca = PCA(n_components=n_components, random_state=42)
    coords = pca.fit_transform(X_scaled)
    var_explained = pca.explained_variance_ratio_ * 100

    fig, ax = _base_fig(w=9, h=7)
    ax.grid(color=GRID_COLOR, linewidth=0.6, linestyle="--", alpha=0.4)

    plotted_gcs = set()
    for i, row in sub.iterrows():
        gc = row.get("best_gc", "")
        label, color = GC_STYLES.get(gc, (gc, "#94a3b8"))
        idx = sub.index.get_loc(i)
        legend_label = label if gc not in plotted_gcs else "_nolegend_"
        plotted_gcs.add(gc)
        ax.scatter(coords[idx, 0], coords[idx, 1] if coords.shape[1] > 1 else 0,
                   color=color, s=110, edgecolors=BAR_EDGE,
                   linewidths=0.7, zorder=3, label=legend_label)
        ax.annotate(row["benchmark"], (coords[idx, 0],
                                       coords[idx, 1] if coords.shape[1] > 1 else 0),
                    fontsize=7.5, color=TEXT_COLOR,
                    xytext=(5, 4), textcoords="offset points")

    xlab = f"PC1 ({var_explained[0]:.1f}% var)"
    ylab = f"PC2 ({var_explained[1]:.1f}% var)" if len(var_explained) > 1 else "PC2"
    ax.set_xlabel(xlab, fontsize=11)
    ax.set_ylabel(ylab, fontsize=11)
    ax.set_title(f"Workload Clusters — Color = Recommended GC\n"
                 f"(Persona: {persona})",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=8, facecolor=CARD_BG, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR)
    _save(fig, out_dir / f"pca_cluster_{persona.lower().replace('-', '_')}.png")


# ---------------------------------------------------------------------------
# CHART 5: Decision tree visualization
# ---------------------------------------------------------------------------

def plot_decision_tree(clf, le, feature_names: list[str],
                       persona: str, out_dir: Path):
    if clf is None:
        return
    class_names = [GC_STYLES.get(gc, (gc,))[0] for gc in le.classes_]
    fig, ax = plt.subplots(figsize=(16, 7), facecolor=LIGHT_BG)
    ax.set_facecolor(LIGHT_BG)

    feat_display = {
        "gc_frequency":   "GC Freq",
        "alloc_rate":     "Alloc Rate",
        "heap_pressure":  "Heap Pressure",
        "tail_ratio":     "Tail Ratio",
        "pause_overhead": "Pause Overhead",
    }
    display_names = [feat_display.get(f, f) for f in feature_names]

    plot_tree(
        clf,
        feature_names=display_names,
        class_names=class_names,
        filled=True,
        rounded=True,
        fontsize=9,
        ax=ax,
        impurity=False,
        precision=3,
    )
    ax.set_title(f"GC Recommendation Decision Tree — {persona} Persona\n"
                 f"(Workload features → recommended GC)",
                 fontsize=12, fontweight="bold", color=TEXT_COLOR, pad=12)
    fig.tight_layout()
    fname = f"decision_tree_{persona.lower().replace('-', '_')}.png"
    fig.savefig(out_dir / fname, dpi=150, bbox_inches="tight",
                facecolor=LIGHT_BG)
    plt.close(fig)
    print(f"  Saved → {fname}")


# ---------------------------------------------------------------------------
# CHART 6: Feature importance bar chart
# ---------------------------------------------------------------------------

def plot_feature_importance(clf, feature_names: list[str],
                             persona: str, out_dir: Path):
    if clf is None:
        return
    importances = clf.feature_importances_
    feat_display = {
        "gc_frequency":   "GC Frequency (evt/s)",
        "alloc_rate":     "Allocation Rate (MB/s)",
        "heap_pressure":  "Heap Pressure (used/alloc)",
        "tail_ratio":     "Tail Ratio (P99/P50)",
        "pause_overhead": "Pause Overhead (STW/walltime)",
    }
    labels = [feat_display.get(f, f) for f in feature_names]
    colors = [GC_STYLES["zgc_gen"][1], GC_STYLES["shenandoah"][1],
              GC_STYLES["g1gc"][1], GC_STYLES["zgc_nogen"][1],
              GC_STYLES["g1gc_pause50"][1]][:len(labels)]

    order = np.argsort(importances)[::-1]
    fig, ax = _base_fig(w=9, h=5)
    bars = ax.bar(range(len(labels)),
                  importances[order],
                  color=[colors[o % len(colors)] for o in order],
                  edgecolor=BAR_EDGE, linewidth=0.7, alpha=0.88)

    for bar, imp in zip(bars, importances[order]):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f"{imp:.3f}", ha="center", va="bottom",
                fontsize=9, color=TEXT_COLOR, fontweight="bold")

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([labels[o] for o in order],
                       rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Feature Importance (Gini)", fontsize=11)
    ax.set_title(f"Which Workload Features Drive GC Selection?\n"
                 f"(Persona: {persona})",
                 fontsize=12, fontweight="bold")
    _save(fig, out_dir / f"feature_importance_{persona.lower().replace('-', '_')}.png")


# ---------------------------------------------------------------------------
# CHART 7: Per-GC score distribution across benchmarks (violin / box proxy)
# ---------------------------------------------------------------------------

def plot_score_distribution(scored: pd.DataFrame, persona: str, out_dir: Path):
    """
    Box plot: for each GC the distribution of composite scores across all
    benchmarks. Shows which GC is consistently good vs. variable.
    """
    col = f"score_{persona}"
    if col not in scored.columns:
        return

    gcs_present = [gc for gc in GC_ORDER if gc in scored["gc_config"].unique()]
    all_data = []
    labels, colors = [], []
    for gc in gcs_present:
        vals = scored[scored["gc_config"] == gc][col].dropna().values
        if len(vals) > 0:
            all_data.append(vals)
            labels.append(GC_STYLES[gc][0])
            colors.append(GC_STYLES[gc][1])

    if not all_data:
        return

    fig, ax = _base_fig(w=10, h=6)
    bp = ax.boxplot(all_data, patch_artist=True, notch=False,
                    medianprops={"color": "#f8fafc", "linewidth": 2},
                    whiskerprops={"color": GRID_COLOR},
                    capprops={"color": GRID_COLOR},
                    flierprops={"marker": "o", "markersize": 3,
                                "alpha": 0.4, "markeredgecolor": "none"})
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.82)
        patch.set_edgecolor(BAR_EDGE)
    for flier, color in zip(bp["fliers"], colors):
        flier.set_markerfacecolor(color)

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, fontsize=10, rotation=15, ha="right")
    ax.set_ylabel(f"Composite Score (0–1)", fontsize=11)
    ax.set_title(f"GC Score Distribution — {persona} Persona\n"
                 f"(Higher = better fit; wider box = more variable)",
                 fontsize=12, fontweight="bold")
    _save(fig, out_dir / f"score_distribution_{persona.lower().replace('-', '_')}.png")


# ---------------------------------------------------------------------------
# CHART 8: Recommendation consistency — does the same GC win across personas?
# ---------------------------------------------------------------------------

def plot_consistency_matrix(recs: pd.DataFrame, out_dir: Path):
    """
    For each benchmark: how many unique GCs are recommended across the 4 personas?
    1 = fully consistent, 4 = different GC for every persona.
    Also shows which GC is most frequent.
    """
    rows = []
    for bm, grp in recs.groupby("benchmark"):
        unique_gcs = grp["best_gc"].nunique()
        dominant   = grp["best_gc"].mode().iloc[0]
        rows.append({
            "benchmark":    bm,
            "n_unique_gcs": unique_gcs,
            "dominant_gc":  dominant,
            "suite":        grp["suite"].iloc[0],
        })
    consistency = pd.DataFrame(rows).sort_values("n_unique_gcs")

    fig, ax = _base_fig(w=11, h=5)
    bar_colors = [GC_STYLES.get(row["dominant_gc"], (None, "#94a3b8"))[1]
                  for _, row in consistency.iterrows()]
    bars = ax.barh(range(len(consistency)),
                   consistency["n_unique_gcs"],
                   color=bar_colors, edgecolor=BAR_EDGE,
                   linewidth=0.6, alpha=0.88)

    ax.set_yticks(range(len(consistency)))
    ax.set_yticklabels(consistency["benchmark"], fontsize=9, color=TEXT_COLOR)
    ax.set_xlabel("# Different GCs Recommended (across 4 personas)", fontsize=10)
    ax.set_title("Recommendation Consistency per Benchmark\n"
                 "(1 = same GC wins regardless of priority; bar color = dominant GC)",
                 fontsize=12, fontweight="bold")
    ax.axvline(2, color=TEXT_COLOR, linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_xlim(0, len(PERSONAS) + 0.5)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_xticklabels(["1\n(Consistent)", "2", "3", "4\n(Divided)"],
                       fontsize=9)
    ax.invert_yaxis()

    # Legend
    patches = [mpatches.Patch(color=GC_STYLES[gc][1],
                              label=f"{GC_STYLES[gc][0]} (dominant)")
               for gc in GC_ORDER
               if gc in consistency["dominant_gc"].values]
    ax.legend(handles=patches, fontsize=8, facecolor=CARD_BG,
              edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
    _save(fig, out_dir / "recommendation_consistency.png")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    os.makedirs(CSV_DIR, exist_ok=True)

    print("=" * 65)
    print("  GC Recommendation Framework — JVM Workload Characterization")
    print("=" * 65)

    # ── Load & merge ─────────────────────────────────────────────────────
    print("\n[1/5] Loading and merging metric data...")
    df = load_and_merge()
    df = engineer_features(df)
    print(f"  {len(df)} rows | {df['benchmark'].nunique()} benchmarks "
          f"| {df['gc_config'].nunique()} GC configs")

    # ── Workload profiles ────────────────────────────────────────────────
    print("\n[2/5] Computing workload profiles...")
    profiles = compute_workload_profiles(df)
    profiles.to_csv(CSV_DIR / "gc_workload_features.csv", index=False)
    print(f"  Saved workload features → gc_workload_features.csv")
    print(profiles[["benchmark"] + WORKLOAD_FEATURE_COLS].to_string(index=False))

    # ── Score & elect best GC ────────────────────────────────────────────
    print("\n[3/5] Scoring GC configs per benchmark and persona...")
    scored = score_gcs(df)
    recs   = elect_best_gc(scored)
    recs.to_csv(CSV_DIR / "gc_recommendations.csv", index=False)
    print(f"  Saved recommendations → gc_recommendations.csv")
    print("\n  Recommendation matrix:")
    pivot = recs.pivot(index="benchmark", columns="persona",
                       values="best_gc")
    pivot = pivot[[p for p in PERSONAS if p in pivot.columns]]
    print(pivot.to_string())

    # ── Decision trees for all personas ─────────────────────────────────
    print("\n[4/5] Training decision trees for all personas...")
    trees = {}
    for persona in PERSONAS:
        clf_p, le_p, feat_names = build_decision_tree(
            profiles, recs, persona=persona)
        trees[persona] = (clf_p, le_p, feat_names)

    # ── Charts ───────────────────────────────────────────────────────────
    print(f"\n[5/5] Generating charts → {GRAPHS_DIR}/")
    plot_recommendation_heatmap(recs, GRAPHS_DIR)
    plot_win_rates(recs, GRAPHS_DIR)
    plot_workload_profiles(profiles, GRAPHS_DIR)
    for persona in PERSONAS:
        plot_pca_cluster(profiles, recs, GRAPHS_DIR, persona=persona)
        plot_score_distribution(scored, persona, GRAPHS_DIR)
        clf_p, le_p, feat_names = trees[persona]
        plot_decision_tree(clf_p, le_p, feat_names, persona, GRAPHS_DIR)
        plot_feature_importance(clf_p, feat_names, persona, GRAPHS_DIR)
    plot_consistency_matrix(recs, GRAPHS_DIR)

    print("\n" + "=" * 65)
    print("  Done!")
    print(f"  CSVs:   {CSV_DIR}/gc_recommendations.csv")
    print(f"          {CSV_DIR}/gc_workload_features.csv")
    print(f"  Charts: {GRAPHS_DIR}/")
    print("=" * 65)

    # ── Quick text summary for paper ────────────────────────────────────
    print("\n── GC Win Counts by Persona ──")
    for persona in PERSONAS:
        sub = recs[recs["persona"] == persona]
        counts = sub["best_gc"].value_counts()
        print(f"\n  {persona}:")
        for gc, n in counts.items():
            bms = sub[sub["best_gc"] == gc]["benchmark"].tolist()
            print(f"    {GC_STYLES.get(gc, (gc,))[0]:25s} {n:2d} wins "
                  f"({', '.join(bms)})")


if __name__ == "__main__":
    main()
