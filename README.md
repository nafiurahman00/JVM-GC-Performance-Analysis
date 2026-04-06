# Performance Study of Modern JVM Garbage Collectors

A comprehensive empirical study comparing six GC configurations on Java 21
across two benchmark suites (DaCapo Chopin and Renaissance), energy
consumption measured via Intel RAPL, tail latency percentile analysis, heap
size sensitivity, Epsilon GC baseline benchmarking, Generational ZGC
statistical analysis, and a workload-aware GC recommendation framework.

---

## Table of Contents

1. [Background and Motivation](#background-and-motivation)
2. [GC Configurations Tested](#gc-configurations-tested)
3. [Benchmark Suites](#benchmark-suites)
4. [Experiments](#experiments)
   - [Experiment 1 — DaCapo Performance Comparison](#experiment-1--dacapo-performance-comparison)
   - [Experiment 2 — Renaissance Performance Comparison](#experiment-2--renaissance-performance-comparison)
   - [Experiment 3 — Heap Size Sensitivity](#experiment-3--heap-size-sensitivity)
   - [Experiment 4 — Epsilon GC Baseline](#experiment-4--epsilon-gc-baseline)
   - [Experiment 5 — Energy Consumption](#experiment-5--energy-consumption)
   - [Experiment 6 — Tail Latency Analysis](#experiment-6--tail-latency-analysis)
   - [Experiment 7 — Generational ZGC Statistical Analysis](#experiment-7--generational-zgc-statistical-analysis)
   - [Experiment 8 — GC Recommendation Framework](#experiment-8--gc-recommendation-framework)
5. [Analysis Pipeline](#analysis-pipeline)
6. [Environment Requirements](#environment-requirements)
7. [Directory Structure](#directory-structure)
8. [Step-by-Step Execution Guide](#step-by-step-execution-guide)
9. [Output Reference](#output-reference)
10. [Troubleshooting](#troubleshooting)

---

## Background and Motivation

The original CSE6305 study benchmarked three garbage collectors (G1GC,
Shenandoah, ZGC) on OpenJDK 11.0.15 using DaCapo 9.12-MR1 and Renaissance.
GC logs were analyzed with GCEasy, a web-based tool.

This study identifies and addresses five gaps:

1. **Java 21 + Generational ZGC.** Java 21 introduced `-XX:+ZGenerational`,
   splitting the ZGC heap into young and old generations. This was unavailable
   on Java 11 and was not studied.
2. **GC tuning parameters.** The original study varied only `-Xmx`. Two
   additional G1GC tuning dimensions are tested: a tighter pause-time target
   (`-XX:MaxGCPauseMillis=50`) and reduced concurrency (`-XX:ConcGCThreads=2`).
3. **No-op GC ceiling.** Epsilon GC never reclaims memory, establishing a
   theoretical performance ceiling with zero GC overhead.
4. **Energy consumption.** Every benchmark/GC combination is measured for CPU
   package energy (Joules) using Intel RAPL, enabling an energy–performance
   Pareto analysis.
5. **Offline reproducible tooling.** GCEasy is replaced with GCViewer 1.36, a
   local CLI tool that produces ~60 structured metrics per log, fully offline.

---

## GC Configurations Tested

| Config name       | JVM flags                                                        | Description                              |
|:------------------|:-----------------------------------------------------------------|:-----------------------------------------|
| `g1gc`            | `-XX:+UseG1GC`                                                   | G1GC with default settings               |
| `shenandoah`      | `-XX:+UseShenandoahGC`                                           | Shenandoah with default settings         |
| `zgc_nogen`       | `-XX:+UseZGC -XX:-ZGenerational`                                 | Non-Generational ZGC (Java 11 equivalent)|
| `zgc_gen`         | `-XX:+UseZGC -XX:+ZGenerational`                                 | Generational ZGC (new in Java 21)        |
| `g1gc_pause50`    | `-XX:+UseG1GC -XX:MaxGCPauseMillis=50`                          | G1GC with 50 ms pause-time target        |
| `g1gc_threads2`   | `-XX:+UseG1GC -XX:ConcGCThreads=2`                              | G1GC with 2 concurrent GC threads        |
| `epsilon`         | `-XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC`            | No-op GC (Experiment 4 only)             |

All configurations enable detailed unified GC logging:

```
-Xlog:gc*:file=<output.log>:time,uptime,level,tags
```

---

## Benchmark Suites

### DaCapo Chopin 23.11-MR2

Real-world Java applications packaged as repeatable benchmarks. The Chopin
release (December 2023) is used for Java 21 compatibility.

| Benchmark | Description                                     |
|:----------|:------------------------------------------------|
| `avrora`  | AVR microcontroller simulator                    |
| `batik`   | SVG rendering/rasterization (Apache Batik)       |
| `fop`     | XSL-FO to PDF rendering (Apache FOP)             |
| `h2`      | In-memory SQL database (OLTP workload)           |
| `luindex` | Full-text index construction (Lucene)            |
| `lusearch`| Full-text search over a corpus (Lucene)          |
| `pmd`     | Static analysis of Java source code              |
| `sunflow` | Ray-tracing image renderer                       |
| `tomcat`  | HTTP server request handling (Apache Tomcat)     |
| `xalan`   | XSLT transformations (Apache Xalan)              |

### Renaissance 0.16.1

Modern JVM workloads focusing on concurrency, functional programming, and
distributed systems patterns. Each benchmark runs for 3 repetitions.

| Benchmark      | Description                                     |
|:---------------|:------------------------------------------------|
| `chi-square`   | Chi-squared statistical test (Spark)            |
| `dec-tree`     | Decision tree classification (Spark ML)         |
| `dotty`        | Scala 3 compiler (Dotty)                        |
| `finagle-http` | Twitter Finagle HTTP server                     |
| `movie-lens`   | Collaborative filtering recommendation (Spark)  |
| `page-rank`    | PageRank graph algorithm (Spark)                |
| `philosophers` | Dining philosophers concurrency problem         |
| `scala-kmeans` | K-means clustering in Scala                     |

---

## Experiments

### Experiment 1 — DaCapo Performance Comparison

**Script:** `scripts/run_dacapo.sh`

Runs all 10 DaCapo benchmarks with 6 GC configurations (all except Epsilon)
at a fixed 2 GB heap. Each benchmark runs once per GC.

- **Total runs:** 10 benchmarks × 6 GCs = 60 runs
- **Output:** `results/dacapo/<benchmark>/<gc_name>.log`

**Metrics captured via GCViewer:**

| Metric              | Unit  | What it measures                           |
|:--------------------|:------|:-------------------------------------------|
| `throughput`        | %     | Time not spent in GC (higher = better)     |
| `avgPause`          | ms    | Mean GC stop-the-world pause duration      |
| `maxPause`          | ms    | Worst single GC pause duration             |
| `pauseCount`        | count | Total number of GC pauses                  |
| `accumPause`        | ms    | Total time in GC pauses                    |
| `totalHeapUsedMax`  | MB    | Peak live heap usage                       |
| `totalHeapAllocMax` | MB    | Maximum heap capacity allocated            |
| `gcPerformance`     | MB/s  | Memory reclamation rate                    |
| `freedMemory`       | MB    | Total memory freed over the run            |
| `wallTimeSec`       | s     | Total benchmark wall-clock execution time  |

**Graphs generated** (`graphs/dacapo/`):

- Per-metric grouped bar charts across all 6 GC configs for all 10 benchmarks
  (`dacapo_<metric>.png`)
- G1GC tuning comparison: default vs `pause50` vs `threads2`
  (`graphs/dacapo/g1gc_tuning/`)
- ZGC generational vs non-generational
  (`graphs/dacapo/zgc_comparison/`)

---

### Experiment 2 — Renaissance Performance Comparison

**Script:** `scripts/run_renaissance.sh`

Runs all 8 Renaissance benchmarks with 6 GC configurations at a fixed 2 GB
heap. Each benchmark runs 3 repetitions (`-r 3`) for statistical robustness.

- **Total runs:** 8 benchmarks × 6 GCs = 48 runs (3 reps each)
- **Output:** `results/renaissance/<benchmark>/<gc_name>.log`

Same metrics and graph structure as Experiment 1, with `renaissance_` prefix.
Renaissance-specific graphs under `graphs/renaissance/`.

---

### Experiment 3 — Heap Size Sensitivity

**Script:** `scripts/run_renaissance_heap_vary.sh`

Tests three memory-intensive Renaissance benchmarks across 7 heap sizes with
4 GC configurations to reveal how each GC responds to heap pressure.

- **Benchmarks:** `chi-square`, `movie-lens`, `page-rank`
- **Heap sizes:** 500, 750, 1000, 1250, 1500, 1750, 2000 MB
- **GC configs:** `g1gc`, `shenandoah`, `zgc_nogen`, `zgc_gen`
- **Total runs:** 3 × 7 × 4 = 84 runs
- **Output:** `results/heap_vary/<benchmark>/<gc_name>_<size>M.log`

**Graphs generated** (`graphs/heap_vary/`):

Line charts plotting throughput, average pause, max pause, pause count, peak
heap used, heap allocated, GC performance, and wall time as a function of heap
size — one chart per metric per benchmark. Cross-benchmark overlay charts at
1000 MB and 1500 MB fixed heap are also produced.

---

### Experiment 4 — Epsilon GC Baseline

**Script:** `scripts/run_dacapo_epsilon.sh`

Runs all 10 DaCapo benchmarks with Epsilon GC using a 4 GB heap. Epsilon never
reclaims memory, providing a theoretical ceiling: the execution time if GC
overhead were zero. Benchmarks that allocate more than 4 GB during their
lifetime crash with `OutOfMemoryError`, which is expected and recorded.

- **Total runs:** 10 benchmarks × 1 GC = 10 runs
- **Output:** `results/epsilon/<benchmark>/epsilon_status.txt` (`SUCCESS` or `OOM_OR_FAILED`)

Results are compared against the 6 standard GCs to quantify the true GC
overhead on each workload.

---

### Experiment 5 — Energy Consumption

**Script:** `scripts/run_energy_benchmarks.sh`  
**Analyzer:** `scripts/analyze_energy.py`

Every benchmark/GC combination is re-run with live energy measurement via
Intel RAPL (Running Average Power Limit). Energy is sampled from the sysfs
interface (`/sys/class/powercap/intel-rapl`) before and after each benchmark
run; if RAPL sysfs is unavailable, `perf stat -e power/energy-pkg/` is used
as a fallback.

- **Domains measured:** CPU package (pkg), CPU cores, uncore (GPU + memory
  controller)
- **Suites:** Both DaCapo (10 benchmarks) and Renaissance (8 benchmarks)
- **GC configs:** All 6 standard configurations
- **Output:** `results/energy/<suite>/<benchmark>/<gc>_energy.txt`
  (keys: `energy_pkg_joules`, `energy_cores_joules`, `energy_uncore_joules`,
  `wall_time_ms`)

**Analysis output** (`results/energy/energy_summary.csv`):

Tabular summary of Joules and watt-average across all combinations.

**Graphs generated** (`graphs/energy/`):

| Graph                                    | Description                                           |
|:-----------------------------------------|:------------------------------------------------------|
| `combined/energy_consumption.png`        | Grouped bar chart: pkg Joules per GC across benchmarks |
| `combined/energy_normalized_vs_g1gc.png` | Normalized energy (G1GC = 1.0) to show relative cost  |
| `combined/energy_vs_walltime.png`        | Scatter plot: wall-clock time vs energy (per run)     |
| `combined/energy_pareto_all.png`         | Pareto frontier: execution time vs energy tradeoff    |
| `dacapo/`                                | DaCapo-only energy charts                            |
| `renaissance/`                           | Renaissance-only energy charts                       |

---

### Experiment 6 — Tail Latency Analysis

**Script:** `scripts/analyze_tail_latency.py`

Parses every raw GC log from Experiments 1 and 2 to extract each individual
stop-the-world (STW) pause duration. Computes pause latency percentiles per
benchmark × GC configuration.

- **Percentiles computed:** P50, P95, P99, P99.9
- **Input:** existing `results/dacapo/` and `results/renaissance/` GC logs
- **Output CSVs:** `results/csv/tail_latency_dacapo.csv`,
  `results/csv/tail_latency_renaissance.csv`

**Graphs generated** (`graphs/tail_latency/`):

| Graph                                              | Description                                    |
|:---------------------------------------------------|:-----------------------------------------------|
| `dacapo_tail_latency_aggregated.png`               | P50/P95/P99/P99.9 grouped bar chart (DaCapo)  |
| `dacapo_tail_latency_p99_per_benchmark.png`        | P99 per benchmark, GCs side by side            |
| `dacapo_tail_latency_p99.9_per_benchmark.png`      | P99.9 per benchmark, GCs side by side          |
| `dacapo_p99_heatmap.png`                           | Heatmap: benchmark × GC → P99 pause (ms)      |
| `dacapo_pause_boxplot.png`                         | Box plot: STW pause distributions per GC       |
| `dacapo_p50_vs_p99_scatter.png`                    | Scatter: median pause vs tail pause            |
| `renaissance_tail_latency_aggregated.png`          | Same charts for Renaissance benchmarks         |
| `renaissance_tail_latency_p99_per_benchmark.png`   |                                                |
| `renaissance_tail_latency_p99.9_per_benchmark.png` |                                                |
| `renaissance_p99_heatmap.png`                      |                                                |
| `renaissance_pause_boxplot.png`                    |                                                |
| `renaissance_p50_vs_p99_scatter.png`               |                                                |
| `cdf/`                                             | Per-benchmark CDF plots, all GCs overlaid      |

---

### Experiment 7 — Generational ZGC Statistical Analysis

**Script:** `scripts/analyze_zgc_gen.py`

Performs a rigorous statistical comparison of Generational ZGC (`zgc_gen`)
versus Non-Generational ZGC (`zgc_nogen`) and all other GC configurations.
Uses Wilcoxon signed-rank tests (non-parametric, paired) plus effect size
estimation (rank-biserial correlation) across multiple metrics.

**Research questions addressed:**

1. Does Generational ZGC improve throughput, pause latency, and heap
   efficiency compared to Non-Generational ZGC on Java 21 workloads?
2. For which workload characteristics does Generational ZGC underperform?
3. How does Generational ZGC compare to G1GC and Shenandoah per benchmark?

**Output CSVs:**

| File                                                | Content                                              |
|:----------------------------------------------------|:-----------------------------------------------------|
| `results/csv/zgc_gen_statistical_tests_dacapo.csv`      | Wilcoxon p-values + effect sizes for DaCapo          |
| `results/csv/zgc_gen_statistical_tests_renaissance.csv` | Same for Renaissance                                 |
| `results/csv/zgc_gen_statistical_tests_combined.csv`    | Combined cross-suite results                         |

---

### Experiment 8 — GC Recommendation Framework

**Script:** `scripts/analyze_gc_recommendation.py`

A workload-characterization-driven recommendation system that answers:
"Given *my workload*, which GC should I choose?"

**Pipeline:**

1. Derives five workload features from GCViewer CSVs and tail-latency data:
   - `gc_frequency` — GC events per second (how often GC fires)
   - `alloc_rate` — MB/s freed (allocation pressure)
   - `heap_pressure` — live-data ratio (used / allocated)
   - `tail_ratio` — P99 / P50 pause (how heavy the tails are)
   - `pause_overhead` — accumulated pause / wall time (fraction in STW)

2. Computes composite scores for four user *personas*: latency-critical,
   throughput-first, memory-constrained, balanced.

3. Elects the best GC per benchmark × persona and builds a recommendation
   matrix.

4. Trains a Decision Tree classifier mapping workload features to the
   recommended GC for the latency-critical persona.

**Output CSVs:**

| File                                    | Content                                              |
|:----------------------------------------|:-----------------------------------------------------|
| `results/csv/gc_recommendations.csv`    | Best GC per benchmark × persona                      |
| `results/csv/gc_workload_features.csv`  | Derived workload features per benchmark              |

**Graphs generated** (`graphs/recommendation/`):

| Graph                                   | Description                                          |
|:----------------------------------------|:-----------------------------------------------------|
| `recommendation_heatmap.png`            | Benchmark × persona → recommended GC (heatmap)      |
| `recommendation_consistency.png`        | How often the same GC wins across personas           |
| `win_rates_per_persona.png`             | Win-rate bar chart per GC config per persona         |
| `workload_profile_heatmap.png`          | Heatmap of normalized workload features per benchmark|
| `decision_tree_<persona>.png`           | Trained decision tree visualization (4 personas)     |
| `feature_importance_<persona>.png`      | Feature importance bar chart (4 personas)            |
| `pca_cluster_<persona>.png`             | PCA 2-D workload cluster map (4 personas)            |
| `score_distribution_<persona>.png`      | Score distribution across GCs (4 personas)           |

---

## Analysis Pipeline

After running the benchmark scripts, the analysis follows this sequence:

```
run_dacapo.sh
run_renaissance.sh
run_renaissance_heap_vary.sh
run_dacapo_epsilon.sh
run_energy_benchmarks.sh
        ↓
analyze_with_gcviewer.sh        # extract ~60 metrics from every GC log
        ↓
generate_graphs.py              # performance bar charts + heap-vary lines
analyze_energy.py               # energy charts + Pareto analysis
analyze_tail_latency.py         # tail latency percentile charts
analyze_zgc_gen.py              # Wilcoxon ZGC Gen vs Non-Gen tests
analyze_gc_recommendation.py    # recommendation heatmap + decision tree
```

---

## Environment Requirements

| Requirement     | Version  | Verify                                   |
|:----------------|:---------|:-----------------------------------------|
| OpenJDK         | 21+      | `java -version`                          |
| Bash            | 4.0+     | `bash --version`                         |
| Python 3        | 3.8+     | `python3 --version`                      |
| matplotlib      | 3.5+     | `python3 -c "import matplotlib"`         |
| numpy           | 1.20+    | `python3 -c "import numpy"`              |
| pandas          | 1.3+     | `python3 -c "import pandas"`             |
| scipy           | 1.7+     | `python3 -c "import scipy"`              |
| scikit-learn    | 1.0+     | `python3 -c "import sklearn"`            |

Install all Python dependencies:

```bash
pip install matplotlib numpy pandas scipy scikit-learn
```

**Energy measurement prerequisites:**

Intel RAPL is used for energy measurement. On most modern Linux distributions
the sysfs interface is readable without root. If not:

```bash
# Enable RAPL sysfs read access
sudo chmod a+r /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj

# Or lower perf_event_paranoid for perf stat fallback
sudo sysctl -w kernel.perf_event_paranoid=-1
```

**Hardware note:** Designed for a machine with at least 16 GB of RAM and 4+
CPU cores. The Epsilon experiment allocates up to 4 GB of heap per run. Full
pipeline execution takes approximately 3–6 hours.

---

## Directory Structure

```
experiment/
├── benchmarks/
│   ├── dacapo_chopin/
│   │   └── dacapo-23.11-MR2-chopin.jar
│   └── renaissance-gpl-0.16.1.jar
│
├── tools/
│   └── gcviewer-1.36.jar
│
├── scripts/
│   ├── run_dacapo.sh                  # Experiment 1: DaCapo (6 GCs)
│   ├── run_renaissance.sh             # Experiment 2: Renaissance (6 GCs)
│   ├── run_renaissance_heap_vary.sh   # Experiment 3: Heap size sensitivity
│   ├── run_dacapo_epsilon.sh          # Experiment 4: Epsilon GC baseline
│   ├── run_energy_benchmarks.sh       # Experiment 5: Energy via RAPL
│   ├── analyze_with_gcviewer.sh       # Batch GCViewer log analysis
│   ├── generate_graphs.py             # Performance comparison graphs
│   ├── analyze_energy.py              # Energy charts + Pareto analysis
│   ├── analyze_tail_latency.py        # Tail latency percentile analysis
│   ├── analyze_zgc_gen.py             # Generational ZGC statistical tests
│   ├── analyze_gc_recommendation.py   # GC recommendation framework
│   ├── fix_results_csvs.py            # CSV repair utility
│   └── fix_heap_vary_csvs.py          # Heap-vary CSV repair utility
│
├── results/
│   ├── dacapo/<benchmark>/
│   │   ├── <gc_name>.log              # Raw JVM GC log
│   │   ├── <gc_name>_time.txt         # Wall-clock time (ms)
│   │   └── <gc_name>_stdout.txt       # Benchmark stdout/stderr
│   ├── renaissance/<benchmark>/
│   │   ├── <gc_name>.log
│   │   ├── <gc_name>_time.txt
│   │   ├── <gc_name>_stdout.txt
│   │   └── <gc_name>_results.csv      # Per-iteration timings
│   ├── heap_vary/<benchmark>/
│   │   ├── <gc_name>_<size>M.log
│   │   └── <gc_name>_<size>M_time.txt
│   ├── epsilon/<benchmark>/
│   │   ├── epsilon.log
│   │   ├── epsilon_time.txt
│   │   └── epsilon_status.txt         # SUCCESS or OOM_OR_FAILED
│   ├── energy/
│   │   ├── energy_summary.csv
│   │   ├── dacapo/<benchmark>/<gc>_energy.txt
│   │   └── renaissance/<benchmark>/<gc>_energy.txt
│   ├── gcviewer_csv/                  # GCViewer SUMMARY CSVs (mirrors above)
│   │   ├── dacapo/
│   │   ├── renaissance/
│   │   ├── heap_vary/
│   │   └── epsilon/
│   └── csv/                           # Aggregated analysis CSVs
│       ├── dacapo_all_metrics.csv
│       ├── renaissance_all_metrics.csv
│       ├── tail_latency_dacapo.csv
│       ├── tail_latency_renaissance.csv
│       ├── gc_recommendations.csv
│       ├── gc_workload_features.csv
│       ├── zgc_gen_statistical_tests_dacapo.csv
│       ├── zgc_gen_statistical_tests_renaissance.csv
│       └── zgc_gen_statistical_tests_combined.csv
│
└── graphs/
    ├── dacapo/                        # DaCapo metric bar charts
    │   ├── dacapo_<metric>.png        # All 6 GCs, all 10 benchmarks
    │   ├── g1gc_tuning/               # G1GC default vs pause50 vs threads2
    │   └── zgc_comparison/            # Gen ZGC vs Non-Gen ZGC
    ├── renaissance/                   # Renaissance metric bar charts
    │   ├── renaissance_<metric>.png
    │   ├── g1gc_tuning/
    │   └── zgc_comparison/
    ├── heap_vary/                     # Heap sensitivity line charts
    │   ├── chi-square/
    │   ├── movie-lens/
    │   ├── page-rank/
    │   ├── cross_benchmark_1000M/
    │   └── cross_benchmark_1500M/
    ├── energy/                        # Energy charts
    │   ├── combined/
    │   ├── dacapo/
    │   └── renaissance/
    ├── tail_latency/                  # Percentile + CDF + box plots
    │   └── cdf/
    └── recommendation/                # Decision tree + feature importance
```

---

## Step-by-Step Execution Guide

All commands assume you are in the `experiment/` directory:

```bash
cd /path/to/Peformance-Study-of-Modern-JVM-GCs/experiment
```

### Step 0: Verify Prerequisites

```bash
# Java 21
java -version

# Check GC feature availability
java -XX:+UseZGC -XX:+ZGenerational -version
java -XX:+UseShenandoahGC -version
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -version

# Check benchmark JARs
java -jar benchmarks/dacapo_chopin/dacapo-23.11-MR2-chopin.jar -l
java -jar benchmarks/renaissance-gpl-0.16.1.jar --list | head -15

# Make scripts executable
chmod +x scripts/*.sh
```

### Step 1: DaCapo Performance Comparison

```bash
bash scripts/run_dacapo.sh 2>&1 | tee results/dacapo_run.log
```

### Step 2: Renaissance Performance Comparison

```bash
bash scripts/run_renaissance.sh 2>&1 | tee results/renaissance_run.log
```

### Step 3: Heap Size Sensitivity

```bash
bash scripts/run_renaissance_heap_vary.sh 2>&1 | tee results/heap_vary_run.log
```

### Step 4: Epsilon GC Baseline

```bash
bash scripts/run_dacapo_epsilon.sh 2>&1 | tee results/epsilon_run.log
```

OOM failures are normal and are recorded automatically.

### Step 5: Energy Measurement

```bash
bash scripts/run_energy_benchmarks.sh 2>&1 | tee results/energy_run.log
```

### Step 6: GCViewer Log Analysis

Extracts ~60 structured metrics from every GC log:

```bash
bash scripts/analyze_with_gcviewer.sh
```

Output is written to `results/gcviewer_csv/`, mirroring the results directory
structure. Each SUMMARY CSV contains semicolon-separated `metricName; value;
unit` rows.

### Step 7: Generate All Charts and CSVs

```bash
python3 scripts/generate_graphs.py        # performance graphs
python3 scripts/analyze_energy.py         # energy graphs
python3 scripts/analyze_tail_latency.py   # tail latency graphs
python3 scripts/analyze_zgc_gen.py        # ZGC Gen statistical tests
python3 scripts/analyze_gc_recommendation.py  # recommendation framework
```

### Full Pipeline (single command)

```bash
{
  bash scripts/run_dacapo.sh
  bash scripts/run_renaissance.sh
  bash scripts/run_renaissance_heap_vary.sh
  bash scripts/run_dacapo_epsilon.sh
  bash scripts/run_energy_benchmarks.sh
  bash scripts/analyze_with_gcviewer.sh
  python3 scripts/generate_graphs.py
  python3 scripts/analyze_energy.py
  python3 scripts/analyze_tail_latency.py
  python3 scripts/analyze_zgc_gen.py
  python3 scripts/analyze_gc_recommendation.py
} 2>&1 | tee results/full_run.log
```

---

## Output Reference

### GCViewer SUMMARY metrics (key subset)

| Metric              | Unit | Description                                  |
|:--------------------|:-----|:---------------------------------------------|
| `throughput`        | %    | Percentage of time NOT in GC (higher = better)|
| `avgPause`          | s    | Mean GC stop-the-world pause                 |
| `maxPause`          | s    | Worst single GC pause                        |
| `accumPause`        | s    | Total time in all GC pauses                  |
| `pauseCount`        | -    | Total number of GC pauses                    |
| `fullGcPauseCount`  | -    | Number of full GC events                     |
| `avgFullGCPause`    | s    | Mean full GC pause duration                  |
| `totalHeapAllocMax` | MB   | Maximum heap capacity allocated              |
| `totalHeapUsedMax`  | MB   | Peak heap memory in use                      |
| `freedMemory`       | MB   | Total memory reclaimed over the run          |
| `gcPerformance`     | MB/s | Memory reclamation rate                      |

### Manual GCViewer usage

```bash
# SUMMARY report (core metrics as CSV)
java -jar tools/gcviewer-1.36.jar <input.log> <output.csv> -t SUMMARY

# Per-event CSV (one row per GC event)
java -jar tools/gcviewer-1.36.jar <input.log> <output.csv> -t CSV

# Plain-text report
java -jar tools/gcviewer-1.36.jar <input.log> <output.csv> -t PLAIN
```

---

## Troubleshooting

**`zsh: no matches found: -Xlog:gc*:...`**
zsh expands the `*` glob. The scripts quote this argument, but if running
manually, use single quotes:
```bash
java -XX:+UseG1GC '-Xlog:gc*:file=out.log:time,uptime,level,tags' -jar bench.jar
```

**Benchmark not found**
DaCapo Chopin has a different benchmark set than the older Bach release.
Scripts validate available benchmarks automatically. To list all available:
```bash
java -jar benchmarks/dacapo_chopin/dacapo-23.11-MR2-chopin.jar -l
```

**Epsilon GC `OutOfMemoryError`**
This is expected. Epsilon never reclaims memory, so workloads allocating more
than 4 GB will crash. The script captures this and writes `OOM_OR_FAILED` to
the status file. These represent the same as workloads that fundamentally
require garbage collection.

**GCViewer warnings about "Unknown gc type"**
GCViewer 1.36 does not recognize some Java 21 log entries (e.g. "Merge Heap
Roots" in G1GC). These warnings are harmless — core metrics (throughput, pause
times, heap usage) remain correct.

**RAPL energy unavailable**
If `/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj` is not readable,
the script falls back to `perf stat`. If neither is available, energy values
are recorded as `N/A`. This is expected on VMs or AMD machines without RAPL
support.

**Java 21 not installed**
```bash
# Ubuntu / Debian
sudo apt install openjdk-21-jdk

# Fedora / RHEL
sudo dnf install java-21-openjdk-devel
```

**Disk space**
The full experiment generates approximately 500 MB–1 GB of GC log files.
Ensure at least 2 GB of free space in the `experiment/` directory.

---

## License

This project is part of the CSE6305 Performance Study of Modern JVM Garbage
Collectors research.

Benchmark suites are distributed under their respective licenses:
- DaCapo Chopin: Apache License 2.0
- Renaissance (GPL edition): GNU General Public License
- GCViewer 1.36: GNU Lesser General Public License (LGPL)
