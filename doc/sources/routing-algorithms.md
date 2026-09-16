# Routing algorithms for a city-scale agent-based simulation

Survey compiled 2026-09-15/16. The question is narrow: what replaces the A\* in
`city.sim.network` so that a full simulated day of ~936,000 people routes in
seconds rather than hours, and what of that survives a port to WGSL.

Every number below carries the URL it came from. Numbers measured **on this
repo's own graphs** are marked *(measured here)* and were taken in the live REPL
against the loaded Stuttgart network on 2026-09-15; they are the only numbers in
this file that are not from the literature, and they are the ones the
recommendation actually rests on.

## 0. What the workload is, measured

The two cities, from [`doc/history/cities.md`](../history/cities.md) and
[`doc/simulator.md`](../simulator.md):

| | Vancouver | Stuttgart |
|---|---|---|
| street graph | 232,290 nodes / 298,512 edges (597,024 directed arcs) | **428,737 nodes / 470,983 edges** (941,966 arcs) |
| graph build from the OSM pull | 4.4 s | 8.5 s (74 MB `out geom`) |
| persons | 670,883 + 94,960 in-commuters | 610,444 + 326,153 in-commuters = **936,597** |
| firms / venues | 89,965 | 24,849 |
| origin cells | 100 m grid | 100 m grid |

The graph is undirected, weights are **metres**, and `mode-speeds-kmh` applies a
flat speed per mode (walk 4.8, bike 15, car 25, transit 18 km/h) *after* routing.
Two consequences that shape everything below:

1. **There is one metric, not four.** Walk, bike, car and transit all route on
   the same edge set and the same lengths. A single distance matrix serves every
   mode. This is a large simplification relative to every production engine
   surveyed here, and it should be preserved as long as it holds.
2. **Destination choice does not use the network at all.** `candidates/build`
   and `day/gravity-table` score candidates on `w/haversine-m` — straight-line
   distance — and both prune hard: `candidates/build` keeps the nearest 128 venues
   plus the 64 largest city-wide, and `gravity-table` keeps the top **K = 256** for
   `:retail` and `:food`, **K = 16** for most other classes. Stuttgart's grid is
   **33,368 cells**. So the impedance problem as posed (35k × 25k) is not the
   problem the code has; the code's problem is **33,368 × 256** for the two
   calibrated classes and 33,368 × 16 for the rest. §5 measures what the
   crow-flight substitution costs.

### The baseline to beat

Measured in the REPL on the loaded Stuttgart graph, 400 random node pairs with
crow-flight separation in [300 m, 8 km] (the urban trip band), cold cache, single
thread *(measured here)*:

| | value |
|---|---|
| A\* (`network/astar`, haversine heuristic) | **38.7 ms per query, 26 queries/s** |
| mean settled path length | 354 nodes |
| plain Dijkstra, one-to-all, 428,737 nodes | **397 ms** |

26 queries/s explains the reported runtimes exactly: the repo records a stride-1
Vancouver day at **2,041 s** for 1.3 M route calls at an 84 % cache hit rate, and
stride-2 city runs at **2,453 s and 2,709 s** with the hit rate down to 39 %
([`doc/simulator.md`](../simulator.md)). 2.5 M uncached queries at 26/s is
**27 hours**; at 1/20 sampling, 1.3 hours — which is the hour the brief reports.

Note what that 38.7 ms is *not*: it is not a fair A\* number. The implementation
pushes `[double-array, node]` tuples into a `java.util.PriorityQueue` with a
boxing `Comparator`, so every relaxation allocates. A tuned binary-heap A\* on
this graph should be 1–3 ms. But even 1 ms leaves 2.5 M queries at 42 minutes
single-threaded. **The constant factor is not the problem; the algorithm is.**

---

## 1. The algorithm families

The reference comparison is Bast, Delling, Goldberg, Müller-Hannemann, Pajor,
Sanders, Wagner and Werneck, *Route Planning in Transportation Networks*
(Algorithm Engineering, Springer 2016),
[arXiv:1504.05140](https://arxiv.org/pdf/1504.05140). Its Table 1 is reproduced
below. **Instance: Western Europe from PTV AG, 18.0 M vertices / 42.5 M directed
arcs, travel-time metric. All single-threaded on one core of an Intel X5680
3.33 GHz.** Our graphs are 40–78× smaller, so every row scales down; where the
scaling is not linear I say so.

| algorithm | space [GiB] | preprocessing [h:m] | scanned vertices | query [µs] |
|---|---|---|---|---|
| Dijkstra | 0.4 | – | 9,326,696 | 2,195,080 |
| Bidirectional Dijkstra | 0.4 | – | 4,914,804 | 1,205,660 |
| CRP | 0.9 | 1:00 | 2,766 | 1,650 |
| Arc Flags | 0.6 | 0:20 | 2,646 | 408 |
| **CH** | **0.4** | **0:05** | **280** | **110** |
| CHASE | 0.6 | 0:30 | 28 | 5.76 |
| HLC (hub label compression) | 1.8 | 0:50 | – | 2.55 |
| TNR | 2.5 | 0:22 | – | 2.09 |
| TNR+AF | 5.4 | 1:24 | – | 0.70 |
| HL (hub labels) | 18.8 | 0:37 | – | 0.56 |
| HL-∞ | 17.7 | 60:00 | – | 0.25 |
| table lookup | 1,208,358.7 | 145:30 | – | 0.06 |

Source: [arXiv:1504.05140](https://arxiv.org/pdf/1504.05140), Table 1. Note the
last row: a full 18 M × 18 M table is **1.2 PB**, precomputed with PHAST in
145 hours. That row is the honest statement of why "just precompute the matrix"
has a size at which it stops being a plan.

### Contraction Hierarchies (CH)

Order vertices by importance, contract least-important first, adding a shortcut
whenever contraction would otherwise lengthen a shortest path. Query is a
bidirectional search that only ever goes *up* the order.

- **Preprocessing:** 5 minutes on 18 M vertices, single-threaded, travel times
  ([Table 1](https://arxiv.org/pdf/1504.05140)). Scaled to Stuttgart's 429 k
  vertices that is ~7 s; independent measurement confirms the order of magnitude
  — Buchhold & Wagner report "**CH preprocessing and CCH order computation take
  less than one second each**" on the MATSim Open Berlin network (73,689 nodes /
  159,039 links) and 4 s / 6 s on Rhine-Ruhr (394,049 nodes / 840,587 edges)
  ([arXiv:2011.02601](https://arxiv.org/pdf/2011.02601), Table 1 and §5).
- **Query:** 110 µs on Europe, 280 settled vertices. City-scale is well under
  50 µs; `fast_paths` (Rust) measures **55 µs on New York City, 264,347 nodes /
  730,100 edges, after 9 s of preprocessing**, on an M1 Max
  ([github.com/easbar/fast_paths](https://github.com/easbar/fast_paths)). That
  graph is within 15 % of Vancouver's.
- **Space:** 0.4 GiB for 18 M vertices ≈ 24 B/vertex, i.e. the CH is about the
  size of the graph.
- **Edge-weight changes: badly.** The vertex order is metric-dependent, so a new
  metric means re-running preprocessing. The survey's Table 2 shows how metric-
  sensitive: with *travel distance* instead of travel time, CH preprocessing goes
  from 0:02 to 0:12 (h:m, 12 threads) and query from 0.11 ms to 0.87 ms, an 8×
  degradation from nothing but a different weight function
  ([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140), Table 2). The CCH paper
  reports the same effect more starkly: classic CH preprocessing on Europe is
  **451 s for travel time but 2,853 s for distances**
  ([arXiv:1402.0402](https://arxiv.org/abs/1402.0402)).

**This is the disqualifying property for us.** Our weights are metres, which is
the *bad* metric for CH, and a road closure changes the topology.

### Customizable Route Planning (CRP) and multilevel overlays

Partition the graph once (metric-independent), then per metric compute overlay
cliques over each cell's boundary vertices. Query is a multilevel Dijkstra.

From the survey's Table 2, Europe with turn costs, **12 threads for
preprocessing/customization, single-threaded queries**
([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140)):

| | metric-independent | customization | query (dist) | query (path) |
|---|---|---|---|---|
| CRP, travel time | 12 min / 3.11 GiB | **0.37 s / 0.07 GiB** | 1.65 ms | 1.81 ms |
| CRP, travel distance | 12 min / 3.11 GiB | **0.37 s** | 1.91 ms | 2.49 ms |
| CH, travel time | 2 min / 0.60 GiB | – | 0.11 ms | 0.21 ms |
| CH, travel distance | 12 min / 0.68 GiB | – | 0.87 ms | 1.07 ms |

The two properties that matter: **customization is 0.37 s for a continent**, and
**query time is essentially independent of the cost function** (1.65 vs 1.91 ms).
The survey adds that GPU customization cuts this to **36 ms** and reduces stored
data 6×, citing Delling, Kobitzsch & Werneck, *Customizing Driving Directions
with GPUs*, Euro-Par 2014
([link.springer.com/chapter/10.1007/978-3-319-09873-9_61](https://link.springer.com/chapter/10.1007/978-3-319-09873-9_61));
without contraction-based customization it is "about one second on a 12-core
CPU".

CRP queries are 15× slower than CH — that is the price of customizability.

### Customizable Contraction Hierarchies (CCH)

The synthesis, and the one to build on: Dibbelt, Strasser & Wagner, ACM JEA
21(1):1.5, 2016, [arXiv:1402.0402](https://arxiv.org/abs/1402.0402). Order
vertices by *nested dissection* on the unweighted topology; that order is
metric-independent, so contraction can be done once and only the shortcut
*weights* recomputed per metric. Queries use an **elimination-tree** search with
no priority queue at all.

Europe, 18,010,173 vertices / 42,188,664 arcs, dual 8-core Xeon E5-2670
([arXiv:1402.0402](https://arxiv.org/abs/1402.0402)):

| phase | time |
|---|---|
| metric-independent order (Metis nested dissection) | 131.3 s |
| CH skeleton construction from that order | 15.5 s |
| customization, 1 thread, no SSE | 21.90 s |
| customization, SSE + precomputed triangles, 1 thread | 7.32 s |
| **customization, SSE + triangles, 16 threads** | **1.03 s** |
| perfect customization (16 threads) | 3.50 s |
| **partial update, one arc weight changed** | **median 0.005–0.008 ms, mean 0.045–0.052 ms, max 81–135 ms** |
| query (elimination tree, perfect) | 161 µs (time) / 214 µs (distance) |
| query (classic CH, stalling) | 107 µs |

The 2025 survey by Bläsius, Buchhold, Wagner, Zeitz & Zündorf,
[arXiv:2502.10519](https://ar5iv.labs.arxiv.org/html/2502.10519), re-measures on
an Intel Xeon E5-2670 and gives a **Stuttgart instance at roughly 110 k vertices
and 252 k edges** — a quarter of ours, same order — with **total metric-
independent preprocessing 0.9 s** (0.8 s ordering + 0.0 s contraction) against
361.1 s for Europe. Europe customization there is 10.76 s sequential / **1.25 s
on 16 threads**, versus CRP's 10.55 s / 1.05 s. Query ≈ 300 µs Europe,
440 µs Germany.

Three findings from these papers worth copying verbatim into an implementation:

- **Query and customization cost are independent of the weights** — unlike CH,
  a distance metric costs nothing extra.
- **Do not port stall-on-demand.** With metric-independent orders the denser
  search space makes the stall test cost more than it saves
  ([arXiv:1402.0402](https://arxiv.org/abs/1402.0402)).
- **Renumber vertices into contraction order**: 2–3× from cache behaviour alone.

**Scaling to us.** Europe's 18 M vertices customize in 1.03 s on 16 threads.
Customization is close to linear in the number of shortcut triangles, which grows
slightly superlinearly with |V| on road graphs; taking it as linear gives
Stuttgart (429 k, 1/42 of Europe) at **~25 ms on 16 threads, ~500 ms
single-threaded**. That is consistent with the survey's 0.9 s *metric-independent*
figure for a 110 k-vertex Stuttgart, and with Buchhold & Wagner's "less than one
second" for order computation on Berlin. Call it **tens of milliseconds to
re-customize a whole city graph** — i.e. a road closure is a customization, not a
re-preprocessing.

### ALT / landmarks

A\* with lower bounds from precomputed distances to/from k landmarks, via the
triangle inequality (Goldberg & Harrelson, SODA 2005). In the survey's Figure 7
ALT sits at ~10 ms on Europe with sub-minute preprocessing — **two orders of
magnitude slower than CH** but with the cheapest preprocessing of anything that
beats bidirectional Dijkstra.

It is what MATSim actually uses: `org.matsim.core.router.speedy.SpeedyALT`,
"a very fast implementation of the ALT algorithm … using a typical value of 16
landmarks", with all landmark values for a vertex adjacent in memory so one cache
line loads them all
([matsim.org doxygen](https://www.matsim.org/doxygen/classorg_1_1matsim_1_1core_1_1router_1_1speedy_1_1_speedy_a_l_t.html)).
Cost is 2 × 4 B per vertex per landmark: 16 landmarks on Stuttgart is
429 k × 16 × 8 B = **54.9 MB**.

The relevant property here is the opposite of CH's: **landmark bounds remain
valid lower bounds when edges get longer or are removed.** Closing a road can
only lengthen paths, so a landmark table built on the open network stays
admissible on the closed one — the bound gets looser, the answer stays exact.
That makes ALT the cheapest correct fallback for scenario graphs.

### Arc Flags

Partition into k cells; for each arc store a k-bit flag saying "this arc lies on
some shortest path into cell c". Query prunes on the flag of the target's cell.
408 µs on Europe, 20 minutes preprocessing, 0.6 GiB
([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140), Table 1). Flags are fully
metric-dependent and must be recomputed on any weight change; the survey notes
PHAST-based preprocessing as the mitigation. **Not a candidate** — it has CH's
rigidity without CH's speed.

### Hub Labelling (HL)

Store for each vertex a label of (hub, distance) pairs such that any s–t pair
shares a hub on the shortest path. Query is a sorted-list merge: **0.56 µs**, the
fastest practical method, at **18.8 GiB for 18 M vertices ≈ 1.1 kB/vertex**
([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140), Table 1). Scaled to
Stuttgart's 429 k vertices that is ~470 MB — affordable on a desktop, over the
WebGPU 256 MiB default buffer limit, and the labels are metric-dependent so a
road closure means rebuilding them (0:37 on Europe). HLC (compressed) trades to
1.8 GiB / 2.55 µs.

HL is the right answer if and only if the query count is enormous and the metric
is frozen. Our metric is frozen *within* a scenario, so it is not absurd — but
CCH's bucket many-to-many gets most of the win without the 470 MB or the rebuild.

### Transit Node Routing (TNR)

Pick ~10 k "transit nodes" (highway access points), precompute the full table
between them plus each vertex's access nodes; a long-range query becomes a few
table lookups. **2.09 µs, 22 min preprocessing, 2.5 GiB** on Europe; with arc
flags, 0.70 µs ([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140), Table 1).

Two reasons it is wrong for us. First, TNR is only correct for *global* queries;
local ones fall back to a graph search and are **slower** than the global ones,
and the survey's Figure 8 shows graph-search methods beating bounded-hop methods
for Dijkstra ranks below 2^16. Our trips are local: the whole point of a city sim
is that most trips are a few kilometres. Second, the transit-node set is derived
from the metric and would have to be rebuilt per scenario.

### Summary: how each family takes an edge-weight change

| family | response to a changed/removed edge | cost at city scale |
|---|---|---|
| Dijkstra / A\* | none needed | free |
| ALT | bounds stay admissible if weights only increase | free; rebuild if weights decrease |
| CH | rebuild the order and contraction | seconds (city), minutes–hours (continent) |
| Arc Flags | recompute all flags | minutes |
| CRP | re-run customization | 0.37 s continental → ms at city scale |
| **CCH** | **re-run customization, or a partial update per arc** | **tens of ms city-wide; ~50 µs per changed arc** |
| Hub labels | rebuild labels | tens of minutes continental |
| TNR | rebuild transit node set and table | tens of minutes |

---

## 2. Batch and many-to-many methods

This is where the real speedup lives, because our queries are not independent:
35,000 origin cells against a small, mostly-fixed target set, repeated every
simulated day.

### PHAST — one-to-all with CH

Delling, Goldberg, Nowatzyk & Werneck. Run a forward CH search from *s*, then a
**single linear sweep** over all vertices in reverse CH-level order, propagating
distances downward. The sweep's instruction flow is independent of the source, so
it vectorises, parallelises and streams.

Europe 18 M / 42 M, Intel Core i7-920 4 cores @ 2.67 GHz
([MSR-TR-2010-125](https://www.microsoft.com/en-us/research/wp-content/uploads/2010/09/phastTR.pdf)):

| | ms per tree |
|---|---|
| Dijkstra, binary heap, random vertex layout | 12,683 |
| Dijkstra, smart queue, DFS layout | 3,290 |
| BFS (a lower bound on any label-setting method) | 2,212 |
| PHAST, original CH ordering | 783 |
| **PHAST, reordered by level** | **195** |
| PHAST, k=16 trees at once, 1 core, SSE | 43.0 |
| PHAST, 4 cores + SSE + k=16 | 19.5 |
| **GPHAST, NVIDIA GTX 480, k=1** | **9.70** |
| **GPHAST, GTX 480, k=16** | **2.90** (161 ps per distance label) |

The IPDPS 2011 version on a **GTX 580** (192.4 GB/s, vs 32 GB/s for a high-end
Xeon of the day) reports k=1 at **5.53 ms = 511× Dijkstra** and k=16 at
**2.21 ms ≈ 1280× Dijkstra**
([dgnw11-phast-ipdps.pdf](https://renatowerneck.wordpress.com/wp-content/uploads/2016/06/dgnw11-phast-ipdps.pdf)).
All-pairs on Europe: **11–14.5 hours on the GPU** versus ~200–230 days for
4-core Dijkstra.

Two structural facts to carry into the WGSL design:

- **Levels are the parallel depth.** Contraction assigns `L(v) = max(L(v),
  L(u)+1)`, and Europe ends with **~140 levels with half the vertices in level 0**
  (USA: 101 levels for travel times, 285 for distances; Europe distances 410).
  CH collapses a diameter-6809 road graph into ~10² sweep levels. That is the
  entire reason a GPU can beat a CPU here and cannot on raw Dijkstra.
- **It is bandwidth-bound, not compute-bound.** A pure sequential traversal of
  the same arrays takes **76.4 ms** against PHAST's 195 ms — only 2.5× off the
  roofline ([MSR-TR-2010-125](https://www.microsoft.com/en-us/research/wp-content/uploads/2010/09/phastTR.pdf)).

An independent reproduction on a single Xeon E5-1630v3 @ 3.7 GHz, Europe
18,010,173 / 42,188,664: Dijkstra one-to-all **2,653.18 ms**, PHAST **144.16 ms**,
GRASP (the CRP-overlay analogue) **171.11 ms**
([arXiv:1512.09090](https://arxiv.org/pdf/1512.09090), Table 1). The agreement
with the original 136.92 ms is good, so these numbers are trustworthy.

### RPHAST — restricted to a target set

Restrict the downward graph to the vertices that can reach a given target set,
then sweep only those. Europe, dual Xeon X5680 6c @ 3.33 GHz, selection and
queries sequential, |T| = 2^14 = 16,384 targets drawn from a ball of the same
size ([OASIcs.ATMOS.2011.52](https://drops.dagstuhl.de/storage/01oasics/oasics-vol020-atmos2011/OASIcs.ATMOS.2011.52/OASIcs.ATMOS.2011.52.pdf),
Table 1):

| method | preprocessing | selection | query |
|---|---|---|---|
| Dijkstra | 0.4 GB | — | 7.43 ms |
| Hub labels (local) | 20.1 GB / 2:39 h | — | 6.27 ms |
| Bucket CH (BCH) | 0.4 GB / 5 min | 943.3 ms | 1.72 ms |
| Bucket HL | 20.1 GB / 2:39 h | 50.9 ms | 1.40 ms |
| PHAST | 0.4 GB / 5 min | — | 136.92 ms |
| **RPHAST** | **0.4 GB / 5 min** | **1.8 ms** | **0.17 ms** |

With targets spread over the whole graph (|B| = 2^20) rather than a compact ball,
RPHAST degrades to selection 27.5 ms / query 1.02 ms, and the restricted graph
grows from 18,009 to 117,419 vertices — **RPHAST's advantage is proportional to
how spatially clustered the targets are.** Ours are venues across a whole city,
i.e. the spread case, not the ball case.

**Many-to-many with |S| = |T| = 2^14 on one core: SSE-RPHAST 0.95 s versus bucket
CH 28.76 s, a 30× gap** (same paper, §4.2). That is 268 M matrix entries in
0.95 s = **3.5 ns per entry**. (The ATMOS text prints these as "ms"; Figure 2's
axis is labelled *Query Time [s]* and 1.72 ms × 16,384 = 28.2 s reproduces the
BCH number exactly, so read them as seconds.)

### CH bucket-based many-to-many

Knopp, Sanders, Schultes, Schulz & Wagner, ALENEX 2007
([distTable.pdf](https://turing.iem.thm.de/routeplanning/hwy/distTable.pdf)).
Backward upward search from each target deposits `(target, dist)` into a bucket
at each settled vertex; forward upward search from each source scans buckets it
meets. Cost is `|S|·upward + |T|·upward + O(|S||T|·f)` with a tiny constant on the
last term.

**One core of a dual AMD Opteron @ 2.6 GHz, Europe 18,029,721 nodes / 42,199,587
arcs: a 10,000 × 10,000 table in 67 s**, against ~one day for 10,000 Dijkstra runs
and ~one day for 10^8 point-to-point highway-hierarchy queries — **>1000× over
both**. 20,000 × 20,000 lands at 5–6 minutes. The paper also reports that on
*clustered* real vehicle-routing instances (|S| = |T| between 173 and 2,892) the
running time is within a factor 1.7 of random instances of the same size, and
that the bucket method beats plain Dijkstra **from |S| = 5 sources upward**.

Modern bucket numbers on CH and CCH, 2× Xeon Gold 6144 8c @ 3.5 GHz, Europe
([arXiv:2103.10359](https://arxiv.org/pdf/2103.10359), Table 1): BCH selection for
|P| = 2^12 targets in a 2^20 ball **134 ms / 72.4 MiB**, query **20 µs**; for
|P| = 2^14 spread over all of V, selection **481 ms**, query **5.0 µs**. BCCH
(bucket over CCH) selection **453 ms** and **1,753 ms** respectively, queries
51 µs / 6.0 µs. The pattern: **bucket methods have the fastest per-source query
but a selection phase that goes into the minutes for large target sets.** They are
an offline/batch tool.

### One-to-many over CRP overlays: GRASP

CRP's papers are point-to-point only; the one-to-all analogue is GRASP
(Efentakis & Pfoser). Europe one-to-all **150 ms sequential / 43 ms on 4 cores**
on an i7-4771 @ 3.5 GHz, with **8 s parallel customization**
([arXiv:1411.0257](https://arxiv.org/pdf/1411.0257), Tables 1–2); independently
re-measured at 171.11 ms against PHAST's 144.16 ms on the same core
([arXiv:1512.09090](https://arxiv.org/pdf/1512.09090)). So GRASP buys CRP's fast
customization at roughly a 20 % one-to-all penalty against PHAST. That trade is
exactly the one we want for scenario graphs.

### Lazy RPHAST — no selection phase

The important recent variant, from the CCH survey
([arXiv:2502.10519](https://arxiv.org/pdf/2502.10519), §5.2.1 and Fig. 5):
targets are supplied incrementally, and distances are computed on demand up the
elimination tree with memoisation, so there is **no selection phase at all**.
Per-distance cost starts near **0.1 ms** and falls **below 0.5 µs** — faster than
hub labels — once more than **2^10 distances** are drawn from the same source
within a small ball. This is the right shape for agents that decide destinations
at runtime, which is our shape.

### Which fits a 35k × 25k matrix

First, do not build it. 35,000 × 25,000 × 4 B = **3.5 GB**; at u16 (decametres,
0–655 km) it is still 1.75 GB. That is 26× the WebGPU default 128 MiB storage
binding and 13× the 256 MiB max buffer. The matrix the code actually consumes is
**35,000 × ~192 = 6.7 M entries = 26.9 MB at u32**, which fits one binding with
room to spare.

Per-entry costs from the numbers above, and what they imply for 6.7 M entries on
a graph 78× smaller than Europe:

| method | Europe ns/entry | mechanism | 6.7 M entries, city-scale estimate |
|---|---|---|---|
| RPHAST (SSE, |S|=|T|=2^14) | 3.5 | restricted sweep | ~10–25 ms/core |
| RPHAST (|T|=2^14, per source) | 10.4 | 1.8 ms select + 0.17 ms/source | ~20–50 ms/core |
| Bucket CH (10k × 10k) | 670 | 67 s / 10^8 | ~1–3 s/core after selection |
| CH point-to-point, batched AVX | ~1,000 | see below | ~1–2 s/core |
| A\* as implemented here | 5.8 × 10^6 | *(measured here)* | 72 hours |

**The decisive city-scale datapoint** is Buchhold, Sanders & Wagner, *Real-Time
Traffic Assignment Using Fast Queries in Customizable Contraction Hierarchies*,
SEA 2018
([LIPIcs.SEA.2018.27](https://drops.dagstuhl.de/storage/00lipics/lipics-vol103-sea2018/LIPIcs.SEA.2018.27/LIPIcs.SEA.2018.27.pdf)),
because the instance is **metropolitan Stuttgart, 134,663 vertices and 307,759
edges** — between our two graphs — with real OD demand, on an Intel Xeon E5-1630
v3, 4 cores @ 3.70 GHz:

| scenario | OD pairs | iterations | Dijkstra | plain CH | **CCH + AVX centralized elimination tree, k=32** | CCH, 4 cores |
|---|---|---|---|---|---|---|
| Tue 7:00–7:30 | 118,933 | 12 | 1,857.27 s | 35.85 s | 4.60 s | **2.65 s** |
| Tue 7:00–9:00 | 478,098 | 12 | 6,028.48 s | 76.54 s | 10.54 s | **4.33 s** |
| whole Tuesday | 3,355,442 | 6 | 20,128.24 s | 183.59 s | 25.14 s | **7.67 s** |
| whole week | 21,248,278 | 6 | 128,993.50 s | 1,082.20 s | 126.70 s | **36.64 s** |

Read the third row against our workload. **20.1 million shortest-path
computations — with a full CCH re-customization before every one of the six
iterations — in 7.67 seconds on four 2015-era cores.** That is ~2.6 M queries per
second, or **~0.38 µs per OD pair**. Our 2.5 M daily OD queries on a graph of the
same size are **about one second on four cores**, and the biggest row shows the
approach holds to 127 M queries.

Against our measured 26 queries/s, that is a factor of **10^5**. The gap
decomposes roughly as: ~30× from replacing the allocating `PriorityQueue` with a
proper heap, ~100–300× from CH/CCH instead of A\*, ~5× from SIMD-batched
centralized searches (the paper measures 5.2× from SSE/AVX alone), ~4× from four
cores. **No GPU appears anywhere in that decomposition.**

Their own reported building blocks: switching CH → CCH is 3× on the smallest
scenario; sorting OD pairs so similar ones run consecutively is ~20 % on the
largest; k = 32 simultaneous searches with AVX is up to 5.2×; combined, 8× over
the prior state of the art and "several hundred times faster" than the Dijkstra
baseline. Customization is 44 % of total time on the smallest scenario, 27 % on
Tue02h, **2 % on the largest** — so customization is free at our query volume.

### The crossover: matrix sweep versus per-pair query

- **PHAST vs per-pair CH, Europe:** 136.92 ms for 18 M distances = **7.6 ns per
  entry**; a CH point-to-point query is 110 µs. A one-to-all sweep wins as soon as
  you want **≳1,250 targets from one source**.
- **RPHAST vs per-pair CH:** `1.8 ms + 0.17 ms·|S|` at |T| = 16,384 ⇒ 10.4 ns per
  entry; RPHAST wins from roughly **|T| ≳ 25 targets** once selection is amortised.
- **Bucket CH** needs ~550 sources just to repay its 943 ms selection against
  RPHAST at |T| = 2^14; Knopp et al. put the threshold against plain Dijkstra at
  **|S| = 5**.
- **CH preprocessing amortises after 278–319 one-to-all trees** versus 4-core
  Dijkstra on Europe
  ([MSR-TR-2010-125](https://www.microsoft.com/en-us/research/wp-content/uploads/2010/09/phastTR.pdf)).

Our candidate sets are ~192 per cell — above the RPHAST crossover (25), far below
the one-to-all crossover (1,250). So the shape that fits is **per-cell one-to-many
over a restricted target set**, or simply batched point-to-point, not a full
one-to-all sweep per cell.

### Production matrix APIs, and why their numbers are weak evidence

- **OSRM** `table` defaults to `--max-table-size 100` (read from
  `src/tools/routed.cpp`); the public demo caps at 10,000 elements
  ([R osrm docs](https://search.r-project.org/CRAN/refmans/osrm/html/osrmTable.html)).
  A maintainer reports a **10k × 10k table in about 8 seconds on a laptop**
  (≈80 ns/entry) and notes that for a 1 × 10,000 matrix the route computation is
  only ~0.0008 s — **spatial-index coordinate snapping dominates** below roughly
  10k × 10k ([issue #6018](https://github.com/Project-OSRM/osrm-backend/issues/6018)).
  In the same thread a user measures **100 × 100 in ~3,500 ms** with the MLD
  pipeline on a foot network, two orders of magnitude off the CH figure. Memory
  with `--max-table-size 10000` was reported at **21.5 GB for Europe**.
- **GraphHopper**'s matrix blog posts quote 1000² in 8 s (2018) and "well below
  five seconds" (2019), and "over 181,000 road distances every second" rising to
  >350,000/s
  ([2018](https://www.graphhopper.com/blog/2018/03/22/matrix-api-update-180k-road-distances-per-second/),
  [2019](https://www.graphhopper.com/blog/2019/06/04/incredibly-fast-distance-matrix-api-with-graphhopper/)).
  **Treat as marketing.** No hardware is named, the two posts contradict each
  other, the 2019 post concedes production hardware is "2 times faster" than
  quoted, and queries were confined to the Berlin city area, which flatters CH.
- **Valhalla** publishes no matrix benchmark; the only public datapoint is 33
  sources × 1 target on a 4-vCPU box averaging **2,095 ms** against OSRM's 10 ms
  ([issue #2604](https://github.com/valhalla/valhalla/issues/2604)). Valhalla's
  matrix is bidirectional A\* per pair, not a bucket or sweep method.
- **RoutingKit**'s README contains no numbers at all, only "within milliseconds or
  even less"
  ([README](https://github.com/RoutingKit/RoutingKit/blob/master/README.md)).

The trustworthy production-scale evidence is the academic Stuttgart, Berlin and
Rhine-Ruhr numbers above, not the API pages.

---

## 3. GPU shortest paths

### The headline result: raw GPU SSSP loses on road networks

Davidson, Baxter, Garland & Owens, *Work-Efficient Parallel GPU Methods for
Single-Source Shortest Paths*, IPDPS 2014
([PDF](https://escholarship.org/content/qt8qr166v2/qt8qr166v2_noSplash_be4e051e39b35de331f67c483ccb78a7.pdf)),
on an NVIDIA GTX 680 against a 2-core i5-650:

| graph class | speedup vs Bellman-Ford | **speedup vs serial Dijkstra** |
|---|---|---|
| road networks | 1.3–14× | **0.24–0.6×** |
| meshes | 3.9–19.85× | 2–29.4× |
| scale-free | 34.7–343× | 22–64× |

Their own sentence: *"For high-diameter road networks, without preprocessing, our
implementations are unable to outperform an efficient serial implementation. This
is expected behavior; the lack of parallelism in processing these networks means
that a good serial implementation should outperform a good parallel one."*

The 350 MTEPS figure everyone quotes from that paper is a 17 M-vertex / 90 M-edge
**RMAT** graph. There is no comparable road-network MTEPS number in it.

Gunrock confirms the shape on a Tesla K40c
([TOPC 2017](https://escholarship.org/content/qt9gj6r1dj/qt9gj6r1dj_noSplash_ffb70bb2bb62526a8c80b9b370ced2c7.pdf),
Table 6):

| algorithm | roadnet USA (23.9 M v / 57.7 M e, diameter 6,809) | rmat_s22_e64 (4.2 M v / 483 M e, diameter 5) |
|---|---|---|
| BFS | 676.2 ms / 85.34 MTEPS | 3.943 ms / 122,516 MTEPS |
| SSSP | **11,037 ms** / 5.229 MTEPS | 583.9 ms / 827.3 MTEPS |

A **1,436× BFS gap and a 259× SSSP gap on identical hardware and identical code.**
Gunrock's SSSP on the USA road network takes 11 seconds. Its own §7: *"work-
efficient traversal is more difficult for small-degree large-diameter graphs (rgg
and roadnet)."*

### Why: the frontier is empty

- **Average degree 2.4–2.8** on every DIMACS road graph — NY 2.76, USA 2.43
  ([arXiv:2602.10080](https://arxiv.org/pdf/2602.10080) dataset table) — against
  6.0 for Delaunay meshes and 12–100+ for social graphs. `europe.osm` is
  50.9 M v / 108.1 M e, **average degree 2.1, search depth 19,314**
  ([NVIDIA TR, Merrill et al.](https://research.nvidia.com/sites/default/files/pubs/2011-08_High-Performance-and/BFS%20TR.pdf)).
- **Phase counts.** Madduri, Bader, Berry & Crobak, ALENEX 2007
  ([PDF](https://www.cse.psu.edu/~kxm85/papers/DeltaSteppingSSSP-ALENEX07.pdf),
  Fig. 3), at comparable sizes: a random graph with n = 2^20 runs **84 phases**
  with request sets up to 27,000; **NE-USA road, n = 1,524,452 / m = 3,897,634,
  runs 23,000 phases, and only ~30 of them have request sets larger than 1,000.**
  That is ~270× more phases with ~27× smaller peak frontiers.
- **The GPU restatement.** ADDS, PPoPP 2021
  ([PDF](https://www.cs.utexas.edu/~lin/papers/ppopp21.pdf)): *"for the road.USA
  graph, the average work count per iteration is only 800, while an RTX 2080 GPU
  has 68K hardware threads."* **1.2 % occupancy**, with a state-of-the-art near-far
  implementation. ADDS gets 3.09× over Near-Far on road-USA only by deliberately
  doing 5× more work to buy parallelism; on RMAT no such trade is needed at all.
- **Δ-stepping's knob points opposite ways.** Neo4j GDS documents a default
  Δ = 2.0, recommends **Δ ≈ 2 for power-law graphs and Δ ≈ 10,000 for high-diameter
  transport networks**
  ([GDS docs](https://neo4j.com/docs/graph-data-science/current/algorithms/delta-single-source/))
  — a 5,000× spread driven purely by topology. Meyer & Sanders' bounds all carry
  an **L/Δ** phase term where L is the maximum shortest-path weight
  ([J. Algorithms 49(1):114–152](https://dl.acm.org/doi/10.1016/S0196-6774(03)00076-2)),
  and road networks maximise L. cuGraph exposes **no** Δ parameter, and Intel's
  independent benchmark notes its "internal defaults may be suboptimal for
  high-diameter graphs like Road networks"
  ([Gabb](https://medium.com/intel-analytics-software/measuring-graph-analytics-performance-2ab1a4052ca4)).
  The frequently-cited cuGraph "8.7 GTEPS on a V100" is **PageRank on a scale-free
  graph**, not SSSP
  ([RAPIDS deck](https://www.slideshare.net/slideshow/rapids-cugraph-accelerating-all-your-graph-needs/180662944)).

**Conclusion for us: do not port Δ-stepping, near-far, or Bellman-Ford frontier
SSSP to WGSL.** They are the wrong algorithms for this graph class, and the
literature says so with numbers.

### What does work on GPUs: CH preprocessing plus a linear sweep

GPHAST's 2.21–9.70 ms per continental tree (§2) is the counter-example, and the
reason is structural: **CH turns a diameter-6,809 graph into ~100–400 levels**,
each of which is embarrassingly parallel, with half the vertices in level 0. The
sweep is a coalesced scan over a CSR array with no queue, no re-insertion and no
dynamic work list.

GPU CH *preprocessing* also works: Karimi, Koppelman & Michael, *GPU Road Network
Graph Contraction and SSSP Query*, ICS 2019
([PDF](https://www.ece.lsu.edu/koppel/pubs/cuch-ics-2019.pdf)) report **20–37×
over Geisberger's serial contraction on DIMACS road graphs, NVIDIA P100 versus
Xeon E5-2640 v4**, with query times on the resulting graphs comparable to serial
CH. On the CPU side, SPoCH
([arXiv:2412.18008](https://arxiv.org/html/2412.18008)) builds a CH for **Europe,
131 M vertices / 169 M edges, in 32.9 s** on four Xeon Gold 6252 (96 cores), with
93–137 µs queries, 3.8–41× over the best parallel baseline and 53.8× over
sequential RoutingKit.

### WebGPU/WGSL: the field is empty

There is no WebGPU routing or road-network SSSP library. What exists:

- **GraphWaGu** (EuroVis 2022,
  [PDF](https://stevepetruzza.io/pubs/graphwagu-2022.pdf)), "the first WebGPU-based
  graph visualization system": Fruchterman-Reingold + Barnes-Hut in WGSL,
  **100,000 nodes / 2,000,000 edges at ≥10 FPS**, 4× the frame rate of the best
  WebGL library. Layout only; no BFS or SSSP. Its edge buffer is 2·|E| u32 — the
  same packing we would use.
- **AntV G6 `webgpu-graph`**
  ([docs](https://g.antv.antgroup.com/en/api/gpgpu/webgpu-graph)) is the only
  WebGPU library shipping SSSP/APSP/BFS. Its published benchmark: **SSSP on 1,000
  nodes / 5,000 edges, 27,687 ms CPU → 261.6 ms GPU**. 261 ms for 5,000 edges is
  ~19 kTEPS, three to four orders off native CUDA. Proof of concept, not a
  baseline.
- **wgpu** ([gfx-rs/wgpu](https://github.com/gfx-rs/wgpu)) is the practical route:
  one WGSL codebase runs native (Vulkan/Metal/D3D12) and in the browser.
- OpenCL is no better: the reference is still the Harish & Narayanan frontier
  kernel from the *OpenCL Programming Guide*, with exactly the occupancy problem
  above. The one GPU city-traffic system at scale, MANTA
  ([arXiv:2007.03614](https://arxiv.org/pdf/2007.03614)), does CUDA
  microsimulation but **routes with a CPU priority-queue Dijkstra**.

**We would be writing the first one.** That is a reason to keep the first
milestone small, not a reason to avoid it.

### WGSL constraints and what they cost

Defaults from the [W3C WebGPU limits table](https://www.w3.org/TR/webgpu/#limits)
and [MDN `GPUSupportedLimits`](https://developer.mozilla.org/en-US/docs/Web/API/GPUSupportedLimits):

| limit | default |
|---|---|
| `maxBufferSize` | 268,435,456 B (256 MiB) |
| `maxStorageBufferBindingSize` | 134,217,728 B (128 MiB) |
| `maxStorageBuffersPerShaderStage` | 8 |
| `maxComputeWorkgroupStorageSize` | 16,384 B |
| `maxComputeInvocationsPerWorkgroup` | 256 |
| `maxComputeWorkgroupSizeX / Y / Z` | 256 / 256 / 64 |
| `maxComputeWorkgroupsPerDimension` | 65,535 |
| `maxUniformBufferBindingSize` | 65,536 B |
| `minStorageBufferOffsetAlignment` | 256 B |

[WGSL §6.2.8](https://www.w3.org/TR/WGSL/): `atomic<T>` requires **T to be `u32`
or `i32`** — no float atomics, no 64-bit atomics, no atomic float min/max.
Distances must therefore be **quantised to u32**; metres as u32 is exact for our
metric and `atomicMin` works directly. 16,384 B of workgroup storage caps a
per-workgroup bucket at ~4,096 u32 entries. A 1-D dispatch covers at most
65,535 × 256 = 16.8 M invocations.

CSR sizing for our graphs, 32-bit throughout:

| | Vancouver (232,290 v / 597,024 arcs) | Stuttgart (428,737 v / 941,966 arcs) |
|---|---|---|
| `offsets` (n+1 × u32) | 0.93 MB | 1.71 MB |
| `targets` (m × u32) | 2.39 MB | 3.77 MB |
| `weights` (m × u32, metres) | 2.39 MB | 3.77 MB |
| **CSR total** | **5.71 MB (5.4 MiB)** | **9.25 MB (8.8 MiB)** |
| one `dist` array (n × u32) | 0.93 MB | 1.71 MB |
| concurrent `dist` arrays in one 128 MiB binding | 144 | 78 |
| the 35k × 192 impedance table (u32) | 26.9 MB | 26.9 MB |
| the 35k × 25k full matrix (u32) | 3.5 GB — **26× over the binding limit** | |
| 500k commute distances (u32) | 2.0 MB | 2.0 MB |

The graph is small. A whole city CSR plus 78 simultaneous source-distance arrays
fits inside a single default storage binding. **Memory is not the constraint;
parallel depth is.**

---

## 4. Transit

Today `city.sim.network` models transit as **nearest stop + 5 minutes fixed wait
+ 18 km/h fixed in-vehicle speed**, degrading to a walk below a 500 m ride
(`transit-wait-min`, `mode-speeds-kmh`, `transit-min-ride-m`). There is no
timetable in the routing; the GTFS feed is used only to place stops and compute a
mean headway for display. Transit is **23.4 % of Stuttgart trips** in the MiD 2023
small-area estimate ([`trip-generation.md`](trip-generation.md)), so this covers
roughly 585,000 of the 2.5 M daily legs.

### The feeds, measured

Row counts obtained by downloading both feeds and counting, 2026-09-15, and
cross-checked against a second mirror hours apart:

| | **Stuttgart VVS** ([gtfs.mfdz.de/VVS.gtfs.zip](https://gtfs.mfdz.de/VVS.gtfs.zip), feed_version 20260914) | **Vancouver TransLink** ([gtfs-static.translink.ca](https://gtfs-static.translink.ca/gtfs/google_transit.zip), 26SEP_20260911) |
|---|---|---|
| zipped / unzipped | 48.5 MB / 421.8 MB (117.7 MB of it `shapes.txt`) | 16.16 MB / 107.7 MB |
| stops | **10,199** | **8,921** |
| routes | 722 | 239 |
| trips | 180,749 | 63,022 |
| `stop_times` | 3,228,536 | 1,847,219 |
| **one Wednesday: trips** | 31,100 | 25,704 |
| **one Wednesday: connections** | **~501,880** | **717,429** |
| CSA quintuple array for that day (20 B/connection) | **10.0 MB** | **14.3 MB** |

(Connections = `stop_times` − trips: a *k*-stop trip yields *k*−1 connections.)
The repo currently keeps only the subset in its bbox — **2,740 Stuttgart stops
(2,251 with weekday service) from 6.88 M `stop_times` rows in 23 s**, and
**2,488 Vancouver stops (2,348 with service) in 7.4 s**
([`doc/simulator.md`](../simulator.md)) — and the Stuttgart NVBW feed has a known
defect: its calendar is all zeros and needs a service-date workaround.

**The whole of a city's weekday timetable is 10–14 MB.** That is smaller than the
street CSR. Whatever the objection to timetable routing is, it is not size.

For scale, the standard research instances: **London 20,843 stops / 2,225 routes /
133,011 trips / 5.13 M departure events / 45,652 footpaths**
([RAPTOR, ALENEX 2012](https://www.microsoft.com/en-us/research/wp-content/uploads/2012/01/raptor_alenex.pdf));
**Germany 252,374 stops / 46.2 M connections / 2.4 M trips**
([CSA, arXiv:1703.05997](https://arxiv.org/pdf/1703.05997)). Our cities are
**5–10× smaller than London in connections**.

### RAPTOR — rounds over arrays, zero preprocessing

Delling, Pajor & Werneck, ALENEX 2012
([PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2012/01/raptor_alenex.pdf)).
Round *k* holds the best arrival using at most *k* trips; each round scans every
marked route at most once, over flat arrays. **No priority queue, no graph, no
preprocessing.** It computes journeys to *all* stops by construction — target
pruning is an optimisation, not inherent — which makes it the natural
accessibility primitive.

London, dual 6-core Xeon X5680 @ 3.33 GHz, 10,000 random queries:

| | rounds | comparisons/stop | journeys | ms |
|---|---|---|---|---|
| **RAPTOR** (arrival + transfers) | 8.4 | 22.2 | 1.9 | **7.3** |
| Time-dependent Dijkstra (arrival only) | — | 7.4 | 0.9 | 14.2 |
| Layered Dijkstra | — | 39.5 | 1.9 | 44.5 |
| Multi-label-correcting (MLC) | — | 28.7 | 1.9 | 67.2 |
| **rRAPTOR** (2 h range) | 138.5 | 346.4 | 16.3 | **87.0** |
| McRAPTOR (+ fare zones) | 10.8 | 396.4 | 9.0 | 107.4 |

Other GTFS instances: **LA 3.4 ms, NY 3.1 ms, Chicago 1.8 ms**. RAPTOR is 9×
faster than MLC and beats even arrival-only Dijkstra while returning twice the
journeys. The survey's independently re-run Table 3 gives RAPTOR at 5.4 ms on
London ([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140)) — same order,
different implementation.

**Intra-query parallelism is poor**, and this matters for the GPU question:
RAPTOR goes 7.7 ms → 5.0 (3 cores) → 4.1 (6) → 3.7 (12), i.e. **only 1.9× on six
cores**; rRAPTOR 3.4×, McRAPTOR 4.2×. The paper's own diagnosis is Amdahl (route
scanning is 75 % of sequential time) plus memory contention. On LA/NY/Chicago the
6-core speedup is **below 1.7×**.

### CSA — one flat sorted array, scanned once

Dibbelt, Pajor, Strasser & Wagner
([arXiv:1703.05997](https://arxiv.org/pdf/1703.05997), ACM JEA 2018). Connections
are quintuples `(dep_stop, arr_stop, dep_time, arr_time, trip)` sorted by
departure time and scanned once — "arguably even easier than Dijkstra's
algorithm". Single pinned thread, Xeon E5-1630v3:

| | Germany (46.2 M conn.) | London (4.85 M conn.) |
|---|---|---|
| "preprocessing" (just the sort) | 3.56 s | 0.35 s |
| earliest arrival — **CSA** | **44.9 ms** | **1.2 ms** |
| earliest arrival — RAPTOR | 325.8 ms | 6.4 ms |
| earliest arrival — time-expanded Dijkstra | 1,996.6 ms | 29.3 ms |
| profile (all departures), CSA | 2,517.2 → 217.9 ms | 242.3 → 9.4 ms |
| profile, CSA vs rRAPTOR | 1.68 s vs 6.27 s | 0.14 s vs 0.97 s |

**The SIMD result is the one that matters for a GPU port.** Pareto profile with
256-bit vectors over 8×32-bit timestamps: Germany **8,298.5 ms → 4,402.9 ms with
AVX** (1.9× from vectorisation alone), and **259.2 ms fully optimised**; London
777.5 → 355.6 → **10.7 ms**. The authors note the algorithm "heavily depends on
memory access speeds" and that AVX's gain comes partly from fewer instructions
making the access pattern predictable. **This is the strongest published evidence
that the transit inner loop vectorises**, and CSA's flat sorted sweep is a far
better WGSL target than RAPTOR's pointer-chasing route scans.

The 2026 T-REX paper re-measures on a Xeon Gold 6144 @ 3.5 GHz
([arXiv:2605.18778](https://arxiv.org/pdf/2605.18778)): **Paris (41,757 stops)
plain CSA 3,280 µs**, Switzerland (29,045 stops, 5.03 M stop events) 3,931 µs,
Germany (435,550 stops, 30.7 M events) 83,101 µs. **A Paris-sized network answers
in 3.3 ms with zero preprocessing.** Our cities are smaller than Paris.

### Transfer Patterns — microseconds, at CPU-months

Bast et al., ESA 2010
([PDF](http://ad-publications.informatik.uni-freiburg.de/ESA_transferpatterns_BCEGHRV_2010.pdf)),
the Google Maps lineage (five of seven authors were at Google Zürich; the survey
confirms it has been in Google Maps transit routing since 2010, and
[Google's 2016 post](https://research.google/blog/an-update-on-fast-transit-routing-with-transfer-patterns/)
cites 20,000+ cities). Precompute, per stop pair, the small set of transfer stop
sequences that can be optimal.

Preprocessing, in **core-hours**: Switzerland 635 h without hubs, 61 h with the
3-legs heuristic; New York 788 h; **North America 3,203 h ≈ 4 months on one core**.
Queries are 5 µs per constructed arc, 15 µs per evaluated arc, **under 10 ms**
station-to-station. The survey's Table 3 gives Germany, 90.4 M connections over
7 days: **541 hours of preprocessing for 0.4 ms queries**
([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140)).

Scalable Transfer Patterns
([ALENEX 2016](https://ad-publications.cs.uni-freiburg.de/ALENEX_scalable_tp_BHS_2016.pdf))
cuts Germany from **372 h / 140 GB to 16.5 h / 1,160 MB** (>20× time, >100× space,
still exact), with local queries at 0.1 ms and non-local Germany at 32 ms.

Even at 16.5 hours this is disqualified for us. **The whole premise of the
intervention machinery is that adding a transit stop or rerouting a line is a
scenario you evaluate in seconds to minutes.** Transfer Patterns is the wrong end
of the preprocessing/query trade for a simulator.

### Trip-Based routing — the middle ground

Witt, ESA 2015 ([arXiv:1504.07149](https://arxiv.org/abs/1504.07149)). Precompute
and prune the transfer relation between trips: London **121.3 M → 19.5 M transfers
(−84 %)**, Germany **1,826 M → 186 M (−90 %)**. Preprocessing **375 s sequential /
30 s on 16 threads** (London), **2,351 s / 220 s** (Germany). Queries: London
earliest-arrival **1.2 ms**, 24-hour profile 70.0 ms; Germany 40.8 ms / 301.7 ms.
Total space including all timetable data: **115.5 MiB London, 1,140.9 MiB
Germany**.

30 seconds of preprocessing for a city-sized feed *is* within our "seconds to
minutes" budget. This is the option to keep in reserve if CSA profile queries turn
out too slow.

### Batch / many-to-many, and the GPU question

**One-to-all is the right primitive, and it is nearly free.** ULTRA-PHAST
([ATMOS 2020](https://drops.dagstuhl.de/storage/01oasics/oasics-vol085-atmos2020/OASIcs.ATMOS.2020.1/OASIcs.ATMOS.2020.1.pdf)),
2× 8-core Xeon Gold 6144 @ 3.5 GHz: Switzerland (25,125 stops, 4.69 M stop events)
one-to-all-stops MCSA **42.3 ms**, UP-CSA 20.4 ms; to all 603,691 street vertices
208.2 → **29.2 ms** (7.1×). Germany to all 6.87 M vertices 4,331.8 → **605.8 ms**.
RAPTOR side: Switzerland all-stops MCR 109.7 → UP-RAPTOR **31.7 ms**.

**Batching across origins beats batching within a query.** For 70 sources × 70
destinations, one-to-many rRAPTOR beats repeated rRAPTOR by **98 %** (Switzerland
413,445 ms → 7,657 ms)
([Agarwal & Rambha, arXiv:2111.06654](https://arxiv.org/pdf/2111.06654); code at
[transnetlab/transit-routing](https://github.com/transnetlab/transit-routing),
MIT, Python). Combined with RAPTOR's 1.9×-on-6-cores intra-query ceiling, the rule
is unambiguous: **parallelise over origins, not inside a search.**

**The most on-point paper for this project is not in the routing canon.** Briem,
Buchhold, Sanders, Strasser & Wagner,
[SEA 2017](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SEA.2017.20),
build a CSA-based **Monte Carlo microsimulation of individual passengers on
greater Stuttgart**: **13,941 stops, 780,042 connections, 47,844 trips,
1,249,910 passengers**. At λ = 10 (12.5 M passenger simulations): **108.57 s
sequential, 65.57 s on 2 threads, 38.41 s on 4 threads**. The speedup is only
2.83× and they attribute it to memory bandwidth. VISUM on the same instance takes
**>30 minutes on 8 threads — about 50× slower**. ULTRA-Assignment
([arXiv:1909.08519](https://arxiv.org/pdf/1909.08519)) on the same Stuttgart
instance does **15 M unique journeys in under 17 s** on 16 cores. **This is our
workload, on our city, already implemented.**

**GPU transit:** there is no GPU RAPTOR and no GPU Trip-Based implementation in
the literature. The GPU work targets CSA, the vectorisable formulation:
[arXiv:1912.00966](https://arxiv.org/pdf/1912.00966) on a GTX 1080 Ti reports
London serial CSA **89.35 ms → 3.20 ms (27.9×)** and Switzerland 53.11 → 1.21
(43.9×), with a maximum claimed 59.09×. **Be skeptical**: the speedup is highly
data-dependent (Paris 39.4× but Madrid 3.77×), and a later paper shows **34–183×
on a single CPU** over the same datasets
([arXiv:2404.19422](https://arxiv.org/pdf/2404.19422)) — so much of the "GPU win"
is a weak serial baseline. Both RAPTOR and CSA are memory-bandwidth-bound, which
is a caution for GPU work generally and the reason CSA's flat array beats RAPTOR's
route scans as a kernel target.

### The libraries

- **Conveyal R5** ([conveyal/r5](https://github.com/conveyal/r5)) — **MIT**
  (verified from `LICENSE`), Java, 53.6 MB. Source confirms **range-RAPTOR** with
  `DEPARTURE_STEP_SEC = 60` plus **Monte Carlo randomised schedules** for
  frequency-based routes (`FastRaptorWorker.java`), ~1,000 draws per origin
  ([Conway et al. 2017](https://core.ac.uk/download/223242270.pdf)).
  **Caveat worth recording: Conway 2017 and 2018 contain no wall-clock benchmark
  at all** — anyone citing R5 timings to those papers is citing something that is
  not there. The real benchmark is Higgins et al.,
  [JTLU 15(1) 2022](https://www.jtlu.org/index.php/jtlu/article/view/2012/1628),
  Toronto, Xeon E7-8890 v3 (18c/36t): **1,000 × 1,000 OD in 9 s** with R5R against
  13 m 42 s for Python-OTP (~91×) and >24 h did-not-finish for R-OTP;
  **10,000 × 10,000 in 7 m 50 s**; 100,000 × 100,000 (10^10 pairs) in **18 h 15 m**,
  the only tool that finished. Network build 2 m 39 s.
- **OpenTripPlanner 2** — **LGPL-3.0-or-later**, not MIT
  ([LICENSE](https://raw.githubusercontent.com/opentripplanner/OpenTripPlanner/dev-2.x/LICENSE)).
  Multi-criteria range-RAPTOR
  ([Version-Comparison](https://docs.opentripplanner.org/en/latest/Version-Comparison/));
  the "10× faster" claim is really **5–10×** and its only source is an
  [Entur blog post](https://medium.com/entur/opentripplanner-2-0-is-here-67a3baeb0dc6),
  with the OTP docs declining to quantify. Entur production peaks at **>20
  requests/second**; memory runs `-Xmx8g` in the Docker docs to `-Xms18g -Xmx18g`
  for a national deployment. The OTP docs themselves say OTP1 "can be orders of
  magnitude slower (and more memory-intensive) than the approaches exemplified in
  R5".
- **MOTIS/nigiri** ([github.com/motis-project/nigiri](https://github.com/motis-project/nigiri))
  — MIT, C++, RAPTOR, data-oriented layout, powers Transitous.
- **SwissRailRaptor in MATSim** — **3 ms vs 273.5 ms for the standard MATSim PT
  router, a 90× gap**, with init 26 s / 0.6 GB against 584 s / 6.4 GB on a
  25,064-stop Swiss network
  ([STRC 2018](https://www.strc.ch/2018/Metrailler_Lieberherr.pdf)).

### What the current approximation costs

No paper tests exactly "nearest stop + fixed wait + fixed speed", but the
surrounding literature brackets it, and the bracket is wide:

- **Schedule versus observed vehicle movements.** Wessel & Farber,
  [JTLU 12(1) 2019](https://www.jtlu.org/index.php/jtlu/article/view/1502), four
  North American agencies, five days of reconstructed AVL: high-access zones
  converge on estimates **5–15 % lower than the schedule predicts**; low-access
  zones are far less reliable hour to hour; and the errors have **strong spatial
  patterns** — a problem when accessibility feeds a spatial model.
- **Schedule versus GPS.** Braga, Loureiro & Pereira,
  [JTG 2023](https://www.ipea.gov.br/acessooportunidades/en/publication/2023_jtg_public_transport_travel_time_inaccuracy_variability/)
  (Fortaleza, one month of GPS): scheduled GTFS **underestimates accessibility by
  1.5 % on average but diverges by over 40 % in some areas**; travel-time
  *variability* has a **50 % average impact** on accessibility estimates and
  **raises accessibility inequality by 30 %**, concentrated in low-income areas.
- **Departure-time sampling.** Stępniak, Pritchard, Geurs & Goliszek,
  [JTG 75:8–24 (2019)](https://research.utwente.nl/en/publications/the-impact-of-temporal-resolution-on-public-transport-accessibili/)
  (Szczecin): sampling every **5 minutes instead of every 1 minute is a negligible
  precision loss for a 5× computation saving**, and **15 minutes** is the
  recommended balance, with Gini errors ≤ 0.001. This bounds how coarsely a
  simulation may sample departure times — coarser than one might fear.
- **Spatial/temporal detail.** Cui, Grisé, Stewart & El-Geneidy,
  [Transport Findings 2019](https://doi.org/10.32866/9736) (Montreal, Conveyal):
  differences between a detailed grid + 7–9 am measure and a conventional tract +
  static one are "minimal" in the core and larger at the periphery; mode-share
  model R² moves **0.785 → 0.795, a 1.3 % relative improvement**, with **no
  improvement at all** for commute duration.
- **Practice.** Access Across America
  ([CTS 14-12](https://cts-d10resmod-prd.oit.umn.edu/pdf/cts-14-12.pdf)) uses the
  **15th-percentile travel time across every minute from 7–9 am** rather than a
  single departure — an implicit admission that a fixed wait is not defensible.
- And see §5: Euclidean versus network distance correlates at 0.9416 by car and
  0.9719 on foot, but only **0.7711 for public transit**, over ~197 M computed
  distances in Montreal
  ([PMC5568316](https://pmc.ncbi.nlm.nih.gov/articles/PMC5568316/)). **Transit is
  the mode where geometric approximation fails hardest.**

Net: our fixed-headway proxy is probably within **±10–15 % of a schedule-based
measure in well-served areas** and off by **40 % or more in peripheral and
infrequent-service zones** — and those errors are **spatially systematic**, i.e.
exactly where policy conclusions are most sensitive. The repo's own numbers make
this concrete: a 5-minute wait is close to right on the Broadway trunk (measured
mean headways of 2.3–2.4 min on routes 8/9/99 and the Expo Line) and badly wrong
for the 48 Mount Pleasant stops at 12–30 minute headways and the 11 with no
weekday service at all.

**Two fixes, in order.** First, a **headway-aware wait** — `0.5 × headway`, which
`city.intake.gtfs` already computes per stop — is hours of work and captures most
of the error. Second, **CSA**: a full day of connections is 10–14 MB, the sort is
sub-second, a one-to-all query on a larger network than ours is ~3 ms, and it has
**zero preprocessing**, which is the only property compatible with interventions
that add stops or reroute lines. Briem et al. have already run this exact
computation on greater Stuttgart for 1.25 M passengers in 38 seconds on four
cores.

---

## 5. Approximations that preserve aggregate fidelity

This section is the one that decides how much routing we actually need. The
answer turns out to depend sharply on the *functional form* of the destination
kernel, and the repo uses two different forms.

### Detour factors: the literature

Network/straight-line ratio ("circuity") for driving clusters at **1.2–1.4**, but
the spread within a single metro is as large as the spread between metros.

- Levinson & El-Geneidy, *Reg Sci Urban Econ* 39(6), on 5,000 home–work pairs each
  in the Twin Cities and Portland
  ([full text](https://tram.mcgill.ca/Research/Publications/txt/Circuity_Levinson_Geneidy.pdf.txt)):
  actual commute circuity **1.18 / 1.19**; random OD pairs 1.22. The distance-band
  decomposition is the number that matters for us: circuity is **1.58 at ≤5 km**,
  1.42 (5–10 km), 1.34 (10–15), 1.30 (15–20), falling to **1.20 at ≥45 km**. Their
  OLS model of circuity on network attributes reaches only **R² = 0.11 on
  N = 10,000** — circuity is mostly *not* predictable from network descriptors.
- Boeing, simulating **4 million routes across 40 US cities** with OSMnx
  ([arXiv:1708.00836](https://arxiv.org/pdf/1708.00836), Table 1): mean driving
  circuity from **1.177 (Dallas)**, 1.194 (Chicago), 1.209 (Manhattan) to
  **1.470–1.523** in curvilinear suburbs (Walnut Creek, Salem MA, Redmond WA,
  Sugar Land TX). **A single global constant is wrong by ±25 % across
  neighbourhood types.**
- Boscoe, Henry & Zdeb, *The Professional Geographer* 64(2), >66,000 US locations
  ([abstract](https://www.tandfonline.com/doi/abs/10.1080/00330124.2011.583586)):
  nationwide distance index **1.417**, straight-line vs driving **r² > 0.90**.
  (The regression table is paywalled; only these two figures are confirmed.)
- Corroborating: **1.324** over 25 Chinese cities
  ([Annals of GIS 27(4)](https://www.tandfonline.com/doi/full/10.1080/19475683.2021.1966503));
  **1.343** radial detour over 300 European cities
  ([Mennicken, Lemoy & Caruso, EPB 51(1):174–194](https://journals.sagepub.com/doi/10.1177/23998083231168870)).
- A better functional form than a scalar: fitting a **Minkowski p-norm** on 2,445
  Calgary cases over 2,138 postal codes gives **p = 1.54 for road distance,
  p = 1.31 for travel time**, cutting mean error from Euclidean's 2.45 km to
  **1.37 km** ([PMC2781002](https://pmc.ncbi.nlm.nih.gov/articles/PMC2781002/)).

### Detour factor measured on our own graph

400 random node pairs on the loaded Stuttgart graph, crow-flight separation
300 m – 8 km, ratio of A\* network distance to haversine *(measured here)*:

| statistic | value |
|---|---|
| mean | **1.227** |
| p10 | 1.118 |
| median | 1.204 |
| p90 | 1.344 |
| p99 | 1.781 |
| max | 2.484 |

A second sample, 40 random origins × 200 candidate targets at 100 m – 5 km
(the destination-choice geometry rather than the trip geometry), gives mean
**1.296**, median 1.248, p95 **1.601** *(measured here)*. Both brackets sit inside
the published 1.18–1.52 range and closest to Boeing's mid-range cities. **The mean
is not the problem; the p90/median ratio of 1.12 and the 2.48 maximum are.**

### Distance-to-time regression

Hu & Wang's national ZIP-to-ZIP drive-time matrix covers 32,478 ZIP codes
([arXiv:2006.14138](https://arxiv.org/pdf/2006.14138), Table 4). Regressing Google
drive times on estimates:

| predictor | short range (N=11,684) | mid (N=11,365) | long (N=101,301) |
|---|---|---|---|
| detailed-network drive time | R² = 0.91 | 0.93 | 0.96 |
| network distance | R² = 0.95 | 0.93 | 0.99 |
| **geodesic distance alone** | **R² = 0.78** | **0.74** | — |

So straight-line distance alone explains **74–78 % of drive-time variance at short
and medium range**, and the crude predictor *improves* with trip length. Montreal
CMA correlations over ~197 million computed distances (904 tracts, 6,167 DAs,
27,126 blocks, 535 facilities): Euclidean vs shortest network **0.9416 by car,
0.9719 on foot, 0.9851 Manhattan — and only 0.7711 for public transit**
([PMC5568316](https://pmc.ncbi.nlm.nih.gov/articles/PMC5568316/)). **Transit is
where the Euclidean approximation collapses**, which matters because our transit
mode is itself already an approximation (§4).

### How the error propagates into destination choice — the structural result

For a Huff/gravity share with **power** deterrence, `P_ij ∝ S_j^α · c_ij^−β / Σ_k`,
multiplying every cost by a common factor k makes `k^−β` cancel between numerator
and denominator: **the predicted shares are exactly unchanged.** With
**exponential** deterrence `exp(−c/λ)` it does not cancel. So the mean detour
factor is irrelevant to a power kernel and relevant to an exponential one; what
hurts a power kernel is only the *residual dispersion* of circuity across OD
pairs.

The repo uses both. `day/default-venue-kernels`:

- `:retail` and `:food` — **`:power`, α = 1.0, β = 2.0, d₀ = 500 m, K = 256**. These
  are the calibrated classes, fitted against Stuttgart's retail-centrality census
  and Vancouver's pedestrian counts.
- everything else (`:school`, `:clinic`, `:outdoors`, `:sports`, `:culture`,
  `:worship`) — **`:exp`, λ = 400 m, K = 16**; `:other-home`, `:street`,
  `:business` — `:exp`, λ = 1500 m.

Elasticity arithmetic for the exponential form: a relative cost error ε gives a
log-flow error of `(c/λ)·ε`. Calibrated exponential β for commuting is around
**0.07 per km** ([Lenormand et al., arXiv:1506.04889](https://arxiv.org/pdf/1506.04889)),
so at a 15 km commute a 10 % impedance error is a ~10 % flow error, and at 40 km
~24 %. For the power form with β = 2, a 10 % *differential* cost error gives
1.1^−2 = 0.826, a 17.4 % weight error — but only to the extent it is differential.

Worth noting against the textbook: **Huff β is usually far below 2 in fitted
work.** ArcGIS documents a default of 2 with published ranges ~1.5–2
([Esri](https://pro.arcgis.com/en/pro-app/3.5/tool-reference/business-analyst/understanding-huff-model.htm)),
but Liang et al., *Transactions in GIS* 24:687–702, calibrating against SafeGraph
store visits for 3 brands in 10 US cities by particle-swarm optimisation
([PDF](https://geography.wisc.edu/wp-content/uploads/sites/28/2022/05/2020_TGIS_DynamicHuffModel.pdf))
find **β mostly 0.4–1.0** — Whole Foods β = 0.80 (LA), 0.91 (Houston), 0.60
(Chicago), **0.44 (New York)**, 1.58 (Phoenix) — with best observed-share
correlation 0.890. A β near 0.8 rather than 2 halves sensitivity to impedance
error. Our β = 2 was fitted here and should stay, but it means we sit at the
*sensitive* end of the published range.

### How much the crow-flight substitution actually costs us — measured

The right measure is not the distance error but the **total variation distance
between the choice-probability distribution the kernel produces on crow-flight
distances and the one it produces on true network distances**, over the same
candidate set. 40 random origins on the Stuttgart graph, 200 candidates each at
100 m – 5 km, exact Dijkstra for the network distances *(measured here)*:

| kernel | form | TVD (crow vs network) | TVD after scaling crow by the fitted 1.281 | TVD after a per-origin factor from 8 probe routes |
|---|---|---|---|---|
| `:retail` / `:food` | power, β = 2, d₀ = 500 | **0.084** | 0.091 (**worse**) | — |
| λ = 400 m | exponential | **0.199** | 0.172 | 0.168 |
| λ = 800 m | exponential | 0.147 | 0.122 | 0.124 |
| λ = 1200 m | exponential | 0.112 | 0.093 | 0.093 |
| λ = 2000 m | exponential | 0.074 | — | — |

Choice-set overlap under the power kernel: **top-16 13.75 / 16 (86 %), top-64
59.4 / 64 (93 %)** *(measured here)*.

Four conclusions, and they are not the ones I expected:

1. **The calibrated retail/food kernel is the least damaged.** TVD 0.084 — about
   8 % of choice probability mass misallocated. That is the power form's scale
   invariance doing exactly what the algebra says it should.
2. **Applying a detour factor to a power kernel makes it worse** (0.084 → 0.091),
   because the factor cancels analytically and only injects the noise of an
   imperfect estimate. Do not "fix" the retail kernel with a circuity constant.
3. **The exponential classes are damaged 2.4× more** (TVD 0.199 at λ = 400 m), and
   the damage rises as λ falls, i.e. the sharper the kernel the worse the crow
   flight. These are the neighbourhood classes — school, clinic, park — where
   a river, a rail cut or a motorway is exactly the thing crow flight cannot see.
4. **A calibrated detour factor barely helps, and a per-origin calibration helps no
   more than a global one** (0.199 → 0.172 → 0.168). The error is **idiosyncratic
   per OD pair, not a scale error.** This is the direct, local refutation of the
   "distance-to-time regression" option: there is no regression on crow flight
   that recovers what the barriers do, which is the same thing Levinson &
   El-Geneidy's R² = 0.11 says at metro scale.

### Landmark lower bounds (ALT), quantified

Goldberg & Harrelson, SODA 2005
([PDF](https://www.cs.princeton.edu/courses/archive/spr06/cos423/Handouts/GH05.pdf)):

- **Bound tightness, Table 8**, Bay Area network M2 (330,024 vertices / 793,681
  arcs — within 40 % of Vancouver), 16 landmarks: the lower bound is **96.0 % of
  the true distance (sd 4.5) for random OD pairs and 89.4 % (sd 9.97) for local
  (BFS-50) pairs**. On a random graph it collapses to 28.5 % — this is a road-
  network property, not a general one.
- **Speedup**, M11 (6,687,940 vertices / 15,561,631 arcs), random OD: Dijkstra
  2,113.80 ms, best ALT variant **133.29 ms — ~16× wall clock, ~50× fewer scans**.
- **The key negative result: A\* with *Euclidean* bounds took 4,693.30 ms, 2.2×
  *slower* than plain Dijkstra.** Geometric bounds are worthless on road networks
  under a time metric. (Ours is a distance metric, where the haversine heuristic
  is at least admissible and useful — but the 89–96 % landmark figure is the ceiling
  a geometric bound cannot reach.)
- Returns are sub-linear in landmark count on M11: 1 landmark 0.20 % efficiency,
  4 → 0.67 %, 8 → 1.17 %, 16 → 1.81 %.
- Cost: 2 × 4 B per node per landmark = **128 B/node at 16 landmarks**, i.e. 54.9 MB
  for Stuttgart, 29.7 MB for Vancouver.

### Zonal aggregation and cell snapping

- **Population-weighted rather than geometric centroids is free accuracy.**
  Mazovia, Poland, 27,632 inhabited 1 km grid points aggregated to 300 LAU-2
  units: extra-zonal travel-time **RMSE 2.625 min with population-weighted
  centroids vs 3.540 min with geometric** — a **26 % error reduction**
  ([PMC5637883](https://pmc.ncbi.nlm.nih.gov/articles/PMC5637883/)). Intra-zonal
  MAPE with the classic "½ radius at constant speed" rule was 0.191 at LAU-2,
  improved to 0.093 by a population-weighted intra-zonal distance.
- Montreal: census-tract centroid vs land-use-adjusted block gives mean Euclidean
  error **236 m (p90 649 m, p95 1.1 km)** and mean walk-time error **4.17 min
  (p90 10.22, p95 17 min)** ([PMC5568316](https://pmc.ncbi.nlm.nih.gov/articles/PMC5568316/)).
- ZIP-centroid study, N = 1,998/242 ZIPs (NH) and 3,016/319 (AZ): MAE **5.2 min for
  population centroid vs 21.1 min for geometric centroid in Arizona**; urban MAE
  2.1–4.0 min vs rural 5.6–23.6 min — and every method still correlated > 0.9 with
  truth ([PMC2683820](https://pmc.ncbi.nlm.nih.gov/articles/PMC2683820)). **High
  correlation coexisting with 20-minute errors is the cautionary tale for anyone
  quoting a correlation as validation.**
- **Our 100 m cells are already below the input noise.** Commercial geocoders show
  mean positional errors of **50–300 m** with vendor-to-vendor differences of
  **228–1,809 m** ([PMC1557664](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1557664/)).
  Caching a distance per (origin-cell, destination-cell) pair at 100 m costs
  essentially nothing in fidelity.
- Prior art for the snapping correction: the Helsinki Travel Time Matrix uses a
  **250 m grid**, snaps cell centroids to the walk network with a maximum snap of
  half a cell diagonal, and adds the walk time for that linear distance
  ([Sci Data 11, 2024](https://www.nature.com/articles/s41597-024-03689-z)). Hu &
  Wang's national matrix uses a **3-level hierarchy** — all-road for short pairs,
  highway-only for medium, geodesic for long — with per-level regression
  correction and intrazonal times fitted from zone perimeter and area on a 1 %
  sample ([arXiv:2006.14138](https://arxiv.org/pdf/2006.14138)).

### Hierarchical / coarse-grained routing: route to district centroids plus local

The classic four-step approach. The literature on aggregation bias is
discouraging about doing it *instead of* real routing: Chang, Khatib & Ou, *Env &
Plan B* 29:37–52, tested **11 zone systems at 3 scales in Idaho** and found smaller
TAZs give shorter trip lengths, more interzonal trips, and lower %RMSE against
ground counts ([SAGE](https://journals.sagepub.com/doi/10.1068/b2742)); Nix
estimated mode-choice logits over 8 Montreal zone systems and found ρ² moving
0.945 → 0.893 across zone structures while the distance-to-CBD coefficient stayed
stable at −0.092 vs −0.091
([CTRF](https://ctrf.ca/wp-content/uploads/2014/07/SeanNix2008.pdf)) — **fit
degrades more than coefficients do**; and *Spatial Aggregation Issues in Traffic
Assignment Models* (NETS 2020,
[Springer](https://link.springer.com/article/10.1007/s11067-020-09505-6))
concludes that adding intrazonal demand is **not** sufficient to remove
aggregation bias. Average within-TAZ auto commute in Cleveland is **11.3 minutes**
([arXiv:2006.14138](https://arxiv.org/pdf/2006.14138)) — omitting intrazonal time
is a large relative error on exactly the short trips that dominate a city sim.

Given that CH-family routing costs ~1 µs per OD pair at our graph size (§2), a
two-level centroid approximation buys nothing worth its bias. **Skip it.**

### How large is the distance-metric effect, in the published record?

Honest summary: **no paper states flatly "using straight-line instead of network
distance changes destination-choice results by X %."** The two sides of the
literature are:

- *It barely matters.* A variance decomposition over accessibility measure ×
  distance type × aggregation method in Montreal attributes **3–6 % of output
  variance to distance type, <1 % to aggregation method, and 74–86 % to the choice
  of accessibility measure** ([PMC5568316](https://pmc.ncbi.nlm.nih.gov/articles/PMC5568316/)).
  In Shenzhen, Gaussian-2SFCA park accessibility over 630 communities correlates
  at **0.986 (Euclidean vs walking), 0.985 (cycling), 0.981 (driving)**, though
  Euclidean systematically overestimates accessibility
  ([PMC6466280](https://pmc.ncbi.nlm.nih.gov/articles/PMC6466280/)).
- *It matters.* Buczkowska, Coulombel & de Lapparent, *Networks and Spatial
  Economics* 19:451–490
  ([Springer](https://link.springer.com/article/10.1007/s11067-018-9439-5)), testing
  seven impedance measures in firm location choice for Greater Paris, find a
  *mixture* of metrics significantly outperforms any single one and conclude
  Euclidean distance is inadequate for spatial spillovers. Of **346 impedance
  specifications** in a systematic review of gravity-based healthcare access,
  **72 % used network travel time, 16 % network distance, 12 % Euclidean**
  ([PMC10693160](https://pmc.ncbi.nlm.nih.gov/articles/PMC10693160/)).

Be suspicious of the 0.98 correlations: they are computed over full metro ranges
where the signal is dominated by near-versus-far, and they coexist with the
20-minute individual errors above. **Our own TVD numbers (0.084 power / 0.199
exponential) are the better estimate for this model, because they are measured on
this graph with this kernel.**

### Approximate distance oracles with stretch guarantees

Kontogiannis, Wagner & Zaroliagis, *Engineering Oracles for Time-Dependent Road
Networks* ([arXiv:1511.08303](https://arxiv.org/pdf/1511.08303)): on Berlin,
average query **81–83 µs**, >1,146× over time-dependent Dijkstra, with **worst-case
observed stretch < 0.771 %**; on Germany (4.6 M vertices / 11.18 M arcs), average
query 1.269 ms, >902×, **worst-case stretch < 1.534 %**. The pattern is that
*observed* stretch runs an order of magnitude below the guaranteed ε — and **under
1.5 %, which is an order of magnitude tighter than any geometric approximation.**
Thorup–Zwick-style (2k−1)-stretch oracles are surveyed in
[Sommer, *ACM Computing Surveys* 46(4)](https://dl.acm.org/doi/10.1145/2530531)
and are not competitive on road networks, where exact hierarchical methods already
reach sub-microsecond queries.

**The summary of this section:** every approximation on offer is *worse* than just
doing the routing, because at our graph size the routing costs about a microsecond
per pair. The approximations are worth knowing about only as the fallback if the
CCH work does not happen — and in that case the one to keep is the crow-flight
power kernel for retail/food (TVD 0.084), the one to replace first is the
λ = 400 m exponential classes (TVD 0.199), and the one **not** to bother with is a
fitted detour factor.


---

## 6. Open source implementations worth borrowing from

| project | license | language | size | algorithms | matrix API | fast re-weighting |
|---|---|---|---|---|---|---|
| **RoutingKit** | **BSD-2-Clause** | C++11 | **21,281 LOC**, 1.4 MB checked out | CH, **CCH**, nested dissection (InertialFlow/FlowCutter), OSM parsing | `pin_sources`/`pin_targets` on both CH and CCH | **yes — CCH customization + partial single-arc updates** |
| OSRM | BSD-2-Clause | C++ | 52.5 MB | CH and MLD (≈CRP) | `/table`, default `--max-table-size 100` | `osrm-customize`, "hours to seconds" |
| GraphHopper | Apache-2.0 | **Java** | 143 MB, 62,847 LOC core | CH, LM (landmarks), flexible | **not in OSS** — commercial Directions API | custom models in hybrid mode |
| Valhalla | MIT | C++ | 130 MB | tiled hierarchical, **no CH** — dynamic costing plugins | `sources_to_targets`, `max_locations: 100` | costing is runtime by design |
| pgRouting | GPL-2.0 | C/C++ in Postgres | 782 MB | Dijkstra, A\*, `pgr_dijkstraCostMatrix`, CH (**experimental**) | `pgr_dijkstraCostMatrix` | no |
| cuGraph | Apache-2.0 | CUDA/C++/Python | 65.6 MB | BFS, SSSP (multi-GPU), PageRank, Louvain… **no CH, no routing** | no | n/a |
| Gunrock | Apache-2.0 | CUDA/C++ | 78.6 MB | BFS, SSSP, frontier primitives | no | n/a |
| MATSim | GPL | **Java** | 1.69 GB | `SpeedyALT` (A\* + 16 landmarks), `MultiNodePathCalculator` | one-to-many via multi-node | landmarks survive re-weighting |
| Conveyal R5 | **MIT** | **Java** | 53.6 MB | RAPTOR-family, built for many-to-many accessibility | **yes, it is the point of the library** | no preprocessing to invalidate |
| OpenTripPlanner 2 | LGPL-3.0-or-later | Java | 234 MB | multi-criteria Range RAPTOR | — | — |
| `fast_paths` | Apache-2.0 OR MIT | Rust | 1.4 MB | classic CH, **32-bit WASM target** | multi-source/target | order reuse only |
| JGraphT | EPL-2.0 / LGPL-2.1 | **Java** | — | `ContractionHierarchyPrecomputation`, `CHManyToManyShortestPaths`, `TransitNodeRoutingShortestPath` | yes | no |

### RoutingKit — the one to actually read

[github.com/RoutingKit/RoutingKit](https://github.com/RoutingKit/RoutingKit),
BSD-2-Clause, C++11, no build system beyond a Makefile and no dependencies except
zlib (plus optional protobuf for OSM PBF). The parts that matter are small:
`src/customizable_contraction_hierarchy.cpp` **1,920 LOC** plus a 180-line header,
`src/contraction_hierarchy.cpp` **2,217 LOC**, `src/nested_dissection.cpp` 883 LOC.
**About 4,100 lines is the whole of what we would port.**

What it gives us directly:

- **OSM in, graph out.** `simple_load_osm_car_routing_graph_from_pbf` produces
  `first_out / head / travel_time / latitude / longitude` — a CSR, the same shape
  `network/build` already produces — plus `GeoPositionToNode` for snapping, which
  replaces our uniform grid index. Pedestrian and bicycle profiles are in
  `src/osm_profile.cpp` (858 LOC).
- **Many-to-many is first class on both CH and CCH**: `pin_targets(...)` /
  `pin_sources(...)` then `run_to_pinned_targets()` /
  `get_distances_to_targets(unsigned*)`. The docs state the design trade-off
  explicitly — "a design goal was to not use more memory per query object than was
  needed to answer one-to-one queries" — so it is a pinned-bucket scheme rather
  than a full RPHAST matrix engine
  ([CH doc](https://github.com/RoutingKit/RoutingKit/blob/master/doc/ContractionHierarchy.md),
  [CCH doc](https://github.com/RoutingKit/RoutingKit/blob/master/doc/CustomizableContractionHierarchy.md)).
- **Secondary metrics for free.** `ContractionHierarchyExtraWeight<T>` carries e.g.
  distance along a time-optimal path without a second search. If we ever split the
  single metric into per-mode metrics, this is how to keep one search.
- **`CustomizableContractionHierarchyPartialCustomization`** — incremental
  single-arc weight updates. This is the road-closure primitive.

It also ships `build_contraction_hierarchy_using_perfect_witness_search()`, which
produces a *real* CH from a CCH "significantly faster than
`ContractionHierarchy::build`" — i.e. you can get CH query speed with CCH
preprocessing economics.

**No Java binding exists.** Wrappers are Go
([nextmv-io/go-routingkit](https://github.com/nextmv-io/go-routingkit),
BSD-2-Clause), Rust/Python
([HellOwhatAs/routingkit-cch](https://github.com/hellowhatas/routingkit-cch)) and
Swift; a WASM build exists as prior art
([stprnvsh/routingkit-wasm](https://github.com/stprnvsh/routingkit-wasm)). From
Clojure the route is **Panama/FFM (`java.lang.foreign`, JDK 22+)** over a thin C
shim; the API surface we need is about eight functions.

The KIT city-scale numbers, Intel Xeon E5-2670, Stuttgart 110 k vertices /
252 k edges *with production turn costs*
([CCH survey Tables 1–3](https://arxiv.org/pdf/2502.10519)):

| | Stuttgart (110 k v) | Europe (18 M v) |
|---|---|---|
| metric-independent preprocessing | **0.9 s** | 361.1 s |
| customization, 1 thread | **49.13 ms** | 10.76 s |
| customization, 8 threads | **11.67 ms** (speedup saturates at 4.2× — the graph is too small to scale further) | 1.25 s (16 threads) |
| elimination-tree distance query, basic | **22.9 µs** | 300.2 µs |
| elimination-tree distance query, perfect customization | **14.5 µs** | 137.5 µs |

The survey's own warning is worth repeating: Stuttgart "is a city network that is
much less hierarchical" than a continental graph, so **CH-family speedups shrink
at city scale**. 14.5–22.9 µs, not 0.1 µs, is the honest per-query expectation
before batching — and the Buchhold traffic-assignment work shows batching and AVX
take it to ~0.38 µs.

### GraphHopper — the zero-FFI JVM fallback

Apache-2.0, on Maven Central as `com.graphhopper:graphhopper-core`
([README](https://github.com/graphhopper/graphhopper/blob/master/README.md)) — the
only entry on this list you can add to `deps.edn` and call from Clojure with no
native code. Three modes: **speed (CH)**, **hybrid (LM — landmarks, "an order of
magnitude faster than the flexible mode", allows per-request custom models)**, and
flexible (plain Dijkstra/A\*). Landmark machinery is in
`core/src/main/java/com/graphhopper/routing/lm/`, and — usefully for isochrones
and reachability fields — `ShortestPathTree.java` (the SPT engine) **is in the
open-source core**.

Planet-scale numbers from their own blog
([link](https://www.graphhopper.com/blog/2022/06/27/host-your-own-worldwide-route-calculator-with-graphhopper/)):
base graph import ~1.5 h planet / ~1 h Europe, base graph 33 GB, **CH preparation
25 h for car, LM preparation 3.5 h for car**, `-Xmx120g` for planet CH. At city
scale those are seconds. The catch: **the Matrix API is commercial, not in the OSS
core** ([docs](https://docs.graphhopper.com/openapi/matrices)); the community
workaround is the Apache-2.0 fork
[StuartApp/graphhopper-matrix](https://github.com/StuartApp/graphhopper-matrix).

### MATSim — the closest comparable workload, and the bar to clear

GPL, Java. The router is `org.matsim.core.router.speedy.SpeedyALT`, "a very fast
implementation of the ALT algorithm … using a typical value of 16 landmarks",
with all landmark values for a vertex adjacent in memory so one cache line loads
them all
([doxygen](https://www.matsim.org/doxygen/classorg_1_1matsim_1_1core_1_1router_1_1speedy_1_1_speedy_a_l_t.html));
`SpeedyGraph` is a flat CSR array graph. **No CH and no CCH** — precisely because
per-iteration congestion feedback re-weights the graph, which classic CH cannot
absorb. That is the argument for CCH stated by omission.

Wall clock: the Open Berlin Scenario network is **73,689 nodes / 159,039 car-only
links** run as a 10 % sample of ~5.7 M adults
([VSP working paper](https://svn.vsp.tu-berlin.de/repos/public-svn/publications/vspwp/2019/19-01/ZiemkeEtAl2019OpenBerlinScenarioVSPWP.pdf)).
Buchhold & Wagner state for that 10 % scenario with demand-responsive transport
enabled: **"one iteration takes more than four hours, performing 500 is not
feasible"** ([arXiv:2011.02601](https://arxiv.org/pdf/2011.02601), §5). The classic
full-Switzerland benchmark is **2.3 M agents, ~7.1 M trips, 36 hours**
(Balmer et al. 2009). On the *same* Berlin network their CH/bucket engine resolves
a ride request in **624–700 µs** against MATSim's **13.75–19.29 ms** — a **~25×
gap**, on 2× Xeon Gold 6144 @ 3.5 GHz, single-core implementations both sides.

**Read that as the bar.** The world's most-used agent-based transport simulator
routes 10 % of Berlin in hours per iteration with an ALT router. We are proposing
to route 100 % of Stuttgart in seconds with a CCH one, and the traffic-assignment
paper (§2) already demonstrates exactly that on exactly this graph size.

### Conveyal R5 and OpenTripPlanner — the transit side

Covered in detail in §4; the short version. **R5** is MIT, Java, 53.6 MB, and
built for exactly our shape — many-to-many travel-time matrices, range-RAPTOR
with Monte Carlo schedule sampling for frequency routes. Its real benchmark is
Higgins et al., [JTLU 15(1) 2022](https://www.jtlu.org/index.php/jtlu/article/view/2012/1628)
(Toronto, Xeon E7-8890 v3): **1,000 × 1,000 OD in 9 s**, 10,000 × 10,000 in
**7 m 50 s**, and 100,000 × 100,000 in 18 h 15 m — the only tool of five tested
that finished. Note that the Conway 2017/2018 R5 papers, commonly cited for R5
performance, **contain no wall-clock benchmarks at all**.

**OpenTripPlanner 2** is **LGPL-3.0-or-later, not MIT** — a material difference
for embedding. Multi-criteria range-RAPTOR; the "5–10× faster than OTP1" claim
traces only to an [Entur blog post](https://medium.com/entur/opentripplanner-2-0-is-here-67a3baeb0dc6),
and the isochrone feature was removed in v2.0.

### GPU libraries: not for this

cuGraph (Apache-2.0) has SSSP and BFS but **no A\*, no CH, no road-network
routing of any kind** ([algorithm list](https://docs.nvidia.com/cugraph/latest/graph_support/algorithms/)),
and its SSSP exposes **no Δ parameter** to tune for high-diameter graphs. Gunrock
(Apache-2.0) is 11 s for one SSSP on roadnet-USA (§3). Both are the wrong tool;
the GPU idea that works is PHAST-style batched CH sweeps, which neither
implements.

### Rust CCH ports — prior art for a WGSL rewrite

[Rodeapps/cch](https://github.com/Rodeapps/cch/tree/main) (MIT) claims
bit-identical results to RoutingKit with no C++/FFI and publishes Albania
(~6.29 M nodes) customization at **366.87 ms single-threaded / 80.7 ms on 18
threads**; its `distance_matrix` number (576×576 in 12.9 ms) is on a 24×24
synthetic grid and tells us nothing about road networks.
[wmsnp/cch-rs](https://github.com/wmsnp/cch-rs) adds built-in partitioning and
incremental updates. Both are unvetted and low-star, but they are the shortest
path to a `wgpu`-based implementation, since
[gfx-rs/wgpu](https://github.com/gfx-rs/wgpu) compiles the same WGSL native and to
WASM/WebGPU.

### The baseline nobody should use

NetworkX is "around 10 times slower than the slowest library" across tasks; SSSP
on Pokec took **67 s versus 6.8 s for networkit**
([benchmark](https://www.timlrx.com/blog/benchmark-of-popular-graph-network-packages/)).
pyrosm defaults to iGraph output precisely because NetworkX "tends to use quite a
lot of memory and is relatively slow with large networks"
([docs](https://pyrosm.readthedocs.io/en/latest/graphs.html)). Fine for data prep,
never for the loop.

---

## 7. Recommendation

### The one number that decides it

Buchhold, Sanders & Wagner computed **20.1 million shortest paths on metropolitan
Stuttgart (134,663 vertices / 307,759 edges), re-customizing the whole hierarchy
six times along the way, in 7.67 seconds on four cores of a 2015 Xeon**
([LIPIcs.SEA.2018.27](https://drops.dagstuhl.de/storage/00lipics/lipics-vol103-sea2018/LIPIcs.SEA.2018.27/LIPIcs.SEA.2018.27.pdf),
Table 3). Our graphs are 232 k and 429 k vertices, and our workload is 2.5 M
queries. **The target — a full day in seconds — has already been demonstrated on
this exact graph size with this exact query count, on a CPU, eight years ago.**

The corollary is uncomfortable and should be said plainly: **the GPU is not on the
critical path.** Nothing in the daily impedance workload needs it. It is worth
building for the *ultimate* goal of the whole simulation as WGSL kernels, and
because PHAST-style sweeps genuinely do run 5–20× faster on a GPU (§2), but
routing should not be the reason.

### (a) Daily many-to-many impedance — **CCH with pinned targets / bucket queries**

Ranked:

1. **CCH (RoutingKit) with `pin_targets` per venue class, re-customized per
   scenario.** Preprocessing is metric-independent and, at 110 k vertices with
   turn costs, takes **0.9 s**; customization is **49 ms single-threaded / 11.7 ms
   on 8 threads** ([arXiv:2502.10519](https://arxiv.org/pdf/2502.10519)).
   Elimination-tree queries are **14.5–22.9 µs** un-batched at that size, and
   ~0.38 µs with the AVX-batched centralized search. For our K = 256 retail
   candidate set over 33,368 cells that is 8.5 M distances — **single-digit
   seconds on one core, sub-second on four.**
   *Trade-off:* a C++ dependency reached through Panama/FFM, and CCH queries are
   ~1.5× a classic CH query.
2. **Classic CH, rebuilt per scenario.** Build is "less than one second" on a
   73 k-node Berlin graph and 4–6 s on a 394 k-node Rhine-Ruhr graph
   ([arXiv:2011.02601](https://arxiv.org/pdf/2011.02601)), so even a full rebuild
   is affordable at our size. Queries are ~1.5× faster than CCH.
   *Trade-off:* our metric is *distance*, which is CH's bad case — Europe
   preprocessing goes 451 s → 2,853 s switching time to distance
   ([arXiv:1402.0402](https://arxiv.org/abs/1402.0402)) — and the whole point of
   the intervention machinery is that the graph changes. Pick this only if the
   CCH nested-dissection ordering turns out to be a problem to get right.
3. **RPHAST per origin cell.** 10.4 ns per matrix entry on Europe
   ([ATMOS 2011](https://drops.dagstuhl.de/storage/01oasics/oasics-vol020-atmos2011/OASIcs.ATMOS.2011.52/OASIcs.ATMOS.2011.52.pdf)),
   and our candidate sets (192–256) are comfortably above the ~25-target
   crossover. *Trade-off:* the target set is spread over the whole city, not a
   ball, which is RPHAST's weak case (selection 1.8 → 27.5 ms as |B| grows from
   2^14 to 2^20).
4. **Bucket-CH many-to-many.** 10,000 × 10,000 in 67 s on a continental graph
   ([Knopp et al.](https://turing.iem.thm.de/routeplanning/hwy/distTable.pdf)),
   and the venue set *is* fixed within a day, so selection amortises. *Trade-off:*
   selection "goes into the minutes" for large target sets
   ([arXiv:2103.10359](https://arxiv.org/pdf/2103.10359)) — an offline tool, not
   an interactive one.
5. **Keep crow flight for `:retail` and `:food` only.** The measured TVD is 0.084
   *(measured here)* and the power kernel's scale invariance is why. Do **not**
   keep it for the λ = 400 m exponential classes at TVD 0.199.

**Concretely: do not build the 35k × 25k matrix.** It is 3.5 GB at u32, 26× the
WebGPU storage-binding default. Build **33,368 cells × K** per venue class
(K = 256 for retail/food, 16 for the rest) — **26.9 MB at u32 for the largest
class**, which fits a single binding.

### (b) Commute paths that repeat — **precompute once per scenario, cache the distance, not the path**

500,000 home→work pairs that do not change day to day. At ~0.38 µs/pair batched
this is **0.2 seconds**; at the un-batched 22.9 µs it is 11.5 seconds. Either way
it is a one-off at scenario setup, stored as 500,000 × u32 = **2.0 MB**.

The right structure is **bucket-CH with workplaces pinned as targets**: workplaces
are far fewer than 500,000 distinct locations, so the bucket selection amortises
over every commuter sharing a workplace. Sort the OD pairs by origin cell before
running them — Buchhold et al. measure **~20 % from OD-pair reordering alone** on
their largest scenario.

Do not cache polylines for these. The repo already found that: `route-cache-max`
is 150,000 entries per variant precisely because a stride-1 city day would hold a
million polylines, costing 1.0 GB as vectors and 160 MB as primitive arrays.

### (c) Sampled visualisation paths — **keep A\*, or unpack CH shortcuts lazily**

Paths are needed for a sampled subset only. Two options:

1. **Leave the existing A\* in place for the sample.** At a few thousand sampled
   legs and even 38.7 ms each *(measured here)* that is under two minutes, and
   under ten seconds once the `PriorityQueue` boxing is fixed. **This is the
   cheapest correct answer and should be the default.**
2. **Unpack CH shortcuts.** The survey's Table 2 gives the cost directly: CH
   distance-only 0.11 ms versus full path 0.21 ms on Europe — **path retrieval
   roughly doubles the query**
   ([arXiv:1504.05140](https://arxiv.org/pdf/1504.05140)). For CRP, where
   shortcuts are built from multiple arcs, unpacking is more involved.

Keep the existing route-variant jitter mechanism (`walk-route-variants`,
`penalty`) — it is a visualisation device and does not need to survive into the
impedance engine.

### (d) A WGSL implementation path

**Do not port Δ-stepping, near-far, or Bellman-Ford.** The literature is
unambiguous that they lose to a single CPU core on road networks: Davidson et al.
measure **0.24–0.6× versus serial Dijkstra**
([IPDPS 2014](https://escholarship.org/content/qt8qr166v2/qt8qr166v2_noSplash_be4e051e39b35de331f67c483ccb78a7.pdf)),
Gunrock takes **11 seconds** for one SSSP on roadnet-USA
([TOPC 2017](https://escholarship.org/content/qt9gj6r1dj/qt9gj6r1dj_noSplash_ffb70bb2bb62526a8c80b9b370ced2c7.pdf)),
and the frontier on road-USA averages **800 items against 68,000 hardware threads**
([ADDS, PPoPP 2021](https://www.cs.utexas.edu/~lin/papers/ppopp21.pdf)).

**Port the CH/CCH structures instead**, in this order:

| milestone | what | memory (Stuttgart, 429 k v / 942 k arcs) | success criterion |
|---|---|---|---|
| **M0** | CSR upload + a WGSL kernel that computes, for a batch of (origin, destination) node pairs, the haversine distance. Nothing graph-theoretic. | CSR **9.25 MB**, 2.5 M pairs × u32 = 10 MB | the plumbing works: buffer upload, dispatch, readback, u32 quantisation of metres |
| **M1** | **Batched elimination-tree CCH query**, one invocation per (source, target) pair, hierarchy built on the CPU by RoutingKit. Queue-free, rank-ordered, no dynamic allocation — the only CH-family query that maps cleanly to WGSL. | CCH upward+downward arcs ~1.5–2× the graph ≈ **16 MB**; elimination-tree parents 1.71 MB; 2.5 M results 10 MB | matches the CPU CCH bit-for-bit on 10^5 random pairs; beats the CPU at ≥10^5 pairs per dispatch |
| **M2** | **PHAST-style level sweep**: one thread per vertex per level, `atomicMin` on a u32 distance array, k = 16 sources per sweep for coalescing (the measured sweet spot on CPU and GPU alike). | k=16 × 429 k × u32 = **27.4 MB** of distance labels — **21 % of one 128 MiB binding**; k=64 is 110 MB and still fits | one-to-all in low single-digit ms; validates against the 397 ms CPU Dijkstra *(measured here)* |
| **M3** | **Customization on the GPU.** Level-synchronous triangle enumeration, embarrassingly parallel within a level. The CPU precedent is 21.9 s → 1.03 s on 16 threads for Europe; the GPU precedent is CRP customization at **36 ms** for a continent ([Euro-Par 2014](https://link.springer.com/chapter/10.1007/978-3-319-09873-9_61)). | triangles are the bulk; budget one 128 MiB binding | a road closure re-customizes in under a frame |
| **M4** | CSA transit sweep — a scan over the departure-sorted connection array, the transit analogue of M2. | one weekday is **~502 k connections (Stuttgart) / 717 k (Vancouver)**; at 20 B each that is **10.0 / 14.3 MB** | matches the CPU CSA; CSA's published AVX speedup of 1.9× is the floor to beat |

Hard constraints to design against, all from the
[W3C limits table](https://www.w3.org/TR/webgpu/#limits) and
[WGSL §6.2.8](https://www.w3.org/TR/WGSL/):

- **Distances must be u32.** `atomic<T>` admits only `u32`/`i32`; there are no
  float atomics and no 64-bit atomics. Metres as u32 is exact for our metric and
  `atomicMin` works directly. (Quantising *time* would need centiseconds.)
- **128 MiB per storage binding, 256 MiB per buffer, 8 storage buffers per stage.**
  Our CSR is 9.25 MB. Everything fits with ~10× headroom; the thing that does not
  fit is a dense OD matrix, which we are not building.
- **16,384 B workgroup storage** — at most ~4,096 u32 in a workgroup-local bucket.
- **256 invocations per workgroup, 65,535 workgroups per dimension** — a 1-D
  dispatch covers 16.8 M invocations, more than our 2.5 M queries.
- **Use `wgpu`** ([gfx-rs/wgpu](https://github.com/gfx-rs/wgpu)) so one WGSL
  codebase runs native and in the browser. There is **no existing WebGPU routing
  library** — the closest prior art is GraphWaGu (layout only, 100 k nodes /
  2 M edges at ≥10 FPS,
  [PDF](https://stevepetruzza.io/pubs/graphwagu-2022.pdf)) and AntV's
  `webgpu-graph` (SSSP on 1 k nodes in 261 ms, a toy). We would be first.

**Realistic expectation for M1–M2:** GPHAST got **5.53 ms per continental tree on
a GTX 480**, 511× a CPU Dijkstra
([IPDPS 2011](https://renatowerneck.wordpress.com/wp-content/uploads/2016/06/dgnw11-phast-ipdps.pdf)).
Our graph is 42× smaller, so the sweep is dominated by kernel launch overhead
rather than work; the GPU win will come from **batching many sources**, not from
any single query. Expect **2–10×** over a well-tuned 4-core CPU CCH, not 100×, and
budget the WGSL work as an investment in the rest of the simulation moving to the
GPU rather than as a routing speedup.

### (e) Road-closure interventions without full re-preprocessing

Ranked, with costs:

1. **CCH partial customization — the right answer.** RoutingKit ships
   `CustomizableContractionHierarchyPartialCustomization`. The measured cost of a
   single changed arc weight on continental Europe is **median 0.005–0.008 ms,
   mean 0.045–0.052 ms** (max 81–135 ms for a pathological arc high in the
   hierarchy) ([arXiv:1402.0402](https://arxiv.org/abs/1402.0402), Table 10).
   Closing a street is a handful of arcs set to infinity. **A road closure costs
   microseconds.** The topology never changes, so the metric-independent
   preprocessing is untouched.
2. **Full CCH re-customization.** **49 ms single-threaded / 11.7 ms on 8 threads**
   at 110 k vertices ([arXiv:2502.10519](https://arxiv.org/pdf/2502.10519)), so
   perhaps **100–200 ms for our 429 k-vertex Stuttgart graph**. Use this when a
   scenario changes many arcs at once (a whole district pedestrianised, a speed
   regime changed city-wide). Within the "seconds to minutes" budget by three
   orders of magnitude.
3. **ALT as the correctness fallback.** Landmark lower bounds built on the *open*
   network stay admissible when edges are removed or lengthened, because closing a
   road can only lengthen paths. 16 landmarks cost **128 B/node** = 54.9 MB for
   Stuttgart, and the bound is **96.0 % of true distance for random pairs, 89.4 %
   for local ones** on a 330 k-vertex Bay Area network
   ([Goldberg & Harrelson](https://www.cs.princeton.edu/courses/archive/spr06/cos423/Handouts/GH05.pdf)).
   This is what MATSim does, and it is the option that needs no preprocessing
   discipline at all.
4. **Full CH rebuild.** 4–6 s on a 394 k-vertex graph
   ([arXiv:2011.02601](https://arxiv.org/pdf/2011.02601)) — acceptable but 100×
   worse than (2) and it throws away the ordering.
5. **Arc flags, hub labels, transit node routing.** All require rebuilding
   metric-dependent structures — 20 minutes to an hour at continental scale, still
   tens of seconds at ours, and for TNR the transit-node *set* itself changes.
   **Rejected.**

Note that `city.sim.scenario` currently intervenes only on the **venue set**
(`close` zeroes a venue's attractiveness, `open` appends a candidate with its own
distance column) and never touches the network. Road closures would be a new axis,
and the CCH partial-customization primitive is what makes that axis cheap: a
scenario becomes *(venue-set delta, arc-weight delta)*, and the second costs
microseconds to apply.

### (f) Transit, which the brief did not ask about but which is the larger error

The street-side work above buys speed. The transit mode is the only place where
the current model buys *wrongness*: a fixed 5-minute wait and a fixed 18 km/h are
within ~10–15 % of a schedule-based measure in well-served areas and off by
**40 % or more in peripheral and infrequent-service zones**, with errors that are
**spatially systematic**
([Braga et al. 2023](https://www.ipea.gov.br/acessooportunidades/en/publication/2023_jtg_public_transport_travel_time_inaccuracy_variability/),
[Wessel & Farber 2019](https://www.jtlu.org/index.php/jtlu/article/view/1502)).

Two steps, and neither is large. **Headway-aware wait** (`0.5 × headway`, already
computed per stop by `city.intake.gtfs`) is hours of work. **CSA** is the second:
a whole weekday of Stuttgart connections is **~502,000 entries, 10.0 MB**, its
"preprocessing" is a sort taking well under a second, one-to-all on a network
larger than ours runs in **~3.3 ms**, and it has **zero preprocessing to
invalidate** — the only property compatible with interventions that add a stop or
reroute a line. Briem et al. have already run a CSA Monte Carlo microsimulation of
**1,249,910 individual passengers on greater Stuttgart in 38.41 s on four cores**,
about 50× faster than VISUM on the same instance
([SEA 2017](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SEA.2017.20)).
Do not consider Transfer Patterns: 16.5–541 hours of preprocessing is the wrong
end of the trade for a simulator whose premise is that the network changes.

### Ranked summary

| rank | change | expected effect | effort | risk |
|---|---|---|---|---|
| 1 | Replace the boxing `PriorityQueue` in `network/astar` with a primitive binary heap | ~10–30× on the existing code, no semantic change (**refuted when measured**: no speed-up, see the note below the table) | hours | none |
| 2 | Route the destination kernel's λ = 400 m exponential classes on the network instead of crow flight | closes the measured TVD 0.199 gap *(measured here)* | days | changes calibrated outputs — rerun the validation |
| 3 | RoutingKit CCH via Panama/FFM: metric-independent order once, customize per scenario, `pin_targets` per venue class | 2.5 M queries in ~1 s on 4 cores | 1–2 weeks | C++ dependency; FFM shim |
| 4 | Headway-aware transit wait (`0.5 × headway`, already computed in `intake/gtfs`) | the largest single fidelity gain per line of code — the fixed 5 min is right on 2.3 min trunk headways and wrong by 5× on the 48 stops at 12–30 min | hours | none |
| 5 | CCH partial customization for road-closure scenarios | interventions on the network at microsecond cost | days, after 3 | none |
| 6 | WGSL M0–M2 (CSR upload, batched elimination-tree query, PHAST sweep) | 2–10× over 4-core CPU; opens the path for the rest of the sim | 1–2 months | first-of-its-kind; no reference implementation |
| 7 | CSA transit routing replacing fixed wait + fixed speed | correctness on the 23.4 % of trips that are transit; published errors of the current proxy run to **40 %+ in peripheral zones and are spatially systematic** | 1 month | needs the Stuttgart feed's calendar defect fixed first |
| 8 | Full GPU customization (M3), transit on GPU (M4) | research-grade | months | high |

**Measured afterwards (2026-09-16):** a primitive binary heap gave 39.5 ms per
query against 38.7 ms with the `PriorityQueue`, and an equirectangular heuristic
44 ms.  A query touches about 50,000 of the 428,737 nodes; the cost is the size
of the search, which only a hierarchy such as item 3 changes.  Item 1's
estimate below was wrong.

**Items 1, 2 and 4 are worth doing before any of the algorithmic work**, because
they are hours of effort each and two of them are fidelity fixes rather than speed
fixes. Item 3 is the one that makes the stated target — a full day in seconds —
true. Item 6 is the one that makes the stated *ultimate* goal reachable, and the
honest framing is that it buys a single-digit multiple over a CPU that is already
fast enough.

### What to be skeptical about in this file

- **Every continental number was scaled down by a factor of 40–78 to reach our
  graph size, and hierarchical methods do not scale linearly.** The CCH survey
  says so explicitly: Stuttgart "is a city network that is much less hierarchical",
  and its query times are 14.5–22.9 µs where Europe's are 137.5–300.2 µs — a factor
  of ~10–13 improvement for a factor of 164 in vertices. **City graphs get less
  benefit from hierarchy than continental ones.** Where I give a city-scale
  estimate derived from a continental measurement, treat it as optimistic by up to
  3×.
- **The vendor matrix-API numbers (GraphHopper, OSRM `/table`) are not benchmarks.**
  No hardware named, mutually inconsistent across posts, queries confined to a
  single city in the case most favourable to CH.
- **The GPU speedups that circulate (350 MTEPS, 8.7 GTEPS, 50–500×) are all
  scale-free-graph numbers.** The road-network figures on the same hardware and
  the same code are 259–1,436× worse.
- **Our own measurements are small samples** — 400 pairs for the A\* timing and
  detour factor, 40 origins × 200 candidates for the TVD. They are the right order
  of magnitude, not three significant figures.
- **The TVD numbers use random graph nodes as proxy venues**, not the real firm
  locations, so they measure the geometry of the network rather than the geometry
  of the venue set. The real venue set is concentrated on high streets, which is
  where the street network is densest and the detour factor lowest — so **the true
  TVD is probably somewhat lower than 0.084 / 0.199.** Re-measuring against the
  actual `candidates/build` output before acting on item 2 would cost an afternoon
  and is worth it.
