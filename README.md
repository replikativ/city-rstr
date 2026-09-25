# city-rstr

A data-grounded simulation of Stuttgart, and Bayesian inference over it.

**This is a research prototype, not a library.** There is no release, the
namespaces and functions change without notice, and nothing here is meant to
be depended on.  The code is published so that readers can see how the model
is built and check it against its description.  Results are conditional on the
assumptions stated in [`doc/model.md`](doc/model.md) §11, several of which are
placeholders, and the published posterior is approximate.  The numbers are not
forecasts.

## What the model does

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

## Reading

- [`doc/model.md`](doc/model.md) (rendered as `public/model.html`): the model
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
