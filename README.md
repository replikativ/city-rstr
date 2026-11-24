# city-rstr

Data-grounded city simulation and replay for Stuttgart and Vancouver. The [implementation plan](doc/implementation-plan.md) tracks the shared engine, browser data library, scientific validation and explorer.

**This is a research prototype, not a library.** There is no release, the
namespaces and functions change without notice, and nothing here is meant to
be depended on.  The code is published so that readers can see how the model
is built and check it against its description.  Results are conditional on the
assumptions stated in [`doc/model.md`](doc/model.md) §11, several of which are
placeholders, and the published posterior is approximate.  The numbers are not
forecasts.

## Run the two-city explorer

To reproduce the reviewed preview from a clean checkout, follow the [release and data instructions](deploy/README.md).

With the producer datasets in `public/data`, run `npm run overview:build` to regenerate the shared engine products (first rebuild the regional grocery catalogue with `python3 -m scripts.vancouver_market ../Simulations/city --data public/data/vancouver/region --continuous`), `npm run release` to compile the explorer, and `npm run preview:bundle` to assemble the checked static preview. The initial Stuttgart build reads the source archive at `../Simulations/city`. Serve the bundle with `python3 -m scripts.preview_local --directory dist/city-previews/current` and open the [local explorer](http://127.0.0.1:8191/city/).

The [shared model](public/weekday-sources.html) explains the clock and simulation outputs. The [Stuttgart](public/stuttgart-model.html) and [Vancouver](public/vancouver-model.html) pages document their population, travel, retail assumptions and source records. Regenerate these pages with `python3 -m scripts.preview_sources`.

The city selector switches between Stuttgart and regional Vancouver on one map. Regional Vancouver includes residents of Vancouver, UBC and the North Shore, plus external commuters in its area counts. Moving dots follow the published subset of routed trips. In Stuttgart the street replay checks each leg against its diary time budget using speeds for the mode and street. Select a moving traveller to see its speed in simulation time. Area overlays include scenario outcomes with their original geographic scope, time period and units. A copied explorer URL restores the release, time, map position and selected shop. The run library also exposes the municipal Vancouver releases.

From a Clojure REPL, rerun any bundled resident day with its run-library release ID. After preparation the same arrays can be evaluated repeatedly without an open database or access to the source archive.

```clojure
(require '[city.weekday :as weekday])
(def prepared (weekday/prepare-release "public/data" release-id))
(def day (weekday/execute prepared :jvm #{:presence :trip-ends :od-flows}))
```

## Stuttgart model

936,597 synthetic people (610,444 residents drawn from the Zensus 2022 grid,
326,153 in-commuters from the employment statistics) live one weekday.  Each
follows an activity diary, chooses shops and other destinations with a
size-and-distance kernel, spends their household's purchasing power, and
travels on the street and transit network.

Retail is split into three demand classes (short-, medium- and long-term
goods), each with its own destination kernel.  The nine kernel parameters are
inferred from the 69 published turnovers by district and class, and policy
scenarios (closing the Milaneo shopping centre, or moving its floor space to
another district) are evaluated under every posterior draw, so each reported
effect comes with a band.

## The explorer

The explorer at [simm.is/city](https://simm.is/city/) shows the published run
on a map: who lives where (population and rent per 100 m cell), movement over
the day (trips by purpose, people at the playhead, transit stops, flows
between districts), the baseline economy (visits and revenue per venue and
demand class, and a scorecard against published figures), and the scenario
effects with their posterior bands.  It is a static export
(`city.demo.stuttgart/export-static!`): nothing is computed in the browser,
and venue names are removed.

The explorer opens on the movement view. Selecting a scenario keeps the current
playback time and shows the district with the highest mean revenue gain, with
its 90% interval. Select that result for the district comparison, or use
**Check calibration** for the observed and predicted turnovers. Both views have
shareable links, for example `?scenario=move-milaneo#district-effects` and
`?scenario=move-milaneo#calibration-short`.

## Reading

- [Vancouver weekday model](doc/vancouver.md) describes the first Vancouver activity baseline, its executable scorecard and the proposed Mount Pleasant grocery-opening comparison.

- [`doc/model.md`](doc/model.md) (rendered as `public/model.html` by
  `python3 scripts/render_model.py`): the model
  as a joint distribution, its assumptions, the inference and the
  interventions.  Start here.
- [`doc/architecture.md`](doc/architecture.md): how the code is laid out, how
  data flows through it, and which namespace computes which part of the model.
- [`doc/api.md`](doc/api.md): what the two HTTP services answer.
- [`DATA.md`](DATA.md): every data source, how to obtain it, and its licence.
- [`doc/simulator.md`](doc/simulator.md): the lab notebook, a dated log of how
  the model was built, including what turned out to be wrong.  It describes
  the code as it was on each date, not as it is now.

Built on the [replikativ](https://github.com/replikativ) stack:
[raster](https://github.com/replikativ/raster) compiles the day's kernels for
the JVM and for GPUs, [spindel](https://github.com/replikativ/spindel) runs the
inference as a probabilistic program over forked execution contexts, and
[Datahike](https://github.com/replikativ/datahike) holds the evidence store.

## Requirements

- JDK 24 or newer (the kernels use `jdk.incubator.vector`).
- Clojure CLI 1.12.
- Node.js and npm for the explorer.
- About 7 GB of heap for the full city (the `:demo` alias sets `-Xmx7g`); the
  tests need no data and little memory.
- Optional: a Level Zero or OpenCL GPU with about 1.5 GB of memory to run the
  day kernels and the likelihood on a device (`dev/checks/kernel_device.clj`,
  `dev/checks/likelihood_device.clj`); `demo/fit-posterior :backend :gpu`
  uses it for inference.

## Tests

```sh
clojure -M:test                        # unit tests; tagged ^:data tests are skipped
clj-kondo --lint src test --fail-level error
```

The tests build their own small worlds and need no data, network or GPU; a
run takes about two minutes and 3 GB of heap is plenty.  `clojure -M:test-data`
runs the tests tagged `^:data`, which read `data/derived/`.

## Running the demo

The demo needs the data described in `DATA.md` under `data/` and the evidence
store built from it.

```sh
clojure -M:demo up            # build Stuttgart, load or fit the posterior, publish, serve on 8092
clojure -M:demo export        # the same, then write the static explorer to dist/lab
```

Build the browser assets with `npm run release` before exporting the standalone explorer.

Or from a REPL (`clojure -M:dev`, nREPL on port 7900), step by step:

```clojure
(require '[city.demo.stuttgart :as demo] '[city.store :as store])
(store/connect!)
(def ctx (-> (demo/build-world) demo/segment-inputs demo/money-inputs))
(def posterior (or (demo/load-posterior) (demo/fit-posterior ctx)))
(def ctx (demo/publish! ctx (demo/posterior-mean posterior) :port 8092))
(demo/scenarios ctx posterior)
```

Build the explorer and serve it:

```sh
npm ci
npm run release
python3 -m http.server 8091 --directory public   # then open http://localhost:8091/lab.html
```

| port | process |
|---|---|
| 7900 | nREPL of the dev JVM |
| 8090 | evidence API (`city.web`) |
| 8091 | static explorer |
| 8092 | simulation API (`city.sim.serve`) |

All servers bind to 127.0.0.1.

Served this way the explorer reads the two APIs.  The published explorer is
the static export instead (`clojure -M:demo export`), deployed to
`https://simm.is/city/` separately from the website; see
[`deploy/README.md`](deploy/README.md).

To develop against local checkouts of raster and spindel placed next to this
repository, add the `:local` alias: `clojure -M:local:dev`.

## Licence

The code is released under the MIT licence (see `LICENSE`).  Data is not part
of the repository; each source keeps its own licence (see `DATA.md`), and
published outputs derived from OpenStreetMap are subject to the Open Database
Licence.  The explorer bundles MapLibre GL JS (BSD-3-Clause) and deck.gl (MIT).

## Vancouver research archive

The shared explorer includes regional Vancouver, UBC and the North Shore, the
full roster and routed sample, and the East Hastings grocery comparison. The
[scientific exposition](public/vancouver-methods.html) explains the population
behind each result. The [source register](public/sources/weekday.json) identifies
the inputs. The regional validation tables are in the [city evidence page](public/vancouver-model.html).

The retired Vancouver workbench included the street-level driving prototype,
the population atlas inspector, transit experiments and alternate shopping
scenarios. The original source, commands and interface are preserved in the
[workbench revision](https://github.com/replikativ/city-rstr/tree/ebaecc15f7d583633580b7009137393e4be892d8).
Its corresponding built artifact on the publishing machine is
`dist/city-previews/c05e52956d9ee807c7c61141328e9f7f134526427a4e7399831ceea930865b7d/`.
