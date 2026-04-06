# Workload-Aware GC Recommendation Framework

## Overview

Choosing the right garbage collector for a Java application is a complex
decision that depends on the workload's characteristics, the operator's
priorities, and the performance dimensions that matter most. This study
introduces a data-driven recommendation framework that, given a workload
profile, recommends the most suitable GC from among six configurations tested
on OpenJDK 21. Rather than prescribing a single "best" GC, the framework
acknowledges that different user priorities lead to different optimal choices,
and it formalizes this through four user personas.

## Problem Statement

The performance comparison across 18 benchmarks and 6 GC configurations
produced a large matrix of metrics—throughput, pause times, heap usage,
execution time, tail latency—with no single GC dominating across all
dimensions. G1GC finishes batch workloads fastest but has the longest pauses.
ZGC has the shortest pauses but uses more memory and takes longer. Shenandoah
occupies a middle ground. The question practitioners face is: "For *my*
workload and *my* priorities, which GC should I use?"

## Approach

### Step 1: Workload Feature Extraction

Five features are derived from GCViewer metrics and tail-latency analysis for
each benchmark, averaged across all GC configurations to characterize the
workload independently of collector choice:

| Feature           | Formula                                  | What it captures                                      |
|:------------------|:-----------------------------------------|:------------------------------------------------------|
| `gc_frequency`    | pauseCount / wallTimeSec                 | How often GC is triggered (events/sec)                |
| `alloc_rate`      | freedMemory / wallTimeSec                | Allocation pressure (MB/s freed)                      |
| `heap_pressure`   | totalHeapUsedMax / totalHeapAllocMax     | Live-data density (fraction of heap occupied)         |
| `tail_ratio`      | P99 pause / P50 pause                    | Pause distribution shape (how heavy are the tails)    |
| `pause_overhead`  | accumPause / wallTimeSec                 | Fraction of execution time spent in GC                |

These features capture the essential characteristics of a workload that
influence GC behavior: how much it allocates, how much it retains, how often
GC must intervene, and how variable the pause durations are.

### Workload Profiles

The 18 benchmarks exhibit diverse profiles:

- **High allocation rate:** lusearch (1102 MB/s), sunflow (1013 MB/s),
  movie-lens (878 MB/s) — these stress the allocator and young generation.
- **Low allocation rate:** avrora (7.9 MB/s), batik (19.9 MB/s), dotty
  (35.5 MB/s) — these barely trigger GC.
- **High heap pressure:** luindex (0.86), pmd (0.85), dec-tree (0.81) — large
  fraction of allocated heap is live, leaving little room for GC to reclaim.
- **Heavy tails:** finagle-http (14.6x), page-rank (14.6x), dec-tree (8.8x)
  — P99 pauses are 9–15x the median, indicating occasional very long pauses.
- **Light tails:** fop (1.9x), sunflow (2.3x), avrora (2.4x) — pause
  distributions are tight with no serious outliers.

### Step 2: Composite Scoring by Persona

Four user personas, each with distinct priorities, are defined. For each
persona, a weighted composite score is computed across the key metrics for
every benchmark × GC pair. Metrics are normalized to [0, 1] within each
benchmark (so scores represent relative standing among the six GCs):

| Persona              | Primary weight             | Secondary weights            | Use case                              |
|:---------------------|:---------------------------|:-----------------------------|:--------------------------------------|
| **Latency-Critical** | P99 pause time (dominant)  | Max pause, avg pause         | Real-time systems, trading, gaming    |
| **Throughput-First** | Throughput % (dominant)    | Wall-clock time              | Batch processing, data pipelines      |
| **Memory-Constrained**| Peak heap used (dominant) | Heap allocated, footprint    | Containers, edge, small VMs           |
| **Balanced**         | Equal weights on all       | All metrics weighted equally | General-purpose applications          |

### Step 3: Recommendation Election

For each benchmark × persona combination, the GC with the highest composite
score is elected as the recommended choice. A runner-up and the margin of
victory are also recorded.

### Step 4: Decision Tree Classification

To make the framework predictive (i.e., usable for new workloads), a Decision
Tree classifier is trained per persona. The input features are the five
workload features; the target label is the GC recommended for that persona. The
tree can be inspected to understand which workload characteristics drive the
recommendation.

## Results

### Recommendation Matrix

The recommendation matrix reveals strikingly different optimal configurations
depending on priorities:

**Latency-Critical persona:**

ZGC variants dominated completely, winning all 18 benchmarks with near-perfect
scores (>0.998). Generational ZGC won 9 benchmarks, Non-Generational ZGC won
9. No other collector came close—the margins of victory were tiny between the
two ZGC variants (0.001–0.010) and enormous against G1GC or Shenandoah.

This is expected: ZGC's sub-millisecond P99 pauses (0.05–0.10 ms) are two
orders of magnitude shorter than G1GC's (30–170 ms).

**Throughput-First persona:**

ZGC variants still won the majority (15 out of 18), but Shenandoah claimed
3 wins (chi-square, page-rank, scala-kmeans). Shenandoah's wins came on
Renaissance workloads where its concurrent compaction, despite consuming CPU,
happened to align well with the workload's allocation pattern. G1GC, despite
often having the fastest wall-clock time, did not win because its lower
throughput *percentage* (time in pauses) penalized it in the scoring.

**Memory-Constrained persona:**

This persona produced the most diverse recommendations. G1GC variants won
12 out of 18 benchmarks: G1GC default (6 wins), G1GC with pause-50ms (3),
G1GC with 2 threads (3). Shenandoah won 3, and ZGC variants only 3.

G1GC's dominance in memory efficiency stems from its compacting, generational
design that promptly frees young-generation garbage and keeps the heap tightly
packed. ZGC's concurrent design requires forwarding pointers and colored
pointers that inflate memory overhead.

**Balanced persona:**

ZGC (Non-Gen) won 10 of 18, ZGC (Gen) won 6, Shenandoah won 2. G1GC did not
win any benchmark under balanced scoring, because its high pause durations
penalize it even when weighted equally against other metrics. ZGC's combination
of near-perfect throughput, sub-millisecond pauses, and reasonable memory usage
wins when all dimensions matter equally.

### Win Rate Summary

| GC Config         | Latency-Critical | Throughput-First | Memory-Constrained | Balanced |
|:------------------|:-----------------|:-----------------|:-------------------|:---------|
| ZGC (Gen)         | 9/18             | 8/18             | 2/18               | 6/18     |
| ZGC (Non-Gen)     | 9/18             | 7/18             | 1/18               | 10/18    |
| Shenandoah        | 0/18             | 3/18             | 3/18               | 2/18     |
| G1GC (default)    | 0/18             | 0/18             | 6/18               | 0/18     |
| G1GC (50 ms)      | 0/18             | 0/18             | 3/18               | 0/18     |
| G1GC (2 threads)  | 0/18             | 0/18             | 3/18               | 0/18     |

### Decision Tree Insights

The trained decision trees reveal which workload features most influence the
GC recommendation:

- For the **Latency-Critical** persona, the decision tree is trivial: it
  always recommends ZGC regardless of workload features, because ZGC
  dominates on pause latency universally.
- For the **Memory-Constrained** persona, `heap_pressure` and `alloc_rate` are
  the most important features. Workloads with high heap pressure (>0.7) and
  low-to-moderate allocation rates tend to favor G1GC. High-allocation
  workloads with lower heap pressure favor Shenandoah.
- For the **Balanced** persona, `tail_ratio` and `pause_overhead` emerge as
  key discriminators. Workloads with heavy tails (tail_ratio > 8) tend to
  favor ZGC more strongly, while workloads with light tails sometimes allow
  Shenandoah to compete.

### PCA Cluster Analysis

A PCA projection of the 18 workloads into 2-D space based on the five
workload features reveals natural clustering:

- Compute-bound workloads with low allocation (avrora, batik, fop) cluster
  together and tend to be GC-agnostic—performance differences between
  collectors are small.
- High-allocation workloads (lusearch, sunflow, h2, movie-lens) cluster
  separately and show the largest performance spread between collectors,
  making GC choice most impactful for these workloads.
- Concurrent server-like workloads (finagle-http, page-rank) occupy their
  own region, characterized by high tail ratios and moderate allocation.

## Practical Takeaways

1. **If latency matters at all, use ZGC.** There is no workload in this study
   where G1GC or Shenandoah provides better tail latency than ZGC. The
   Generational and Non-Generational variants are interchangeable for latency.

2. **If running in a memory-constrained container, use G1GC.** G1GC's compact
   heap layout uses 10–30% less peak heap than ZGC on most workloads.

3. **For general-purpose applications, ZGC (Non-Generational) is the safest
   default.** It won 10 of 18 benchmarks under balanced scoring, never
   performing poorly on any single dimension.

4. **Workload profiling matters.** The five derived features—particularly
   allocation rate, heap pressure, and tail ratio—are sufficient to predict
   the optimal GC with reasonable accuracy. Teams can profile their own
   application's GC logs and map into this framework to obtain a
   recommendation.

5. **G1GC tuning has minimal impact on recommendations.** The two non-default
   G1GC configurations only won in the Memory-Constrained persona, and even
   there they split wins with the default. The effort of tuning G1GC is
   rarely justified compared to simply switching to ZGC or Shenandoah.
