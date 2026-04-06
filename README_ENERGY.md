# Energy Consumption of JVM Garbage Collectors

## Overview

Software energy consumption is an increasingly important dimension of system
design, driven by concerns over data center electricity costs and environmental
sustainability. Garbage collection is a non-trivial contributor to the total
energy budget of managed-runtime applications—it consumes CPU cycles, generates
cache pollution, and extends execution time. This study measures the energy
footprint of three major JVM garbage collectors (G1GC, Shenandoah, ZGC) across
18 Java workloads from the DaCapo Chopin and Renaissance benchmark suites on
OpenJDK 21, using Intel RAPL (Running Average Power Limit) for direct hardware
energy measurement.

## Measurement Approach

Energy was measured through the Intel RAPL interface exposed via the Linux
sysfs pseudo-filesystem at `/sys/class/powercap/intel-rapl`. RAPL provides
hardware-level energy counters for three domains:

- **Package (pkg):** Total CPU socket energy, including all cores, caches,
  and the memory controller.
- **Core:** Energy consumed by the CPU compute cores alone.
- **Uncore:** Energy consumed by non-core components (integrated GPU, memory
  controller, last-level cache controller).

For each benchmark/GC combination, the package energy counter was read
immediately before starting the JVM and again after the process exited. The
difference yields the total CPU energy consumed during that run, reported in
Joules. A fallback to `perf stat -e power/energy-pkg/` is used on systems
where the sysfs files are not readable without root.

Wall-clock time was measured concurrently, enabling computation of average
power draw (Watts = Joules / seconds) alongside total energy.

## Workloads

The energy experiment covered all 18 benchmarks from the performance study:

- **DaCapo (10):** avrora, batik, fop, h2, luindex, lusearch, pmd, sunflow,
  tomcat, xalan.
- **Renaissance (8):** chi-square, dec-tree, dotty, finagle-http, movie-lens,
  page-rank, philosophers, scala-kmeans.

Each was run with G1GC, Shenandoah, and ZGC under a fixed 2 GB heap.

## Results

### Aggregate Energy (Suite Averages)

| GC          | DaCapo Mean    | Renaissance Mean |
|:------------|:---------------|:-----------------|
| G1GC        | 165.3 J        | 348.4 J          |
| Shenandoah  | 199.0 J        | 362.4 J          |
| ZGC         | 184.5 J        | 356.7 J          |

Across DaCapo workloads, G1GC consumed the least energy on average (165.3 J),
followed by ZGC (184.5 J) and Shenandoah (199.0 J). On Renaissance workloads,
the gap narrowed considerably—all three collectors fell within a 14 J window
of each other—but the ranking remained the same: G1GC was the most energy-
efficient.

### DaCapo Energy per Benchmark

G1GC was the most energy-efficient collector on 8 out of 10 DaCapo workloads.
Notable observations:

- **h2 (in-memory SQL):** The most energy-hungry DaCapo benchmark. G1GC
  consumed 412.5 J, ZGC 520.7 J (1.26x), and Shenandoah 605.6 J (1.47x).
  The 47% Shenandoah surcharge reflects its longer execution time (67.3 s vs
  47.6 s for G1GC) due to concurrent compaction overhead.
- **sunflow (ray tracing):** G1GC consumed 172.1 J, Shenandoah 224.9 J
  (1.31x), ZGC 210.9 J (1.23x). Shenandoah's concurrent barriers slowed this
  compute-intensive workload, extending execution time and energy.
- **lusearch (full-text search):** A rare case where ZGC matched G1GC
  (193.7 J vs 195.7 J), both finishing in about 20 seconds. Shenandoah was
  14% more expensive.
- **avrora (simulation):** The sole benchmark where Shenandoah was the most
  energy-efficient (78.8 J vs 83.1 J for G1GC), owing to a slightly shorter
  execution time on this low-allocation workload.

### Renaissance Energy per Benchmark

The Renaissance picture was more mixed:

- **finagle-http (HTTP server):** ZGC was most efficient (401.7 J vs G1GC's
  475.9 J), finishing in 43.3 s compared to G1GC's 52.3 s. ZGC's minimal
  pause overhead benefited this latency-sensitive server workload.
- **page-rank (graph algorithm):** Shenandoah was cheapest (476.0 J) while
  ZGC was most expensive (576.7 J), an outlier caused by ZGC's higher memory
  overhead inflating execution time on this heap-intensive Spark job.
- **philosophers (concurrency):** ZGC was cheapest (204.1 J), while G1GC and
  Shenandoah consumed 233.0 J and 225.3 J respectively. ZGC's lightweight
  barriers interact well with fine-grained concurrency.
- **scala-kmeans:** All three collectors were within 5 J of each other on this
  very short benchmark (<3 s), illustrating that GC energy impact is
  negligible for extremely short-lived processes.

### Why Does G1GC Use Less Energy?

The energy result appears to contradict the throughput and latency results,
where ZGC and Shenandoah had better GC metrics. The explanation lies in
wall-clock time:

1. **G1GC finishes faster.** Despite spending a larger fraction of time in GC
   pauses, G1GC's stop-the-world compaction is highly efficient at freeing
   memory in bulk, which allows the application to proceed without allocation
   stalls. On DaCapo, G1GC averaged 19.0 s vs Shenandoah's 22.4 s.

2. **Concurrent GC steals CPU.** Shenandoah and ZGC run their concurrent mark
   and relocation phases on background threads that consume CPU (and therefore
   energy) while the application is also running. The CPU is never idle during
   these phases—it is doing GC work instead of application work, extending
   total execution time.

3. **Energy scales with time.** At an average power draw of ~8 W, every
   additional second of execution costs approximately 8 Joules. Shenandoah's
   3–4 extra seconds on DaCapo translates to 24–32 J of additional energy,
   which closely matches the observed gap.

### Energy–Performance Tradeoff

The Pareto analysis reveals a genuine tradeoff:

- For **latency-sensitive** workloads (finagle-http, philosophers), ZGC
  provides both the lowest pause latency and the lowest energy, because its
  minimal pauses allow the application to finish sooner.
- For **batch/compute** workloads (h2, sunflow, lusearch), G1GC is
  simultaneously the fastest and most energy-efficient, because it spends less
  total CPU time despite its longer pauses.
- Shenandoah sits on neither extreme of the Pareto frontier for most
  workloads—it rarely wins on energy, though it provides good pause
  characteristics.

### Average Power Draw

All three collectors drew similar average power (6.7–8.8 W per run across all
benchmarks), confirming that energy differences are primarily driven by
execution time differences rather than instantaneous power draw. The JVM's
workload saturates the CPU similarly regardless of which GC is running.

## Implications

1. **Energy does not correlate with throughput percentage.** ZGC achieves
   99.9%+ throughput but consumes more energy than G1GC because it extends
   execution time through concurrent overhead.
2. **The cheapest GC is the one that finishes fastest.** For most batch
   workloads, minimizing wall-clock time is the most effective way to minimize
   energy. This favors G1GC.
3. **For server workloads, the calculus changes.** In long-running server
   applications, GC pauses cause request queuing, tail-latency spikes, and
   potentially retries—all of which consume additional energy at the system
   level. ZGC's sub-millisecond pauses may produce lower total system energy
   even if the JVM itself is slightly more expensive.
4. **Shenandoah's concurrent compaction is cost-intensive.** Its concurrent
   read barriers and forwarding pointers impose a per-access overhead that
   accumulates into measurably higher energy consumption, especially on
   allocation-heavy workloads like h2 and sunflow.

## Conclusion

G1GC is the most energy-efficient garbage collector for short-to-medium batch
Java workloads, primarily because it finishes faster despite longer pauses.
ZGC's sub-millisecond pauses come at a modest energy premium (typically 5–15%
above G1GC) and are justified for latency-sensitive server applications.
Shenandoah tends to be the most energy-expensive option across both suites,
with a 10–47% premium over G1GC depending on the workload. Developers
optimizing for green computing should consider wall-clock execution time as a
proxy for energy cost when choosing a garbage collector.
