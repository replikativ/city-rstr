# Interactive simulation compute boundary

Status: architectural audit, 2026-09-13. This note separates existing compiler
capabilities from proposed intervention support. A bounded daily2 evaluator has
since been implemented; its new local timings and limitations are recorded in
the regional preview guide (not in the published repository), separately from the historical
full-city benchmarks below.

## Current execution stages

The city pipeline already has useful stage boundaries, although it currently
executes and publishes them as one batch in
[`publish-city!`](../../src/city/sim/publish.clj):

| Stage | Current result | Reuse boundary |
|---|---|---|
| World construction | Persons, firms, workplace assignment and fixed primitive-array columns | Reuse while population, firms and jobs are unchanged. |
| [`day/prepare`](../../src/city/sim/day.clj) | Grid; retail, food and other destination CSRs; diary CSR; mode table; person type, home-cell and work-cell arrays | Reuse its independent products rather than treating the returned map as one cache entry. |
| [`day/step-day`](../../src/city/sim/day.clj) | `visits int[n-firms*24]` and counts from one full pass over persons | Recompute when destinations, diary probabilities, person profiles or the seed change. It does no routing. |
| [`day/step-day-traces`](../../src/city/sim/day.clj) | The same destination process plus optional routed legs | Run only for the requested sample or viewport. It can stream traces through `:trace-fn`. |
| [`network/route-fn`](../../src/city/sim/network.clj) | A mode router over one loaded street graph and one installed stop index | Route geometry is cached by node pair and walk variant, but not by scenario or network version. |
| Publication | Area aggregates, economic scores and JSON layers | [`serve/publish!`](../../src/city/sim/serve.clj) stores completed outputs in a process-local atom. Lazy trips are cached only by area and stride. |

Counter-based randomness makes paired evaluation practical:
[`day/uniform`](../../src/city/sim/day.clj) addresses each draw by seed,
person and draw index. Baseline and scenario should therefore use the same
world, configuration and seed. A changed destination can change a later anchor,
so matching random numbers reduces comparison noise but does not make later
choices identical.

## Intervention invalidation

| Intervention | Reusable | Must be invalidated for current exact semantics |
|---|---|---|
| Add or close a grocery | Persons, diaries, person types, mode table, road graph, transit stops and noncommercial venue sources. Workplace assignment is reusable when the intervention does not change jobs. | Firm candidate/alive state, attractiveness, retail choice CSR, full day and trace results under the current APIs, area aggregates and economic scores. Adding a firm also requires extending `work-cell`, even when it has no jobs. [`venue-attract`](../../src/city/sim/day.clj) derives fallback size from all nearby customer-facing venues, so an opening can also change food attractiveness: rebuild both retail and food CSRs unless measured attractiveness makes that dependency absent. Rebuild the business class and workplaces only when employment is part of the intervention. |
| Move a grocery | Same as add/close. The old and new locations are one intervention and should be applied atomically. | Same destination products as add/close. If the move expands the world bounding box, the grid and every grid-derived table are invalid. |
| Close a road | Destination CSRs, diary selection, visit allocation, OD endpoints and current area aggregates. The aggregate reducer reads leg endpoints, not their interior routes ([`area-aggregates`](../../src/city/sim/cityworld.clj)). Current gravity choice uses straight-line distance rather than network impedance. | Street graph weights/topology, every route cache entry that can cross the closure, routed geometry and routed timing. Current graph construction produces a fixed-layout CSR in mutable primitive arrays and exposes no closure overlay ([`network/build`](../../src/city/sim/network.clj)). Give caches a network/scenario identity before attempting selective reuse. |
| Add or remove a transit stop | Destination choice and unrouted visits. | Stop spatial index and transit legs whose access stop can change, including their access/egress walks and timings. |
| Change transit service or close a line | No current line or timetable state exists to modify. | This first requires a time-dependent transit model. The current router uses nearest stops, a fixed five-minute wait, a fixed speed and a street route between stops; it explicitly has no line topology or timetable ([`mode-router`](../../src/city/sim/network.clj)). |
| Update diary or daily conditioning inputs | World geometry, firm tables and road network when those inputs are unchanged. | Rebuild only the diary CSR when chains or weights change, only the mode table when mode profiles change, then recompute the day and dependent outputs. Traffic or service observations additionally require time-indexed routing semantics. |

Retail and food currently use an unbounded power kernel with a top-K candidate
set ([`gravity-table`](../../src/city/sim/day.clj)). An added venue can enter
the top K of any cell. A removed venue can expose a candidate that was not
stored. Exact full-city incremental invalidation therefore cannot in general be
limited to nearby cells. A region prototype must either rebuild every cell in
its frozen candidate universe or state an explicit distance/candidate boundary.

## Next prototype

Keep the existing instant, deterministic grocery experiment as the first
fidelity. `city.lab.model` (no longer in the repository) already provides a
pure JVM/ClojureScript `fork-world`, conserved expected allocation and
baseline/scenario comparison over the Stuttgart-West fixture. It deliberately
has equal attractiveness, a complete choice set and no diaries, routing,
capacity, prices or budgets. Those semantics should stay visible rather than be
presented as a daily simulation.

Add a second evaluator around the small Stuttgart daily world:

1. Freeze a baseline identity containing source versions, code revision,
   resolved configuration, seed, grid/candidate boundary and network version.
2. Fork the numerical state, apply one grocery add, close or move intervention,
   rebuild retail and food destination tables, and run the unrouted day with the
   baseline seed.
3. Return baseline, scenario and delta visits first. Compute traces only for a
   bounded sample or viewport, and route only after an interaction asks for
   paths.
4. Cache stage products by baseline identity plus intervention. Check unchanged
   control equality, visit-allocation conservation where the model promises it,
   parent/sibling isolation and repeatability.
5. Measure world construction, table preparation, day stepping, routing,
   aggregation and serialization separately before choosing an accelerator.

Primitive arrays are mutable even when the maps containing them are persistent.
`assoc`, Datahike history, or a source-version identifier does not isolate a
fork if two branches still share `int[]`, `double[]` or resident device buffers.
Clone every array a branch may change, or give buffers explicit immutable or
copy-on-write ownership. In parallel evaluation, a branch must never mutate a
baseline or sibling tensor. Datahike should retain source and experiment
identity; it cannot by itself make mutable numerical state persistent.

## Raster boundary: current support and proposed work

City declares Raster as a local dependency
([`deps.edn`](../../deps.edn)), but no city source namespace currently requires
Raster. `daily2` is SOA/CSR-shaped preparation for a port, not a compiled kernel.

The first useful port is the destination draw and visit histogram in
`step-day`. Flatten the per-class object arrays into typed buffers and express
the outer person loop as a Raster `deftm` using `par/map-void!`; keep the CSR
binary searches and episode loops inside it; replace shared visit increments
with typed `par/atomic-add!`. Raster provides sequential fallbacks and GPU
lowering for both operations
([`raster.par`](https://github.com/replikativ/raster/blob/main/src/raster/par.clj)). Its firms ABM is the
working analogue: irregular per-agent logic outside shared mutation, followed
by atomics, scans and scatters
([`firms/phases.clj`](https://github.com/replikativ/raster/blob/main/src/raster/abm/firms/phases.clj)). Add
reference parity for visits and counts before profiling devices.

The callable compiler boundary exists today:
[`pipeline/compile-aot`](https://github.com/replikativ/raster/blob/main/src/raster/compiler/pipeline.clj)
selects JVM/SIMD, native C, or a target device and retains sequential fallbacks
for unsupported parallel forms. Persistent accelerator sessions can compile,
allocate, bind and replay kernels
([`gpu/core.clj`](https://github.com/replikativ/raster/blob/main/src/raster/gpu/core.clj)); certified
resident programs can be lowered, instantiated and invoked without downloading
outputs between steps
([`gpu/compiled.clj`](https://github.com/replikativ/raster/blob/main/src/raster/gpu/compiled.clj)). These
APIs can keep stable diary and choice tables resident while a scenario uploads
changed tables. They do not derive the city dependency graph or decide which
tables an intervention invalidates.

Raster's scalar partial evaluator performs compiler transformations such as
constant propagation, trivial inlining and dead-branch simplification
([`passes/scalar/pe.clj`](https://github.com/replikativ/raster/blob/main/src/raster/compiler/passes/scalar/pe.clj),
[`pe_test.clj`](https://github.com/replikativ/raster/blob/main/test/raster/compiler/pe_test.clj)). It is not
partial simulation evaluation, memoization, or scenario dependency
invalidation. Likewise, `gpu.compiled` invalidates projected output wrappers
when resident buffers will be overwritten; that is a buffer-lifetime rule, not
a domain dependency engine
([`gpu/compiled.clj`](https://github.com/replikativ/raster/blob/main/src/raster/gpu/compiled.clj)).

After the day kernel, batched gravity-table construction is a plausible GPU
target, but the current implementation allocates per-cell temporary top-K
arrays and uses host collections. It needs a fixed scratch layout and explicit
parallel phases first. A* routing should remain on CPU for this slice: it uses a
priority queue and query-local irregular state. GPU routing would be a separate
batched shortest-path design, not a consequence of compiling the daily
histogram.

## Performance evidence

No fresh benchmark was run for this audit. Existing repository notes report a
full Stuttgart day step near 0.9 seconds and identify routing as the dominant
cost ([`architecture.md`](../architecture.md)); historical preparation tables
report 203--259 seconds ([`simulator.md`](../simulator.md)). The publisher's
docstring estimates a complete Stuttgart publish at about 40 minutes
([`publish.clj`](../../src/city/sim/publish.clj)). These are prior recorded
measurements on earlier runs and configurations. Re-measure them on the small
Stuttgart artifact, with its exact revision and hardware recorded, before using
them as prototype latency claims.

## Daily observations and specialization

Daily conditioning needs an as-of boundary: retain the observation's valid time,
publication/ingestion time, source revision and uncertainty. Freeze these inputs
for each scenario comparison; do not let a changing feed silently alter one branch.
A new weather, mobility-count or service observation would update only mechanisms
that actually consume it. None of these live feeds is connected in the current
preview. Validation should hold out later observations rather than score a model
against the same daily counts used to condition it.

For compiler specialization, keep seeds, changing weights and intervention values
as runtime inputs initially. Specialize stable model structure, types and layout
where compilation cost can be amortized. Keep the compiled-program cache distinct
from the dataset/table cache and from scenario results. On the current small
preview, millisecond day evaluation is already cheap: avoiding repeated preparation
and unnecessary result reloads matters more than moving that loop to the GPU.
