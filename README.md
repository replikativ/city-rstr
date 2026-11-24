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

With the published datasets in `public/data`, run `npm run overview:build` to regenerate the shared engine products (first rebuild the regional grocery catalogue with `python3 -m scripts.vancouver_market ../Simulations/city --data public/data/vancouver/region --continuous`), `npm run release` to compile the explorer, and `npm run preview:bundle` to assemble the checked static preview. The initial Stuttgart build reads the source archive at `../Simulations/city`. Serve the bundle with `python3 -m scripts.preview_local --directory dist/city-previews/current` and open the [local explorer](http://127.0.0.1:8191/city/).

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
  `python3 dev/render_model.py`): the model
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

## Run the Vancouver walking replay

From the repository root, build the sampled weekday with the local Vancouver archive. The exporter uses Clojure and Python with NetworkX, SciPy, matplotlib and openpyxl.

```sh
python scripts/vancouver_walks.py ../Simulations/city --replicates 12
python -m http.server 8187 --bind 127.0.0.1 --directory public
```

Open [Mount Pleasant weekday](http://127.0.0.1:8187/vancouver.html). Click a walker to follow their route, use the timeline to set the time of day, or select one of four surveyed intersections to compare observed and modelled traffic by hour. The first seed supplies the map. The hourly table shows the lowest and highest weighted passings across the runs. Omit `--replicates` for a single replay or use `--seed` to choose a different first seed. The generated replay includes its street geometry and works without a tile service. [Model and data assumptions](doc/vancouver.md#mount-pleasant-walking-replay)

### Compare two grocery openings

Build the grocery comparison using the same archive, then open **Shop opening** in the Vancouver replay.

```sh
python -m scripts.vancouver_grocery ../Simulations/city --replicates 12
```

Choose the baseline or either address. Change the choice assumptions to see how the same demand responds to shorter opening hours, a preference for the new shop, a broader competitor inventory, or employment-weighted workplace locations. Select a changed trip and press **Play** to follow the shopper. **Inspect evidence** shows paired site differences, the lunchtime diagnosis and the reserved Broadway surveys. [Pilot specification](doc/vancouver.md#two-site-grocery-pilot)

### Citywide population atlas

The municipal builder needs the 2021 Geographic Attribute File in addition to the census archive. Pass its ZIP with `--geography` or place it at `data/mobility/2021_92-151_X.zip`. [Archive and download command](doc/vancouver.md#walk-to-a-local-grocer)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_atlas ../Simulations/city
python -m http.server 8187 --bind 127.0.0.1 --directory public
```

Open the [2021 Vancouver population atlas](http://127.0.0.1:8187/population.html). Select a home neighbourhood or census dissemination area to audit the population and compare census shares. Inspect any household or resident, scrub the weekday from 04:00 to 04:00, or copy the URL to return to that resident. The generator uses the local census and street archives, Clojure, NumPy, SciPy and DuckDB with its spatial extension installed. [Population model and output format](doc/vancouver.md#citywide-population-atlas)

Use **Test household income and commuting against the census** to compare the roster with published local distributions and the original metro donors. Select **Local housing values and costs** for owner-estimated dwelling values, mortgage prevalence and tenant costs. New population builds publish these checks. To regenerate both reports for existing city and regional releases, run `python -m scripts.vancouver_population_check ../Simulations/city`. [Grandview-Woodland commute check](http://127.0.0.1:8187/population.html?area=Grandview-Woodland&check=commute) · [Kitsilano housing](http://127.0.0.1:8187/population.html?area=Kitsilano&housing=1)

### Follow a Vancouver resident

Build the atlas first, then build the day assignments and the offline street scene in the same checkout. The street builder uses the MapLibre runtime from `npm ci`.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_cityday ../Simulations/city
python -m scripts.vancouver_streets ../Simulations/city
python -m scripts.vancouver_short_walks
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_city_transit ../Simulations/city
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_inbound ../Simulations/city
```

Open [A Vancouver weekday](http://127.0.0.1:8187/cityday.html) or choose **Follow on the city map** in an atlas household. The counts cover the full resident roster. The map animates a fixed sample of 6,622 residents and can follow any resident by ID. Choose **Drive here** or **Walk here** to enter the street network at the centre of the map. Hold the up arrow to advance. Left and right queue a turn at the next junction. [Spatial assignments and limits](doc/vancouver.md#citywide-spatial-weekday)

Build the optional 3D ground surface with `python -m scripts.vancouver_terrain --fetch`. Pitched street views use it automatically when the tiles are installed. [Drive in Lynn Valley](http://127.0.0.1:8187/cityday.html?coverage=region&place=lynn&street=drive&at=-123.039500,49.337300,35) · [Elevation data and dependencies](DATA.md#vancouver-terrain)

Build the 2025 LiDAR building height overlays with `python -m scripts.vancouver_building_heights --fetch`. In **Map → Building heights**, compare LiDAR estimates with the original heights. The **Go to a place** menu includes Downtown and Commercial Drive. [Walk downtown](http://127.0.0.1:8187/cityday.html?street=walk&camera=eye&at=-123.1209,49.2831,325&minute=1020&buildingHeights=f3560690e7b3c4089774) · [Sources and dependencies](DATA.md#vancouver-building-heights)

Build separate roof levels with `python -m scripts.vancouver_roof_sections`. Use **Show separate roof levels** in **Map → Building heights** to compare the same scene with one height per building. [Explore Downtown roofs](http://127.0.0.1:8187/cityday.html?place=downtown&minute=1020&buildingHeights=1c6664a5c10104f0a211)

Build the five elevated road decks with `python -m scripts.vancouver_decks --fetch`. Choose **Cross Lions Gate Bridge** in the scenario menu to drive over Burrard Inlet at deck height. [Lions Gate street view](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&decks=b90d91ccc87929d229c6&street=drive&camera=eye&at=-123.139263,49.314678,31&minute=480) · [Deck geometry and sources](doc/vancouver.md#bridge-decks)

Open **Rush hour in Downtown** for hourly, morning or afternoon flows by travel mode and residents’ home neighbourhood. The station check compares matched riders with published SkyTrain traffic for six Downtown stations. Under **Scheduled transit**, select a route to see residents walking to and from its stops. Select a purple or orange dot, or choose **Follow a walking rider**, to follow their trip. [Morning peak](http://127.0.0.1:8187/cityday.html?downtown=am) · [99 B-Line](http://127.0.0.1:8187/cityday.html?service=99)

Choose **City residents and incoming workers** in the Downtown panel to include workers from other Metro Vancouver municipalities. Filter by home municipality and open **Inspect incoming workers** to see a worker’s usual mode, workplace and schedule. The incoming-worker builder runs Raster on the JVM by default. Add `--backend ze:0 --verify-workers` to check grouped and individual execution on a Level Zero GPU. [Combined morning rush](http://127.0.0.1:8187/cityday.html?downtown=am&commuters=combined&minute=480) · [Cohort assumptions and checks](doc/vancouver.md#incoming-workers-and-downtowns-workday)

To compare a grocery opening on that same day, run `python -m scripts.vancouver_market ../Simulations/city` after building the day and street files. Open **Open a grocery shop** on the city map, select a neighbourhood and storefront, then choose **Follow this visit**. Switch back to **Existing grocers only** to compare the same resident at the same minute. [Manitoba Street example](http://127.0.0.1:8187/cityday.html?shop=37) · [Model and scope](doc/vancouver.md#opening-a-grocery-on-the-citywide-weekday)

Under **Household food budgets within walking distance**, select the walking time and the share of annual food spending assigned to the closest grocer. The shop build also computes these catchments using Raster on the JVM. To rebuild only the household analysis and verify both fidelities on an Intel Level Zero GPU, run `python -m scripts.vancouver_household_market ../Simulations/city --backend ze:0 --verify-households`. [Budget assumptions and sources](doc/vancouver.md#household-grocery-spending-within-walking-distance)


### Explore UBC and the North Shore

After building the City atlas and installing the browser dependencies with `npm ci`, build the regional view from the same archive. The first run downloads the campus boundary, campus buildings and regional OpenStreetMap extract into `data/region`. Subsequent builds can pass `--reuse-inputs` to reuse the extracted geographies.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_region ../Simulations/city
```

Select **Vancouver, UBC & North Shore** in the population atlas or weekday map. Jump to a campus or North Shore street, follow a resident, or open **Regional transit** to see vehicles from the September 15, 2026 timetable. [Campus atlas](http://127.0.0.1:8187/population.html?coverage=region&area=UBC+Vancouver+campus) · [UBC street view](http://127.0.0.1:8187/cityday.html?coverage=region&place=ubc) · [Lonsdale and the SeaBus](http://127.0.0.1:8187/cityday.html?coverage=region&place=lonsdale&service=SeaBus) · [Regional model](doc/vancouver.md#ubc-and-the-north-shore)

Under **Vehicle counts on bridges**, compare free-flow driving with the measured Highway 1 travel times. Select an hourly count to follow a resident or incoming worker using the same route costs. [Afternoon Ironworkers comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=5bea5bc3322eb2bbae9f&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=pm&bridgeMetric=highway1) · [Timing model and build](doc/vancouver.md#observed-highway-1-travel-times)

The **Downtown workplace fit** compares two weekday assignments against the same bridge counts. Open **North Shore residents’ downtown workplaces** to see the survey shares by municipality and follow an exchanged worker. [Morning Lions Gate comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1) · [Workplace model and results](doc/vancouver.md#downtown-workplaces-for-north-shore-commuters)

The eastern workplace replay follows North Shore commuters to assigned jobs in Burnaby and New Westminster. Open the workplace table to see each municipality’s census target and follow a commute. [Morning Ironworkers comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=c1b31a9daf40041dcb73&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1) · [Eastern workplace model](doc/vancouver.md#workplaces-in-burnaby-and-new-westminster)

Open **Compare with the North Shore travel survey** to compare weekday trip rates by mode, purpose, hour and home municipality. On the downtown-fit weekday, you can replay reconstructed short walks between assigned places. [Compare trip purposes](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&northDemand=North+Shore&northBreakdown=purposes) · [Demand and survey definitions](doc/vancouver.md#north-shore-resident-travel-demand)

Open **Add shopping and recreation outings** to follow a resident to a shop or recreation site and back. Choose walking, driving, cycling or a scheduled bus. [Replay the complete outings](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&outingsRun=78d6fe9df0b082599d8f) · [Outing model](doc/vancouver.md#additional-north-shore-shopping-and-recreation-outings)

In the UBC view, open **UBC campus weekday** and scrub the time to see who is on campus. Click an hour in the chart to compare arrivals and departures, or choose **Follow a campus transit rider** to board the same scheduled vehicle shown on the map. The regional build includes this analysis. To regenerate it for an existing regional release, run `python -m scripts.vancouver_campus`. [Campus demand and timetable assumptions](doc/vancouver.md#ubc-weekday-demand-and-scheduled-riders)

Open [Campus café catchments at Mercante](http://127.0.0.1:8187/cityday.html?coverage=region&place=ubc&cafe=mercante&cohort=students&minute=720) to compare the resident weekday with external student or employee attendance. Change the location or scrub the clock to see the five-minute walking catchment. Select a building point to inspect external attendance there. To rebuild for the current regional day, run `OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_visitors ../Simulations/city`. [Attendance and catchment specification](doc/vancouver.md#external-campus-attendance-and-caf%C3%A9-catchments)

### Raster weekday scenarios

The city and regional weekday builds include a paired work-from-home scenario under **Working from home**. The area totals and travel changes come from Raster. Select an area and choose **Compare a worker** to see where a resident spends the same part of the day in each case. [Regional comparison](http://127.0.0.1:8187/cityday.html?coverage=region&policy=50&minute=540) · [Model and fidelity checks](doc/vancouver.md#raster-weekday-execution)

The default build runs the grouped kernel on the JVM. To dispatch that phase on a Level Zero GPU and check the individual-resident execution as well, run the following from the checkout. Omit `--region` for the municipal day.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_raster --region --backend ze:0 --verify-agents
```

### Vancouver resident workplaces

Open the [Downtown commute with external workplaces](http://127.0.0.1:8187/cityday.html?workplaces=census&downtown=am&commuters=combined&minute=720). Under **Residents working outside Vancouver**, select a municipality to inspect a resident or compare the daytime population of a neighbourhood. Switch **Residents’ workplaces** to compare both geographies. [Model and evidence](doc/vancouver.md#resident-workplaces-outside-vancouver)

Choose **Compare a commute** to inspect one external trip. Switch between the travel diary and the resident’s usual commute mode at the same minute. Choose a worker age to compare both estimates with the census. [Paired commute replay](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=usual&downtown=am&commuters=combined&minute=480)

Under **Neighbourhood commute modes**, select a home neighbourhood to compare the original worker population, the fitted population and the local census shares. Follow a walking or cycling commute to see its street route and compare the travel time with the diary. The panel shows how many trips in that neighbourhood exceed their travel-time budget before and after the mode assignment. Choose **Cycle here** to ride from the centre of the map. Hold the up arrow to move and use the left or right arrow to choose a turn at the next junction. [Neighbourhood replay](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=local&downtown=am&commuters=combined&minute=480) · [Calibration and travel-time checks](doc/vancouver.md#neighbourhood-commute-calibration)

Choose **Compare a workplace change** to see how an existing worker's trip changes when they take another job slot in the same neighbourhood and occupation. The inspector compares that assignment with the shortest possible walk to any licensed site. [Paired Downtown walk](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=sites&downtown=am&da=59150777&person=124&minute=1035) · [Workplace matching](doc/vancouver.md#matching-walking-commuters-to-existing-workplaces)

Open **Do trips stay in the home zone?** to compare the simulated weekday with Vancouver's 2023 travel survey. Select work, other home-based trips, or trips between two non-home stops. The boundary filter repeats the calculation away from uncertain zone edges. [Explore the nine-zone comparison](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=sites&zones=work) · [Methods and findings](doc/vancouver.md#travel-within-the-home-zone)

Switch **Workplace assignment** to **Census tract employment** to see the effect on the same day. Select **Follow a reassigned worker** to compare that person's workplace at the same minute. **Rush hour in Downtown** shows the resulting arrivals and departures by mode. [Open the paired weekday](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&zones=work&downtown=am&minute=720) · [Workplace model and limits](doc/vancouver.md#assigning-workplaces-across-census-tracts)

To rebuild from the current city release and archived census sources, run the following commands. Add `--backend ze:0` to the outbound data build for a Level Zero GPU. The normal frontend watch and release scripts include the ClojureScript workplace inspector.

```sh
mkdir -p data/mobility
curl -fL https://www150.statcan.gc.ca/n1/tbl/csv/98100462-eng.zip -o data/mobility/98100462-eng.zip
python -m scripts.vancouver_outbound ../Simulations/city
python -m scripts.vancouver_worksites
curl -fL https://www.arcgis.com/sharing/rest/content/items/31b1106ca5fb4c91b303e26f446eb173/data -o data/mobility/taz-gvrd.geojson
python -m scripts.vancouver_survey_zones
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver experiments
```

With the workplace table and tract boundaries archived as described in [DATA.md](DATA.md), build the paired run with `python -m scripts.vancouver_tract_scenario ../Simulations/city`.

Then run `python -m scripts.vancouver_market ../Simulations/city --workplaces-only` to evaluate grocery openings on that census-workplace day. Pick **Follow next arrival** to meet a shopper, or select a blue dot to follow their walk. **Existing grocers only** restores the incumbent stores for comparison. [Open 2541 Kingsway](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&shop=4654&minute=600) · [Shop results and coverage](doc/vancouver.md#opening-the-same-shop-with-census-workplaces)

For the pedestrian check, compile the shared workplace lookup with `clojure -M:ui -m shadow.cljs.devtools.cli release vancouver`, then run `python -m scripts.vancouver_pedestrians ../Simulations/city` with the short-walk and census-workplace runs in place. **Pedestrian counts at intersections** compares both weekdays to the City sheets. Select a model count to follow one of its walkers. [Open the Ontario & 5th comparison](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&crossing=1&minute=720) · [Definitions and results](doc/vancouver.md#full-roster-pedestrian-counts-at-six-intersections)

Enable **Include walks to and from scheduled transit** to compare the hours with directly matched transit journeys. The counts to and from stops link to riders at the passing second. Add `--verify-routes` to the pedestrian build to reproduce every hourly count using independent Dijkstra trees and the pilot's survey-radius calculation before publishing the release. A municipal transit build also writes the route walking index. To recreate only that index, run `python -m scripts.vancouver_city_transit ../Simulations/city --index-walks-only`.

**When residents leave for work** compares one replayed weekday with the 2021 census by home neighbourhood. Select a home area or follow a resident leaving at the busiest minute. Rebuild the two geographic extents with `python -m scripts.vancouver_departures ../Simulations/city`. [Open the comparison](http://127.0.0.1:8187/cityday.html?departures=) · [Timing model and coverage](doc/vancouver.md#when-residents-leave-for-work)

Choose **Match household commute times** in the departure comparison to replay the same population with complete worker diaries conditioned on household microdata. The worker button shows both departure times and opens the revised trip. Rebuild with `python -m scripts.vancouver_departures ../Simulations/city --match-households`, then `python -m scripts.vancouver_market ../Simulations/city --household-clock` for municipal grocery openings. [Compare the two weekdays](http://127.0.0.1:8187/cityday.html?clock=household&departures=Downtown) · [Method, coverage and sensitivity](doc/vancouver.md#matching-a-complete-weekday-to-household-commute-times)

**Saved shop openings** keeps experiments in a local Datahike database across reloads. Save a storefront under two opening schedules, compare their shoppers, then follow a visit under either schedule. The map reopens the archived market and resident releases. The grocery builder publishes the archive alongside its usual catalogue. Use `npm run release` to build the browser modules. [Try 2541 Kingsway](http://127.0.0.1:8187/cityday.html?shop=4654) · [Storage and replay](doc/vancouver.md#saved-shop-openings)

Choose **Custom hours** to test a daytime or overnight shift. **Who would visit?** shows how many source diaries supply the simulated shoppers. [Try the evening shift at 488 Robson Street](http://127.0.0.1:8187/cityday.html?shop=2726&hours=20:00-08:00) · [Evening demand and its evidence](doc/vancouver.md#setting-shop-hours-and-checking-diary-support)

Street mode draws nearby pedestrians and cyclists from the complete municipal or regional roster. Choose **Drive here**, **Walk here** or **Cycle here**, move with the arrow keys, then follow a nearby resident. **Link to this street** reopens the scene. The weekday and household-clock builders publish the hourly index. For an existing release, run `python -m scripts.vancouver_street_walks`, adding `--region` or `--clock household` for those variants. [Drive by the Robson evening shop](http://127.0.0.1:8187/cityday.html?street=drive&at=-123.117837,49.279749,0&minute=1205&shop=2726&hours=20:00-08:00) · [Coverage and verification](doc/vancouver.md#exploring-a-street-among-resident-pedestrians)

**Bicycle counts on city streets** compares resident cycling trips with City counts at Arbutus and West 10th and on the 700 block of Powell Street. Select an hourly model count to follow a rider through the site. [Compare bicycle traffic](http://127.0.0.1:8187/cityday.html?cycleCheck=arbutus) · [Coverage, results and rebuild instructions](doc/vancouver.md#bicycle-counts-on-city-streets)

Choose **Prefer City bikeways** to compare route choices for the same cyclists. The hourly table shows the City count and both simulations. Select a simulated count to follow a rider or inspect the upper bound on how many residents could reach a junction in time. [Try Ontario and 5th](http://127.0.0.1:8187/cityday.html?bikeRoutes=bikeways&cycleCheck=ontario5) · [Model assumptions and results](doc/vancouver.md#a-paired-test-of-bicycle-route-choice)

**Prefer bikeways and gentler hills** adds an uphill preference to the same bikeway comparison. The route inspector and nearby riders use the selected profile. [Compare uphill routing at Ontario and 5th](http://127.0.0.1:8187/cityday.html?bikeRoutes=hills&cycleCheck=ontario5) · [Grade model and count results](doc/vancouver.md#hills-in-bicycle-route-choice)

The travel survey comparison also lets you select a home zone and travel mode, inspect trip purposes and follow a resident. The trip counts and the number of source diaries behind them are indexed in the same browser Datahike store as shop experiments. [Inspect cycling in Kitsilano](http://127.0.0.1:8187/cityday.html?demand=360&tripMode=Cycling) · [Population coverage and purpose definitions](doc/vancouver.md#resident-trip-demand-by-home-zone)

The municipal replay can switch complete shopping, dining, recreation and social outings from driving to cycling. Compare the original day with zonal bicycle access from the travel survey, follow each leg of an outing and inspect the changed bicycle counts on city streets. [Try a Kitsilano shopping outing](http://127.0.0.1:8187/cityday.html?cycleTours=access&tourZone=360&tourPurpose=Shopping) · [Assumptions and results](doc/vancouver.md#complete-discretionary-cycling-outings)

The municipal grocery scenario includes arrivals on foot and by bicycle. Switch between the original day and two bicycle-access assumptions, then save and replay individual visits in browser Datahike. [Try 2693 E Hastings Street](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access) · [Model and diary support](doc/vancouver.md#grocery-arrivals-on-foot-and-by-bicycle)

**Check shopping travel and opening hours** compares how residents reach shops with the City's travel surveys. At any storefront, compare the fixed grocery share with historical urban BC diary estimates, apply the eight-hour opening that admits the most visits, and save either run for replay. [Explore shop hours on East Hastings](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&grocery=bc2010&shopCheck=1) · [Survey data and model limits](doc/vancouver.md#survey-based-grocery-demand-and-shop-hours)

The local grocery walking scenario lets eligible drivers choose a closer shop, walk there and back, and keep their original schedule. Its neighbourhood comparison checks the model’s store coverage against Statistics Canada at census reference points. [Follow a shopper on East Hastings](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&grocery=bc2010&localWalk=1&accessCheck=1) · [Assumptions and geographic coverage](doc/vancouver.md#walk-to-a-local-grocer)

### Opening a published city run

The [city run library](http://127.0.0.1:8187/runs.html) opens Stuttgart, the City of Vancouver or Vancouver with UBC and the North Shore. A blank visit to the local site opens the shared weekday map. Existing links to the laboratory and its scenarios still open their selected view.

**Choose a scenario** opens published weekdays and comparisons from either map or from the library. Both maps have playback speed, a time slider and 15-minute steps. In Vancouver, the **Scenarios** tab holds the comparisons and the **Evidence** tab holds the survey checks and model assumptions. You can keep following a resident while switching tabs.

**Compare routes across Burrard Inlet** tests whether the same North Shore drivers could reach their destinations on either bridge within their recorded trip time. The map follows a resident on both feasible routes. The counts show how route choice redistributes the morning traffic. [Open the bridge comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1&bridgeChoice=6f09a6463ee864dcee5b) · [Method and results](doc/vancouver.md#alternative-bridge-routes-for-the-same-drivers)

The browser’s Datahike database indexes each published weekday by city and release. The municipal Vancouver entry links its verified coverage of all 1,016 census areas to the corresponding population atlas. It stores the two Stuttgart shopping-centre scenarios’ mean annual changes in resident spending and their 5th and 95th posterior percentiles for each district. Under **Compare district turnover**, choose a district and open a scenario to inspect its map and evidence. Saved Vancouver openings show visit and resident counts, visits diverted from existing grocers and newly feasible visits. Opening one reloads its market, hours and travel assumptions. Population rosters, map geometry and trajectory files load from the selected release as the simulation needs them. The Vancouver release pins the population, daily schedules and streets, plus the transit feed in the regional view. Optional model layers have their own releases.

After building the Vancouver municipal and regional weekdays and exporting Stuttgart, publish the library and compile its browser modules.

```sh
clojure -M -m city.run-catalog all dist/lab/data/stuttgart
npm run release
```

Pass `stuttgart`, `vancouver` or `region` in place of `all` to publish one study area independently. The publisher fingerprints the exported Stuttgart layers and scenario results. It archives each version under `public/data` before switching the catalogue. Browsers retain previously indexed runs and can reopen them while the corresponding files are served.
