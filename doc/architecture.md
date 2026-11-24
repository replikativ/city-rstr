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
| inference | `city.infer`, `city.sim.device` | the three-class model as a spindel program; importance-sampling and MH drivers; the likelihood's expected allocation on a GPU |
| scenarios | `city.sim.scenario` | interventions on the venue set under the posterior particles |
| scoring | `city.sim.validate`, `city.econ.validate`, `city.econ.quantities`, `city.econ.report` | simulated quantities against published targets |
| serving | `city.sim.serve`, `city.sim.publish`, `city.sim.run` | the published run over HTTP (port 8092), and the run's parameter table |
| pipeline | `city.demo.stuttgart` | the whole chain as functions over one context map, and the static export |
| explorer | `city.ui.app`, `city.ui.explorer`, `city.ui.catalog`, `city.ui.remote`, `city.ui.city-layers`, `city.ui.city-panels`, `city.ui.timeline` | the browser page: MapLibre and deck.gl layers, evidence panels, scenarios |
| saved experiments | `city.experiment`, `city.ui.experiments` | the shared Datahike schema and queries for saved openings link the scored run, storefront, residents and visits. The browser adapter persists them in IndexedDB. The map loads the referenced simulation arrays on demand. |

Where each section of [`model.md`](model.md) is computed:

| model | namespace and function |
|---|---|
| §1 persons from marginals | `city.synth.stuttgart` |
| §2 workplaces and commuting | `city.sim.cityworld/assign-workplaces-grid!`, `place-externals!`, `place-out-commuters!` |
| §3 attractiveness | `city.synth.retail/attract`, per class `city.synth.segments/attract-by-segment` |
| §4 destination choice | `city.sim.kernel/store-choices!` (store, per demand class, exact), `city.sim.day/gravity-table` (other classes, top-K) |
| §5 diaries | `city.synth.timeuse`, `city.synth.tripgen` |
| §6 the day | `city.sim.day/step-day`, `step-day-traces`; `city.sim.day/uniform` for the draws |
| §7 money | `city.econ.household`, `city.econ.spending` |
| §8, §9 likelihood and posterior | `city.demo.stuttgart/segmented-simulator`, `city.infer/run-segmented` |
| §10 interventions | `city.sim.scenario` |
| §12 money on the day | `city.sim.kernel/store-choices!`, `city.econ.day/money-from-choices` |

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
(`data/derived/stuttgart-seg-posterior-n48-iter200-pooled.edn`).

### Browser database and city replay

The browser Datahike database indexes Stuttgart and Vancouver weekdays in IndexedDB. A published run identifies the city, geographic coverage and release. Stuttgart runs carry district turnover distributions. Vancouver runs identify the population, daily schedules and street network. The municipal run also records the number of census areas when both membership and population reconcile to the geographic audit. The library links that figure to the audit for the selected release.

A saved shop opening links its market, hours, storefront and visits. A played opening also stores its effective minute. A resident in a saved visit is identified by city, atlas release, census area and position within that area's roster. The map resolves that identity against the release that generated the visit. Trip-demand queries also use this database. The renderer and Raster kernels read dense arrays directly from versioned files. Vancouver applies an opening action to the current weekday by recomputing the destinations of eligible shoppers who have yet to set off. Both map views use the resulting destinations and the same clock.

The two weekday maps share the timed path contract and the position interpolation in `city.ui.timeline`. Stuttgart exports sampled paths and timestamps after routing its chosen destinations. Vancouver resolves the displayed sample's current paths in a worker and caches results by endpoints, mode and time budget. Both forms feed a map at a point on the simulation clock.

`city.ui.replay-shell` connects the playback controls, inspector and result card to each city's replay. Stuttgart mounts it from the ClojureScript explorer, and Vancouver uses the ESM adapter in `city.ui.replay`. The shared layout uses the simm.is palette. Each city supplies its map layers, clock range, scenario results and evidence.

`city.replay` supplies common rules for selecting published runs and building weekday links. The top-bar City selector opens the target city's preferred weekday at the displayed local time. The scenario picker and the run library use the same catalogue ordering. Vancouver's study-area switch opens the preferred published run for the target area and carries the displayed minute and selected transit service. Resident selections and interventions tied to the source release end at either boundary. The target timetable resolves service availability.

`city.resident/visit-at` resolves the current inbound leg, stop or outbound leg from a scheduled visit and a replay minute. Vancouver's recorded grocery walks use that contract with the market's chosen storefront, the released pedestrian graph and the diary's walking-time budget. The overview, resident inspector and street actors use the same position and path. When a walk cannot be routed within the diary time, the inspector reports an unresolved position.

Stuttgart uses `city.resident/trace-at` to follow a sampled resident along the published baseline legs. The Milaneo scenario can pick a baseline shopping leg whose endpoint matches a closed venue's coordinates at the published precision. The scenario export describes counterfactual visits by venue. Individual replacement routes need their own traces.

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

`city.sim.kernel/store-choices!` decides every store episode of the day: its
demand class, its leakage and its venue under the class's kernel.  The money
day (`city.econ.day/money-from-choices`), the untraced day and the traced day
(`city.sim.day/step-day`, `step-day-traces`, through `:store-choices` in the
tables) all read those decisions, so trips, visits and money agree; the
Stuttgart tables carry no store table at all, and a day run without the
decisions throws.  Run uncompiled the kernels are plain JVM loops, which is
how the tests exercise them and how the demo runs them.  Compiled through
raster's GPU backend (0.2.951 or later) they run on a Level Zero or OpenCL
device; `dev/checks/kernel_device.clj` compiles `store-choices!` and expects
arrays identical to the JVM run.  The kernel bodies keep to shapes raster's
typed GPU pipeline lowers: no `and`/`or` (boolean bindings), no `Math/max` on
integers, integer locals cast explicitly, literals inlined, one `recur` per
loop iteration and at most two loop carries, a candidate walk with a single
exit (the hit rides in a carry), and atomic adds rather than plain stores
around and inside the episode loop.

## Inference

`city.infer` writes the model as a spindel program: nine (or twelve, with
optional class levels) sampled sites with explicit ids and one observe per
(district, class).
Each particle is a forked execution context.  The MH kernel re-executes the
program from the checkpoint of the site it perturbs; `run-segmented` drives it
with independent chains or with resample-move.  Inference evaluates the exact
expectation (`reduce-dense`), so the likelihood carries no Monte Carlo noise.
`fit-posterior :backend :gpu` evaluates that expectation on a GPU instead
(`city.sim.device`, three kernels in `city.sim.kernel`): about 0.5 s per
likelihood evaluation on Stuttgart against 3.6 s on the CPU, equal to about
1e-13 relative, and a short fit with either backend ends in the same chain
states (`dev/checks/likelihood_stuttgart.clj`).

## Serving and export

`city.sim.serve/publish!` registers a run under a key; `handler` answers
`/sim/*` requests from what the run holds, filtering by viewport and capping
trips at 20,000 legs (see [`api.md`](api.md)).
`city.demo.stuttgart/export-static!` calls the same handler in process and
writes one JSON file per response, so the explorer runs from static files with
no server.

## Running the shared weekday presence phase

At the Clojure REPL, use the same entry point for both cities.

```clojure
(require '[city.weekday :as weekday])
(def vancouver (weekday/run {:city :vancouver :atlas "59b3bcac4137ca1483c9"
                             :day "dbd7a101357f3c27976f" :backend :jvm}))
;; Row zero is 04:00 on this Vancouver release. Columns follow :areas.
(nth (:presence vancouver) 240)

;; Requires the Stuttgart source data, evidence store and saved retail posterior.
(def stuttgart (weekday/run {:city :stuttgart :seed 1 :backend :jvm}))
```

The CLI accepts the same EDN map with `clojure -M -m city.weekday`. Vancouver
selects a fitted population and spatial day by release. Its adapter checks the
computed matrix against that day's published reference. Stuttgart accepts a
local `:trip-rate` calibration target when building its world. A prepared world
can also be supplied through `:context` with its resolved store choices.

Both adapters submit weighted schedules during `city.weekday/prepare`. The numerical runtime in `city.sim.weekday` accepts only prepared schedules and array inputs. A caller can request `#{:presence :trip-ends}` from `city.weekday/execute` after closing its data source. Presence uses the selected Raster backend. Hourly trip ends currently run on the JVM. Each
schedule lists exclusive interval ends in minutes from the local day start
and an area index. The result accounts for each resident in each of 1,440
minutes. Stuttgart uses the day engine's modelled movement times, marks time
outside the available diary window unresolved and tracks known outbound work
stops separately. External commuters are outside this resident count.
