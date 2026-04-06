# Performance Comparison of Modern JVM Garbage Collectors on Java 21

## Overview

This study evaluates the performance of six garbage collector (GC)
configurations on OpenJDK 21 across 18 diverse Java workloads drawn from the
DaCapo Chopin and Renaissance benchmark suites. The goal is to answer a
straightforward question: when throughput, pause duration, heap footprint, and
wall-clock execution time are all taken into account, which collector—or class
of collectors—delivers the best overall performance on modern Java workloads?

## Garbage Collectors Under Test

Six configurations spanning three collector families were tested:

- **G1GC (default)** — the JVM's default collector since Java 9, using a
  region-based, generational, mostly concurrent design.
- **G1GC (50 ms pause target)** — the same collector with
  `-XX:MaxGCPauseMillis=50`, forcing shorter but more frequent collection
  cycles than the default 200 ms target.
- **G1GC (2 concurrent threads)** — G1GC constrained to two concurrent GC
  threads (via `-XX:ConcGCThreads=2`), simulating a resource-limited
  environment.
- **Shenandoah** — a low-pause concurrent collector that performs heap
  compaction concurrently with the application.
- **ZGC (Non-Generational)** — the original ZGC design available since Java 11,
  performing all collection concurrently with sub-millisecond pause targets.
- **ZGC (Generational)** — the new generational extension introduced in Java 21
  (`-XX:+ZGenerational`), which splits the heap into a young and old generation
  to reduce scanning overhead and improve throughput.

An Epsilon GC (no-op) baseline was also run on DaCapo benchmarks to establish
the theoretical best-case execution time with zero GC overhead.

## Benchmarks

### DaCapo Chopin (10 workloads)

Real-world Java applications: `avrora` (microcontroller simulation), `batik`
(SVG rendering), `fop` (XSL-FO to PDF), `h2` (in-memory SQL), `luindex` and
`lusearch` (Lucene indexing/search), `pmd` (static analysis), `sunflow`
(ray tracing), `tomcat` (HTTP serving), and `xalan` (XSLT transforms). These
cover a wide range of allocation rates and live-data densities.

### Renaissance (8 workloads)

Modern concurrent and data-intensive workloads: `chi-square` and `dec-tree`
(Spark statistical/ML), `dotty` (Scala 3 compiler), `finagle-http` (Twitter
HTTP server), `movie-lens` (Spark collaborative filtering), `page-rank` (Spark
graph algorithm), `philosophers` (concurrency stress test), and `scala-kmeans`
(Spark clustering). Each benchmark was run for three repetitions.

## Methodology

Every benchmark was executed with a fixed 2 GB heap (`-Xmx2g`) on the same
hardware. Detailed unified GC logs were collected with Java 21's
`-Xlog:gc*:file=...:time,uptime,level,tags` and parsed offline using
GCViewer 1.36 to extract approximately 60 structured metrics per run. Wall-clock
execution time was measured independently via shell timing.

## Key Performance Findings

### Throughput

Throughput measures the percentage of time the application spends doing useful
work (i.e., not paused by the GC). Higher is better.

| GC Config        | DaCapo Mean | Renaissance Mean |
|:-----------------|:------------|:-----------------|
| G1GC (default)   | 97.44%      | 95.72%           |
| G1GC (50 ms)     | 97.39%      | 95.70%           |
| G1GC (2 threads) | 97.41%      | 95.74%           |
| Shenandoah       | 98.52%      | 99.92%           |
| ZGC (Non-Gen)    | 99.96%      | 100.00%          |
| ZGC (Gen)        | 99.98%      | 99.98%           |

Both ZGC variants achieved near-perfect throughput (>99.9%) across both suites.
G1GC's throughput was notably lower on Renaissance workloads (around 95.7%),
meaning roughly 4.3% of execution time was spent inside GC pauses. Shenandoah
fell between G1GC and ZGC on DaCapo but nearly matched ZGC on Renaissance.

### Average Pause Time

This metric captures the mean duration of individual stop-the-world events.

| GC Config        | DaCapo Mean | Renaissance Mean |
|:-----------------|:------------|:-----------------|
| G1GC (default)   | 9.15 ms     | 15.58 ms         |
| G1GC (50 ms)     | 8.22 ms     | 13.53 ms         |
| G1GC (2 threads) | 9.36 ms     | 15.74 ms         |
| Shenandoah       | 0.40 ms     | 0.32 ms          |
| ZGC (Non-Gen)    | 0.058 ms    | 0.061 ms         |
| ZGC (Gen)        | 0.055 ms    | 0.058 ms         |

There is a dramatic separation: G1GC pauses are 150–270x longer than ZGC
pauses. ZGC (Generational) and ZGC (Non-Generational) are nearly identical in
average pause time, both consistently under 0.1 ms. Shenandoah pauses are
5–6x longer than ZGC but still well under 1 ms on average. Setting a 50 ms
pause target on G1GC reduced average pauses slightly (9.15 → 8.22 ms on
DaCapo), but the improvement was modest and came with a higher pause count.

### Maximum Pause Time

The single worst pause observed per run—critical for latency-sensitive
applications.

| GC Config        | DaCapo Mean | Renaissance Mean |
|:-----------------|:------------|:-----------------|
| G1GC (default)   | 53.10 ms    | 165.57 ms        |
| G1GC (50 ms)     | 58.82 ms    | 182.89 ms        |
| G1GC (2 threads) | 54.11 ms    | 138.82 ms        |
| Shenandoah       | 3.19 ms     | 2.89 ms          |
| ZGC (Non-Gen)    | 0.090 ms    | 0.140 ms         |
| ZGC (Gen)        | 0.102 ms    | 0.151 ms         |

G1GC maximum pauses were two orders of magnitude larger than ZGC. On
Renaissance, G1GC's worst pause reached nearly 183 ms with the 50 ms target
enabled—paradoxically worse than the default. This occurs because the 50 ms
target causes more frequent mixed collections, which occasionally pile up.
Reducing concurrent threads to 2 actually slightly lowered the worst-case on
Renaissance (138.82 ms), likely because less thread contention reduced
scheduling jitter. ZGC consistently kept max pauses under 0.2 ms across all
18 workloads.

### GC Pause Count

Total number of stop-the-world pauses over the benchmark run.

| GC Config        | DaCapo Mean | Renaissance Mean |
|:-----------------|:------------|:-----------------|
| G1GC (default)   | 47.3        | 130.2            |
| G1GC (50 ms)     | 50.8        | 146.1            |
| G1GC (2 threads) | 48.6        | 133.4            |
| Shenandoah       | 26.4        | 57.8             |
| ZGC (Non-Gen)    | 7.9         | 17.0             |
| ZGC (Gen)        | 9.4         | 22.1             |

G1GC with the 50 ms target triggered the most pauses, confirming that a
tighter target shortens individual pauses by splitting work into more
collections. ZGC triggered the fewest pauses overall; its Generational variant
fires slightly more often than Non-Generational (9.4 vs 7.9 on DaCapo)
because it additionally collects the young generation. Despite the higher
count, each individual pause remains sub-millisecond.

### Wall-Clock Execution Time

Total time from benchmark start to finish, including all GC overhead.

| GC Config        | DaCapo Mean | Renaissance Mean |
|:-----------------|:------------|:-----------------|
| G1GC (default)   | 18.47 s     | 40.34 s          |
| G1GC (50 ms)     | 19.55 s     | 40.97 s          |
| G1GC (2 threads) | 19.80 s     | 39.83 s          |
| Shenandoah       | 23.29 s     | 41.72 s          |
| ZGC (Non-Gen)    | 21.39 s     | 40.07 s          |
| ZGC (Gen)        | 21.32 s     | 40.89 s          |

Despite G1GC's much longer pauses, it finished DaCapo workloads fastest on
average (18.47 s). This is because G1GC's concurrent work is more efficient
for short-lived benchmarks, and its stop-the-world compaction is better at
handling memory fragmentation. On Renaissance (longer, more concurrent
workloads), wall-clock differences between collectors largely vanish—all six
configurations fall within a 2-second window. Shenandoah had the longest
DaCapo execution times despite good throughput, suggesting its concurrent
compaction consumes CPU that would otherwise go to the application.

### G1GC Tuning Impact

The two tuning parameters had minimal overall effect:

- **Lower pause target (50 ms):** average pauses dropped by ~10%, but max
  pauses increased and more pauses were triggered. Wall-clock time was
  marginally worse.
- **Fewer concurrent threads (2):** virtually identical to defaults on most
  metrics. Minor improvements appeared on a few Renaissance workloads where
  reduced thread contention helped.

The takeaway is that G1GC's default settings are already well-tuned for
general-purpose workloads. Aggressive tuning provides marginal gains at best
and can be counterproductive.

### Generational vs Non-Generational ZGC

The two ZGC variants performed remarkably similarly across all metrics.
Generational ZGC triggered slightly more pauses (due to separate young-gen
collections) but had marginally shorter average pauses. A Wilcoxon signed-rank
test found no statistically significant difference in throughput, average
pause, max pause, execution time, or heap usage between the two
(p > 0.05 for all except pause count, where Generational showed significantly
more pauses, p = 0.017). The generational design does not appear to hurt
performance on any workload but also does not dramatically improve it on these
benchmarks, which may not generate enough young-object churn to benefit.

### Epsilon GC Baseline

Epsilon (no-op GC) successfully completed short-lived DaCapo benchmarks with
small allocation footprints (e.g., avrora, luindex) within a 4 GB heap. Longer
or more allocation-heavy workloads (lusearch, h2, sunflow) crashed with
`OutOfMemoryError`, confirming they fundamentally require garbage collection.
For the workloads that completed, the Epsilon execution time represents the
absolute minimum—a ceiling that no real GC can beat.

### Heap Size Sensitivity

Three Renaissance benchmarks (chi-square, movie-lens, page-rank) were tested
across heap sizes from 500 MB to 2000 MB with G1GC, Shenandoah, ZGC
(Non-Gen), and ZGC (Gen).

- All collectors saw improved throughput and reduced pause times as heap size
  increased, with diminishing returns above 1250–1500 MB.
- G1GC was the most sensitive to small heaps—its throughput dropped
  significantly at 500 MB and max pauses spiked.
- ZGC variants were the most resilient to heap pressure, maintaining
  near-constant sub-millisecond pauses even at 500 MB.
- Shenandoah fell in between: stable pauses across heap sizes but with
  a larger wall-clock penalty at smaller heaps.

## Summary

ZGC (both variants) is the clear winner for latency-sensitive workloads—its
sub-millisecond pauses are 100–1000x shorter than G1GC's. G1GC remains
competitive for throughput-first workloads with short benchmark lifetimes,
finishing faster in wall-clock terms on DaCapo despite its longer pauses.
Shenandoah provides a middle ground with sub-millisecond pauses and moderate
throughput. The new Generational ZGC in Java 21 performs on par with the legacy
non-generational mode, with no regressions observed and slight benefits in
specific workloads. G1GC tuning provides marginal improvements and should be
approached with caution.
