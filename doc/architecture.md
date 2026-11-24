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

The Datahike library indexes published city runs by release in IndexedDB.
Each run selects a prepared schedule, a minute-by-area scene, 24 local-clock
street-trace shards and a scenario catalogue. The ClojureScript explorer uses the
same map, clock and resident inspector for both cities. The map interpolates
street coordinates between successive timestamps and can show the whole roster
at its latest modeled stops. Display sampling is independent of the population
used to compute movement and retail results.

Stuttgart supplies its street reconstruction and baseline and counterfactual
spending products. Vancouver supplies a regional synthetic roster, attending
external workers, routed samples and walking grocery occasions. Model pages link
the underlying observations to each city's assumptions. The compiler and replay
use packed arrays after preparation. The retired Vancouver workbench and its
historical saved-opening playback are preserved in the [archived revision](https://github.com/replikativ/city-rstr/tree/ebaecc15f7d583633580b7009137393e4be892d8).

### Building a published weekday

`city.build/build!` is the release entry point for both cities. It selects a run from the catalogue, verifies its [producer inputs](../resources/city/weekday-builds.edn), and stages the numerical day, retail outcomes and 24 hourly trajectory files. Passing `:verify true` also checks the underlying local source receipts and each generated file against the reviewed release. The browser consumes the resulting static products.

Vancouver's regional roster uses a stable person index in published census-area order. The diary clock assigns each person a reproducible phase within the five-minute source bin. Presence observes that clock at whole minutes; journeys and grocery occasions use its fractional time. The municipal releases retain their original timing and sample order. Stuttgart reconstructs the geometry of its recorded waypoints. The shared trajectory publisher owns the hour boundaries and file format. Vancouver's directed-network routing adapter and the JSON number encoding used for historical content hashes still run in Node.

| To change | Start here | Product to compare |
|---|---|---|
| A source, coverage, or fitted dataset version | [Build recipes](../resources/city/weekday-builds.edn) and [source roles](../public/sources/weekday.json) | Input receipts, cohort sizes and geography |
| Vancouver household and workplace assignments | [Atlas preparation](../scripts/vancouver_atlas.py), [regional workplaces](../src/city/vancouver/regional_workplaces.clj) and [roster identity](../src/city/vancouver/roster.clj) | Resident IDs, institutional counts, destinations and modes |
| The time an agent leaves, arrives, or becomes visible on a route | [Vancouver diary clock](../src/city/vancouver/diary_clock.cljc), [weekday reductions](../src/city/sim/weekday.clj) and [trajectory publisher](../src/city/trajectory.clj) | Presence, hourly trips and adjacent hours of the same route |
| A shop-opening estimate or its interpretation | [Vancouver grocery occasions](../scripts/vancouver_market.py), [Stuttgart economic day](../src/city/econ/day.clj) and [scenario publication](../src/city/overview_cases.clj) | Visits, spending units, opening hours and incumbent losses |
| A saved file or release pointer | [Clojure artifact publication](../src/city/artifact.clj) and [offline Python producer I/O](../scripts/artifacts.py) | File bytes, digests and retry behaviour |

To add a weekday for an existing city, publish its producer manifest and catalogue entry, then add a recipe keyed by the release ID. A file pin covers its bytes. A directory pin covers filenames and file hashes, so replacing one census-area shard invalidates the pin. Source records carry their published role and locator. Use a separate `--output` directory to compare a candidate's numerical and retail outputs before updating the reviewed preview. A new city also supplies a schedule producer through [the dataset registry](../resources/city/datasets.edn), geography and a trajectory adapter.

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
