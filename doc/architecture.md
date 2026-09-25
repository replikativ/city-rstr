# Architecture

How the code is laid out, how data flows through it, and where each part of
the model in [`model.md`](model.md) is computed.

## Layers

| layer | namespaces | job |
|---|---|---|
| intake | `city.intake.core`, `.overpass`, `.overture`, `.gtfs`, `.stuttgart-counts` | download or adopt a source file and write its receipt (URL, SHA-256, time); GTFS stops and headways; counted bicycles and pedestrians |
| load | `city.load.census`, `city.load.stuttgart`, `city.store`, `city.web`, `city.geo.core` | read sources into the Datahike evidence store, assign points to areas, and serve areas, cells and records over HTTP (port 8090) |
| synthesis | `city.synth.stuttgart`, `.stuttgart-firms`, `.anchors`, `.retail`, `.segments`, `.timeuse`, `.tripgen`, `city.resolve` | synthetic persons from Zensus marginals; firms from Overture and the employment statistics, with named employers matched by site and name; raked floor area per demand class; diaries reweighted to the trip rate |
| world | `city.sim.cityworld`, `city.sim.world`, `city.econ.household`, `city.econ.spending` | persons with homes, workplaces and purchasing power; firms with capacity and categories; the great-circle metric |
| the day | `city.sim.day`, `city.sim.candidates`, `city.sim.kernel`, `city.sim.venues`, `city.sim.network`, `city.econ.day` | diaries, destination choice, visits, money, routing |
| inference | `city.infer` | the three-class model as a spindel program; importance-sampling and MH drivers |
| scenarios | `city.sim.scenario` | interventions on the venue set under the posterior particles |
| scoring | `city.sim.validate`, `city.econ.validate`, `city.econ.quantities`, `city.econ.report` | simulated quantities against published targets |
| serving | `city.sim.serve`, `city.sim.publish`, `city.sim.run` | the published run over HTTP (port 8092), and the run's parameter table |
| pipeline | `city.demo.stuttgart` | the whole chain as functions over one context map, and the static export |
| explorer | `city.ui.app`, `city.ui.explorer`, `city.ui.catalog`, `city.ui.remote`, `city.ui.city-layers`, `city.ui.city-panels`, `city.ui.timeline` | the browser page: MapLibre and deck.gl layers, evidence panels, scenarios |

Where each section of [`model.md`](model.md) is computed:

| model | namespace and function |
|---|---|
| §1 persons from marginals | `city.synth.stuttgart` |
| §2 workplaces and commuting | `city.sim.cityworld/assign-workplaces-grid!`, `place-externals!`, `place-out-commuters!` |
| §3 attractiveness | `city.synth.retail/attract`, per class `city.synth.segments/attract-by-segment` |
| §4 destination choice | `city.sim.candidates` (store, exact), `city.sim.day/gravity-table` (other classes, top-K) |
| §5 diaries | `city.synth.timeuse`, `city.synth.tripgen` |
| §6 the day | `city.sim.day/step-day`, `step-day-traces`; `city.sim.day/uniform` for the draws |
| §7 money | `city.econ.household`, `city.econ.spending` |
| §8, §9 likelihood and posterior | `city.demo.stuttgart/segmented-simulator`, `city.infer/run-segmented` |
| §10 interventions | `city.sim.scenario` |
| §12 money on the day | `city.econ.day`, `city.sim.kernel/spend-day!` |

## Data flow

```
data/raw, data/derived ──► synthesis ──► world ──► the day ──► expected turnover ──► likelihood ──► posterior
        │                                             │                                              │
        └──► evidence store (Datahike) ──► city.web   └──► traced legs, visits, money ──► serve ◄─────┘ scenarios
                                               │                                          │
                                               └───────────────► explorer ◄───────────────┘
                                                                     │
                                                          export-static! ──► dist/lab (files only)
```

The world is built once per process and held in memory, about 5 GB for the
whole city with its choice tables.  Apart from the input files and the
evidence store, the only thing persisted between processes is the posterior
(`data/derived/stuttgart-seg-posterior-n48.edn`).

## Representation

Persons and firms are structs of arrays: one primitive array per attribute,
indexed by person or firm.  The store choice table is dense and exact:
`city.sim.candidates` precomputes distances from every 100 m cell to every
retail candidate as float32, writes the full table when the day samples from
it (`table-dense`), and reduces the kernel over the distances without
materialising a table when only an expectation is needed (`reduce-dense`).
The other destination classes use top-K tables (`city.sim.day/gravity-table`).
All kernel specifications live in `city.sim.day/default-venue-kernels`; the
run config (`city.sim.run`) overrides the store and restaurant entries.

Random draws are counter-addressed (`city.sim.day/uniform`): a draw is a pure
function of (seed, person, purpose index), so a day can be evaluated in any
order, split across threads or devices, and replayed under a changed venue set
with the same draws for every person.

## The day on a device

`city.sim.kernel` states the retail part of the day, and the economic day, as
raster kernels (`deftm` with `par/map-void!` over persons and `atomic-add!`
into shared counters).  Run uncompiled they are plain JVM loops, which is how
the tests exercise them and how the demo runs the economic day.  Compiled
through raster's GPU backend (0.2.951 or later) they run on a Level Zero or
OpenCL device; `dev/checks/kernel_device.clj` compiles `retail-visits!` and
`spend-day!` and expects arrays identical to the JVM run.  The kernel bodies
keep to shapes raster's typed GPU pipeline lowers: no `and`/`or` (boolean
bindings), no `Math/max` on integers, integer locals cast explicitly, literals
inlined, one `recur` per loop iteration, and a candidate walk with a single
exit (the hit rides in a carry).

## Inference

`city.infer` writes the model as a spindel program: nine (or twelve, with
optional class levels) sampled sites with explicit ids and one observe per
(district, class).
Each particle is a forked execution context.  The MH kernel re-executes the
program from the checkpoint of the site it perturbs; `run-segmented` drives it
with independent chains or with resample-move.  Inference evaluates the exact
expectation (`reduce-dense`), so the likelihood carries no Monte Carlo noise.

## Serving and export

`city.sim.serve/publish!` registers a run under a key; `handler` answers
`/sim/*` requests from what the run holds, filtering by viewport and capping
trips at 20,000 legs (see [`api.md`](api.md)).
`city.demo.stuttgart/export-static!` calls the same handler in process and
writes one JSON file per response, so the explorer runs from static files with
no server.
