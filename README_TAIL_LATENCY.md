# Tail Latency Analysis of JVM Garbage Collectors

## Overview

Average pause time tells only part of the story. For latency-sensitive
applications—web servers, trading systems, real-time analytics—it is the rare
worst-case pause that causes user-visible impact: dropped frames, timeout
errors, SLA violations. This study performs a detailed tail-latency analysis of
six JVM garbage collector configurations on OpenJDK 21, extracting every
individual stop-the-world (STW) pause from raw GC logs and computing pause
percentiles at P50, P95, P99, and P99.9.

## Why Tail Latency Matters

Consider a web service where each user request may trigger several backend
calls. If each call has a 1% chance of hitting a long GC pause (the P99), then
a page composed of 10 backend calls has a roughly 10% chance of being affected.
This is the "tail at scale" problem: rare per-request events become common at
aggregate scale. The P99 and P99.9 GC pause durations directly determine the
worst-case request latency in such architectures.

## Methodology

### Pause Extraction

Every raw GC log produced by the DaCapo and Renaissance experiments was parsed
to extract individual STW pause durations. Java 21's unified logging format
records each pause with millisecond precision. The extraction captures all
pause types—young gen, mixed, full GC, remark, cleanup—regardless of the
collector family.

### Metrics Computed

For each benchmark × GC combination, the following statistics were computed
over the set of all STW pauses:

- **P50 (median):** The typical pause—half of all pauses are shorter.
- **P95:** Long pauses—only 5% of pauses exceed this duration.
- **P99:** Tail pauses—only 1% of pauses exceed this.
- **P99.9:** Extreme tail—one-in-a-thousand worst case.
- **Min, max, mean, standard deviation:** Full distribution characterization.

### Visualization

Six chart types were generated:

1. **Percentile bar charts:** Grouped bars showing P50/P95/P99/P99.9 for all
   GCs, aggregated across benchmarks.
2. **Per-benchmark P99 charts:** P99 per benchmark with GCs side by side,
   revealing workload-specific behavior.
3. **Per-benchmark P99.9 charts:** Same for the extreme tail.
4. **P99 heatmaps:** Benchmark × GC matrix with color intensity proportional
   to P99 duration—immediate visual identification of problem spots.
5. **Box plots:** Full pause distribution per GC, showing median, quartiles,
   and outliers.
6. **CDF plots:** One per benchmark, showing all GCs overlaid—the empirical
   distribution function of pause durations.
7. **P50 vs P99 scatter:** Plots median against tail pause for each
   benchmark/GC, revealing which collectors have "loose" tails compared to
   their median.

## Results

### DaCapo Suite

#### Pause Percentiles by GC (averaged across 10 benchmarks)

| GC Config        | P50      | P95       | P99       | P99.9     |
|:-----------------|:---------|:----------|:----------|:----------|
| G1GC (default)   | 7.70 ms  | 18.13 ms  | 36.61 ms  | 51.45 ms  |
| G1GC (50 ms)     | 6.95 ms  | 15.80 ms  | 30.92 ms  | 56.03 ms  |
| G1GC (2 threads) | 7.95 ms  | 17.23 ms  | 38.61 ms  | 52.56 ms  |
| Shenandoah       | 0.26 ms  | 0.81 ms   | 2.87 ms   | 3.18 ms   |
| ZGC (Non-Gen)    | 0.016 ms | 0.039 ms  | 0.050 ms  | 0.054 ms  |
| ZGC (Gen)        | 0.026 ms | 0.050 ms  | 0.074 ms  | 0.104 ms  |

**Key observations:**

- **ZGC pauses are sub-millisecond at every percentile.** Even at P99.9, both
  ZGC variants remain under 0.11 ms. This is three orders of magnitude shorter
  than G1GC's P99.9 (51–56 ms).

- **Shenandoah occupies a distinct middle tier.** Its P50 (0.26 ms) is close
  to ZGC, but its tail diverges: the P99 (2.87 ms) is 38–57x larger than
  ZGC's. This tail is caused by Shenandoah's occasional final-mark and
  degenerated GC pauses, which are longer than its typical init-mark pauses.

- **G1GC's tail is 5–7x its median.** A P50 of 7.7 ms growing to a P99 of
  36.6 ms indicates that a small fraction of G1GC's pauses—typically mixed
  collections or young-gen pauses that scan many old-gen references—are
  substantially longer than the common case.

- **The 50 ms target helps the median, hurts the extreme tail.** G1GC with
  `MaxGCPauseMillis=50` reduced P50 from 7.7 to 6.95 ms and P99 from 36.6 to
  30.9 ms. However, P99.9 actually *increased* from 51.5 to 56.0 ms. The
  tighter target causes more frequent collections, and occasionally several
  collections cluster, producing an outlier pause that exceeds the default
  configuration's worst case.

- **Reducing concurrent threads has negligible tail-latency impact.** G1GC
  with 2 threads was within 5% of the default on all percentiles.

#### Per-Benchmark Patterns

Individual benchmarks showed distinctive patterns:

- **h2 (in-memory SQL):** G1GC's P99 reached 73.7 ms, the highest among
  DaCapo workloads. This benchmark performs frequent small transactions that
  generate high allocation pressure in the young generation, causing many mixed
  collections. ZGC remained at 0.07 ms.

- **lusearch (full-text search):** Shenandoah's P99 spiked to 9.56 ms—its
  worst across DaCapo—because the search workload triggers rapid allocation
  bursts that force degenerated GC cycles. ZGC and G1GC showed no such spike.

- **avrora (simulation):** All collectors had relatively benign tails because
  this workload has very low allocation pressure (7.9 MB/s). Even G1GC's P99
  was only 11.8 ms.

### Renaissance Suite

#### Pause Percentiles by GC (averaged across 8 benchmarks)

| GC Config        | P50      | P95       | P99        | P99.9      |
|:-----------------|:---------|:----------|:-----------|:-----------|
| G1GC (default)   | 7.96 ms  | 48.15 ms  | 109.95 ms  | 159.25 ms  |
| G1GC (50 ms)     | 8.36 ms  | 35.14 ms  | 111.67 ms  | 169.86 ms  |
| G1GC (2 threads) | 8.00 ms  | 53.51 ms  | 111.36 ms  | 137.94 ms  |
| Shenandoah       | 0.17 ms  | 0.80 ms   | 1.06 ms    | 2.60 ms    |
| ZGC (Non-Gen)    | 0.016 ms | 0.036 ms  | 0.078 ms   | 0.108 ms   |
| ZGC (Gen)        | 0.023 ms | 0.046 ms  | 0.075 ms   | 0.091 ms   |

**Renaissance amplifies G1GC's tail problem.** G1GC's P99 jumped from 36.6 ms
(DaCapo) to 109.9 ms (Renaissance), and P99.9 from 51.5 ms to 159.3 ms.
Renaissance workloads are longer-running and more concurrent, generating more
live data and more complex reference graphs that G1GC must scan during
pause. The 3x tail inflation from DaCapo to Renaissance highlights that G1GC's
worst-case behavior is workload-dependent and can be severe.

**ZGC is remarkably stable across suites.** Its P99.9 went from 0.054 ms
(DaCapo) to 0.108 ms (Renaissance)—still well under 0.2 ms. The doubling is
attributable to the larger live-data sets in Renaissance causing slightly more
work during ZGC's short STW phases (root scanning and relocation start), but
the absolute numbers remain negligible.

**Shenandoah's tail stays tight on Renaissance.** Its P99.9 (2.60 ms) is
better than on DaCapo (3.18 ms) because Renaissance's concurrent workloads
interleave well with Shenandoah's concurrent compaction, reducing the chance
of degenerated cycles.

#### Per-Benchmark Patterns

- **page-rank (Spark graph algorithm):** The worst tail benchmark overall.
  G1GC's P99.9 reached 396 ms—nearly 0.4 seconds for a single GC pause.
  This workload creates a large, densely-connected object graph that G1GC
  must scan during mixed collections. ZGC remained at 0.12 ms throughout.

- **finagle-http (HTTP server):** G1GC P99 was 218 ms, making it unsuitable
  for any latency SLA tighter than ~250 ms. ZGC's P99 was 0.04 ms—5000x
  shorter.

- **chi-square (Spark statistics):** Even this relatively simple Spark job
  pushed G1GC to a P99 of 57 ms, while ZGC remained at 0.03 ms.

- **philosophers (concurrency):** All collectors performed well due to low
  allocation rates, but G1GC's P99 was still 6.8 ms vs ZGC's 0.05 ms.

### CDF Analysis

The cumulative distribution function (CDF) plots reveal the full shape of each
collector's pause distribution:

- **ZGC's CDF is a vertical line.** Nearly 100% of pauses fall within a
  narrow 0.01–0.15 ms band. There is effectively no tail—the distribution
  has almost zero variance.

- **Shenandoah's CDF shows a long right tail.** 95% of pauses fall under
  0.5 ms, but the remaining 5% spread out to 2–10 ms. This "fat tail" is
  driven by init-mark and final-mark STW phases.

- **G1GC's CDF has a slow climb.** The median is around 8 ms, but some pauses
  stretch to 50–400 ms. The distribution is roughly log-normal, which means
  extreme outliers are structurally expected.

### Tail Ratio Analysis

The tail ratio (P99 / P50) quantifies how much worse the tail is relative to
the typical case:

| GC Config        | DaCapo Avg Tail Ratio | Renaissance Avg Tail Ratio |
|:-----------------|:----------------------|:---------------------------|
| G1GC (default)   | 4.76x                 | 13.81x                     |
| G1GC (50 ms)     | 4.45x                 | 13.36x                     |
| G1GC (2 threads) | 4.86x                 | 13.92x                     |
| Shenandoah       | 11.03x                | 6.24x                      |
| ZGC (Non-Gen)    | 3.13x                 | 4.88x                      |
| ZGC (Gen)        | 2.85x                 | 3.26x                      |

ZGC (Generational) has the tightest tail ratio—its P99 is only ~3x its
median. G1GC's tail ratio explodes on Renaissance (13.8x), meaning the worst
1% of pauses are nearly 14 times longer than the median. Shenandoah shows an
unusual pattern: its tail ratio is *higher* on DaCapo (11.0x) than Renaissance
(6.2x), because DaCapo's bursty allocation patterns are more likely to trigger
degenerated cycles.

## Implications for System Design

### SLA Budgeting

If a service has a 10 ms latency SLA at P99:
- **ZGC:** Safe. P99 GC pause contributes <0.1 ms, leaving 9.9 ms for
  application logic.
- **Shenandoah:** Marginal. P99 GC pause of 1–3 ms consumes 10–30% of the
  budget.
- **G1GC:** Unsafe. P99 GC pause of 30–110 ms alone exceeds the SLA.

### Capacity Planning

ZGC's consistent sub-millisecond P99.9 means that GC pauses can be treated as
negligible in capacity models. With G1GC, capacity planners must account for
occasional 100–400 ms pauses that will cause request queuing—typically
requiring 20–40% more backend capacity to absorb the tail without SLA breach.

### Collector Migration

Applications currently running G1GC that experience tail-latency problems
should consider migrating to ZGC. The migration is a single JVM flag change
(`-XX:+UseG1GC` → `-XX:+UseZGC -XX:+ZGenerational`). The expected tail
improvement is 100–1000x with no throughput regression on most workloads.

## Conclusion

ZGC (both Generational and Non-Generational) provides the lowest tail latency
by a wide margin, keeping P99.9 pauses under 0.2 ms across all 18 benchmarks.
G1GC's tail latency is workload-dependent and can reach hundreds of
milliseconds on memory-intensive concurrent workloads, making it unsuitable for
strict latency SLAs. Shenandoah offers a meaningful improvement over G1GC
(10–50x shorter tails) but cannot match ZGC's consistency. The 50 ms
pause-target tuning of G1GC provides slight median improvement at the cost of
worse extreme-tail behavior, making it an unreliable optimization for
latency-sensitive use cases.
