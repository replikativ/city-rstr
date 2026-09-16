# Lab notebook: building the Stuttgart simulation

This is a chronological log of the passes made from 2026-09-10 to 2026-09-16.
Findings are dated, and later passes correct earlier ones; where a figure was
revised, a bracketed note at its first occurrence points to the correction.
The current description of the model is [doc/model.md](model.md), not this
log. The passes about Vancouver describe code that is not part of the public
release. Numbers are model outputs, conditional on the
assumptions stated with them, unless they are marked as observed.

Status 2026-09-10: an end-to-end skeleton runs for Vancouver / Mount Pleasant.
Nothing in it is calibrated yet; its purpose is to make the data → model →
validation loop concrete so the model can decide what data it needs next.

## World

Structure-of-arrays columns (`city.sim.world/build`), chosen so step
functions can move into raster kernels unchanged:

- persons: da, household, age group, sex, labour status, industry, occupation,
  commute mode, school attendance, employed flag, home lon/lat, workplace index
- firms: name, type, lon/lat, employees, food flag, storefront flag, alive

Persons come from `city.synth` (PUMF seed fitted by IPU to dissemination-area
marginals). Firms come from the store through the JSON API: issued licences
with coordinates (rentals excluded) and the storefront inventory; the
`/api/firms` endpoint merges the two through the resolution links so one
business is one firm.

## Modules (`city.sim.modules`)

Each module declares reads/writes over the schema and a step function.

| module | reads | writes | v0 rule |
|---|---|---|---|
| `:workplaces` | employed, home, firm capacity | persons.work | capacity-weighted gravity choice, exp(−d/3 km) |
| `:daily` | work, home, food/storefront flags | visits[firm][hour] | template weekday: worker 9–17 with 55 % lunch near work; non-worker errand near home 60 %; evening food trip 15 % |
| `:firm-year` | visits, storefront flag | firms.alive | closure hazard base·exp(−visits/scale) |

## What the data has already corrected (2026-09-10)

- **Schedules.** TUS 2022 urban weekday diaries (7,017): workers eat at a
  restaurant on ~7–8 % of weekdays and visit a store on ~15–23 %; retirees
  visit stores on ~45 %. The template's 55 % lunch-out rate overstated lunch
  traffic ~7×. `:daily-diaries` samples real chains by person type instead;
  store episodes go to retail places, restaurant episodes to food places, near
  the previous anchor (home or work).
- **Labour market.** Census commuting flows (98-10-0459): 130,595 Vancouver
  residents work in the city, ~60k commute out, ~100k commute in; the city's
  jobs are ~56 % held by residents. A district is not a closed market:
  workplace choice must be city-wide with external in/out commuters.
- **Firms.** Licences and storefronts double counted until merged through the
  resolution links (`/api/firms`): Mount Pleasant 2025 has 7,311 resolved
  businesses, 642 storefronts, 25,315 licensed employees.

## Validation targets available now

- storefront turnover 6–11 %/yr (2020–2025 inventory, name continuity)
- licence employee counts by type (firm-size distribution)
- DA marginals held out from synthesis (occupation)
- Stuttgart: grid population per Stadtbezirk (passes within 1–4 %)

## Known crudeness (ordered by how much it matters)

1. Residents only work inside their own district and all district jobs are
   filled by residents. Fix: commuting flow tables (StatCan 98-10-0459) and
   a city-wide world.
2. Homes are jittered around DA centroids. Fix: place households on lots by
   dwelling type.
3. Schedules are fixed templates. Fix: time-use survey episodes by person type.
4. Trip legs are routed on the OSM street graph (`city.sim.network`: one
   Overpass `way["highway"]` pull over Mount Pleasant + 500 m, 7,170 ways →
   22,485 nodes / 29,152 edges, A* with a haversine heuristic, routes cached
   by node pair — a whole traced day is 1.8 s cold, 0.4 s warm at stride 10)
   and now carry a **mode speed** (see "The movement layer" below), so a leg
   has a routed duration as well as a routed shape. What is still missing is
   congestion, a transit *timetable* (the in-vehicle run follows the street
   graph at a flat 18 km/h, not a line), and choice models that see travel
   time rather than distance decay.
5. Closure hazard has no revenue or rent behind it. Fix: Axtell firm core with
   spatial revenue from visits and rent from assessed values.
6. Store/restaurant choice is nearest-k with distance decay; no attractiveness,
   no capacity, no opening hours yet (OSM hours cover 54 % / 71 %).

## First certified result (2026-09-10, Mount Pleasant)

Target: storefront closure rate by category, pooled over 2020→2025 (name
continuity rule). Observed with binomial standard errors:

| category | n | closure/yr | se |
|---|---|---|---|
| Convenience Goods | 356 | 11.8 % | 1.7 |
| Comparison Goods | 572 | 9.4 % | 1.2 |
| Food & Beverage | 780 | 7.9 % | 1.0 |
| Service Commercial | 1075 | 7.3 % | 0.8 |
| Entertainment and Leisure | 123 | 6.5 % | 2.2 |
| Automotive | 126 | 3.2 % | 1.6 |

Error budget for the visits-only hazard `base·exp(−visits/scale)`:
- compute: 6 seeds, district total ±0.9 % (sd 38 on 4,172 visits); per
  storefront CV 0.55 from one simulated day (falls with more days)
- data: pooling five transitions brought category SEs to 1–2 pp; the category
  spread is now significant (convenience vs services: 5 se)
- model: best fit (base 0.08, scale 80) is flat in visits and predicts
  7.0–7.7 % for every category → cannot reproduce the spread. **The model term
  dominates.** Next move is structure, not compute or data: category-specific
  margins/rent exposure (Axtell core + assessed values), not more seeds.

## Error budget (to implement)

For each target: Monte Carlo variance over seeds (compute), sensitivity to the
data-derived inputs (data), and posterior predictive misfit (model). The agent
loop chooses the cheapest move that shrinks the dominant term.

## Per-storefront identification (2026-09-10, later)

With the fast daily module (84 ms/day) the closure model was tested at the
storefront level: 583 storefronts of 2024 with known 2025 outcome (37 closed).
- The demand coefficient β in h = base_c·exp(−β(v/v̄_c − 1)) is identified by a
  per-storefront Bernoulli likelihood: the maximum is at **β = 0**; AUC 0.62
  comes from category baselines alone; any positive β lowers the likelihood.
  Simulated relative demand (gravity on distance, no attractiveness, no
  capacity) carries no information about which storefront exits.
- Feature screen from the store showed a **temporal leakage trap**: cluster
  size and Overture brand "predict" closure (AUC 0.18 / 0.44) only because the
  Overture/OSM snapshots are from 2026 and closed businesses have vanished from
  them. Rule for the data layer: every claim needs an observation date and the
  model may only use claims dated before the outcome window. The receipt
  carries the acquisition date; per-record dates (Overture `update_time`,
  licence issue dates) must be kept.
- Leakage-free 2024 signals: the only usable one is "no matching 2024 licence"
  (59 % of closers vs 84 % of survivors had one; AUC 0.62 inverted), which mixes
  informality with resolution failure. Business age (licence history since
  2013), years licensed, size, and food category carry no signal at n=583/27.
  Conclusion: one-year storefront exit is largely idiosyncratic given current
  data; the literature anchor is survival by age (Seoul: >50 % of food service
  closes within 3 years), which needs licence history before 2013 (the
  1997–2012 dataset is downloadable) and the Axtell–Guerrero firm kernel for
  size dynamics rather than a visits hazard.

## Firm layer (Axtell–Guerrero kernel), first fit

`city.sim.firms`: monthly activation a; active worker moves to a random
worker's firm (size-biased) w.p. p, to a uniform firm w.p. q, founds w.p. ν.
Initialized from the licence-assigned workforce (26,681 workers, 2,175 firms
with employees). 120 months in ~2 s. Grid over (p, q, ν):
- p 0.05, q 0.05, ν 0.03: tail exponent 1.44 vs 1.50 observed in licence
  employee counts, firm death 7.3 %/yr vs 7–12 % observed exit, job-switch
  1.0 %/month; but firm count grows from 2,175 to 8,300 because founding
  (~80/month) exceeds deaths. Needs size-dependent exit (small firms die more,
  cf. Stuttgart demography: 71 % of births at size 0) and lower ν, or a
  stationarity target. This is a 4-parameter, 4-target problem — the first
  candidate for NPE/ABC rather than a grid.

## First N-ladder (population fraction 10/25/50/100 %, capacities rescaled)

| frac | persons | firm death/yr | switch/mo | tail exponent | max firm | visit Gini |
|---|---|---|---|---|---|---|
| 0.10 | 3,524 | 0.067 | 0.010 | 2.72 | 46 | 0.14 |
| 0.25 | 8,917 | 0.067 | 0.010 | 2.57 | 137 | 0.20 |
| 0.50 | 18,151 | 0.069 | 0.010 | 1.65 | 226 | 0.28 |
| 1.00 | 36,430 | 0.070 | 0.010 | 1.60 | 530 | 0.38 |

As the literature predicts (Axtell 2018/JEL 2025; OpenABM; Wise 2023): rates
of well-mixed kernels (firm death, job switching) are N-invariant and can be
calibrated on small worlds; the size tail, the largest firm, and the
inequality of storefront visits are N-dependent and must be read at full
scale. Storefront visits per resident also drifted with N because external
in-commuters were scaled by capacity while the resident local-work share is
sampled; every constant tied to the sample must be rescaled together
(lesson 13).

### With size-dependent exit (δ on firms of size ≤1) and q/p = θ

| p | θ | ν | δ | firms | max | tail | death/yr | births | deaths | switch/mo |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.05 | 0.4 | 0.005 | 0.10 | 2,187 | 724 | 1.82 | 0.081 | 197 | 176 | 0.007 |
| 0.05 | 0.4 | 0.010 | 0.10 | 2,734 | 664 | 1.82 | 0.108 | 344 | 291 | 0.007 |

Targets: firms 2,175 (stationary), death ~0.09, tail 1.5, switch ~0.01. The first
row is within reach on three of four targets; the tail stays steeper than
observed at this N (tail is N-dependent, see the ladder). Parameters
(a, p, θ, ν, δ) and these four targets are the first NPE/ABC exercise.

## Empirical business survival by age (Mount Pleasant, licences 1997–2026)

`city.synth.survival`: 82,636 licence records → 9,256 businesses (normalized
trade name + civic address; rentals excluded), 7,638 in entry cohorts ≥1999,
right-censored at 2026. Kaplan–Meier:

| age | at risk | hazard | survival |
|---|---|---|---|
| 0 | 7,638 | 0.20 | 0.80 |
| 1 | 5,904 | 0.19 | 0.65 |
| 2 | 4,590 | 0.16 | 0.55 |
| 3 | 3,615 | 0.14 | 0.48 |
| 5 | 2,482 | 0.14 | 0.36 |
| 7 | 1,766 | 0.10 | 0.28 |
| 10 | 1,112 | 0.11 | 0.20 |
| 15 | 492 | 0.11 | 0.12 |

Food and retail follow the same curve (year-0 hazard 0.20 / 0.23). Liability
of newness is the dominant structure: hazard halves between year 0 and year
7, then flattens at ~10 %/yr — consistent with the storefront inventory's
7–12 %/yr for established storefronts and the Seoul anchor (>50 % of food
service gone within 3 years). Caveat: renames and moves count as exits, so
early hazards are upper bounds. This age-stratified hazard is the exit rule
the firm lifecycle should use (FRED-style age-stratified transitions), with
demand entering only as a modifier if it is ever identified.

### Firm kernel with the empirical age hazard × size modifier

`step-aged!`: monthly exit hazard h(age)/12 from the Kaplan–Meier table times
exp(−(size−1)/s0); initial firms get ages drawn from the observed age
distribution of currently licensed businesses. With p 0.05, q 0.02, ν 0.01:

| s0 | firms | tail | death/yr | births | deaths |
|---|---|---|---|---|---|
| 3 | 3,533 | 1.93 | 0.095 | 344 | 335 |
| 30 | 2,723 | 1.82 | 0.129 | 344 | 350 |
| none | 2,490 | 3.41 | 0.151 | 344 | 377 |

Without the size modifier the age hazard kills large old firms as readily as
small ones and the tail collapses (3.4); with s0≈30 the kernel is stationary
(births ≈ deaths), the death rate (13 %/yr) sits between the storefront
inventory (7–12 %) and the licence-level hazard (~15 %), and the tail is 1.8
vs 1.5 observed at this N. Parameters now grounded: hazard table (data),
s0, ν, p, θ (to calibrate).

## Run interface (`city.sim.run`)

`defaults` = documented parameter table with `:prior` on the calibration
targets (p-own-district, workplace and venue distance decay, p-switch, θ, ν,
size-scale); `(run (config overrides) inputs)` → `{:series :summary :world
:firm-state}` with a fixed-shape monthly series (10 keys × 240 months) and a
summary of the target statistics; `distance` is the relative squared error
against `targets`. One full run (world, 20 days, 240 months) takes ~7 s on
the dev JVM; seed-to-seed distance varies 0.22–0.30 at the defaults, which is
the compute floor any calibration must respect.

## First rejection-ABC pass (60 prior draws, 5 targets)

Best 10 % of draws by `distance` (0.25–0.54; median of all 2.6):

| parameter | prior | accepted range (median) |
|---|---|---|
| ν founding | log-U(0.001, 0.05) | 0.005–0.010 (0.007) — stiff |
| p-switch | U(0.01, 0.15) | 0.025–0.089 (0.050) — stiff |
| θ = q/p | U(0.2, 0.9) | 0.26–0.83 — sloppy |
| size-scale | log-U(3, 300) | 7–135 — sloppy |
| workplace decay λ | log-U(1000, 8000) | 1.0–6.7 km — sloppy |
| venue decay | log-U(150, 1500) | 190–835 m — sloppy |
| p-own-district | U(0.2, 0.6) | 0.23–0.54 — sloppy |

Two stiff directions (founding rate, switch rate) and five sloppy ones, as
Bouchaud (2024) predicts. The sloppy parameters need targets that see them:
θ and size-scale need the size tail at full city scale; the distance decays
need commute-duration and visitation-distance marginals (census commute
duration 2611–2617, Schläpfer's r·f collapse); p-own-district needs
district-level place-of-work data, which does not exist publicly and has to
come from the city-wide world. 60 runs × 7 s; a proper NPE needs ~10⁴.

## Multi-scale and multi-fidelity (design, 2026-09-10)

Two different problems that share a vocabulary:

**Simulation fidelity** is a property of the module composition, not of the
view. Every module exists (or should exist) at three fidelities over the same
column schema: *aggregate* (rates per area: employment, visits, closures as
expected counts), *cell* (100 m grid: gravity tables, population cells) and
*agent* (persons, firms, legs). A world is a composition that names one
fidelity per module per area; a fork may refine one district to agent level
while the rest of the city stays aggregate, and the interfaces (what a module
reads and writes) are the contract that makes the swap legal. The reconcile
step between fidelities is a segmented reduce (agents → cell counts → area
rates) and its inverse is a synthesis (rates → cells → agents, the same IPU /
MaxEnt machinery as the population stage). This is what raster is for: the
same kernel body scheduled over agents, cells or areas, with the reduce and
the scan as the fidelity bridges (cf. Covasim's weight columns and the hybrid
metapopulation results in the literature note). The N-ladder is the
experiment that tells which statistics survive each bridge.

**Visualization level of detail** is a property of the view and is solved
independently: individual rings/trails above zoom 13, GPU hexagon aggregation
below, area choropleths below that. The view must never fake fidelity the
model does not have (GlassBox rule): an aggregate-fidelity district shows
rates and expected counts, drawn dashed, never synthetic dots.

Consequences for the roadmap: (1) the city-wide world starts at aggregate
fidelity everywhere and agent fidelity in the districts under study;
(2) each module gets an aggregate twin with a documented reduce;
(3) the console shows the fidelity per area as a layer.


## The movement layer (2026-09-10, later still)

Three pieces landed together: speeds on the graph, GTFS stops, and the first
*movement* validation target.

### Mode speeds

`city.sim.network/mode-router` routes a leg at the speed of its mode — walk
4.8 km/h, bike 15, car 25 (a district door-to-door speed: a leg here is a few
blocks and its time goes into junctions, parking and the first/last block),
transit as *walk to the nearest stop + 5 min wait + 18 km/h in-vehicle + walk
off*, degrading to a walk when there is no stop within reach, when both ends
share a stop, or when the ride would be under 500 m. The mode comes from the
TUS travel episode's location code (`city.sim.day/mode-codes` → walk / bike
/ car / transit); "travel, other" and legs with no travel episode at all are
resolved by distance (walk under 1 km, else car).

The timing rule keeps the data and the model apart. **When the diary timed the
movement, the diary wins** — it measured a real trip — and the routed time is
only used to *flag* the leg when it exceeds the reported duration by more than
2×. **When it did not** (the old flat 15-minute default), the routed time sets
the leg, anchored so the person still arrives when the episode starts.

One full-population traced weekday (57,270 persons, 53,653 diaries, seed 1):

| | legs | share |
|---|---|---|
| all legs | 32,859 | |
| timed by a diary travel episode | 28,049 | 85.4 % |
| **flagged: routed > 2× the diary's duration** | **169** | **0.6 % of timed legs** |
| mode resolved by distance, not by the diary | 5,380 | 16.4 % |
| car | 24,112 | 73.4 % |
| walk | 7,935 | 24.1 % |
| transit | 584 | 1.8 % |
| bike | 228 | 0.7 % |

The flagged share is small, so the diary's own durations and the street network
agree about trip times far more often than not — the 15-minute default was the
part that needed replacing, not the diaries. The **mode mix, on the other hand,
is not this district's**: TUS 2022 gives urban-Canada travel, and 1.8 % transit
legs in a district with a SkyTrain station and the 99 B-Line is not credible.
That is the next data fix (census commute mode is already on every person; the
diary mode needs to be conditioned on it).

Cost: a traced day at stride 1 is 10.2 s with a cold route cache and 0.8 s warm.

### GTFS (`city.intake.gtfs`)

TransLink's static feed is read in place out of its 16 MB zip: stops in a bbox,
the routes that call there, and one streaming pass over `stop_times.txt`
(1.84 M rows after the weekday-service filter) for the 07:00–19:00 weekday
departure count per stop → mean headway = 720 / departures. Weekday service is
`calendar.txt` rows with Monday–Friday set and not both weekend days, so
holiday and special-event patterns cannot pass as a typical day.

Mount Pleasant + 300 m: **125 stops, 114 with weekday service**, 2.5 s. Broadway
@ Fraser 2.3 min mean headway (routes 8/9/99), Main St–Science World 2.4 (Expo
Line), 26 stops under 6 min, 48 between 12 and 30, 11 with no weekday service in
the window. The table is written once to
`data/derived/mount_pleasant_gtfs_stops.json` with a receipt; the stops are
installed into the router as transit access points and served as
`GET /sim/stops?area=<eid>`, drawn on the map as small hollow squares sized by
headway.

### Pedestrian counts (`city.intake.vancouver-counts`)

The City of Vancouver ArcGIS GDH service has ~2,600 intersection
turning-movement studies with xlsx attachments that count pedestrians per
crosswalk in 5-minute bins. Sixty of them fall in the Mount Pleasant bbox since
2019; **15 weekday studies** (2021–2024, one per intersection, the most recent)
are parsed into `data/derived/vancouver_ped_counts_mp.json` with a receipt.
What the data cost:

- only the 2019 layer returns geometry. Every other year answers the spatial
  query correctly but sends `"geometry": null` whatever `returnGeometry`,
  `outSR` or `f` say — so coordinates come from geocoding the intersection name
  against the OSM street graph already pulled for routing ("W 1ST AV" and "West
  1st Avenue" normalise to the same key; the junction is the shared graph
  node). 25 of 26 resolve to a shared node, one to a within-40 m pair.
- the workbooks pad every hour the study did not cover with zero rows, older
  ones write times as `01:00 PM`, and some split the count into one sheet per
  vehicle class with the `Peds` columns repeated but only one filled.
- **half the studies are Saturdays.** The April 2021 Main Street counts have no
  morning peak at all. Weekend studies are dropped before anything is
  downloaded — a lesson worth generalising: a count without its day of week is
  not a count.

Cold run (15 downloads + openpyxl): 51 s.

## Second certified result: pedestrian counts vs simulated walk legs

`city.sim.validate/pedestrian-counts` runs one traced weekday at full
population (stride 1, seed 1) and counts every **walk** leg whose routed
polyline passes within 30 m of a counted intersection, by hour. Bike, car and
transit legs are excluded. Segments are tested rather than vertices (a
simplified polyline puts two vertices at the ends of a straight block).

Observed / simulated, at the two peak hours and summed over each study's own
observed hours:

| intersection | study date | hrs | in district | 08 obs/sim | 17 obs/sim | obs | sim | sim/obs |
|---|---|---|---|---|---|---|---|---|
| E Broadway & Kingsway | 2021-04-07 | 24 | yes | 240 / 18 | 798 / 19 | 6,905 | 189 | 0.027 |
| Main St & E Broadway | 2021-04-07 | 24 | yes | 228 / 5 | 607 / 6 | 5,193 | 64 | 0.012 |
| W 1st Av & Ontario St | 2023-08-09 | 12 | yes | 244 / 0 | 651 / 1 | 4,363 | 10 | 0.002 |
| Main St & E 2nd Av | 2021-04-21 | 24 | yes | 227 / 8 | 253 / 6 | 3,471 | 49 | 0.014 |
| Ontario St & E 5th Av | 2023-07-12 | 12 | yes | 278 / 2 | 301 / 5 | 3,273 | 79 | 0.024 |
| E 12th Av & Main St | 2021-04-07 | 22 | yes | 39 / 5 | 334 / 6 | 3,088 | 98 | 0.032 |
| Commodore Rd & Spyglass Pl | 2022-06-29 | 15 | no (475 m) | 135 / 0 | 217 / 0 | 2,526 | 0 | 0.000 |
| Fraser St & E Broadway | 2023-05-04 | 7 | yes | 229 / 4 | 528 / 6 | 2,291 | 39 | 0.017 |
| Ontario St & W 10th Av | 2023-07-12 | 12 | yes | 150 / 3 | 267 / 2 | 2,021 | 19 | 0.009 |
| Prince Edward St & E Broadway | 2023-04-05 | 7 | yes | 156 / 0 | 417 / 7 | 2,006 | 27 | 0.013 |
| W 2nd Av & W 5th Av | 2022-11-10 | 4 | no (401 m) | 440 / 1 | 733 / 1 | 1,870 | 4 | 0.002 |
| E 12th Av & Kingsway | 2021-04-15 | 24 | yes | 169 / 13 | 164 / 15 | 1,663 | 129 | 0.078 |
| Kingsway & Fraser St | 2023-04-26 | 7 | yes | 85 / 1 | 288 / 4 | 1,308 | 15 | 0.011 |
| Prince Edward St & E 16th Av | 2023-05-25 | 7 | yes | 49 / 0 | 76 / 0 | 376 | 0 | 0.000 |
| W 12th Av & Alberta St | 2024-10-30 | 4 | yes | 35 / 3 | 26 / 2 | 108 | 15 | 0.139 |

Hourly profile (matched cells only, i.e. summed over the intersections that
observed that hour):

| hour | sites | observed | simulated | sim/obs |
|---|---|---|---|---|
| 06 | 5 | 270 | 11 | 0.041 |
| 07 | 15 | 1,434 | 64 | 0.045 |
| 08 | 15 | 2,704 | 63 | 0.023 |
| 09 | 13 | 2,117 | 29 | 0.014 |
| 12 | 9 | 2,882 | 38 | 0.013 |
| 15 | 13 | 3,843 | 42 | 0.011 |
| 16 | 15 | 4,769 | 124 | 0.026 |
| 17 | 15 | 5,660 | 80 | 0.014 |
| 18 | 12 | 4,109 | 72 | 0.018 |
| 20 | 6 | 923 | 26 | 0.028 |

Headline numbers (205 intersection-hour cells):

| statistic | all 15 sites | the 13 inside the district |
|---|---|---|
| Σ observed | 40,462 | 36,066 |
| Σ simulated | 737 | 733 |
| **ratio sim/obs** | **0.018** | **0.020** |
| Pearson across sites, 08:00 | 0.11 | 0.29 |
| Pearson across sites, 17:00 | 0.30 | 0.41 |
| hourly-profile correlation (24 hours) | **0.86** | |

### The honest reading

**The model reproduces the shape of the day and almost none of its volume.**

The profile correlation of 0.86 says the simulated walking has a morning rise, a
midday plateau and an evening peak in the right places — the diaries carry the
clock and the routing carries it onto the street. The cross-sectional
correlations (0.29 at 08:00, 0.41 at 17:00 among district sites) say the model
is only weakly right about *which* intersection is busy; it puts too much of its
walking on the quiet residential crossings (W 12th & Alberta: 0.14 of observed)
and far too little on the arterial ones (Main & Broadway: 0.012).

The level is off by a factor of **~50** (2.0 % of observed). Four causes, in
descending size, and none of them is a bug:

1. **No through traffic.** The world is one local area. Everyone crossing Main
   & Broadway on their way from Riley Park to a SkyTrain platform, every
   in-commuter, every transfer at the 99 B-Line — none of them exists. The two
   sites that lie inside the bbox but outside the modelled area (Commodore &
   Spyglass, W 2nd & W 5th) simulate exactly zero, which is the same effect at
   its limit.
2. **Too few trips.** 32,859 legs from 53,653 diaries is **0.61 legs per person
   per day**, against ~3 trips/person/day in any travel survey (MiD Stuttgart
   3.2). (Corrected in the eighth pass: 3.2 is the 2017 figure; the MiD 2023
   estimate for Stuttgart is 2.86 trips per person per day.) The daily module only emits four destination types —
   home, work/school, store, restaurant — so school runs, errands, escorting, sport, visits and
   every walk that is its own purpose are missing.
3. **Too little walking in the mix.** 24 % of legs are walked, against a walk
   mode share above 30 % for trips inside a district like this one, and the
   1.8 % transit share means the walk *to* and *from* transit — a large part of
   what a downtown-facing arterial counts — is both rare and (deliberately) not
   counted here.
4. **A crossing is not a passer-by.** The observed value sums the `Peds` column
   over all four approaches, so it counts crosswalk crossings; the simulated
   value counts people whose route passes the intersection. A pedestrian
   crossing two legs of an intersection is counted twice by the workbook and
   once by the model. This is worth a factor between 1 and 2, no more.

Error budget for this target: the **model term dominates by an order of
magnitude** over anything else. Compute is negligible (one seed at full
population is 0.8 s warm; the counts are integers in the hundreds, so seed noise
is percent-level, not 50×). Data is small: the observed counts are single-day
studies at 15 intersections spread over 2021–2024, so day-to-day variation is
maybe ±20 % and the 2021 studies are pandemic-era (if anything they *under*-state
today's volumes, which makes the gap worse, not better). The next moves are
structural and in this order: (a) a city-wide world with commuting flows so
through traffic exists, (b) the missing trip purposes in the daily module, (c)
diary modes conditioned on the district's own mode split, and only then (d)
counting transit access walking as walking.

What this target *is* already good for: it is the first check that can falsify a
routing change. The profile correlation and the per-site ratios move when speeds,
modes or the network change, and they cost under a second to recompute.

## Third certified pass: a destination for every diary location (2026-09-10, later)

The reading above named "too few trips" as the second-largest cause of the
50× miss. The daily module emitted destinations for four diary locations out
of thirteen, so every episode at a park, a clinic, a gym, a friend's flat or
"elsewhere" was a stay with no journey. All thirteen now have somewhere to go.

### Where the new destinations come from

| diary location | destination | source |
|---|---|---|
| :work-or-school (no workplace, in school) | a school | OSM `amenity=school/kindergarten/college/university` |
| :clinic | a clinic | `amenity=clinic/doctors/dentist/hospital`, `healthcare=*` |
| :outdoors | a park | `leisure=park/playground/pitch/dog_park` |
| :sports-venue | a gym or sports centre | `leisure=sports_centre/fitness_centre/…`, `amenity=dojo` |
| :culture | a museum, gallery, library, theatre, community centre | `tourism=museum/gallery`, `amenity=library/theatre/…` |
| :worship | a place of worship | `amenity=place_of_worship` |
| :other-home | another resident's home ≤ 1.5 km | occupied home cells, weighted by residents |
| :neighbourhood, :elsewhere | a street-graph node ≤ 500 m of the anchor | the routing network itself |
| :business | an employer firm | firms with employees, weighted by size |

`city.sim.venues` reads the *cached* Overpass `pois-and-buildings` pulls whose
bbox overlaps the world's (no new download) into a flat class/lon/lat table:
Mount Pleasant + 500 m gives **434 venues from 34 pulls in 3.3 s** — 169
outdoors, 103 clinic, 59 sports, 40 culture, 34 school, 29 worship. Each class
becomes one more gravity CSR over the same 100 m grid (784 cells) and is drawn
by the same binary search as a store, so there is one code path for venue
choice, not nine. The two classes that are *neighbourhood* by definition use a
new `max-m` bound on the choice set (1.5 km, 500 m) instead of pure distance
decay. Table build for the whole world: **6.8 s** (was ~1 s), once per world.

Two rules that had to come with it:

- **A stay is a stay.** The TUS splits an episode whenever the *activity*
  changes, so eating and then socializing at one restaurant is two episodes at
  one place. `split-chain` now collapses consecutive same-location episodes
  with no travel between them; without it, every such pair would draw a second
  venue and invent a trip. Side effect: a day at a workplace is one visit, not
  four, and storefront visits/day fall from 5,201 to 3,981. That is double
  counting removed, not demand removed.
- **No workplace is not a school.** Only someone actually in school walks to a
  school; a resident whose job is outside the district still has no
  destination, because that trip needs the city-wide world.

### Mode from the district's own census

Every person now draws **one default mode per person-day** from the commute-mode
split of their own dissemination area (census 2021 characteristics 2604 car,
2607 transit, 2608 walked, 2609 bicycle, 2610 other), and that mode is used for
the legs whose diary carries no travel episode. The diary's own mode still wins
where it exists; the distance rule (walk under 1 km, else car) survives only
for "travel, other". Pooled over the district's 47 DAs the census says: **car
50.4 %, transit 21.0 %, walk 15.9 %, bike 9.9 %, other 2.9 %**.

| | legs | share | before |
|---|---|---|---|
| all legs | 82,067 | | 32,859 |
| timed by a diary travel episode | 57,664 | 70.3 % | 85.4 % |
| flagged: routed > 2× the diary's duration | 506 | 0.9 % of timed legs | 0.6 % |
| mode from the diary's own travel episode | 56,237 | 68.5 % | 83.6 % |
| **mode from the home DA's census split** | **23,690** | **28.9 %** | — |
| mode resolved by distance | 2,140 | 2.6 % | 16.4 % |
| car | 60,116 | 73.3 % | 73.4 % |
| walk | 15,979 | 19.5 % | 24.1 % |
| transit | 2,805 | 3.4 % | 1.8 % |
| bike | 3,167 | 3.9 % | 0.7 % |

**The census split moved transit and bike, and it moved walking the wrong
way.** It only reaches the 29 % of legs the diary does not time; the other 70 %
still carry TUS 2022's urban-Canada mode, which is 73 % car. The distance rule
it replaced walked everything under a kilometre, and most of the untimed legs
are short, so trading it for a 50 % car / 16 % walk split lowered the walk
share even while doubling the number of walked legs. The real fix is the one
the last pass already named and this one does not do: condition the *diary's*
mode on the district's split, not just the fallback.

### Legs

| | legs | per person-day |
|---|---|---|
| before | 32,859 | 0.61 |
| **now** | **82,067** | **1.53** |
| TUS 2022 itself (travel episodes per weekday diary) | | **1.90** |
| travel surveys (MiD Stuttgart) | | ~3.2 (2017; 2.86 in MiD 2023, see the eighth pass) |

By purpose: home 33,452 · other 18,369 · store 10,192 · leisure 8,969 ·
restaurant 3,540 · work 4,903 · school 2,642.

The 1.53 is now close to the ceiling the diaries themselves impose: the TUS
weekday chains contain 1.90 travel episodes per diary, not 3. The 0.37 the
model still loses against its own input is almost entirely commuting it cannot
place — 18,793 residents work outside the district and 20,840 in-commuters have
no home in it, so neither end of those journeys exists. Closing the gap from
1.90 to ~3 is not a modelling bug to fix here: it is the difference between a
time-use diary (episodes ≥ 10 min, one day, everyone 15+, including the 48 % of
person-days with no trip at all — 32 % of the weekday diaries, 29 % by weight)
and a trip-based travel survey. If ~3 is the
target, the trip generator needs a travel survey behind it, not the TUS.

### Pedestrian counts, rerun (stride 1, seed 1, warm cache, 1.6 s)

| statistic | before | now | all 15 sites | in-district (13) |
|---|---|---|---|---|
| legs per person-day | 0.61 | **1.53** | | |
| walk legs | 7,935 | **15,979** | | |
| walk share of legs | 24.1 % | 19.5 % | | |
| Σ observed | | | 40,462 | 36,066 |
| Σ simulated | 737 | **2,469** | 2,469 | 2,449 |
| **ratio sim/obs** | **0.018** | **0.061** | 0.061 | 0.068 |
| Pearson across sites, 08:00 | 0.11 / 0.29 | **0.11 / 0.33** | 0.108 | 0.331 |
| Pearson across sites, 17:00 | 0.30 / 0.41 | **0.39 / 0.50** | 0.386 | 0.504 |
| hourly-profile correlation | 0.86 | **0.91** | | |

Per site (observed / simulated at 08 and 17, then over the study's own hours):

| intersection | in district | 08 obs/sim | 17 obs/sim | obs | sim | sim/obs |
|---|---|---|---|---|---|---|
| E Broadway & Kingsway | yes | 240 / 55 | 798 / 54 | 6,905 | 670 | 0.097 |
| Main St & E Broadway | yes | 228 / 19 | 607 / 18 | 5,193 | 222 | 0.043 |
| W 1st Av & Ontario St | yes | 244 / 8 | 651 / 12 | 4,363 | 97 | 0.022 |
| Main St & E 2nd Av | yes | 227 / 26 | 253 / 22 | 3,471 | 289 | 0.083 |
| Ontario St & E 5th Av | yes | 278 / 17 | 301 / 20 | 3,273 | 171 | 0.052 |
| E 12th Av & Main St | yes | 39 / 26 | 334 / 36 | 3,088 | 282 | 0.091 |
| Commodore Rd & Spyglass Pl | no (475 m) | 135 / 0 | 217 / 0 | 2,526 | 0 | 0.000 |
| Fraser St & E Broadway | yes | 229 / 7 | 528 / 12 | 2,291 | 81 | 0.035 |
| Ontario St & W 10th Av | yes | 150 / 19 | 267 / 15 | 2,021 | 104 | 0.051 |
| Prince Edward St & E Broadway | yes | 156 / 22 | 417 / 22 | 2,006 | 133 | 0.066 |
| W 2nd Av & W 5th Av | no (401 m) | 440 / 6 | 733 / 7 | 1,870 | 20 | 0.011 |
| E 12th Av & Kingsway | yes | 169 / 25 | 164 / 30 | 1,663 | 308 | 0.185 |
| Kingsway & Fraser St | yes | 85 / 9 | 288 / 6 | 1,308 | 55 | 0.042 |
| Prince Edward St & E 16th Av | yes | 49 / 1 | 76 / 0 | 376 | 3 | 0.008 |
| W 12th Av & Alberta St | yes | 35 / 8 | 26 / 7 | 108 | 34 | 0.315 |

Hourly profile (matched cells only):

| hour | 06 | 07 | 08 | 09 | 12 | 15 | 16 | 17 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|
| observed | 270 | 1,434 | 2,704 | 2,117 | 2,882 | 3,843 | 4,769 | 5,660 | 4,109 | 923 |
| simulated (before) | 11 | 64 | 63 | 29 | 38 | 42 | 124 | 80 | 72 | 26 |
| **simulated (now)** | 28 | 153 | 248 | 130 | 148 | 200 | 277 | 261 | 252 | 97 |

### The honest reading, again

**The volume gap closed by a factor of 3.4 and the model is still 16× short.**

What moved and why: the extra destinations put 2.5× as many legs on the
network and doubled the walked ones, and the profile correlation rose from 0.86
to 0.91 because the new purposes fill the middle of the day (the midday and
afternoon hours were the worst-fitting part of the old profile: 0.013 of
observed at 12:00, now 0.051). The cross-sectional fit improved where it
should — inside the district at the evening peak, 0.41 → 0.50 — because
errands, sport, visits and "elsewhere" walk along the commercial streets rather
than only between homes and the same handful of storefronts. The remaining
08:00 correlation of 0.11 over all sites is still noise: the two out-of-district
sites simulate ~0 and the morning peak is dominated by commuting the world does
not contain.

What did not move: **the level, because through traffic is still the biggest
missing term.** 18,793 residents work outside the district and 20,840
in-commuters have no home in it; their journeys are exactly the ones that cross
Main & Broadway. Main & Broadway is still at 0.043 of observed while the quiet
residential crossing W 12th & Alberta is at 0.315 — the same signature as
before, an order of magnitude weaker. And the walk share *fell* (24 % → 19.5 %),
so part of the volume gain was spent on legs that are driven; on the pedestrian
target specifically, conditioning the diary's mode on the district's census
split is now worth more than any further trip purpose.

Error budget: the model term still dominates by an order of magnitude, and the
ordering of the next moves is unchanged except that (b) is now done —
(a) a city-wide world with commuting flows, (c) diary modes conditioned on the
district's own mode split (which the fallback alone cannot do), and only then
(d) counting transit access walking as walking. What this pass proves is that
the target is sensitive: adding purposes moved every statistic in the table,
and none of them by an amount that could be mistaken for noise (one seed at
full population costs 1.6 s).

## The city-wide world (2026-09-11)

Known crudeness item 1 — "residents only work inside their own district and all
district jobs are filled by residents" — is closed. `city.sim.cityworld/build`
puts all 22 Vancouver local areas in one world at agent fidelity.

| stage | cost | result |
|---|---|---|
| `cw/build` :sample **1.0** | **63 s** | 670,883 residents + 94,960 in-commuters = **765,843 persons**, **89,965 firms** |
| `day/prepare` (city grid) | **112 s** | 147 × 111 = 16,317 cells of 100 m, 11 gravity CSRs, 4,547 venues from 252 cached OSM pulls |
| `network/load!` (city pull) | **4.4 s** | **232,290 nodes / 298,512 edges** from 72,688 ways |
| GTFS city stop table | 7.4 s | **2,488 stops**, 2,348 with weekday service |
| `step-day` | **0.7 s** | 690,553 diaries, 60,218 storefront visits |
| `step-day-traces` stride 10 | 225 s cold | 104,957 legs over 37,866 traced people |

Heap after the whole thing, on the 4 GB dev JVM: **~600 MB**. The sample did not
have to be reduced; the two things that would not have fitted were fixed
instead. The 49 MB highway pull is now parsed **one element at a time** off a
`PushbackReader` (`network/stream-elements!`) rather than as one Clojure value,
and `step-day-traces` takes a `:trace-fn` so a traced day can be *reduced* as it
is produced instead of collected (a city day at stride 1 is ~1 M polylines).

### The labour market is the census's, not the capacity's

The first city build produced **250** external in-commuters where the census
counts 94,960 — and that is the whole point of a city-wide world, so it is worth
saying exactly what was wrong.

The synthetic population has **367,341 employed** Vancouver residents. The
commuting table (98-10-0459) counts **193,970** residents with a *usual place of
work*: 130,595 in the city, 63,375 outside it. The rest — 173,748 people —
worked at home or had no fixed workplace address (2021 is a pandemic census and
the work-at-home share is large). The old rule sent 67.3 % of *all* employed
residents to a city firm, which is 247,696 people; the licensed capacity
rescaled to the census job count is 225,555, so residents filled it and the
in-commuters were squeezed out by the leftover-capacity rule.

`labour-roles!` now draws each employed resident's destiny from the census
proportions directly, and appends `jobs − jobs held by residents` in-commuters
regardless of what is left over:

| role (`:workstat`) | simulated | target |
|---|---|---|
| works in the city | 130,217 | 130,595 (census) |
| commutes out of the city | 63,376 | 63,375 (census) |
| no fixed workplace (home / variable) | 173,748 | 173,371 (residual) |
| external in-commuter | 94,960 | 94,960 (census) |

The three census rows land within 400 people; the fourth is the residual of the
synthetic employed count against the census's usual-place-of-work total, so it
inherits both of their errors and is the least certain number in the table. The cost is that the 47 % of employed residents
with no fixed workplace now make no commute leg at all, which is the honest
reading of the 2021 data and not a modelling convenience — it is also why the
work-leg share of the day is lower than a pre-pandemic travel survey would give.

### One weekday, city-wide (seed 1)

`step-day` over 765,843 persons in **0.7 s**: 690,553 diaries, 151,669 work
episodes, 154,474 store visits, 49,352 restaurant visits, 60,218 of those
landing on a *storefront*. Traced at stride 10 (104,957 legs, 37,866 people,
1.52 legs per traced person-day — the same rate as the district):

| purpose | legs (stride 10) |
|---|---|
| home | 44,821 |
| store | 15,325 |
| other | 14,350 |
| leisure | 11,392 |
| work | 9,199 |
| school | 4,985 |
| restaurant | 4,885 |

| mode | legs (stride 10) | share | at stride 1 | Mount Pleasant district run |
|---|---|---|---|---|
| car | 82,098 | 78.2 % | 811,082 | 73.3 % |
| walk | 12,529 | 11.9 % | 125,353 | 19.5 % |
| transit | 8,122 | 7.7 % | 81,110 | 3.4 % |
| bike | 2,208 | 2.1 % | 21,724 | 3.9 % |
| **all** | **104,957** | | **1,039,269** | |

The stride-10 day extrapolates to the full-population one to within 1 %
(1,049,570 against 1,039,269 actual), which is the sampling check that makes the
cheaper stride usable for the console and the OD matrix.

The pooled census commute-mode split over all of Vancouver's DAs is car 57.0 %,
transit 23.2 %, walk 12.9 %, bike 4.9 % — the whole city drives and rides more
than Mount Pleasant does, and the legs follow. Two other numbers moved with the
scale: **15.5 %** of diary-timed legs are now flagged `:slow` (the routed time is
more than twice the diary's own), against 0.9 % in the district, because a
city-wide trip is long and TUS 2022 measures urban-Canada trips that mostly are
not; and the route cache hit rate fell to 84 % (from ~95 % in one district),
which is what makes a traced day minutes rather than seconds.

### Area fidelity as a reduce

`cityworld/area-aggregates` reduces a finished run to one row per local area —
residents, resident workers, jobs, in- and out-commuters, storefronts and their
visits — plus the origin–destination matrix of resident trips, counted on the
traced day and multiplied by its stride. This is the *reconcile step* the
multi-scale note calls for (agents → area rates), and it is what the zoomed-out
console draws instead of hexagons: an aggregate is drawn as a rate with a dashed
outline, never as synthetic dots (GlassBox).

The commuting picture it produces is recognisably Vancouver's:

| area | residents | jobs | in-commuters | out-commuters | storefront visits/day |
|---|---|---|---|---|---|
| Downtown | 77,326 | 110,987 | 104,118 | 18,263 | 9,467 |
| Hastings-Sunrise | 35,687 | 14,843 | 13,677 | 8,349 | 2,294 |
| Fairview | 33,448 | 13,524 | 13,130 | 10,510 | 3,001 |
| Mount Pleasant | 36,430 | 13,050 | 12,430 | 12,463 | 3,332 |
| West End | 45,719 | 11,299 | 10,727 | 14,533 | 4,379 |
| Kitsilano | 42,341 | 8,377 | 8,006 | 13,113 | 5,331 |
| Renfrew-Collingwood | 54,208 | 7,631 | 6,971 | 14,360 | 4,577 |

Top inter-area flows of the OD matrix (scaled from stride 10): West End →
Downtown 12,990 and back 12,780; Fairview → Downtown 5,610; Mount Pleasant →
Downtown 5,190; Kitsilano → Downtown 4,480. Downtown receives 214,250 of the
1,049,570 modelled trip legs (residents and in-commuters together) — 20 % of all movement, from 12 % of the
population and 49 % of the city's fixed jobs.

**A caveat that belongs with the number.** The workplace choice is a
capacity-weighted gravity draw with λ = 6 km, not an observed flow matrix:
public data has commuting flows at the *municipality* level only, so
area-to-area commuting is a model output, not a calibration target. What the
census pins is the three city-level totals in the table above. The OD matrix is
therefore the first quantity in this model that is worth *predicting* and cannot
yet be *checked* — the honest use of it is as a hypothesis about where the
gravity assumption breaks, not as a measurement.

## The Stuttgart world (2026-09-11)

The same three files the Vancouver city world consumes — a persons EDN, a firm
JSON, a commute-shares EDN — built for Stuttgart **from aggregates only**.
Germany publishes no public microdata seed at city level (the Mikrozensus SUF
needs an FDZ contract), so there is nothing to reweight the way
`city.synth.ipu` reweights the Canadian PUMF. `city.synth.stuttgart` and
`city.synth.stuttgart-firms` synthesize directly from marginals instead;
`city.sim.cityworld/build-stuttgart` assembles the world.
`scripts/stuttgart_world.clj` runs the whole chain.

| stage | cost | result |
|---|---|---|
| `ss/cache-cells!` (store read, once) | 4 s | 7,692 populated 100 m cells, 610,444 people |
| `ss/synthesize!` | 9 s | **610,444 persons in 294,642 households** |
| `sf/cache-places!` (point-in-polygon) | 6 s | **25,743** Overture places inside a Stadtteil |
| `sf/build!` | 3 s | 25,743 firms, 507,605 employees |
| `cw/build-stuttgart` :sample **0.1** | **14 s** | 61,083 residents + 32,615 in-commuters, 25,743 firms |
| `cw/build-stuttgart` :sample **1.0** | **57 s** | 610,444 residents + 326,153 in-commuters = **936,597 persons** |

The finished world holds ~113–220 MB of columns; the dev JVM sat at 1.8 GB of
its 4 GB after the 1.0 build, most of that the synthesis stage's own garbage in
the same REPL.

### Where every attribute comes from

The person rows carry the **Vancouver key vocabulary** (PUMF codes), so
`persons-columns` and every diary module read them unchanged: `:AGEGRP`
1–13, `:GENDER` 1 women / 2 men, `:LFACT`, `:NAICS`, `:NOC21`, `:MODE`,
`:ATTSCH`, `:da`, `:la`, `:hh`, `:size`. `:da` is a Zensus 100 m cell id
rather than a dissemination area and `:la` is a Stadtteil rather than a local
area; nothing else changes, and the home jitter drops from 0.002° (a DA) to
0.0013° (a 100 m cell).

| attribute | source | how |
|---|---|---|
| where | Zensus 2022 100 m grid, cells located to Stadtteile in the store | one cell = one `:da`; 7,692 populated cells sum to 610,444, the city total |
| age | `:cell/age`, 19 five-year bands → 13 PUMF bands | suppressed bands filled from the Stadtteil's own age profile |
| household size | `:cell/household-size`, 6 classes | same fill; sizes reconciled to the cell's population |
| sex | Regionalstatistik **12411-04-02-4** (Fortschreibung 31.12.2022, single years of age × sex, Kreis 08111) | P(male) per 5-year band: 0.516 at 0–4 falling to 0.311 at 90+ |
| employment | Zensus 2022 Regionaltabelle Bildung+Erwerbstätigkeit, Gemeinde 08111000, sheet `CSV-ET_Alter` | Erwerbstätige in 15–19/20–29/…/60–67/68+ over the grid's population in the same span → P(employed \| band): 0.265 at 15–19, 0.80–0.82 at 30–59, 0.54 at 60–64, 0.08 at 70+ |
| unemployment | same table, `CSV-Erwerbsstatus`: 22,380 Erwerbslose of 338,280 Erwerbspersonen | LFACT 9 drawn over the non-employed 15–74 at p = 0.147 so the city total lands on 22,380 |
| school | same workbook, `CSV-Schulform`: 62,860 Personen in schulischer Ausbildung | ATTSCH 1 at p = 0.80 for ages 5–19, plus 45 % of 20–24 |
| NAICS / NOC21 / MODE | — | 0 (unknown): no German source gives industry, occupation or commute mode by residence at this geography |

### Validation against the resident register

`data/raw/stuttgart/einwohner_altersgruppen_stadtbezirke.csv`
(opendata.stuttgart.de, ISO-8859-1), Stichtag **31.12.2022** — an independent
source from the Zensus, seven months later.

**Total** 610,444 synthetic against 610,010 registered: **+0.1 %**.

**Per Stadtbezirk**, mean absolute error **1.2 %**, worst **4.3 %**:

| Stadtbezirk | register | synthetic | error |
|---|---|---|---|
| Plieningen | 13,686 | 13,098 | −4.3 % |
| Münster | 6,572 | 6,790 | +3.3 % |
| Hedelfingen | 10,322 | 9,989 | −3.2 % |
| Obertürkheim | 8,477 | 8,689 | +2.5 % |
| Bad Cannstatt | 70,867 | 69,759 | −1.6 % |
| West | 52,031 | 52,827 | +1.5 % |
| … 17 others | | | ≤ 1.3 % |
| Birkach | 7,291 | 7,282 | −0.1 % |

**By age band.** The register's ten groups and the PUMF AGEGRP scale agree only
at 0/15/30/45/65/75 (AGEGRP 11 is 55–64), so six bands is the finest honest
comparison:

| band | register | synthetic | error |
|---|---|---|---|
| 0–14 | 80,721 | 82,556 | +2.3 % |
| 15–29 | 117,959 | 119,594 | +1.4 % |
| 30–44 | 143,522 | 141,220 | −1.6 % |
| 45–64 | 156,570 | 153,603 | −1.9 % |
| 65–74 | 51,512 | 51,102 | −0.8 % |
| 75+ | 59,726 | 62,369 | +4.4 % |

Held out entirely: **employment**. The synthesis produces 317,679 employed
against the Zensus's 315,900 (+0.6 %) and 22,691 unemployed against 22,380
(+1.4 %); 303,335 men against the Zensus's 303,207. **Household sizes** against
the published cell counts: 1-person 135,458 vs 143,556 (−5.6 %), 2-person
78,791 vs 81,594 (−3.4 %), 3-person 34,507 vs 33,500, 4-person 27,095 vs
25,926, 5-person 11,315 vs 9,075, 6+ 5,713 plus a 1,763-household tail of 7–10
(the published 6+ class is 5,568).

### The firm register

25,743 Overture places inside a Stuttgart Stadtteil. **OSM shops and amenities
are not merged in** — the place/POI matching step the Vancouver world does is
skipped here, so this is Overture only, and the count is what the source has,
not what the Unternehmensregister counts (32,158 Niederlassungen in 2024).

Sizes are synthesized in three steps:

1. **Section.** Each Overture category is mapped to a WZ-2008 section by a
   prioritised keyword table (`stuttgart-firms/category-rules`): food and
   lodging → I, schools → P, dentist/physio/pharmacy → Q, lawyer/architect/
   engineering/consulting/advertising → M, software/telecom/publishing → J,
   bank/insurance → K, real estate → L, logistics → H, trades → F,
   manufacturing → C, utilities → BDE, government → O, museums/gyms/venues →
   R, shops and car trade → G, agencies/cleaning/rental → N, everything else →
   S. 928 categories that are infrastructure (ATMs, car parks, EV chargers,
   lakes, monuments) get **zero** employees so nobody is ever sent to work
   there.
2. **Size.** Kreis 08111's four size classes (52111-01-02-4, 2024: 26,486 /
   4,290 / 1,125 / 257) give a city-wide class distribution; per section it is
   exponentially tilted (MaxEnt under one moment constraint) so its mean equals
   that section's own employees-per-Niederlassung from 52111-02-01-4 and
   52111-07-01-4. A firm then draws log-uniformly inside its class. The 250+
   class has no published upper bound; 1,300 is the value at which the four
   class means reproduce the Kreis's 499,665 employees over 32,158
   Niederlassungen, so it is calibrated rather than guessed.
3. **Place.** Each Stadtbezirk × section cell is scaled to a target, and the
   target is **not** the CKAN table's level. `unternehmen_svb_stadtbezirke.csv`
   counts 311,797 SvB against the BA's 435,469 at workplaces in Stuttgart, and
   its coverage is worst exactly where Overture is best (Gastgewerbe: 6,456
   against the Unternehmensregister's 25,578). So the *level* per section comes
   from the Kreis register and the *spatial shares within a section* from CKAN:
   target(bezirk, section) = URS employees(section) × CKAN share(bezirk \|
   section). A pair CKAN does not list is a pair it asserts has no employment
   there; those places fall to a one-person floor.

Result: 507,605 employees over 25,743 firms, every section within 0.1–7 % of
its Unternehmensregister total (S is +6.7 %, the floor; the rest under 3 %),
median firm 2, p99 279, largest 11,670.

| section | URS Niederlassungen | Overture places | URS employees | synthetic |
|---|---|---|---|---|
| C manufacturing | 908 | 446 | 75,809 | 75,912 |
| M professional | 7,393 | 3,378 | 67,011 | 68,081 |
| Q health | 2,294 | 1,713 | 64,074 | 64,437 |
| G retail | 4,060 | 3,775 | 46,775 | 48,034 |
| N business services | 2,075 | 954 | 44,862 | 44,502 |
| J information | 2,112 | 829 | 39,298 | 39,484 |
| K finance | 991 | 804 | 29,600 | 29,891 |
| I hospitality | 2,276 | 2,555 | 25,578 | 26,432 |
| H transport | 998 | 483 | 24,560 | 24,168 |
| P education | 840 | 1,271 | 21,936 | 21,964 |
| S other services | 2,513 | 6,040 | 18,730 | 19,978 |
| F construction | 2,109 | 628 | 16,502 | 16,662 |
| R arts, recreation | 1,168 | 1,105 | 10,902 | 11,232 |
| L real estate | 2,177 | 514 | 6,661 | 6,846 |
| BDE utilities | 244 | 41 | 6,212 | 6,165 |
| O public admin | — | 279 | — | 2,416 |

The firm-count column is the honest failure: Overture over-represents
consumer-facing sectors (S 6,040 places against 2,513 registered
Niederlassungen; I 2,555 against 2,276) and badly under-represents the
office sectors (M 3,378 against 7,393; L 514 against 2,177; F 628 against
2,109). Scaling employment per cell fixes the *level* but not the *count*, and
where a section has few places and much employment the employment piles onto
them: the largest synthetic firm is a winery with 11,670 synthetic
employees, which is really the payroll of the Mercedes-Benz plant in
Untertürkheim landing on the only section-C place nearby. Section O is outside both registers and is left
unconstrained.

Storefronts: Vancouver reads "storefront" off an observed storefront
inventory; Stuttgart has none, so the 6,330 retail (G) and hospitality (I)
places stand in for it.

### Commuting

`data/derived/stuttgart_commute_shares.edn`, from the **Bundesagentur für
Arbeit** Gemeindedaten der Beschäftigungsstatistik, 30.06.2024, Gemeinde
08111000 (`gemband-dlk-0-202406.xlsx`, fetched without login):

| BA, SvB only | |
|---|---|
| am Wohnort | 267,688 |
| am Arbeitsort | 442,289 |
| Wohnort = Arbeitsort | 165,914 |
| Einpendler | 276,247 |
| Auspendler | 101,756 |

BA counts only sozialversicherungspflichtig Beschäftigte — no self-employed, no
Beamte, no marginal-only jobs — and covers 267,688 of the Zensus's 315,900
employed residents, **84.7 %**. The job count is lifted by that same factor on
the assumption that the uncovered employment commutes like the covered kind:
`:share-work-in-city` 0.6198, `:jobs-in-city` **521,948**,
`:share-jobs-held-by-residents` 0.3751.

Germany measures no "no fixed workplace / worked at home" category, so the
third Vancouver role is empty here and 1,783 people land in it only as the
residual between the synthetic employed count and the Zensus's. At sample 1.0
the world produces 195,484 residents working in the city (target 195,795),
120,412 commuting out (BA's 101,756 × 1.18 = 120,073) and 326,153 external
in-commuters (276,247 × 1.18 = 326,464).

The resulting job geography is recognisably Stuttgart's — the industrial and
office belts, not the old town:

| Stadtbezirk | residents | resident workers | jobs | in-commuters |
|---|---|---|---|---|
| Möhringen | 33,741 | 16,733 | 66,896 | 62,656 |
| Mitte | 23,619 | 13,949 | 61,537 | 60,084 |
| Vaihingen | 46,516 | 24,166 | 57,820 | 52,728 |
| Feuerbach | 30,988 | 15,822 | 49,180 | 46,511 |
| West | 52,827 | 29,711 | 47,988 | 42,954 |
| Bad Cannstatt | 69,759 | 36,418 | 38,902 | 34,658 |
| Zuffenhausen | 38,294 | 19,608 | 36,690 | 35,635 |

That ordering is the CKAN table's, not a model output: Möhringen, Feuerbach,
Vaihingen, Mitte and Zuffenhausen are its five largest SvB totals. Mitte
placing second rather than first is inherited from the source — several of the
city's biggest employers are registered at addresses outside the centre.

### Every assumption, in one place

1. **Sex is age-specific but not cell-specific.** No public source crosses age
   with sex below the Kreis, and the Zensus 2011 100 m grid (which does) is no
   longer at the URLs the 2011 release used. The 12411 ratios are a 2022
   Fortschreibung, not the Zensus.
2. **Cell-key noise is reconciled to the published total.** A 100 m cell's
   bands are noised independently of its total, so published bands can sum
   above the total (3,142 of 7,692 cells) or below it with nothing suppressed
   (85 cells). Both are rescaled to the total by largest remainder. 874 cells
   publish no age band at all and 427 no household total; those take the
   Stadtteil profile and the Stadtteil mean household size.
3. **"6 Personen und mehr" is expanded, not truncated.** Counting it as 6
   leaves the cell short of its own population; the shortfall enlarges those
   households first (to at most 10) and only then creates one-person
   households. This is why the synthetic 5-person count overshoots by 25 %.
4. **Households are assembled adult-first**: one adult (AGEGRP ≥ 4) per
   household, then children into the largest remaining slots, then the rest of
   the adults. No relationship, marital-status or family-type structure is
   modelled, and there is no correlation between a household's size and its
   members' ages beyond that rule.
5. **P(employed | age) is uniform within a Zensus age band** and identical for
   men and women — the Gemeinde table publishes employment by age and by sex
   but not by age × sex.
6. **45 % of 20–24-year-olds are in education.** The Zensus Schulform table
   counts general schools only and Hochschule enrolment is published by place
   of study, not residence. This number is a national Bildungsbeteiligung
   figure, the one input here with no Stuttgart source behind it.
7. **Industry, occupation and commute mode are unknown** (NAICS/NOC21/MODE 0),
   so any module that conditions on them treats Stuttgart people as a single
   class. Mode in particular: the Vancouver world draws a person-day mode from
   the census commute-mode split of their own DA, which has no German
   counterpart at this geography; MiD 2017/2023 is the source that would fix it
   and it needs a research application.
8. **The employment universe differs from the population universe** by 2.7 %:
   the Erwerbsstatus table covers the 593,900 people in private households, the
   grid counts 610,458 residents. No rescale is applied.
9. **Dates do not line up.** Grid and Gemeinde tables 2022-05-15; register
   2022-12-31; sex ratio 2022-12-31; Unternehmensregister 2024; CKAN firms 2020;
   BA commuters 2024-06-30; Overture places 2026-08-19. The world is labelled
   2025.
10. **Overture only, no OSM merge, no deduplication.** A business with a Meta
    and a Foursquare record is two firms.
11. **`:cell/household-size` in the store holds only the total.** The loader's
    `pick` regex read `\d` as an escaped backslash, so the six size classes
    were never transacted; the regex is fixed in `city.load.census` but the
    store is not reloaded here, and the histograms are read from the adopted
    grid extract instead.
12. **Place → area links in the store are broken for Stuttgart.** An earlier
    `load-overture!` ran with a `stadtteile` that returned the area *name*, so
    a string went into a ref attribute: 18,245 of the 25,743 Stuttgart places
    point at phantom entities and only 7,498 carry a real Stadtteil ref
    (`repair-area-links!` exists for exactly this and has not been run over all
    of them). `cache-places!` therefore repeats the point-in-polygon assignment
    locally from the same two adopted files — 25,743 places, which is
    7,498 + 18,245 exactly.

## Fourth certified pass: pedestrian counts with through traffic (2026-09-11)

The last two passes both named the same missing term first: *no through traffic*
— "the world is one local area… everyone crossing Main & Broadway on their way
from Riley Park to a SkyTrain platform, every in-commuter, every transfer at the
99 B-Line — none of them exists." The city-wide world exists now, so the same
target can say how big that term actually was.

Same target, same 15 Mount Pleasant intersections, same rule (a **walk** leg
whose routed polyline passes within 30 m, counted by hour; bike, car and transit
excluded). What changed is only the world: 765,843 persons instead of 57,270,
the whole city's firms and venues, and a 232k-node street graph.

Run: seed 1, **stride 1** (every person), 1,039,269 legs of which **125,353 are
walked**, **2,041 s** (the cost is A*: 1.3 M route calls at an 84 % cache hit
rate; the district run was 1.6 s).

| statistic | district run | **city run** | change |
|---|---|---|---|
| persons | 57,270 | **765,843** | |
| legs / traced person-day | 1.53 | **1.51** | — |
| walk legs | 15,979 | **125,353** | ×7.8 |
| Σ observed (205 cells) | 36,066 (13 sites) / 40,462 (15) | 40,462 | |
| Σ simulated | 2,449 / 2,469 | **12,024** | ×4.9 |
| **ratio sim/obs** | **0.068** / 0.061 | **0.297** | **×4.4** |
| Pearson across sites, 08:00 | 0.331 / 0.108 | **0.427** | |
| Pearson across sites, 17:00 | 0.504 / 0.386 | **0.414** | |
| hourly-profile correlation | **0.91** | **0.615** | **worse** |

(The district table reported 13 "in-district" sites separately because two of
the 15 lay outside the modelled area. In the city world every site has a
simulated home within 200 m, so that split is gone and the two columns are one.)

### Per site

| intersection | hrs | 08 obs/sim | 17 obs/sim | obs | sim | sim/obs | was |
|---|---|---|---|---|---|---|---|
| E Broadway & Kingsway | 24 | 240 / 464 | 798 / 275 | 6,905 | 2,809 | 0.407 | 0.097 |
| Main St & E Broadway | 24 | 228 / 78 | 607 / 63 | 5,193 | 466 | 0.090 | 0.043 |
| W 1st Av & Ontario St | 12 | 244 / 53 | 651 / 33 | 4,363 | 299 | 0.069 | 0.022 |
| Main St & E 2nd Av | 24 | 227 / 79 | 253 / 48 | 3,471 | 670 | 0.193 | 0.083 |
| Ontario St & E 5th Av | 12 | 278 / 17 | 301 / 17 | 3,273 | 103 | 0.031 | 0.052 |
| E 12th Av & Main St | 22 | 39 / 45 | 334 / 33 | 3,088 | 311 | 0.101 | 0.091 |
| Commodore Rd & Spyglass Pl | 15 | 135 / 36 | 217 / 34 | 2,526 | 378 | 0.150 | **0.000** |
| Fraser St & E Broadway | 7 | 229 / 16 | 528 / 14 | 2,291 | 83 | 0.036 | 0.035 |
| Ontario St & W 10th Av | 12 | 150 / 16 | 267 / 13 | 2,021 | 114 | 0.056 | 0.051 |
| Prince Edward St & E Broadway | 7 | 156 / 41 | 417 / 29 | 2,006 | 185 | 0.092 | 0.066 |
| W 2nd Av & W 5th Av | 4 | 440 / 611 | 733 / 350 | 1,870 | 1,911 | **1.022** | 0.011 |
| E 12th Av & Kingsway | 24 | 169 / 443 | 164 / 250 | 1,663 | 2,651 | **1.594** | 0.185 |
| Kingsway & Fraser St | 7 | 85 / 451 | 288 / 254 | 1,308 | 1,888 | **1.443** | 0.042 |
| Prince Edward St & E 16th Av | 7 | 49 / 10 | 76 / 9 | 376 | 41 | 0.109 | 0.008 |
| W 12th Av & Alberta St | 4 | 35 / 29 | 26 / 28 | 108 | 115 | 1.065 | 0.315 |

### Hourly profile (matched cells only)

| hour | 06 | 07 | 08 | 09 | 12 | 15 | 16 | 17 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|
| observed | 270 | 1,434 | 2,704 | 2,117 | 2,882 | 3,843 | 4,769 | 5,660 | 4,109 | 923 |
| simulated (district) | 28 | 153 | 248 | 130 | 148 | 200 | 277 | 261 | 252 | 97 |
| **simulated (city)** | **275** | **1,842** | **2,389** | 781 | 252 | 454 | 1,881 | 1,450 | 853 | 226 |
| sim/obs (city) | 1.02 | 1.28 | **0.88** | 0.37 | **0.09** | 0.12 | 0.39 | 0.26 | 0.21 | 0.24 |

### The honest reading

**Through traffic was worth a factor of 4.4 overall — and essentially the whole
morning peak.** At 08:00 the model now walks 2,389 people past these
intersections against 2,704 counted (0.88; it was 0.09). At 07:00 it walks
*more* than were counted (1.28). The commute is no longer missing; if anything
the peak is now slightly over-supplied.

**It was worth almost nothing in the middle of the day.** At 12:00 the ratio
went from 0.051 to 0.087 and at 15:00 from 0.052 to 0.118. Through traffic *is*
commuting, and commuting does not happen at noon. What a real arterial counts at
midday is shopping, errands, lunch and walking that is its own purpose — which
the TUS 2022 diaries do emit, but as few, short, and mostly driven trips. The
remaining volume gap is now almost entirely a **midday trip-generation** gap,
and it is the reason the hourly-profile correlation *fell* from 0.91 to 0.615:
the model went from flat-and-uniformly-too-low (which correlates well with a
flat-ish observed day) to peaky-and-right-at-the-peaks with an empty middle. A
matched peak with a hollow midday is a better model and a worse correlation, and
saying so is the point of keeping the statistic.

**The spatial error changed character rather than going away.** Three sites are
now *over*-predicted — E 12th & Kingsway (1.59), Kingsway & Fraser (1.44),
W 2nd & W 5th (1.02) — while the Main Street corridor barely moved: Main &
Broadway 0.043 → 0.090, Ontario & E 5th 0.052 → **0.031** (it went down). The
pattern is legible: **Kingsway is the diagonal shortcut across a rectangular
street grid**, so a shortest-path router sends cross-town walkers along it,
while real pedestrians are on Main Street because that is where the destinations
are. Cross-sectional correlation is held at 0.41–0.43 by this one systematic
substitution. The fix is route choice that is not pure shortest-path (and a
destination-density term on the street), not more agents.

**The clearest single confirmation** is the two sites that lie inside the count
bbox but outside Mount Pleasant. They simulated exactly **zero** in both earlier
passes — the missing-world effect at its limit. They now simulate 378 and 1,911
(1.02 of observed at W 2nd & W 5th). Nothing about their behaviour model
changed; only the world around them did.

Smaller things the table exposes: the model walks at 03:00 (123 against 23
observed), which is a diary-timing artefact worth one look; and the evening
shoulder (18:00–19:00, 0.21 and 0.12) falls off faster than the observed one,
which is the same midday deficit arriving late.

> **Correction (fifth pass).** Every number in this section was produced with
> the shared street network reverted to the *Mount Pleasant* pull:
> `network/route-fn` called `(load!)` unconditionally, which rebuilds the graph
> from the district dataset whenever the city pull is the one loaded, so a
> city-wide population had every leg snapped onto a 22k-node district graph.
> The qualitative finding survives — through traffic is worth a large factor —
> but the levels here are wrong. On the corrected graph the same rules give
> 0.234 rather than 0.297, and 0.099 rather than 0.427 at 08:00. See the fifth
> pass for the re-measured baseline.

**Error budget.** Compute is negligible: one seed at full population, counts in
the thousands. Data is unchanged (15 single-day studies, 2021–2024). The model
term still dominates, but it is no longer the *same* model term — the missing
population is supplied, and what is left is (a) midday trip generation, which
needs a travel survey rather than a time-use diary behind it, (b) route choice
and street-level attractiveness, and (c) the diary's own mode split, which the
city-wide census (car 57 %, walk 12.9 %) makes worse for this target rather than
better. Ordered by size, (a) and (b) are now roughly equal and both above (c).

## Fifth certified pass: the diary's own modes, access walking, route choice (2026-09-11, later)

The fourth pass named three moves: condition the diary's own mode on the census,
count transit access walking as walking, and stop routing every walker down the
shortest path. All three are in. It also, in the process, turned up the reason
its own numbers were too flattering.

### The correction that comes first

`city.sim.network/route-fn` called `(load!)` with no arguments, and `load!`
rebuilds the shared graph whenever the requested pull differs from the loaded
one. The default pull is the *district* one. So every caller that asked for a
router — `validate/simulated-pedestrians` included — silently replaced the
232,290-node city graph with the 22,485-node Mount Pleasant graph, and a
city-wide population then had **both ends of every leg snapped to the nearest
node inside Mount Pleasant**. That is why the fourth pass found sites outside
the district simulating 1.0 of observed and three sites over-predicted: it was
not through traffic arriving, it was the whole city being folded into six
square kilometres.

`route-fn` and `distance-fn` now route on **whatever network is loaded** and
build one only when none is (`:ds` forces a pull). Everything below is measured
on the city graph, and the "previous rules" column is *re-measured* there too,
so the comparison is rules-against-rules and not graph-against-graph.

### The three rules, and their parameters

**1. Mode substitution (`city.sim.day/make-leg`).** Every person already drew
one commute mode from their home DA's census split (externals from the pooled
city split), but the draw only reached the legs the diary did not time; the
other 77 % kept TUS 2022's urban-Canada mode, which is 78 % car. The draw is now
a *profile* that can replace the diary's own mode: one draw per person-day
decides whether the day keeps the diary's modes (probability
`:p-keep-diary-mode`, **0.5**) or takes the census profile for **every** leg of
that day. A profile is not a promise — a "walk" person walks a leg up to
`:profile-walk-max-m` (**2.5 km** crow flight) and rides transit beyond it, a
"bike" person likewise above 8 km — so the rule is consistent within a day and
distance-aware within a leg. When the mode is substituted the *clock* moves with
it: the leg is re-routed at the new mode's speed and re-timed from the routed
time, anchored on the episode's own start minute, because a leg that was driven
and is now walked does not take the driving time. Where the diary's mode
survives, the diary's timing survives with it.

**2. Access and egress walking (`city.sim.network/mode-router`).** A transit leg
was already built as *walk to the nearest stop + wait + ride + walk off*, but it
was emitted as one polyline of mode `transit` and the pedestrian target dropped
it whole. The router now returns the two walk stubs in `:sub-legs` and
`step-day-traces` emits them as legs of their own — mode `walk`, purpose
`access`, flagged `:access` — scaled into the parent leg's span. The in-vehicle
run is still not counted; the walking to and from the stop now is.
(`area-aggregates` skips flagged sub-legs, so the OD matrix still counts one
trip per trip.)

**3. Route diversity (`city.sim.network/router`).** A walk leg no longer takes
the strict shortest path. It draws one of `:route-variants` (**3**)
near-shortest alternatives: variant 0 is the shortest path, the others run the
same A\* over edge lengths multiplied by a deterministic per-edge penalty in
[1, 1 + `:route-jitter`] (**0.3**), hashed on the unordered node pair so both
directions agree and a variant is a fixed alternative network. Each variant
keeps its own route cache, so the alternatives cost cache space rather than a
k-shortest-path search, and the draw is reproducible from the leg's own RNG
stream.

### The day the three rules produce

Seed 1, **stride 2** (every second diary, counts scaled by 2), the city graph,
520,371 traced legs. Stride 2 rather than 1 because a stride-1 pass on the
city graph is ~1.4 M A\* queries at a 39 % cache hit rate; the two runs below
already cost 2,453 s and 2,709 s.

| | previous rules | **now** |
|---|---|---|
| traced legs | 520,371 | 520,371 |
| car | 400,472 (77.0 %) | **350,789 (67.4 %)** |
| walk | 79,228 (15.2 %) | **101,402 (19.5 %)** |
| transit | 29,651 (5.7 %) | **49,837 (9.6 %)** |
| bike | 11,020 (2.1 %) | **18,343 (3.5 %)** |
| legs the diary timed | 402,217 | 402,217 |
| …whose mode the census replaced | — | **201,695 (50.1 %)** |
| mode from the diary | 392,172 | 195,484 |
| mode from the census profile | 115,713 | 313,505 |
| mode by the distance rule (census "other") | 12,486 | 11,382 |
| transit access/egress walk stubs | 59,302 (not counted) | **99,674 (counted)** |
| **walk polylines the target sees** | **79,228** | **201,076** |
| legs flagged `:slow` (routed > 2× the diary) | 3.2 % | **1.6 %** |

Re-timing substituted legs halves the `:slow` share, which is the one
self-consistency check the substitution has: the diary's clock and the router's
clock disagree less when the router is allowed to set the clock for the legs
whose mode it changed.

### Pedestrian counts: district-only, city with the previous rules, city now

| statistic | district-only (stride 1) | city, previous rules (stride 2) | **city, now (stride 2)** |
|---|---|---|---|
| persons | 57,270 | 765,843 | 765,843 |
| street graph | 22,485 nodes | 232,290 | 232,290 |
| Σ observed (205 cells) | 40,462 | 40,462 | 40,462 |
| Σ simulated | 2,469 | 9,464 | **7,656** |
| **ratio sim/obs, all 15 sites** | **0.061** | **0.234** | **0.189** |
| **ratio sim/obs, in-district** | **0.068** (13 sites) | 0.234 (15) | **0.189** (15) |
| Pearson across sites, 08:00 | 0.108 (0.331 in-district) | 0.099 | **0.284** |
| Pearson across sites, 17:00 | 0.386 (0.504 in-district) | 0.150 | **0.343** |
| hourly-profile correlation | **0.91** | 0.651 | **0.715** |
| wall clock | 1.6 s | 2,453 s | 2,709 s |

(In the city world every site has a simulated home within 200 m, so "all sites"
and "in-district" are the same 15; the district run had two sites outside the
modelled area, which is why it reports both.)

Hourly profile (matched cells only):

| hour | 06 | 07 | 08 | 09 | 12 | 15 | 16 | 17 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|
| observed | 270 | 1,434 | 2,704 | 2,117 | 2,882 | 3,843 | 4,769 | 5,660 | 4,109 | 923 |
| simulated (district) | 28 | 153 | 248 | 130 | 148 | 200 | 277 | 261 | 252 | 97 |
| simulated (city, previous rules) | 242 | 1,396 | 1,682 | 768 | 236 | 424 | 1,378 | 1,120 | 728 | 210 |
| **simulated (city, now)** | **152** | **1,078** | **1,124** | **552** | **224** | **378** | **1,114** | **974** | **580** | **196** |
| sim/obs (now) | 0.56 | 0.75 | 0.42 | 0.26 | 0.08 | 0.10 | 0.23 | 0.17 | 0.14 | 0.21 |

Per site, as the ratio sim/obs over the site's own observed hours:

| intersection | hrs | obs | district | city, previous rules | **city, now** |
|---|---|---|---|---|---|
| E Broadway & Kingsway | 24 | 6,905 | 0.097 | 0.279 | **0.184** |
| Main St & E Broadway | 24 | 5,193 | 0.043 | 0.057 | **0.061** |
| W 1st Av & Ontario St | 12 | 4,363 | 0.022 | 0.067 | **0.069** |
| Main St & E 2nd Av | 24 | 3,471 | 0.083 | 0.415 | **0.297** |
| Ontario St & E 5th Av | 12 | 3,273 | 0.052 | 0.032 | **0.043** |
| E 12th Av & Main St | 22 | 3,088 | 0.091 | 0.137 | **0.159** |
| Commodore Rd & Spyglass Pl | 15 | 2,526 | 0.000 | 0.238 | **0.276** |
| Fraser St & E Broadway | 7 | 2,291 | 0.035 | 0.041 | **0.086** |
| Ontario St & W 10th Av | 12 | 2,021 | 0.051 | 0.093 | **0.105** |
| Prince Edward St & E Broadway | 7 | 2,006 | 0.066 | 0.083 | **0.074** |
| W 2nd Av & W 5th Av | 4 | 1,870 | 0.011 | 0.231 | **0.301** |
| E 12th Av & Kingsway | 24 | 1,663 | 0.185 | **1.169** | **0.785** |
| Kingsway & Fraser St | 7 | 1,308 | 0.042 | **1.028** | **0.654** |
| Prince Edward St & E 16th Av | 7 | 376 | 0.008 | 0.250 | **0.165** |
| W 12th Av & Alberta St | 4 | 108 | 0.315 | **1.111** | **0.593** |

### Which of the three moves did what

One seed, **stride 10**, city graph, the moves switched on cumulatively —
`:p-keep`, `:route-variants` and `:count-access?` are parameters of
`validate/pedestrian-counts` precisely so this can be asked. Stride 10
under-counts the level by ~8 % against stride 2, so read the *rows against each
other*.

| | ratio | r 08:00 | r 17:00 | r profile | Main & Bwy | E Bwy & Kingsway | E 12th & Kingsway | Kingsway & Fraser | W 12th & Alberta |
|---|---|---|---|---|---|---|---|---|---|
| A previous rules | 0.216 | 0.161 | 0.209 | 0.629 | 0.050 | 0.266 | 1.064 | 0.894 | 0.741 |
| B + access walking | 0.224 | 0.241 | 0.223 | 0.626 | 0.050 | 0.269 | 1.100 | 0.917 | 0.741 |
| C + mode substitution | 0.191 | 0.349 | **0.447** | 0.634 | 0.060 | 0.194 | **0.800** | **0.543** | 0.741 |
| D + route diversity | 0.188 | **0.370** | 0.452 | **0.646** | **0.064** | **0.188** | 0.752 | 0.558 | **0.556** |

### The honest reading

**The level fell and every fit statistic rose, and that is the result.**
Σ simulated goes 9,464 → 7,656 (0.234 → 0.189 of observed) while the
cross-sectional correlation at 08:00 goes 0.099 → 0.284, at 17:00 0.150 →
0.343, and the hourly profile 0.651 → 0.715. The volume that disappeared was
concentrated in the three sites that were *over*-predicted: E 12th & Kingsway
1.17 → 0.79, Kingsway & Fraser 1.03 → 0.65, W 12th & Alberta 1.11 → 0.59. A
model that is 5× short everywhere is a better description of the truth than one
that is 4× short on Main Street and 15 % over on Kingsway, and the correlations
are the statistic that says so.

**Mode substitution did most of the spatial work, and it did it by *shortening*
walks rather than by adding them.** The ablation is unambiguous: the Kingsway
pair only moves at row C, and the 17:00 correlation doubles there
(0.223 → 0.447). The mechanism is not the walk share — that rose, 15.2 % →
19.5 % — it is the 2.5 km cap in the profile. TUS 2022 reports walk episodes
that the city world turns into 6 km cross-town legs, and the shortest path for
a cross-town leg on a rectangular grid is the Kingsway diagonal. A census "walk"
person who rides beyond 2.5 km stops making those legs and the diagonal empties.
The fourth pass called that a route-choice artefact; it is mostly a *trip
length* artefact.

**Counting access walking is worth +4 % of volume and almost nothing
spatially.** It adds 99,674 walk polylines — as many again as there are walk
legs — but they are the few hundred metres around a stop, and a counted
intersection is not a stop. It is right (that walking is real, and the model now
sees it), it lifts the 08:00 correlation on its own (0.161 → 0.241) because stop
access is concentrated in the commute peak, and it is not where the missing
pedestrians are.

**Route diversity does what it was asked to do, on the street where it matters
least.** W 12th & Alberta, the quiet residential crossing, falls 0.741 → 0.556
at stride 10 (1.111 → 0.593 at stride 2), because a strict shortest path funnels
every walker through the same low-traffic corner; Main & Broadway gains 7 %
(0.060 → 0.064); the Kingsway sites barely move once the long walks are gone.
Off the diagonal and onto the parallel streets is the right direction, and the
effect size is small: ±2 % of total volume.

**What the error budget now says is next.** Compute is no longer free but it is
still not the binding term: 2,453 s + 2,709 s for the two headline runs, 4 × 200
s for the ablation, all at one seed. Data is unchanged (15 single-day studies,
2021–2024). The model term is four things, in this order:

1. **Midday trip generation.** 0.08–0.10 of observed at 12:00–15:00 against
   0.42–0.75 at the morning peak. No rule about *modes* can invent trips the
   generator does not make; this needs a travel survey behind the trip
   generator, not another routing rule. It is the whole remaining shape error in
   the hourly profile.
2. **The 47 % of employed residents with no fixed workplace**, who make no
   commute leg at all (2021 is a pandemic census). Their day is the emptiest
   part of the model and it is exactly the day that would produce midday
   walking. A work-at-home day with local errands is a decision that has not
   been made yet, and it is cheap to make.
3. **Transit-rider walking inside the destination area.** Access and egress
   exist now, but a rider is set down at the nearest stop to their destination;
   the transfer- and platform-walking of a Downtown arrival is not modelled, and
   Downtown receives 20 % of all legs.
4. **Crossing vs passing.** Every observed number is a *crosswalk crossing*
   summed over four approaches; a simulated number is a person passing within
   30 m. A pedestrian who crosses one intersection can enter the observed total
   more than once, so the comparison may carry a factor between 1 and 2 that no
   model change will ever supply. Pinning it from the workbooks' own
   per-approach columns is the cheapest remaining move in the budget, and it
   belongs before any further work on the level.

(1) and (2) are the level, (4) is a factor on the target itself, (3) is local.
Route choice and the mode split, the two this pass implemented, have left the
top of the list.

## A Stuttgart weekday, on the Vancouver modules (2026-09-11)

The Stuttgart *world* already existed (above): persons, firms and commuting
shares synthesized from aggregates. What did not exist was a Stuttgart **day** —
the grid, the venue classes, the transit access points, the street graph, the
diaries and the modes that `city.sim.day` needs before anybody moves. All of
it is below, and the honest headline is in the title: this is the Vancouver
model *transferred*, not a German model. Two of its inputs are Canadian and one
is missing entirely, and each is named where it is used.

### The tables

| stage | cost | result |
|---|---|---|
| `cw/build-stuttgart` :sample **1.0** | **56 s** | 610,444 residents + 326,153 in-commuters = **936,597 persons**, **25,743 firms** |
| `net/load!` :ds `stuttgart-highways` | **8.5 s** | **428,737 nodes / 470,983 edges** from the 74 MB `out geom` pull |
| GTFS: `gtfs/write-stuttgart-derived!` | **23 s** | **2,740 stops** in the bbox, **2,251** with weekday service, from 6.88 M `stop_times` rows |
| `venues/table-cached` | 7.6 s | **5,918 venues** from **23** Stadtbezirk pulls |
| `day/prepare` (city grid) | **225 s** | 172 × 194 = **33,368 cells** of 100 m, 9 gravity CSRs |
| `step-day` | **0.9 s** | 854,041 diaries, 262,797 storefront visits |

Every one of those is a separate, named pull, and three of them needed the
module to learn something new.

**The street graph is Stuttgart's, and the Vancouver one is still there.**
`city.sim.network` holds *one* graph. `stuttgart-highways` joins
`vancouver-highways` as a named pull and every routing caller now says which it
means (`route-fn :ds`, `day/prepare :net-ds`, `serve/city-routing`). The
Vancouver run keeps being served out of its cached legs while the Stuttgart
graph is the loaded one — a cached day needs no router, which is the whole
reason two cities can be served while only one graph is ever held.

While making that explicit, the same bug the fifth pass found in `route-fn`
turned up one call further on: `day/venue-classes` built the `:street` venue
class — the destination for every `:neighbourhood` and `:elsewhere` episode —
by calling `(net/load!)` with no arguments, which loads the *Mount Pleasant*
pull. The published Vancouver city run therefore has a :street class of
**22,485 district nodes**, so those episodes had no destination at all outside
six square kilometres. It is fixed (`:net-ds`, else whatever is loaded);
Stuttgart's :street class is its own 428,737 nodes; **the Vancouver city run
above has not been re-measured with the fix and its `:neighbourhood`/
`:elsewhere` legs are still missing.** That is the next thing to redo.
(Done in the seventh pass: with the fix the city run makes no destination-less
episode at all — `:no-venue` falls to 0 — and the pedestrian target's 08:00
cross-sectional correlation goes 0.370 → 0.450 at stride 10 while the level is
unchanged at 0.187. It is the "city, previous" column there.)

**The venue pulls are in two formats.** Overpass would not serve sixteen of the
twenty-three Stadtbezirke, so those were pulled from ohsome as GeoJSON
centroids; thirteen exist in both formats. `venues/table` now reads either, and
where both exist the **ohsome** pull wins — an Overpass `out center` is the
centre of a way's bounding box and an ohsome `/centroid` is the polygon's
centroid, so keeping both would put the same park on the map twice, tens of
metres apart, where no coordinate-level dedup could see it. The files are
streamed one feature at a time (`network/stream-array!`), because a 14 MB
ohsome pull held as one Clojure value is a hundred megabytes of heap.

**The GTFS feed has no weekday.** NVBW's Baden-Württemberg feed writes an
all-zero `calendar.txt` — all 16,657 services have every weekday column at `0`
— and puts every service day in `calendar_dates.txt` as an exception. There is
therefore no such thing as "the service that runs Monday to Friday" in this
feed, and `gtfs/weekday-services` (which is exactly that question) returned the
empty set and 0 trips. `gtfs/services-on` implements the GTFS date rule
instead, and the Stuttgart table is built for **one named weekday, Wednesday 23
September 2026**: in school term, no public holiday, and 3,960 services against
3,940–3,990 on the other Mon–Thu of its month, 4,170 on the Fridays, 3,600 on
the Saturdays and 3,030 on the Sundays. (The same pass also found that NVBW
quotes every CSV field, which the fast `stop_times` reader was trimming rather
than unquoting — so no stop id matched and no departure time parsed.)

Mean weekday 07:00–19:00 headway over the 2,251 served stops: median **13.3
min**, p10 5.0, p90 40.0.

### The diaries are Canadian. That is the largest assumption in this run.

Germany publishes no open time-use microdata. The ZVE 2022 PUF needs an FDZ
registration and MiD 2017/2023 microdata needs a Mobilithek one; neither is a
file that can be read here. So **the activity chains are the Canadian TUS 2022
urban-weekday diaries, unchanged** — the same 59 person-type tables the
Vancouver world draws from, matched to Stuttgart people by activity status, age
band and sex.

What that assumes, stated plainly:

1. **The shape of the day transfers.** When a Stuttgart 35-year-old worker
   leaves for work, how long they stay, whether they shop on the way home and
   at what hour — all of it is a Canadian urban weekday. Germany's own
   published aggregates say this is wrong in a specific direction: MiD 2017
   gives Stuttgart **3.2 trips per person per day** (corrected in the eighth
   pass: MiD 2023 gives 2.86), while the TUS diaries used
   here produce about **1.5 legs per traced person-day**. The model therefore
   makes roughly *half* the trips the German survey counts, before any mode or
   route rule is applied. Every level in the validation below inherits that
   factor.
2. **School has no German timetable.** A German Grundschule commonly ends at
   midday and a Gymnasium day is not the North American one; the diaries carry
   the Canadian school day, and 22,468 school legs are placed on it.
3. **The pandemic-era work-at-home share is Canadian too.** The Stuttgart
   labour market comes from the BA register and has no "no fixed workplace"
   category at all (1,783 people land in it as a residual, against Vancouver's
   173,748), so the Stuttgart day has *more* commuting than Vancouver's — but
   the hours of that commuting are still TUS 2022's.

This is a transfer, and it is the reason the run is labelled one.

### The modes are Stuttgart's own

The one behaviour input that is *not* Canadian is the modal split. The
Vancouver world draws a person-day mode profile from the commute-mode split of
that person's own dissemination area; Stuttgart has no such table at any level
below the city. What it has is the **MiD 2017 Stadt Stuttgart Grundauswertung**
(n = 6,252 trips): walk 29 %, bike 8 %, car driver 31 %, car passenger 9 %,
public transport 23 %. Car driver and car passenger are one road mode here, so
the profile is `{:car 40 :transit 23 :walk 29 :bike 8 :other 0}`
(`cityworld/mid-2017-stuttgart-modes`).

`day/mode-table` was taught to accept **one** profile for the whole city
rather than a map of per-zone profiles, and to say so (`:rows 1`,
`:city-wide? true`). Faking 152 identical Stadtteil rows would have produced
the same numbers and hidden the fact; the model has exactly as much spatial
variation in mode as the source does, which is none.

Two differences from the Vancouver table are worth keeping in sight. MiD's is a
split of **all trips**, not of commutes, which for this use is the better
measurement of the two — Vancouver's journey-to-work table is being applied to
shopping and leisure legs as well. And `p-keep-diary-mode` is unchanged at
**0.5**: half of person-days keep the Canadian diary's own mode and half take
the MiD profile, exactly as in the fifth pass.

### One Stuttgart weekday (seed 1)

`step-day` over 936,597 persons in **0.9 s**: 854,041 diaries, 348,428 work
episodes, 181,032 store visits, 59,817 restaurant visits, **262,797** of those
landing on a storefront. No episode anywhere in the day failed to find a
destination (`no-venue` 0), which is the first thing the repaired `:street`
class buys.

Traced at **stride 10**: 48,402 people, **142,909 trip legs** plus 29,368
transit access/egress walk stubs = 172,277 polylines, **1,051 s** (207,841 A\*
queries at an 18 % cache hit rate on a 429k-node graph; 1,591 routes failed and
fell back to the straight line).

| purpose | legs (stride 10) |
|---|---|
| home | 59,250 |
| other | 28,780 |
| store | 18,233 |
| work | 14,494 |
| leisure | 14,049 |
| restaurant | 5,861 |
| school | 2,242 |
| *(access walk stubs)* | *29,368* |

| mode | legs | share | MiD 2017 target |
|---|---|---|---|
| car | 80,089 | 56.0 % | 40 % |
| walk | 40,299 | 28.2 % | 29 % |
| transit | 14,684 | 10.3 % | 23 % |
| bike | 7,837 | 5.5 % | 8 % |

The walk share lands on MiD almost exactly; car is 16 points over and transit
13 points under, and the reason is `p-keep-diary-mode` = 0.5. Half the
person-days keep TUS 2022's own modes, which are 78 % car for urban Canada, so
the day's split is roughly the average of MiD and Canada. That parameter is now
doing visible work against a published target and is the obvious thing to fit —
but fitting it to this one number would be fitting the *only* mode observation
the city has, so it stays at the Vancouver value and the gap is reported.

50,895 of the 102,183 diary-timed legs (49.8 %) had their mode substituted;
1.7 % of legs are flagged `:slow`.

**Trip generation, against the German survey.** 142,909 legs at stride 10 is
**1,429,090 legs** over 854,041 diaries: **1.67 legs per person-day**. MiD 2017
reports **3.2 Wege per person per day** for Stuttgart. The model makes **52 %**
of the trips the German survey counts, and that is the Canadian diaries
speaking, not any rule in the movement layer. Every level below inherits it.
(Corrected in the eighth pass: against the MiD 2023 rate of 2.86 the share is
58 %.)

### The run at Stadtteil fidelity

`cityworld/area-aggregates` over 152 Stadtteile (the raster is 33,368 grid cells
against 152 polygons; 20,484 of them fall inside the city). The OD matrix is
7,863 ordered pairs — which is where the old fixed stride of 64 in the OD key
packing was found and fixed, because it folds Stadtteil 70 onto Stadtteil 6.

| Stadtteil | residents | resident workers | jobs | in-commuters | storefront visits/day |
|---|---|---|---|---|---|
| Feuerbach-Ost | 1,277 | 664 | 20,654 | 20,626 | 4,939 |
| Weilimdorf-Nord | 579 | 357 | 18,611 | 18,529 | 4,185 |
| Möhringen-Mitte | 8,453 | 4,469 | 17,647 | 17,175 | 7,698 |
| Rathaus (Mitte) | 4,048 | 2,395 | 15,976 | 15,976 | 6,421 |
| Vaihingen-Mitte | 7,136 | 3,700 | 15,660 | 15,375 | 9,414 |
| a small Stadtteil (winery artefact) | 709 | 366 | 14,999 | 14,926 | 473 |
| Neue Vorstadt | 1,152 | 722 | 14,833 | 14,798 | 3,219 |
| Zuffenhausen-Schützenbühl | 2,183 | 1,163 | 14,653 | 14,650 | 1,798 |

That is Stuttgart's employment geography as the firm register has it — the
Feuerbach/Weilimdorf/Zuffenhausen industrial belt, Möhringen and Vaihingen in
the south, the Rathaus quarter in the centre — with one small Stadtteil still
carrying the Untertürkheim payroll that the synthesis put on a winery (see the firm
register above). It is an inherited artefact of the firm layer, now visible at
the fidelity the console draws.

Of 1,424,010 modelled trips, **724,570 (51 %) stay inside one Stadtteil** and
699,440 cross one. The top inter-Stadtteil flows are all adjacent pairs —
Lehen ↔ Karlshöhe 2,930/2,840, Weilimdorf-Nord ↔ Weilimdorf 2,730/2,550,
Hölderlinplatz → Rosenberg 2,350. At 152 areas of a few thousand people each,
the OD matrix is mostly measuring *adjacency*, which is the honest thing to say
about it: Vancouver's 22 local areas produce a commuting matrix, Stuttgart's 152
Stadtteile produce a neighbour matrix, and the same code produced both.

The console draws it at `?city=stuttgart&area=stuttgart`
(`data/screens/stuttgart-areas.png`; street zoom on Königstraße at
`data/screens/stuttgart-mitte-trips.png`).

**Cost.** Both city runs are served from one process: two worlds, two
published days, two cached leg sets, and **one** street graph, because a
published run's legs are cached and a cached day never routes.

## Sixth certified pass: Stuttgart bicycle counts (2026-09-11)

The first target for the transferred model, and the first one that is not
Canadian. Mobidata BW republishes the Baden-Württemberg Eco-Counter network as
one gzipped CSV per month of hourly values; **eighteen** of its permanent
counters carry the domain *Landeshauptstadt Stuttgart*
(`city.intake.stuttgart-counts`). A rectangle over the city also catches the
Rems-Murr counters in Fellbach and Waiblingen and a Landkreis Böblingen one in
Waldenbuch, on roads this world does not contain; the operator domain is the
filter that excludes them.

**Target:** `fahrradzaehler_stundenwerten_202606.csv.gz` (June 2026), mean
**weekday** hourly count per site over the month's **21** weekdays — 22 Mon–Fri
minus Fronleichnam, 4 June. Value is `channels_all`, both directions past the
loop. Σ = **20,934** bicycles per mean weekday over the 18 sites.

**Simulated:** every **bike** leg of the traced day whose routed polyline passes
within **30 m** of a counter, by hour, scaled by the stride
(`validate/bicycle-counts`, which is `simulated-passings` with the mode changed
from walk to bike). Seed 1, stride 10, 7,837 traced bike legs = **78,370** bike
legs city-wide. 432 site × hour cells; scoring a day already in hand costs
428 ms.

| statistic | value |
|---|---|
| Σ observed (432 cells, 18 sites) | **20,934** |
| Σ simulated | **3,890** |
| **ratio sim/obs** | **0.186** |
| Pearson across sites, daily total | **−0.03** |
| Pearson across sites, 08:00 | 0.25 |
| Pearson across sites, 17:00 | **−0.15** |
| **hourly-profile correlation** | **0.86** |

### Per site

| counter | obs/weekday | sim | sim/obs |
|---|---|---|---|
| Tübinger Straße | 3,692 | 70 | **0.019** |
| König-Karls-Brücke | 2,955 | 300 | 0.102 |
| Samaraweg | 2,387 | 70 | **0.029** |
| Lautenschlager Straße | 1,796 | 280 | 0.156 |
| Böblinger Straße | 1,473 | 290 | 0.197 |
| Inselstraße | 1,416 | 570 | 0.402 |
| Kremmlerstraße | 1,294 | 330 | 0.255 |
| Kirchheimer Straße | 876 | 120 | 0.137 |
| Stuttgarter Straße | 752 | 190 | 0.253 |
| Solitudestraße | 662 | 280 | 0.423 |
| Waldburgstraße | 630 | 0 | **0.000** |
| Am Kräherwald | 596 | 140 | 0.235 |
| Neckartalstraße | 584 | 0 | **0.000** |
| Waiblinger Straße | 498 | 170 | 0.341 |
| Hardware für Waiblinger-/Taubenheimstr. | 487 | 330 | 0.678 |
| Taubenheimstraße | 412 | 220 | 0.535 |
| Waiblinger Str. Ri. Wilhelmsplatz | 229 | 300 | **1.310** |
| Taubenheimstr. von Kursaal | 194 | 230 | **1.186** |

### Hourly profile (all 18 sites summed)

| hour | 05 | 06 | 07 | 08 | 09 | 12 | 15 | 16 | 17 | 18 | 19 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| observed | 335 | 912 | 1,906 | 1,812 | 991 | 914 | 1,357 | 1,798 | 2,067 | 1,734 | 1,183 |
| simulated | 80 | 150 | 260 | 460 | 190 | 70 | 120 | 290 | 420 | 330 | 190 |
| sim/obs | 0.24 | 0.16 | 0.14 | 0.25 | 0.19 | 0.08 | 0.09 | 0.16 | 0.20 | 0.19 | 0.16 |

### The honest reading

**The shape of the cycling day is right and the map of it is not.** The hourly
profile correlates at **0.86** — two peaks, a midday trough, a long evening
shoulder, and a ratio that is 0.14–0.25 at every hour of the working day. The
*cross-sectional* correlation over the 18 counters is **−0.03**, and at 17:00 it
is negative. The model produces the right *kind* of day and puts it on the wrong
streets. These two statistics disagreeing this sharply is the result; a model
that were merely short everywhere would show a positive site correlation and a
lower profile one.

**The level, 0.186, decomposes into three factors that are each known
independently.** Trip generation is **0.52** (1.67 legs per person-day against
MiD's 3.2; corrected in the eighth pass to 0.58 against MiD 2023's 2.86). The bike mode share is **5.5 %** against MiD's 8 %, a factor of
**0.69**. Those two alone predict 0.36. The rest — another factor of about
**0.5** — is where the bikes are put, and that is the finding, not a residual:
a counter is one loop on one cycle path, and a shortest-path router on a street
graph that does not know a Radweg from a Bundesstraße puts the bike on the
parallel road. **Tübinger Straße (0.019) and Samaraweg (0.029)** are the two
clearest cases: both are dedicated cycle routes in the top three by volume, and
both simulate almost nothing. **Waldburgstraße and Neckartalstraße simulate
exactly zero** — 1,214 real bicycles a day on two links no simulated bike ever
uses.

**The counters that are over-predicted are all one corridor.** Waiblinger
Straße, Waiblinger Str. Ri. Wilhelmsplatz, Taubenheimstraße, Taubenheimstr. von
Kursaal and "Hardware für Waiblinger-/Taubenheimstr." — **five** of the eighteen
— stand within about 100 m of each other in Bad Cannstatt (9.2260–9.2269 E,
48.8049–48.8054 N) and are channel splits of one crossing. The model routes one
flow past all five and scores it five times, at 0.34–1.31. They are **1,820 of
the 20,934 observed (8.7 %) and 1,250 of the 3,890 simulated (32 %)**, and they
are most of why the cross-sectional correlation is negative rather than merely
weak. The counters are not an independent sample of the city's streets and the
comparison should not pretend they are.

**What the target cannot see.** The observed value is a mean over 21 weekdays in
June; the simulated value is one seed of one modelled day. June is a good
cycling month in Stuttgart, so this is if anything the easiest month to match on
level. And the diaries are Canadian: TUS 2022's cycling is urban Canada's, on a
bike share the MiD profile then partly overrides for half the person-days.

**Error budget.** Data is strong here for the first time — a permanent network,
21 weekdays, hourly, one mode, an open licence — and the model term dominates
completely, in this order:

1. **Network semantics.** The router has one graph and no notion of a cycle
   route, a one-way, a gradient or a river crossing. In a city built in a valley
   this is not a refinement: Stuttgart's cycling is concentrated on the Neckar
   paths and the valley floor, and the model spreads it over the road network.
   This is the top item and nothing else will move the site correlation.
2. **Trip generation**, factor 0.52, inherited whole from the Canadian diaries.
   A German travel-survey trip generator is the fix and it is a data
   acquisition, not a model change.
3. **The mode split within the day**, factor 0.69, which is `p-keep` at 0.5
   averaging MiD against urban Canada.
4. **Counter independence.** Five of the eighteen sites are one corridor. A
   site-weighted statistic that does not know this over-weights Bad Cannstatt by
   5×, and it is where a third of all simulated passings land.

### The one pedestrian number Stuttgart publishes

hystreet's free ranking page carries **monthly** pedestrian totals for six
Stuttgart locations (August 2026; the hourly series behind them is a paid API).
A month is not a day, so the observed total is divided by the month's 21
weekdays — which counts a Saturday like a Tuesday and is therefore an *upper*
bound for a weekday on a shopping street. The observed counts come from
hystreet and are not reproduced here; its terms do not allow republishing them.

| location | simulated per weekday |
|---|---|
| Königstraße (Mitte) | 90 |
| Königstraße (Nord) | 400 |
| Königstraße (Süd) | 1,050 |
| Schulstraße | 260 |
| Stiftstraße | 250 |
| Hirschstraße (Mitte) | 480 |

(Positions are the centroid of each street's own OSM geometry — Königstraße is
35 ways over 48.7733–48.7826, split into equal thirds by latitude for hystreet's
Süd/Mitte/Nord. hystreet does not publish the sensor location.)

**Every site is short by one to three orders of magnitude, not the factor of 5
the bicycle target shows, and the shortfall is worst on the busiest observed
site, Königstraße (Mitte).** It names a specific missing mechanism: **there is
no city-centre in the destination model.** Store and
restaurant destinations are drawn from a gravity CSR with **λ = 400 m**, so a
shopping trip picks a shop near wherever the person already is. Nobody in the
model travels *to* the high street; Königstraße's tens of thousands of daily
pedestrians are people who came to the centre because it is the centre, and a 400 m kernel
cannot represent that at any population. The pedestrian-count pass in Vancouver
never showed this because Main Street is a neighbourhood high street inside the
district its shoppers live in, and Königstraße is not.

The fix is a destination model with a size term that does not decay at 400 m —
a competing-destinations or intervening-opportunities form, where a 300-shop
pedestrian zone outcompetes a corner shop for a whole city's shopping trips.
That is the largest single unbuilt piece of the movement layer, and it took a
city with a real city-centre to make it visible.

## Seventh certified pass: a destination model with a size term (2026-09-11, later)

The sixth pass ended on a named mechanism rather than a residual: *there is no
city-centre in the destination model*. Store and restaurant destinations were
drawn from a gravity CSR with **λ = 400 m and no size term**, so a shopping trip
picked a shop near wherever the person already was; Königstraße (Mitte), the
busiest of the observed sites, simulated **90** pedestrians on a weekday. This pass replaces that
kernel, calibrates it on both cities, and re-measures every movement target.

### What the kernel is now

`day/gravity-table` builds each cell's choice set from

> **w = attract^α · f(d)**,  f(d) = (1 + d/d₀)^−β  (power)  or  exp(−d/λ)  (exp)

with three things that did not exist before, none of which is sufficient alone:

1. a **size term** α — an exponential kernel with no size term is the old model;
2. a **scale-free decay** — the Huff / universal-visitation form (Schläpfer et
   al. 2021 find visitation density ∝ (r·f)^−2; Deep Gravity's POI utilities);
   an exponential kernel cannot reach a centre however large it is, because at
   6λ its weight is 0.25 % of the local one;
3. a **larger choice set**, K = 64 rather than 16 — at K = 16 a distant centre
   is crowded out of a suburban cell's CDF by the sixteen shops on the corner
   *before* the kernel is ever consulted. The K ablation below is worth 16 % of
   the level on its own.

The parameters are **per venue class** (`day/default-venue-kernels`), and only
`:retail` and `:food` moved. A park, a clinic, a school, "a street node in the
block" and "another resident's home nearby" keep the pure-distance kernel of the
earlier passes, deliberately: those are neighbourhood destinations and the model
has no measurement of their size. `day/previous-venue-kernels` is the
fourth-to-sixth-pass setting (α = 0, exp, λ = 400 m, K = 16), kept so that every
"previous" column below is *re-measured on today's code* rather than quoted.

New entries in `run/defaults`, with priors: `:venue-kernel` (:power | :exp),
`:venue-alpha` α ∈ [0, 1.5], `:venue-beta` β ∈ [1, 3.5], `:venue-d0-m`
d₀ ∈ [200, 2000] m, `:venue-lambda-m` λ ∈ [150, 4000] m, `:k-venues` ∈ {16, 32,
64}, `:venue-attract-radius-m` ∈ [50, 400] m.

### Where attractiveness comes from

`day/venue-attract`, in the order the data supports it: (1) the cluster's
**employee count** where the register has one — licence employment in Vancouver,
synthesized sizes in Stuttgart; (2) else the number of **co-located
customer-facing venues within 100 m**, a street-density proxy; (3) else 1. The
count is a spatial hash at the radius, not 8·10⁹ pairs.

**The two cities exercise different branches, and that is itself a finding.**
Vancouver's 8,355 storefront clusters carry *no* licence employment at all and
78 % of its 11,410 retail clusters carry none either, so Vancouver's
attractiveness is almost entirely the street-density proxy — which is exactly
the quantity that makes Main Street bigger than a corner shop. Every one of
Stuttgart's 3,637 retail firms has a synthesized employee count (median 2), so
Stuttgart's is employment — and employment in the centre is small (2,756
employees within 500 m of Königstraße against 84,727 city-wide) while the
*number* of venues there is large (865 of 6,634). The two branches are not the
same measurement of "big", and Stuttgart gets the weaker of the two.

### The Mount Pleasant grid search

The district world is 84 ms a day and 75 s a scored pedestrian target, so the
kernel was chosen there first: 20 settings, seed 1, **stride 2**, the same 15
intersections and 205 cells as every pass since the fourth.

| kernel | α | β / λ | K | Σsim/Σobs | r 08 | r 17 | r profile | Main & Bwy | visit Gini |
|---|---|---|---|---|---|---|---|---|---|
| **exp (fourth–sixth pass)** | 0 | λ 400 | 16 | 0.122 | 0.194 | 0.395 | 0.906 | **0.069** | 0.532 |
| power | 0 | β 1.5 | 64 | 0.129 | 0.200 | 0.472 | 0.925 | 0.075 | 0.501 |
| power | 0 | β 2 | 64 | 0.128 | 0.196 | 0.438 | 0.911 | 0.077 | 0.506 |
| power | 0 | β 3 | 64 | 0.128 | 0.176 | 0.445 | 0.913 | 0.074 | 0.504 |
| power | 0.5 | β 1.5 | 64 | 0.162 | 0.208 | 0.557 | 0.948 | 0.203 | 0.605 |
| power | 0.5 | β 2 | 64 | 0.148 | 0.194 | 0.544 | 0.938 | 0.143 | 0.576 |
| power | 0.5 | β 3 | 64 | 0.139 | 0.166 | 0.492 | 0.929 | 0.112 | 0.552 |
| power | 1 | β 1.5 | 64 | 0.220 | 0.216 | 0.527 | 0.965 | 0.437 | 0.713 |
| **power (chosen)** | **1** | **β 2** | **64** | **0.198** | **0.230** | 0.540 | **0.970** | **0.357** | 0.667 |
| power | 1 | β 3 | 64 | 0.157 | 0.197 | 0.541 | 0.949 | 0.183 | 0.609 |
| power (**K ablation**) | 1 | β 2 | **16** | 0.171 | 0.222 | 0.562 | 0.957 | 0.282 | 0.729 |
| exp | 0 | λ 400 | 64 | 0.129 | 0.203 | 0.455 | 0.918 | 0.075 | 0.504 |
| exp | 0 | λ 1500 | 64 | 0.129 | 0.174 | 0.452 | 0.914 | 0.074 | 0.507 |
| exp | 0 | λ 4000 | 64 | 0.131 | 0.174 | 0.468 | 0.920 | 0.073 | 0.505 |
| exp | 0.5 | λ 400 | 64 | 0.145 | 0.189 | 0.532 | 0.933 | 0.137 | 0.571 |
| exp | 0.5 | λ 1500 | 64 | 0.225 | 0.225 | 0.515 | 0.968 | 0.455 | 0.725 |
| exp | 0.5 | λ 4000 | 64 | 0.264 | 0.219 | 0.515 | 0.972 | 0.557 | 0.774 |
| exp | 1 | λ 400 | 64 | 0.170 | 0.230 | 0.569 | 0.946 | 0.239 | 0.640 |
| exp | 1 | λ 1500 | 64 | 0.265 | 0.216 | 0.524 | 0.970 | 0.577 | 0.771 |
| exp | 1 | λ 4000 | 64 | **0.274** | 0.217 | 0.503 | **0.975** | **0.575** | 0.782 |

Per setting: table build 5.1–12.6 s, the day itself 17–127 ms, the scored target
74–78 s.

**α is the whole result and the decay form is second.** Along the α column at
β = 1.5 the ratio goes 0.129 → 0.162 → 0.220 and Main & Broadway 0.075 → 0.203 →
**0.437**; along the β column at α = 1 it goes 0.220 → 0.198 → 0.157. With α = 0
*nothing* moves, whichever kernel or K: three rows sit at 0.128–0.131 and Main &
Broadway at 0.073–0.077. A size term is not a refinement of the distance kernel,
it is the missing term.

**The district's own summary ranks a kernel we did not take.** exp with α = 1 and
λ = 4 km scores the best ratio (0.274) and profile correlation (0.975) in the
table, and it is rejected on transferability, not on fit: Mount Pleasant is 6 km²,
so λ ≥ 1.5 km is "no distance decay at all" *inside this district*, and the
district cannot tell that apart from a kernel that is flat locally and still
decays across a 20 km city. That is what the power form is for, and it is why
the confirmation below is run on two whole cities rather than on this table.
Saying which row won and why it was not taken is the point of printing all 20.

**β = 2 over β = 1.5 is the one judgement call.** β = 1.5 buys a higher level
(0.220 vs 0.198 here, and 13 % more at Königstraße) and β = 2 buys the
correlations (r 08 0.230 vs 0.216 here; on Stuttgart's bike counters r 08 0.295
vs 0.214, r 17 0.074 vs 0.020, site r 0.025 vs 0.014) and a lower `:slow` share
(3.1 % vs 4.0 % of diary-timed legs — β = 1.5 makes trips the diary's own clock
cannot fit). β = 2 is also the exponent Schläpfer's visitation law reports. The
fifth pass's rule — *a model that is short everywhere beats one that is short
here and over there, and the correlations are the statistic that says so* —
picks β = 2, and that is what `default-venue-kernels` ships. (Revised later:
this choice was made on a truncated choice table. The eleventh pass showed the
truncation, the default moved to β = 1.6, and the fifteenth pass and the
posterior in [doc/model.md](model.md) §9 infer β rather than choose it.)

### Vancouver re-measured

Two corrections land in the same column. The sixth pass found that
`venue-classes` built the `:street` class (the destination of every
`:neighbourhood` and `:elsewhere` episode) from **whatever `(net/load!)` returns
with no arguments**, which is the Mount Pleasant pull — so the published city run
had those episodes confined to six square kilometres. The **city-previous** column
below is the old kernel re-measured *with that fix*, so the kernel comparison is
kernel-against-kernel.

Seed 1, city graph (232,290 nodes), **stride 10**, 15 intersections, 205 cells,
Σ observed 40,462.

| statistic | district, previous | district, now | **city, previous** | **city, now** |
|---|---|---|---|---|
| stride | 2 | 2 | 10 | 10 |
| Σ simulated | 4,920 | 8,002 | 7,560 | **9,470** |
| **ratio sim/obs** | 0.122 | 0.198 | **0.187** | **0.234** |
| Pearson across sites, 08:00 | 0.194 | 0.230 | **0.450** | 0.433 |
| Pearson across sites, 17:00 | 0.395 | 0.540 | 0.428 | **0.691** |
| hourly-profile correlation | 0.906 | 0.970 | 0.639 | **0.743** |
| **Main St & E Broadway** | 0.069 | 0.357 | **0.067** | **0.256** |
| storefront visits / day | — | — | 60,218 | **88,447** |
| storefront-visit Gini | 0.532 | 0.667 | 0.567 | 0.663 |
| walk legs (traced) | — | — | 25,577 | 23,985 |
| transit legs (traced) | — | — | 10,104 | 11,686 |
| access/egress walk stubs | — | — | 20,208 | 23,372 |
| table build | 9.6 s | 5.4 s | **121 s** | **141 s** |
| traced day | 0.1 s | 0.02 s | **602 s** | 184 s (warm cache) |

Per site, the ratio over each study's own observed hours:

| intersection | obs | city, previous | **city, now** |
|---|---|---|---|
| E Broadway & Kingsway | 6,905 | 0.184 | **0.271** |
| **Main St & E Broadway** | 5,193 | 0.067 | **0.256** |
| W 1st Av & Ontario St | 4,363 | 0.069 | 0.069 |
| Main St & E 2nd Av | 3,471 | 0.300 | 0.314 |
| Ontario St & E 5th Av | 3,273 | 0.043 | 0.046 |
| E 12th Av & Main St | 3,088 | 0.175 | 0.185 |
| Commodore Rd & Spyglass Pl | 2,526 | 0.305 | 0.313 |
| Fraser St & E Broadway | 2,291 | 0.057 | **0.113** |
| Ontario St & W 10th Av | 2,021 | 0.163 | 0.178 |
| Prince Edward St & E Broadway | 2,006 | 0.070 | 0.090 |
| W 2nd Av & W 5th Av | 1,870 | 0.246 | 0.246 |
| E 12th Av & Kingsway | 1,663 | 0.740 | 0.752 |
| Kingsway & Fraser St | 1,308 | 0.566 | 0.573 |
| Prince Edward St & E 16th Av | 376 | 0.186 | 0.160 |
| W 12th Av & Alberta St | 108 | 0.463 | 0.463 |

Hourly profile (matched cells only):

| hour | 07 | 08 | 09 | 12 | 15 | 16 | 17 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|
| observed | 1,434 | 2,704 | 2,117 | 2,882 | 3,843 | 4,769 | 5,660 | 4,109 | 923 |
| city, previous | 1,260 | 940 | 520 | 210 | 400 | 1,340 | 720 | 390 | 200 |
| **city, now** | 1,260 | 1,010 | 710 | 290 | 530 | 1,740 | 1,010 | 640 | 220 |

### Stuttgart re-measured

Seed 1, Stuttgart graph (428,737 nodes), stride 10, the 18 Eco-Counter sites
(Σ observed 20,934 bicycles per mean June weekday) and hystreet's six locations.
The **previous** column reproduces the sixth pass exactly — 0.186, −0.03, 0.86,
Königstraße 90/400/1,050 — which is the regression check on the refactor.

| statistic | previous (= sixth pass) | **now (α 1, β 2, K 64)** | (α 1, β 1.5) |
|---|---|---|---|
| bike Σ simulated | 3,890 | **5,990** | 6,570 |
| **bike ratio sim/obs** | 0.186 | **0.286** | 0.314 |
| **Pearson across sites (daily)** | **−0.035** | **+0.025** | +0.014 |
| Pearson across sites, 08:00 | 0.247 | **0.295** | 0.214 |
| Pearson across sites, 17:00 | **−0.152** | **+0.074** | +0.020 |
| bike hourly-profile correlation | 0.860 | 0.857 | 0.864 |
| **Königstraße (Mitte)**, simulated | 90 | **380** | 430 |
| Königstraße (Nord), simulated | 400 | 280 | 290 |
| Königstraße (Süd), simulated | 1,050 | **1,920** | 2,050 |
| Schulstraße, simulated | 260 | 340 | 410 |
| Stiftstraße, simulated | 250 | 490 | 390 |
| Hirschstraße (Mitte), simulated | 480 | 700 | 600 |
| storefront visits / day | 262,797 | 228,286 | 225,205 |
| storefront-visit Gini | 0.551 | 0.884 | 0.903 |
| walk legs (traced) | 40,299 | 35,424 | 33,959 |
| transit legs (traced) | 14,684 | 19,412 | 20,943 |
| access/egress walk stubs | 29,368 | 38,824 | 41,886 |
| `:slow` share of diary-timed legs | 1.7 % | 3.1 % | 4.0 % |
| table build / traced day | 224 s / 892 s | 241 s / 1,057 s | 243 s / 1,266 s |

Per counter (simulated, stride 10):

| counter | obs | prev | now | | counter | obs | prev | now |
|---|---|---|---|---|---|---|---|---|
| Tübinger Straße | 3,692 | 70 | 170 | | Waldburgstraße | 630 | 0 | **0** |
| König-Karls-Brücke | 2,955 | 300 | 590 | | Am Kräherwald | 596 | 140 | 230 |
| Samaraweg | 2,387 | 70 | **60** | | Neckartalstraße | 584 | 0 | 10 |
| Lautenschlager Straße | 1,796 | 280 | 290 | | Waiblinger Straße | 498 | 170 | 320 |
| Böblinger Straße | 1,473 | 290 | 600 | | Hardware Waiblinger/Taubenheim | 487 | 330 | 480 |
| Inselstraße | 1,416 | 570 | 830 | | Taubenheimstraße | 412 | 220 | 280 |
| Kremmlerstraße | 1,294 | 330 | 340 | | Waiblinger Str. Ri. Wilhelmsplatz | 229 | 300 | 480 |
| Kirchheimer Straße | 876 | 120 | 170 | | Taubenheimstr. von Kursaal | 194 | 230 | 390 |
| Stuttgarter Straße | 752 | 190 | 440 | | Solitudestraße | 662 | 280 | 310 |

### The honest reading

**The mechanism the sixth pass named is real and the size term is what carries
it.** Main & Broadway — a high street inside the district its shoppers live in,
and the site that had refused to move through three passes (0.043 → 0.057 →
0.064 → 0.067) — goes to **0.256**, a factor of 3.8, without a single new agent
or a single change to trip generation. Fraser & Broadway doubles. The three
*over*-predicted Kingsway sites move by 1–2 % (0.740 → 0.752, 0.566 → 0.573),
which is the shape of a correct fix: the volume appears where destinations are,
not everywhere.

**The correlations move with it, which is the test that the level is not being
bought.** At 17:00 Vancouver's cross-sectional correlation goes 0.428 → **0.691**
and the hourly profile 0.639 → 0.743, because the afternoon is when shopping
happens and shopping is what changed. Stuttgart's bicycle site correlation
crosses zero for the first time (−0.035 → +0.025) and its 17:00 correlation goes
**−0.152 → +0.074**: the model was previously *anti*-correlated with the evening
bicycle map and is now weakly positive.

**Königstraße is four times better and still short by more than two orders of
magnitude.** 90 → 380 at the Mitte sensor (the observed hystreet counts are not
reproduced here). Three terms explain the remainder and only one of them is the
destination model:

1. **The measurement is a point, the observation is a street.** hystreet does
   not publish its sensor location; the simulated value counts walk legs within
   30 m of the centroid of each third of Königstraße's own OSM geometry. The
   three thirds disagree by 7× (Süd 1,920, Mitte 380, Nord 280) on a street whose
   observed counts differ by less than 2×, which is a measurement artefact of
   ours, not a model result. The model *does* put people on Königstraße: at the
   Süd cross-section it is about eight times closer to the observed count than
   at Mitte.
2. **Trip generation is still 0.52 of MiD** (1.67 legs per person-day against
   3.2; corrected in the eighth pass to 0.58 against MiD 2023's 2.86) and the
   diaries are still Canadian. No destination kernel can invent
   the trips that are not made, and Königstraße's footfall is a *midday and
   afternoon* phenomenon, which is exactly the part of the day the fifth pass
   identified as empty.
3. **Attractiveness in Stuttgart is employment, and the centre's employment is
   small.** 865 venues within 500 m of Königstraße Mitte, 2,756 employees: with
   α = 1 on employees the centre is 3 % of the city's retail mass, while by venue
   count it is 13 %. Vancouver's storefronts get the density proxy and move 3.8×;
   Stuttgart's firms get employment and move 4.2× on a far worse starting point.
   A German retail-floorspace or a Handelsregister size source is the fix, and it
   is a data acquisition, not a model change.

**Two things got worse and both are legible.** Vancouver's 08:00 correlation
falls 0.450 → 0.433 — the morning peak is commuting, which this change does not
touch, and the extra shopping volume is noise against it. Stuttgart's storefront
visit total falls 262,797 → 228,286 while Vancouver's rises 60,218 → 88,447: the
size term moves visits onto the *largest* retail firms, and in Stuttgart the
largest firms are less often flagged `storefront` than in Vancouver, where the
storefront inventory *is* the high street. The storefront-visit Gini rises in
both (0.567 → 0.663, 0.551 → 0.884) and has no observed target in either city —
a real weakness of this calibration, and the cheapest way to close it is a
receipt- or card-panel distribution of spend per venue.

**The turnover target is unaffected, as required.** Re-fitting the storefront
closure hazard against the pooled 2020–2025 observed turnover by category
(`validate/calibrate-hazard`, 5 seeds of mean visits) returns the *same*
parameters — base 0.08, scale 80 — under both kernels, with weighted squared
error 1.560 → 1.642 and no per-category expected rate moving by more than 0.002
(Comparison Goods 0.070 → 0.068, Convenience Goods 0.069 → 0.068, overall
expected 0.074 both times, observed 0.085). The hazard reads *relative* visit
levels within a category and the kernel change is close to a monotone
transformation of them.

**Cost.** District grid search 20 × ~85 s = 28 min. Vancouver: table
build 121 s / 141 s, traced day 602 s cold and 184 s on a warm route cache.
Stuttgart: graph 9.5 s, table build 224–243 s, traced day 892–1,266 s (the new
kernel makes store legs longer, so the router does more work and the cache hits
less often — the trace cost rose 18 % at β = 2 and 42 % at β = 1.5). Both city
runs are re-published, with 144,251 Vancouver legs and 181,638 Stuttgart legs
at stride 10 (both larger than before, because the new kernel makes more
transit legs and therefore more access-walk stubs). The published worlds carry `:daily-tables` rebuilt with the shipped kernel, so a
request for an uncached stride re-routes with the same destination model the
published day used.

**Error budget.** Data is unchanged on every target. The model term still
dominates and the order has changed at the top:

1. **Trip generation — the Canadian trip rate.** (**Target corrected
   2026-09-11**: 3.2 is Stuttgart *2017*; the MiD 2023 small-area estimate for
   Stadt Stuttgart is **2.86** at a mobile share of 0.838, so the gap is a
   factor of 1.56, not 1.9. See `doc/sources/trip-generation.md`.)
   1.67 legs per person-day is
   0.52 of MiD's 3.2 (0.58 of the corrected 2.86), and the diaries behind it are a *time-use* survey rather
   than a travel survey in both cities. It is now
   the single largest factor on every level statistic in both cities, it is a
   *multiplicative* factor of about 2 that no behavioural rule can supply, and
   the fix is a travel-survey trip generator (MiD 2017/2023 for Stuttgart, the
   Canadian GTS/TTS for Vancouver) rather than a time-use diary.
2. **The missing midday, and the 47 % of Vancouver's employed residents with no
   fixed workplace.** 2021 is a pandemic census; those people make no commute
   leg at all, and a work-from-home day with local errands is exactly the day
   that would fill 11:00–15:00, where Vancouver still runs at 0.10–0.15 of
   observed. A WFH-day rule is cheap and is the next model change.
3. **Attractiveness data.** Stuttgart needs venue size that is not payroll;
   Vancouver needs the density proxy checked against floor area. Neither city
   has an observed *visit distribution* to calibrate the Gini against, which is
   the one statistic this pass moved a great deal and cannot score.
4. **Network semantics** (unchanged from the sixth pass, and still the only
   thing that will move Stuttgart's site correlation above ~0.1): the router has
   one graph and no notion of a cycle route, a one-way or a gradient.
   Waldburgstraße and Neckartalstraße still simulate 0 and 10 against 630 and
   584; Samaraweg *fell*, 70 → 60. A destination model cannot fix a link the
   router will not use.
5. **Crossing vs passing**, and hystreet's unpublished sensor location: a factor
   between 1 and 2 on Vancouver's target and a factor of several on Königstraße
   that no model change will ever supply.

## The console's runs are heap, and a firm kernel for the cities (2026-09-11)

Two faults, both found by clicking around Stuttgart and seeing an empty
console: nothing was published at all, and half the dashboard could not
have drawn even if it had been.

### Everything the console serves lives in one JVM's heap

`city.sim.serve/outputs` is an atom. The three runs it holds — Mount Pleasant,
Vancouver city, Stuttgart — exist only as long as the dev JVM does, and the
JVM was killed for running out of memory. The console then answers `404 no run for area`
to every `/sim/*` request, which the UI draws as an empty legend, an empty
dashboard and a map with no movement. Nothing in the interface said that the
model server was gone rather than the model being empty.

The recipe for rebuilding them lived in REPL history and in prose in this file.
It is now `city.sim.publish`:

```clojure
(require 'city.sim.publish)
(future (city.sim.publish/republish-all!))   ;; tail data/derived/publish.log
```

which rebuilds and publishes all three in order — the district first, because
`city.sim.network` holds **one** graph and the order decides which pull is
loaded when (the fifth pass's bug); Vancouver next; Stuttgart last, its graph
left loaded. Timings from the run of 2026-09-11:

| stage | Vancouver | Stuttgart |
|---|---|---|
| world | 73 s | 56 s |
| graph | (cached) | 9.3 s |
| `day/prepare` | 259 s | 203 s |
| `step-day` | 1.5 s | 0.7 s |
| traced day, stride 10 | 594 s | ~25 min of CPU |
| legs cached | 157,496 | 161,432 |

### A city-wide run had no firm kernel, and said so nowhere

The city runs were one traced weekday and nothing else. Two consequences the
console showed without explaining:

- `/sim/series` returned `[]`, so the **firms per month** panel drew empty axes;
- `/sim/firms` fell back to each firm's **licensed headcount** — an
  *observation* — and the UI drew it in the simulated style under the label
  "firm size after 20 y". That is a provenance fault, not a missing feature.

`city.sim.publish/publish-firm-kernel!` runs the same kernel the district run
uses over an already-published city world (no rebuild, no re-routing): 8 s for
Vancouver, 20 s for Stuttgart, 240 months. Initial firm ages need a pool:
Vancouver's licences carry a first year, so the pool is an observation;
Stuttgart has none — the Unternehmensregister publishes stocks and the
Unternehmensdemografie publishes births, deaths and 3-year survivors, but never
an age — so `stationary-ages` derives the age mix the kernel's *own* hazard
implies at stationarity (share at age a ∝ S(a)). The config records which of
the two was used, because they are not the same kind of input.

| | Vancouver city | Stuttgart |
|---|---|---|
| firms in the register | 89,965 | 25,743 |
| of those, holding a worker at month 0 | 25,316 | 25,743 |
| alive at month 240 | 22,764 (−10 %) | **46,355 (+80 %)** |
| tail exponent (Hill) | 1.88 | 1.48 |
| death rate | 12.9 %/yr | 13.7 %/yr |
| births | 2,818/yr | 6,126/yr |

Vancouver is roughly stationary; **Stuttgart nearly doubles**, and the reason is
structural rather than a bad parameter. In the Axtell–Guerrero kernel births
scale with *workers* (ν per activation) and deaths scale with *firms*, so the
stationary firm count is set by the workers-per-firm ratio. Vancouver's
synthesized register carries ~9 workers per firm holding one; Stuttgart's
carries ~20, so the kernel founds firms until the ratio falls to the same
place. That ratio is exactly the known defect of the Stuttgart firm layer:
25,743 Overture places matched to the Unternehmensregister's sector *employment*
means the employment is right and the firm *count* is too small, because
Overture sees consumer-facing businesses and little else.

So the kernel turns a static data gap into a measurable one, and Stuttgart has
a real target for it. The Unternehmensdemografie (52111-51/52-01-4, 2023) gives
stock 26,251, births 2,369 (9.0 %/yr) and deaths 2,494 (9.5 %/yr). The model
produces 13.2 % and 13.7 % against a stock it inflated itself. Two things to
separate before reading that as a parameter error: the register counts
*Unternehmen* and the model counts establishments holding a worker, and the
model's hazard is Vancouver's licence-derived Kaplan–Meier applied to Germany.

**Next on this thread**, in order: a city-wide Kaplan–Meier from the 545k
Vancouver licences now in the store (the hazard is still measured on one
district and applied to a city); the Unternehmensdemografie 3-year survivor
table as an independent S(3) for Stuttgart; and only then ν.

### Console fixes

Both were the same lookup mismatch. Runs are published under whole-city keys,
but selecting a Stuttgart Stadtteil made the console ask `/sim/<layer>?area=<its
own eid>`, which no run answers. The map layers and the dashboard both now ask
`sim-key` — the area's own run if it has one, else the city's — with the
viewport as a filter. Two consequences for what the panels *mean*: a spatial
panel served this way describes the viewport, so its title says "— in view";
and a panel with no rows now writes why (`this run has no firm kernel — one
weekday only`) instead of drawing empty axes, which is indistinguishable from a
chart of zeros.

## Eighth certified pass: trip generation (2026-09-11, later)

The largest term in the error budget for four passes running, and the first one
that was not a modelling choice at all: the schedules come from a **time-use**
survey, which records travel only when a respondent reports it as its own
episode. The pool contains 2.00 travel episodes per person-day. A travel
survey, which asks for every trip by name, counts 2.86 in Stuttgart.

**The target was also wrong.** Every earlier pass compared against 3.2 trips
per person-day, which is the *2017* Stuttgart figure. The MiD 2023 small-area
estimate for Stadt Stuttgart is **2.861** at a Mobilitätsquote of **83.79 %**;
the German series runs 3.3 (2002), 3.4 (2008), 3.1 (2017), 2.9 (2023). The gap
was a factor of 1.56, not 1.9. Sources and access recipes are in
`doc/sources/trip-generation.md`.

### What the gap was made of

Measured on the published runs before the change, counting a trip the way the
surveys do — one movement between activities, transit access walk excluded:

| | Vancouver | Stuttgart | Stuttgart observed |
|---|---|---|---|
| trips per person per day | 1.92 | 1.83 | **2.86** |
| share making any trip | 0.635 | 0.612 | **0.838** |
| trips per mobile person | 3.02 | 3.00 | 3.41 |
| residents / in-commuters | — | 2.12 / 1.38 | — |

Two thirds of the shortfall was people who never left home, not short days.

### Two changes

**In-commuters now commute.** They were appended with no home and began the day
already at their workplace: 94,960 people in Vancouver and 326,153 in
Stuttgart, 38 % of the Stuttgart world, who made no commute leg and crossed
none of the counting sites these passes score against. `place-externals!` gives
each of them a home at the city edge on the side they come from, drawn from the
census commuting table's origin municipalities (21 of them cover 97.1 % of the
Vancouver flow, geocoded to municipality centroids and clamped into the city's
own bounding box). A person from Burnaby now enters on Boundary Road, one from
Richmond across the southern shore, one from the North Shore where the bridges
land. Nothing is claimed about the journey before that point, which happens
outside every graph and counter this model has.

**The diary pool is tilted to the survey's rate.** For each person type,

    w'(d) ∝ w(d) · exp(λ_t · n_d)

with n_d the diary's travel-episode count and one λ_t per type solved so the
induced mean equals the published rate for that type — the
minimum-relative-entropy reweighting subject to one moment constraint. Levels
and shapes are published numbers: MiD 2023 for Stuttgart's level and MiD 2017
table P32.1 for its shape by Haupttätigkeit and age; TransLink's 2011 life-stage
rates for Vancouver's shape, with the level bracketed by Metro 2011 (2.77,
ages 5+) and the City panel (3.03, adults 18+).

**The check is the statistic that was not fitted.** Only the mean is targeted.
The share of people making no trip is then a prediction:

| | fitted | predicted | published |
|---|---|---|---|
| Stuttgart | mean 2.861 | mobile share **0.834** | **0.838** |
| Vancouver | mean 2.900 | mobile share 0.842 | none published |

A 0.4-point agreement on an unfitted statistic is consistent with the tilted
diary pool reproducing the survey's mobility, not only its mean.

**The pool also lost its province filter.** It was British Columbia only: 1,117
diaries over 53 person types, about 21 each, which is why 56 % of simulated
mobile days came out as one trip out and back. All provinces gives 7,017
diaries over 59 types. The rate is a property of the instrument and does not
change; the chain variety does.

### What it did to Vancouver

| | before | after | target |
|---|---|---|---|
| trips per person per day | 1.918 | **2.508** | 2.9 |
| share making any trip | 0.635 | **0.744** | — |
| trips per mobile person | 3.02 | 3.37 | — |
| residents / in-commuters | — | 2.43 / 3.03 | — |
| legs cached (stride 10) | 157,496 | 209,563 | — |

**Pedestrian counts, the certified target:** Σsim/Σobs over 205 matched
intersection-hours rose **0.234 → 0.436**, and Main & Broadway, the site that
has resisted every pass, **0.26 → 0.48**. Hourly profile correlation 0.72,
17:00 cross-site correlation 0.62.

The gain is larger than the trip count alone explains: trips rose 31 % and the
counted ratio rose 86 %. That is the signature of the in-commuter fix rather
than the tilt — the people who were missing were the ones crossing town, which
is exactly where the counters are.

**Two caveats on that comparison.** The 0.234 was measured during the seventh
pass by tracing a day at measurement time; 0.436 is measured from the published
day's cached legs at stride 10. The methods are not identical, and where a
matched pair exists (Stuttgart, measured both ways before the change) the
cached-leg route reads about 8 % higher. The Stuttgart comparison below is
matched and is the cleaner of the two.

### The generator hits its target; the simulator loses part of it

The tilt puts 2.901 trips per person into the diaries. The simulated day emits
**2.508**, a 14 % loss where the same loss used to be 4 %.

It is not a denominator artefact: persons aged 15+, persons assigned a diary
type, and persons counted in the trip rate are all exactly **690,553** in the
Vancouver world, so the tilt and the measurement divide by the same people. The
legs are genuinely not emitted. The mechanism is `step-day-traces`, which emits
a leg only when the endpoints differ, so a travel episode resolving to a
destination the person already occupies produces nothing — and the more trips a
day has, the more often that collides. This is now a named model term of its
own rather than part of the trip-generation gap, and the fix is a destination
draw that excludes the current location.

### Stuttgart baseline, measured the same way as the result

Captured from the pre-change published day before it was replaced, so the
comparison below is matched on method as well as on run:

| | baseline |
|---|---|
| trips per person per day | 1.834 |
| share making any trip | 0.612 |
| trips per mobile person | 2.995 |
| bicycle counts, Σsim/Σobs (18 Eco-Counter sites) | 0.308 |
| Königstraße Mitte, simulated per weekday | 1,940 |
| Königstraße Süd, simulated | 6,300 |
| Hirschstraße Mitte, simulated | 1,310 |

(The observed hystreet counts are not reproduced here.)

(The seventh pass reported 0.286 for bicycles and 380 for Königstraße Mitte,
measured by tracing a day at measurement time rather than from the published
day's cached legs. Those are not the same measurement, which is precisely why
this baseline was re-taken by the new method before anything changed.)

### What it did to Stuttgart, including the target it made worse

Matched on method: the baseline below was re-measured from the pre-change
published day's cached legs before that run was replaced, so both rows are the
same measurement.

| | before | after | observed |
|---|---|---|---|
| trips per person per day | 1.834 | **2.645** | 2.861 |
| share making any trip | 0.612 | **0.792** | 0.838 |
| trips per mobile person | 2.995 | 3.338 | 3.41 |
| residents / in-commuters | 2.12 / 1.38 | 2.41 / **3.03** | — |
| legs cached (stride 10) | 161,432 | 314,845 | — |
| work legs | 13,899 | **39,725** | — |
| **bicycle counts**, Σsim/Σobs, 18 sites | 0.308 | **0.488** | 1.0 |
| bicycle hourly profile correlation | 0.845 | **0.924** | 1.0 |
| Königstraße Mitte, simulated/weekday | 1,940 | **660** | not reproduced |
| Königstraße Süd | 6,300 | **1,800** | not reproduced |
| Hirschstraße Mitte | 1,310 | **340** | not reproduced |

(The observed pedestrian counts come from hystreet and are not reproduced
here.)

Work legs nearly tripled, which is the in-commuter fix doing exactly what it
was supposed to: 326,153 people who used to begin the day at their desk now
travel to it.

**The bicycle target improved and the pedestrian target got worse**, and the
mode composition says why:

| | before | after |
|---|---|---|
| walk | 60,135 | **38,578** |
| transit | 2,397 | **44,468** |
| car | 85,846 | 133,428 |
| bike | 8,260 | 9,435 |
| access walk (transit stubs) | 4,794 | **88,936** |

**Pure walk legs fell by a third while total legs rose by 44 %.** An
in-commuter's journey is long by construction, and a long leg cannot be walked:
the mode model substitutes it to transit or car, and each transit leg then
emits access and egress walk stubs. Walking did not disappear — counting the
stubs, walk-mode legs nearly doubled — but it *moved*, from continuous walking
inside the city to short stubs distributed around the network wherever a stop
is.

That is consistent with both target movements. The Eco-Counter sites are a
**cordon**: in-commuters now cross it, so the bicycle ratio rises by 58 % and
the hourly profile correlation reaches 0.92, its best yet. The hystreet sensors
are on a **city-centre shopping street**: the walking that used to pass them
was generated by externals who began their simulated day already inside the
centre, and they now arrive by transit and walk only from the nearest stop.

**The test was run, and it refutes that story.** Counting walk legs passing
within 30 m of Königstraße Mitte, split by origin:

| | at the site | all walk legs |
|---|---|---|
| residents | 11 | 64,405 |
| in-commuters | 8 | 63,109 |

In-commuters are **not** under-represented at the sensor; they contribute 42 %
of the walking there against 49 % of all walking, which is proportional within
the noise. The explanation above is wrong.

What the same measurement shows instead is far more important: **19 of 127,514
walk legs pass Königstraße at all.** The model puts essentially nobody on the
city's main shopping street. That is not a mode-substitution problem and not an
in-commuter problem — it is the destination and routing model never choosing
the high street, which is the same defect the seventh pass attacked with a size
term and only partly moved.

It also means this target cannot support the comparison being made of it. At 19
sampled legs, a change from 1,940 to 660 is a change from roughly sixty legs to
nineteen: the sign is probably real, the magnitude is mostly sampling noise at
stride 10, and no pass should be graded on it until the stride is lowered or
the destination model puts somebody there. The bicycle cordon, with 432 matched
site-hours, is the sounder of the two Stuttgart targets and it improved.

Two things it does not change. The trip rate and the mobile share both moved
decisively toward their published values, and those are measured against the
city's own statistics rather than against a sensor whose location hystreet does
not publish. And the level on Königstraße was never within two orders of
magnitude of observed (660 simulated at Mitte), so this target was not close enough
to be described as having regressed from a good state.

**Cost.** The traced day took 90 minutes of routing for 372,255 queries at a
28 % cache hit rate, against 165,281 queries before: long cross-city journeys
are both more numerous and far less cacheable than local ones. The publish path
was also rewritten to reduce the traced day as it is produced rather than
holding the nested traces and their flattened copy at once, after the OOM
killer took a 6 GB heap mid-Stuttgart; peak heap is now 2.8 GB for two city
runs where it previously exceeded six.

### Why Königstraße is empty: the attractiveness is nonsense

Traced 2026-09-12. Neither the graph nor the destinations are missing. There is
a street node **6 m** from the sensor, and **194 firms within 150 m of it, 86
of them storefronts and 73 retail**. The router can get there and there is
plenty to go to.

The destination kernel is `attract^α · (1 + d/d₀)^−β`, and `attract` is the
firm's employee count where the register knows one, falling back to a
co-location street-density proxy otherwise. In Stuttgart the synthesis gives
*every* Overture place an employee count, so the fallback never runs — and
those counts are badly misallocated:

| retail attractiveness | value |
|---|---|
| citywide median | 2 |
| 90th percentile | 22 |
| 99th percentile | 182 |
| maximum | 2,889 |
| **median of the 73 retail shops on Königstraße** | **1** |
| largest on Königstraße | 221 |

The city's most attractive retail venues are a small convenience store with
2,889 synthetic employees 6.2 km away, a knitting shop with 1,811, and an
industrial firm with 1,416 that is not retail at all. This is the same defect
the sixth pass noted in passing when a small Stadtteil carried the Untertürkheim
payroll on a winery; it is not a curiosity, it is the dominant
term in destination choice.

The arithmetic is unforgiving. A shop with attract 1 a hundred metres away
scores 0.69; the distant convenience store with 2,889 scores 17.1 from six
kilometres. It wins by a factor of 25 from across the city, in every cell. That
is why the per-cell choice sets reach 8–10 km and why, **standing on
Königstraße itself, only 3 of the 64 retail choices are on Königstraße** — and
from Bad Cannstatt, Vaihingen or Feuerbach, none are.

So the kernel is doing exactly what it was asked to. It is being asked with the
wrong numbers, and no change to α, β or d₀ can fix that: the size term is the
whole effect (seventh pass) and the sizes are wrong.

**What would fix it**, in order of how much it is worth:

1. **Stop letting a synthesized number silence the measured proxy.** The
   co-location density fallback is the thing that makes Main Street bigger than
   a corner shop in Vancouver. In Stuttgart it never runs. Use it whenever the
   employee count is not *observed*, which in Stuttgart is always.
2. **Allocate sector employment plausibly.** The register total for a sector is
   right; spreading it across Overture places without regard to what the place
   is puts a department store's payroll on a knitting shop.
3. **A size proxy that is not payroll at all**: retail floor area, building
   footprint from the OSM building layer or LoD2, or simply the count of
   customer-facing venues per block, which is what a high street *is*.

### The cheap fix, measured, and why parameter tuning cannot finish the job

Applied 2026-09-12: `:emp-observed` on every firm, so a synthesized headcount
no longer outranks the street-density proxy, plus 969 non-establishment rows
dropped. Measured on the published Stuttgart world without re-running a day, by
rebuilding the retail table and asking what share of retail demand it sends to
Königstraße, weighted by where people live:

| | before | after |
|---|---|---|
| per-cell choice-set radius | 8–10 km | **220–700 m** |
| Königstraße in the centre's own choice set | 3 of 64 | **11 of 64** |
| expected share of retail trips reaching Königstraße | 0.84 % | **1.25 %** |

The artefacts are gone and shopping is local, which is what a convenience-goods
kernel should do. The centre is still not reached from the suburbs.

**A kernel sweep says tuning cannot fix that, and says why.** The same metric
over the destination parameters, with the population-weighted mean chosen-venue
distance alongside it:

| α | β | d₀ | Königstraße share | mean trip |
|---|---|---|---|---|
| 1.0 | 2.0 | 500 | 0.0125 | **4.0 km** |
| 1.0 | 1.5 | 500 | 0.0184 | 4.8 km |
| 1.0 | 1.0 | 500 | 0.0294 | 5.8 km |
| 1.0 | 0.7 | 500 | 0.0331 | 6.3 km |
| 2.0 | 1.0 | 500 | 0.0354 | 6.6 km |
| 1.0 | 1.0 | 2000 | 0.0359 | 6.4 km |

**MiD 2017 Stuttgart puts the mean shopping trip at 3.6 km** (table W12). The
shipped kernel produces 4.0 km, which is close, and every setting that triples
Königstraße's share pushes the mean to 6 km or more and breaks a fit we already
have. The trip-length distribution is not the thing that is wrong.

So the centre cannot be reached by making everything slightly further away. It
needs the *size* term to be right about the centre specifically, which is an
argument for measured floor area or a curated register of anchors rather than
for any exponent.

**A second decomposition the target needs.** The observed weekday count on
Königstraße, in the tens of thousands, cannot be shopping arrivals:
Stuttgart's residents make on the order of 300,000 store trips a day in total,
so the sensor would have to capture a large share of them. Most of that count is people walking *along* Königstraße between other
places — it is the main pedestrian axis from the Hauptbahnhof to Schlossplatz.
The model has no reason to route anyone through a pedestrian street they are
not going to, and until arrivals and through-traffic are separated this target
cannot be scored as one number.

**Method note.** The expected-demand share is computable in seconds from the
gravity table alone, where the pedestrian count needs a 90-minute traced day
and then delivers 19 legs of signal. Destination-model changes should be
iterated against the former and only then confirmed with the latter.

### The destination fix, scored against the retail census

The centrality target (`doc/sources/economy.md`) arrived after the fix was
committed, so it could be applied as a genuine out-of-sample test:
`city.sim.validate/retail-centrality` reads the simulated ratio straight off the
gravity table, weighting each cell's choice set by the people who anchor there
and summing by destination district. No traced day, seconds to compute.

| | payroll attractiveness (as published) | street-density proxy (the fix) |
|---|---|---|
| correlation across 23 districts | 0.267 | **0.987** |
| log-correlation | 0.328 | 0.752 |
| mean absolute log ratio | 1.058 | **0.760** |
| **Mitte, simulated against an observed 10.54** | **1.72** | **11.46** |

**The centre goes from 16 % of its measured draw to 109 % of it.** The fix I
could previously only measure as "expected demand share 0.84 % → 1.25 %" turns
out to have very nearly solved the target it was aimed at, and the evidence is
22 districts rather than one sensor.

Read the two correlations properly. The 0.987 is carried by Mitte, which is an
order of magnitude above every other district; the log-correlation of 0.75 is
the honest statement about the rest of the range, and a mean absolute log ratio
of 0.76 means a typical district is still out by a factor of 2.1.

Where the remainder sits:

| district | observed | simulated | ratio |
|---|---|---|---|
| Mitte | 10.54 | 11.46 | 1.09 |
| Wangen | 1.36 | 0.65 | 0.48 |
| Feuerbach | 1.20 | 0.57 | 0.47 |
| Vaihingen | 0.55 | 1.51 | 2.75 |
| Plieningen | 0.28 | 0.84 | 2.99 |
| Münster | 0.47 | 0.05 | 0.10 |
| Nord | 0.29 | 0.00 | 0.01 |

Two failure shapes, and they say different things. **Wangen and Feuerbach are
under-served by the model at about half their measured draw**, and both are
districts whose retail is large-format — the density proxy counts *venues per
block*, so a single big-box store on its own site scores as one shop. That is
exactly the error a measured floor area removes, which is the next change.
**Nord and Münster are near zero**, which is a different fault: their few retail
venues sit inside the choice sets of neighbouring districts and lose.

Also worth stating: this test uses residents as a proxy for purchasing power,
where the study uses measured purchasing power, which varies across Stuttgart's
districts by roughly ±35 %. That is a known term in the comparison rather than a
silent one, and correcting it needs the income layer.

### Ninth pass: venue size measured, choice set widened (2026-09-12)

Everything in this pass is scored on the retail census's own centrality, 22
usable districts, read off the gravity table in seconds without a routed day.

| | log-corr | mean abs log ratio | Mitte (observed 10.54) |
|---|---|---|---|
| synthesized payroll, as shipped | 0.328 | 1.058 | 1.72 |
| street-density proxy | 0.752 | 0.760 | 11.46 |
| **footprints raked to the census, K = 256** | **0.854** | **0.416** | **8.25** |

A typical district is now missed by a factor of 1.52, against 2.88 when the
size term was a synthesized headcount.

**Three findings worth separating from the numbers.**

*The proxies measure different things and neither is sufficient.* The density
count measures agglomeration and alone reaches the centre's observed draw; the
footprint measures unit size and is much better across ordinary districts;
summing split footprints over a block scores worse than either parent, because
the parts sum back to the building area and the agglomeration cancels exactly.
Raking resolves it by taking the within-district shape from the footprint and
the level from a measurement.

*The exponents never needed refitting.* (Revised later: these exponents were
compared on a choice table truncated at K = 256. The eleventh pass showed that
the truncation changes the choice rule, the default became β = 1.6, and the
fifteenth pass and [doc/model.md](model.md) §9 infer β instead.) Once the size term is measured, α = 1
and β = 2 win on both the centrality error and the independent check of MiD's
3.6 km mean shopping trip. Raising α is structurally wrong here, not merely
worse: the size term is raked to measured district totals, so α = 1 preserves
that level and anything else destroys it. The Karlsruhe survey's fitted trip
exponents (0.94, −1.24) do better on the centre and worse overall, and stretch
the mean trip to 5.3 km.

*The binding parameter was a truncation, not a behaviour.* K bounds how many
destinations a cell may consider, so a larger K is simply less approximation.
It was still improving at 256 when 512 exhausted an 8 GB heap with three runs
resident. That limit is set by memory rather than by diminishing returns, which
is a concrete argument for the data-parallel port rather than an abstract one.

**Inputs acquired for it:** 193,299 OpenStreetMap building footprints for
Stuttgart, 22,863 of 25,743 firms matched to the smallest polygon containing
them with a building shared by n firms giving each area/n; and the 2021
establishment census's retail floor area for all 23 Stadtbezirke, whose parse is
checked against our own synthesized population to within 4.7 % per district.

### The ninth pass on the published run

Republished 2026-09-12 with the measured size term, K = 256, and a stride of
20 rather than 10 (memory, below). The gravity-table prediction and the routed
day agree to three decimals, which is worth knowing in itself: the fast metric
is a faithful predictor of the published run, so destination work can be
iterated in seconds and confirmed once.

| | published run |
|---|---|
| trips per person per day | 2.641 (2.645 at stride 10 — the stride does not move it) |
| share making any trip | 0.792 |
| retail centrality, log-correlation over 23 districts | **0.854** |
| mean absolute log ratio | **0.415** |
| Mitte, observed 10.54 | **8.25** |

**The counted targets moved with it.** The six city-centre pedestrian sensors,
simulated weekday passings (the observed counts come from hystreet and are not
reproduced here):

| site | before this pass | after |
|---|---|---|
| Königstraße Mitte | 660 | 1,020 |
| Königstraße Nord | 280 | **2,920** |
| Königstraße Süd | 1,800 | 2,160 |
| Schulstraße | 320 | 720 |
| Stiftstraße | 390 | 600 |
| Hirschstraße Mitte | 340 | 700 |
| **total** | **3,790** | **8,120** |

Every site rose and the aggregate more than doubled, with Königstraße Nord up
tenfold. They remain far below the observed counts, which is the standing
gap and partly the target's own problem: these are passings on a pedestrian
axis, most of whose traffic is people walking *between* other places, and this
model has no reason to route anyone through a street they are not going to.

**The bicycle cordon reads 0.425 against 0.488 before**, with the hourly
profile correlation at 0.895 against 0.924. Do not read that as a regression:
the stride doubled in the same change, so the comparison is confounded and the
count halved before scaling. It is a wash at best and needs a matched-stride
measurement before anything is claimed.

### Memory

**Our polyline representation was six times heavier than it needed to be.**
A 20-point routed polyline costs **2,353 bytes** as vectors of vectors and
**354** as one primitive array, because every point was a PersistentVector
holding two boxed Doubles. The route cache bounds at 450,000 entries across
three walk variants, about a gigabyte of pure overhead, and a published day's
legs were another 700 MB.

Fixed: cached polylines are primitive arrays (contained to the router, the
public `:path` shape unchanged and a cache hit reproduces an identical path);
and the trace stride doubled, which halves the legs and cut routing from 90
minutes to 53.

Still outstanding: the *published* legs are still vectors of vectors, worth
about 400 MB at this stride. That change touches the serving and validation
paths and was deliberately not made mid-republish.

### Error budget after this pass

1. **Destination attractiveness for a city centre.** 19 of 127,514 walk legs
   pass Königstraße. Nothing sends anyone to the high street, so it is two
   orders of magnitude short and the measurement is too sparse to grade a pass
   on. This is now the top term, promoted by the test above.
2. **The walk/transit substitution for long journeys.** Pure walk legs fell a
   third while transit rose nineteenfold: an in-commuter's in-city portion
   inherits the mode of a journey that began 15 km outside the boundary. Real,
   and it depresses every pedestrian count, but it is not what moved
   Königstraße.
3. **Trip generation residual.** 2.645 against 2.861 is 92 % of target, with a
   further 14 % lost between the diary and the emitted leg where a destination
   resolves to the location the person already occupies.
4. **Crossing versus passing**, and hystreet's unpublished sensor location,
   unchanged and unfixable by any model change.

## Tenth pass — two scores the data finally allowed (2026-09-12)

A day of extraction (see `doc/sources/employers.md`, not in the published repository, and the receipts under
`data/derived/`) produced two targets this simulator had never been scored
against. Both are cheap: neither needs a routed day, and the firm one needs no
day at all.

### Retail revenue, in euros

The 2024 Einzelhandels- und Zentrenkonzept publishes **turnover per
Stadtbezirk** — 4,484.4 M € citywide, of which Mitte alone is 1,905.8 M € —
along with purchasing power, floor area and establishment counts, for all 23
districts and all 76 zentrale Versorgungsbereiche, each split by 20 assortment
groups. `city.synth.retail/targets` loads it; `validate/retail-revenue` scores
against it.

The model distributes that known total by its own choice probabilities. First
run, on the published Stuttgart world (936,597 persons, 24,849 firms):

| metric | value |
|---|---|
| districts scored | 23 |
| share of the city's retail euro in the right district | **83.4 %** |
| mean absolute log ratio | 0.42 (a typical district missed by ×1.5) |
| Mitte | 1,431.2 M € simulated against 1,905.8 M € observed, ratio 0.75 |

The residual is not noise and it points at the kernel:

| district | observed | simulated | ratio |
|---|---|---|---|
| Mitte | 1,905.8 | 1,431.2 | 0.75 |
| West | 230.0 | 160.9 | 0.70 |
| Möhringen | 182.1 | 302.2 | **1.66** |
| Weilimdorf | 156.4 | 217.6 | 1.39 |
| Feuerbach | 281.5 | 366.8 | 1.30 |

The centre is undershot and the suburbs overshot: the choice set spreads too
evenly. That is the same under-concentration the centrality score reports as
Mitte 8.25 against 10.54, now denominated in euros — about **475 M € of annual
turnover moved out of the centre that belongs there**. Error term 1 of the
ninth pass, restated in a unit that can be argued with. (Corrected in the
eleventh pass: most of this under-concentration was an artefact of truncating
the choice table at K = 256. On the exact kernel at β = 1.6, 5.9 % of the
retail euro is misplaced (16.6 % here) and Mitte reads 0.92 of observed (0.75
here).)

**What this is not.** The citywide total is taken from the census, not
predicted. The model has no prices and no baskets. Only the *distribution* is
the model's own claim. That is still a stronger test than a ratio — a model can
reproduce centrality while being wrong about scale everywhere by one factor —
but it is not "we derive revenue", and it should not be described as such.

**A caveat retired rather than fixed.** `retail-centrality` proxied purchasing
power by resident count and warned that the study's own Kaufkraft varies ±35 %
per district. Now measured: passing the real Kaufkraft moves log-correlation
0.825 → 0.832 and the mean absolute log ratio 0.431 → 0.429, Mitte 8.25 → 8.21.
The proxy was fine. Both scores now read the same `retail-demand-share`, so they
cannot drift apart, and the refactor reproduces Mitte at 8.25 exactly.

### The firm stock, and a parameter that was never calibrated

Jahrbuch 5.2.4 gives sixteen years of establishments: **33,174 (2008) →
31,467 (2023)**, a **−0.35 %/yr** drift, so twenty years multiplies the stock
by 0.93. The eighth pass recorded Stuttgart at **+80 %** over the same horizon
and correctly diagnosed the cause as structural — births scale with workers,
deaths with firms, so the stationary count follows the workers-per-firm ratio,
and Stuttgart's is ~20 against Vancouver's ~9 because Overture under-counts
firms. But ν itself had never been fitted to anything: 0.01 was a prior centre.

ν is the one parameter that sets the net drift, so it is solved *for*, with exit
held at the age hazard — the hazard has a survival curve behind it and founding
had nothing. Result **ν = 0.0037**, four-seed mean over 240 months −0.35 %/yr
against the measured −0.35 %/yr, seeds spanning −0.23 % to −0.55 %. The seed
spread (±0.16 pp) is as large as the residual bias, so this is calibrated to the
limit of the compute term and deliberately no further. `validate/firm-stock-drift`
scores it.

**The flows came along, and they were not in the calibration.** The
Unternehmensdemografie (52111-51/52-01-4, 2023) gives births 2,369/yr and
deaths 2,494/yr:

| | before (ν = 0.01) | after (ν = 0.0037) | register |
|---|---|---|---|
| stock at 240 months | 46,355 (+80 %) | 23,484 (−5 %) | 26,251 |
| births/yr | 6,126 | **2,434** | 2,369 |
| deaths/yr | — | **2,568** | 2,494 |

Absolute births and deaths land within 3 % of a target that was not used to fit
ν. That is out-of-sample agreement, and it is consistent with the kernel's
*form* being right and only its founding rate being wrong.

The rates still read high — 10.4 % and 10.9 % against 9.0 % and 9.5 % — but only
because the denominator is our own under-counted register: 23,484 firms against
26,251 Unternehmen and 31,467 Niederlassungen. **So ν = 0.0037 is conditional on
the current register and must be re-fitted once the anchor repair raises the firm
count**, which will lower workers-per-firm from today's 22.2 and change the
stationary point. That dependency is the honest caveat on this number.

Cost: the tail exponent moves 1.48 → 1.42 against 1.50 observed in Vancouver
licence counts. A 0.06 degradation on a transferred target, in exchange for
turning a +80 % stock error into −5 % and bringing two independent flow measures
into line. Stuttgart now has its own size-distribution target anyway —
Jahrbuch 5.2.6, the section × size-class joint — which is the better thing to
score the tail against next.

### Error budget after this pass

1. **Destination under-concentration.** Unchanged as the top term but now
   measured in money: 475 M € of annual turnover in the wrong districts, the
   centre short by a quarter and the outer districts long by a third to two
   thirds. Same defect as the Königstraße shortfall. (Corrected in the eleventh
   pass: this term was mostly the K = 256 truncation, not the kernel; see the
   note in the retail revenue section above.)
2. **The firm register's count and top end.** 24,849 firms against 31,467
   establishments, no firm above 187 employees in the manufacturing cells that
   need them, and 16,741 synthetic jobs of the Untertürkheim plant on three
   wineries. Every input for
   the repair is now on disk; it is blocked on one scope decision.
3. **Trip generation residual and the walk/transit substitution**, both
   unchanged from the ninth pass.

## The resident mobility gap, traced to out-commuters (2026-09-12)

Trip generation sits at **2.675 per person against a 2.861 target**, 93.5 %, and
the shortfall is not where the aggregate suggests.

**Split by group**, on a stride-200 traced day over the rebuilt world:

| group | eligible | mobile share | trips/person |
|---|---|---|---|
| in-commuters | 326,153 | **0.873** | 3.061 |
| residents | 527,888 | **0.737** | 2.436 |
| city | 854,041 | 0.789 | 2.675 |

In-commuters are on target — they have a commute by construction. Residents are
ten points short of the 0.834 the tilted diary pool carries.

**Split again, within residents**, and it resolves completely:

| group | eligible | mobile share |
|---|---|---|
| residents working in the city | 405,693 | 0.779 |
| **out-commuters** | **122,195** | **0.597** |

Every low-mobility person type is resident-only and 100 % without an assigned
workplace — type 18 sits at 0.212 mobile, type 25 at 0.265 — and all 122,195 of
those people are flagged `:outside`. **Zero** employed residents are unplaced by
accident, so the workplace assignment is not failing; this is a modelling gap,
and a visible asymmetry:

- an **in**-commuter is given a home at the city edge on the side they come from
  and travels in, so their day is complete;
- an **out**-commuter is correctly identified and then given no destination at
  all, so they stay home and read as immobile.

The arithmetic closes. Out-commuters are 23 % of eligible residents; at the
~0.95 mobile share a commuter actually has, residents would reach ≈0.82 against
the 0.834 target, which is the whole gap.

### Fixed, 2026-09-13

`cityworld/place-out-commuters!` gives each out-commuter an exit point — a
destination Kreis centroid clamped into the city's bounding box — and
`daily2` emits a work leg to it when the person holds no firm. Measured on the
same stride-200 traced day:

| | before | after | target |
|---|---|---|---|
| mobile share | 0.789 | **0.832** | 0.834 |
| trips per person | 2.675 | **2.845** | 2.861 |
| residents, mobile share | 0.737 | **0.807** | — |
| in-commuters, mobile share | 0.873 | 0.873 | — |

Trip generation is at **99.4 % of target**, from 93.5 %. In-commuters are
untouched to three decimals, which is the check that matters: the change is
confined to the population it was aimed at.

The 122,195 are placed in the published proportions — Esslingen 27,451,
Ludwigsburg 25,392, Böblingen 20,570, Rems-Murr 14,876, Übrige 27,890.

Exit points live on the persons block as `:exit-lon` / `:exit-lat`, **not** as
boundary firms. Phantom firms would have been handed 122,195 workers by
`firms/init` and would have wrecked a size distribution whose tail exponent is
currently 1.52 against an observed 1.50.

Still open, and unchanged by this: we carry 122,195 out-commuters against the
yearbook's 101,756 SvB, and 326,153 in-commuters against 276,247 SvB. Both are
consistent with counting all Erwerbstätige rather than SvB, and the trip rate
above inherits whatever that basis difference is worth.

**The fix was the mirror of `cityworld/place-externals!`**: give an out-commuter a
workplace outside the bbox on the side they commute to, so the trip to the
boundary is generated the same way an in-commuter's inbound trip is. The
destinations are now available — `data/derived/stuttgart_commuter_flows.json`
carries out-commuter counts by destination Kreis (Ludwigsburg 19,109, Esslingen
20,783, Böblingen 15,535, Rems-Murr 11,123 for 2020), verified to sum to the
published total.

One calibration note to settle while doing it: the model carries **122,195**
out-commuters against the yearbook's **101,756** (SvB, 30.06.2024), 20 % high —
the same basis question as the in-commuter side, where the model's 326,153 sits
against 276,247 SvB. Both are consistent with our figures counting all
Erwerbstätige rather than SvB, and both should be stated on one basis before
either is called calibrated.

## Eleventh pass — K was behaviour, and the exact kernel passes a holdout (2026-09-15)

`city.sim.candidates` began as a speed-up: precompute cell-to-venue distances
once so a kernel change is a reweight. Checking it exposed the destination
model itself.

### The truncation, measured

`gravity-table` keeps each cell's top-K venues by weight and renormalises.
Against the **untruncated** power kernel (β 1.6, d₀ 500, α 1.0, all 3,637
retail candidates), on a 400-cell sample of the 34,650-cell grid:

| K | share of the kernel's choice mass in the top-K |
|---|---|
| 16 | 16 % |
| 64 (production) | **30 %** |
| 256 (ninth/tenth pass sweeps) | **50 %** |
| 1024 | 77 % |
| 2048 | 92 % |

Half of all draws land beyond the 256th-best shop. Every K table implements a
different, much more concentrated choice rule than the kernel it names, and
the two production values score 17.3 % and 13.0 % of the retail euro misplaced
at the same β. **β = 1.6 was calibrated on top of a truncation.** No candidate
superset rescues it — nearest 512 ∪ largest 256 is exact for K = 64 and 17 %
exact for K = 256.

### The exact table

`build-dense` stores every distance as float32 (126 M entries, ~0.5 GB, 17 s
once); `table-dense` gives the exact kernel for any θ in `gravity-table`'s
layout, 2–10 s per θ, agreeing with double-precision rows to a total variation
of 1.5e-8. `step-day` on it takes **0.45 s for 936,597 persons** — faster than
on the K table, since a contiguous row is cache-friendly. Heap 2.8 GB with the
world, less than the K = 512 attempt that exhausted it.

| kernel, β = 1.6 | retail euro misplaced | mean abs log | Mitte |
|---|---|---|---|
| truncated K = 64 | 17.3 % | — | 0.80 |
| truncated K = 256 | 13.0 % | 0.461 | 0.88 |
| **exact** | **5.9 %** | **0.198** | **0.92** |

94 % of the city's retail euro in the right district; a typical district
missed by ×1.22 rather than ×1.5. The truncation had been costing two-thirds
of the destination error.

### The holdout, and why two observables are needed

The exact kernel makes a second prediction the fit never saw: the
resident-weighted expected straight-line distance to the chosen shop.
MiD 2017 puts Stuttgart's mean shopping trip (Einkauf) at **3.6 km**.

| β | misplaced | Mitte | expected shop distance |
|---|---|---|---|
| 1.0 | **4.8 %** | 0.99 | 4.56 km |
| 1.2 | 5.0 % | 0.97 | 4.28 km |
| 1.4 | 5.3 % | 0.95 | 4.00 km |
| **1.6** | 5.9 % | 0.92 | **3.70 km** |
| 2.0 | 8.2 % | 0.85 | 3.09 km |
| 2.5 | 12.8 % | 0.73 | 2.36 km |
| 3.0 | 17.5 % | 0.62 | 1.75 km |

Turnover alone would send β to 1.0 — a nearly distance-blind, floor-area-driven
kernel — and that kernel sends people too far. Trip distance alone pins β near
1.6–1.7. **Neither observable identifies the kernel; together they do**, which
is the whole argument for inference over a hand sweep, and the ridge the
posterior should show.

d₀ tells the same story (250 m → 3.42 km, 2000 m → 4.38 km, turnover preferring
the larger); α barely moves distance and is best on turnover at 1.0. A hard
reach bound is ruled out: cutting the kernel at 3 or 6 km gives 25–28 %
misplaced and Mitte at 0.5 — the fat tail is real, the centre is reached from
everywhere.

**Caveats, in order of size.** MiD reports self-reported *route* km; ours is
straight-line. A detour factor of ~1.25 moves the crossing toward β ≈ 2.0,
still inside the ridge, and the comparison should be made on routed distance
once the day is traced on the exact table. MiD's Einkauf includes grocery
trips; the scored table is the retail class only (restaurants are a separate
class). Grid is 34,650 cells here against 12,394 in earlier passes — different
extent, same kernel.

### What changes

- Never calibrate on a K table again. `prepare` takes `:retail-table :dense`,
  default on, recorded in the published config.
- Previously reported destination numbers (β sweep, 13.0 %, Mitte 0.88) were
  K = 256 results and stand as such; the exact-kernel figures supersede them.
- The kernel parameters are now cheap enough to infer rather than sweep, with
  turnover and trip distance as the two observables. That is the next pass.

## Twelfth pass — the kernel inferred, not swept (2026-09-15)

`city.infer` runs the destination kernel as a probabilistic program through
spindel: θ = (α, β, d₀) from the priors `run/defaults` declares, the exact
table (`candidates/table-dense`) as a host simulator giving derived turnover
per district, a log-normal observation model (σ = 0.15) over the published
districts, and `smc-infer` with one forked execution context per particle.

**Synthetic recovery on the real city.** Observations generated at
θ\* = (1.0, 2.0, 500 m), 48 particles, 23 observe barriers, 524 s
(10.9 s per evaluation, serialised on the shared 1.5 GB buffer):

| | α | β | d₀ |
|---|---|---|---|
| truth | 1.0 | 2.0 | 500 |
| posterior weighted mean | 1.08 | **2.12** | 443 |
| best particle | 1.20 | 2.27 | 377 |

Recovered. The tiny-world version is a test in the suite (160 particles,
seconds, fresh JVM).

**The honest diagnostic is not ESS.** The run reports ESS 33.5 of 48 — and
`distinct-theta` **5**. With spindel's prior kernel there is no move step:
resampling at each of 23 barriers duplicates survivors and never proposes new
θ, so the final set collapsed onto five ancestors, each copied about ten
times. ESS is computed over the copies and flatters the result. The effective
posterior is five draws from the prior, reweighted. `summarise` reports both,
and `distinct-theta` is the number to read.

**What follows from that.** Rejuvenation (an MH move between barriers) is
required for anything real, and every MH step is one evaluation — 500
particles × 10 moves is ~14 hours serialised on the JVM. The bottleneck is
evaluation, not algorithm: spindel already has random-walk and single-site MH,
custom-proposal MCMC, PIMH, PGibbs, PGAS. The port worth making is a raster
kernel that evaluates `table-dense` for a *batch* of θ in one launch, and a
batched checkpoint in spindel so particles waiting at a barrier are evaluated
together. Measured cost of the memory model as it stands: 48 retained particle
contexts took the heap from 2.6 to 4.5 GB, ~40 MB per particle for three
numbers — profile before scaling.

Next: the same run on the published turnover, with MiD's 3.6 km shopping
distance as the held-out check on the surviving θ.

## Thirteenth pass — the real posterior, and what a seed means (2026-09-15)

**A run that was not what it said.** The first "real-data" run of the night
observed `OBS*`, which was the synthetic target from the recovery run, not
the published turnover. It reported a tidy posterior around β ≈ 2.7 and was
about to be written up as such. What caught it was the check that should
precede every fit: scoring a few hand-picked θ against the observations the
run claims to use. The residual at θ\* was exactly zero. Nothing in the run's
output could have revealed this — the numbers were plausible, the ESS was
fine — so the rule is procedural: score the observation map by hand before
inferring on it, and name observation maps by what they contain, never by
what they are for.

**The likelihood landscape on the published turnover** (23 districts, log
residual of derived turnover against `:umsatz-eur`):

| θ = (α, β, d₀) | RMS log residual | Mitte ratio | worst districts |
|---|---|---|---|
| (1.0, 1.0, 500) | 0.290 | 1.08 | Obertürkheim −0.56, Wangen +0.48, Hedelfingen −0.47 |
| (1.0, 1.6, 500) | 0.263 | 1.02 | Obertürkheim −0.60 |
| (1.0, 2.0, 500) | **0.244** | 0.94 | Obertürkheim −0.53 |
| (1.0, 2.7, 1250) | 0.256 | 0.93 | Obertürkheim −0.56 |
| (0.5, 1.6, 500) | 0.266 | 0.87 | West +0.60, Süd +0.47 |
| (1.3, 1.6, 500) | 0.454 | 1.08 | Obertürkheim −0.93 |

Two things follow. The residual floor is ~0.24 in log terms and does not
move along the β ridge: the same three Neckar-valley districts are wrong by
half a log unit at every kernel, which is a placement error in the register
(Wangen over, Obertürkheim and Hedelfingen under, adjacent districts), not a
kernel error. And α is sharply identified while β is not: α = 1.3 costs 18
nats at σ = 0.3, β from 1.0 to 2.0 costs 3. So σ = 0.15, the value used for
the synthetic runs, claims a fit the model cannot reach on real data (best
attainable log-likelihood −30 against 0 for a perfect fit), and every
particle would be scored on noise. The real runs use **σ = 0.25**, the
residual scale the model actually attains.

**Posterior, prior kernel, 48 particles, σ = 0.25, 531 s:** distinct-theta
**16**, ESS 24.6, weighted mean (α 0.78, β 1.76, d₀ 812 m). The wider σ keeps
three times as many ancestors alive as the synthetic run did. Surviving θ,
best first, with the two checks the run does not fit:

| α | β | d₀ | log-weight | misplaced | Mitte | shop-km (straight-line) |
|---|---|---|---|---|---|---|
| 0.77 | 2.08 | 979 | −0.37 | 0.079 | 0.84 | 3.39 |
| 0.88 | 1.61 | 464 | −0.42 | 0.062 | 0.89 | 3.62 |
| 0.69 | 1.69 | 785 | −1.02 | 0.076 | 0.86 | 3.74 |
| 0.83 | 1.26 | 1329 | −1.17 | **0.047** | **0.95** | 4.52 |
| 0.92 | 1.28 | 920 | −2.00 | **0.047** | **0.96** | 4.36 |
| 0.57 | 1.69 | 1229 | −2.56 | 0.085 | 0.85 | 3.98 |
| 0.53 | 2.82 | 1768 | −3.47 | 0.126 | 0.73 | 3.07 |
| 0.48 | 2.76 | 1912 | −4.01 | 0.125 | 0.74 | 3.20 |

Reading it. The second survivor is the hand-tuned kernel of the eleventh
pass, found from the prior by inference, with α a little under 1. The top
five are within 1.6 nats of each other across β from 1.26 to 2.08: on
turnover alone the posterior is close to the prior along that ridge, as the
landscape said it would be. The flattest kernels (β ≈ 1.27) are the best on
the two turnover-derived checks — misplaced share 4.7 %, Mitte 0.95 — and
the worst on the one the run did not see: they send residents 4.4–4.5 km
straight-line for shopping. MiD 2017 reports 3.6 km door-to-door for the
region; at a detour factor of 1.25 that is ~2.9 km straight-line, which
**no survivor reaches**. Every θ the turnover accepts over-predicts the
shopping distance, and the steep θ that come closest (β ≈ 2.8, 3.1–3.2 km)
are the worst on turnover. That is the eleventh pass's tension, now measured
on a posterior rather than a sweep. The distance observe (`:distance`, added
today, with the detour factor stated by the caller) trades the two off
explicitly, but trading them off is not a fix: no θ satisfies both.

**The diagnosis was wrong, and the data said so within the hour.** The first
version of this section blamed missing non-resident demand: in-commuters and
visitors spend in the centre, the model has no such money, so the kernel has
to fake it by sending residents too far. That is wrong at the city scale, and
the EZK's own numbers refute it. Summed over the 23 Stadtbezirke:

| | million € per year |
|---|---|
| retail turnover | 4,484.4 |
| residents' retail purchasing power | 4,650.9 |
| city retail centrality | **0.96** |

Stuttgart sells slightly *less* than its own residents can spend. Our world
carries 4,651 M € of resident retail potential, raked to that same IFH figure,
and over-predicts the published turnover by 3.7 % — which is the same 0.96
read from the other side, and exactly the `city-ratio` 1.037 that every θ in
the landscape above produces. There is no missing pot of outside money in
aggregate. A model that added in-commuter spending without also letting
residents spend outside the city would make the city total worse, not better.

**What is missing is the segment structure, and it is already on disk.** The
EZK splits every district into three demand classes that reconcile to its
totals, and they do not behave alike:

| segment | turnover | resident potential | city Z | Mitte Z |
|---|---|---|---|---|
| kurzfristiger Bedarf (food, convenience) | 2,168.7 | 2,443.1 | 0.89 | 4.49 |
| mittelfristiger Bedarf (clothing, shoes) | 1,331.7 | 732.5 | **1.82** | **36.72** |
| langfristiger Bedarf (furniture, electronics) | 979.8 | 1,356.8 | 0.72 | 8.17 |

The three sum to 4,480.2 M € of turnover against the 4,484.4 M € district
total, and to 4,532.4 M € of purchasing power against 4,650.9, the residue
being the `Sonstiges` group that sits in no class.

This dissolves the contradiction without a new mechanism. Food shopping is
local — city centrality 0.89, Mitte only 4.49 — and it is the large majority
of shopping *trips*, which is what MiD's 3.6 km average measures. Clothing is
a rare trip to the centre with a Mitte centrality of 36.72 and is 38 % of
Mitte's turnover. One kernel asked to explain both had to choose between
putting the money in Mitte and keeping the trips short, and the posterior
above is that choice being made badly in both directions. Three kernels, one
per segment, each scored against its own published district map, can satisfy
both at once: 69 observations instead of 23, against 9 parameters instead of 3.

**Non-residents do belong, at a size the data fixes.** The medium-term segment
draws 599 M € more than residents can spend while long-term goods leak 377 M €
out to regional big-box stores, and those two nearly cancel. So the correct
model is two opposing flows, not one: in-commuters and visitors buy clothes in
Mitte, Stuttgart residents drive out of the city for furniture. The
in-commuters are already in the world — 326,153 external persons with real
workplaces — so giving them a spending capacity anchored at the workplace cell
is a small change. Visitors are the one piece with no data in hand. The
constraint that keeps all of it honest is that the three segment balances must
reproduce themselves *per district*, and the city-level 0.96 must fall out
rather than be imposed.

The lesson is the same one as the mislabelled observation map, one level up:
the residual was real, the story attached to it was invented, and five minutes
with the source table would have caught it before it was written down. See
[the model description](model.md) for the algebra of both the current model
and the segmented one.

**What a seed meant, and means.** `:seed` was added to make runs
reproducible and the tests said it worked, twice, in fresh JVMs. Then it
failed. Two causes, both now written down where they were found. spindel
drew its systematic-resampling offset, MH site choice and acceptance from
`clojure.core/rand`, which no seed touches — so a seeded run was
reproducible in its prior draws and random in its moves; that is fixed in
spindel today, every inference-side draw now goes through anglican's seeded
generator. And even with one executor thread, particle contexts are started
by one thread while another drains them, so N particles race for the one
stream and assemble θ from whichever draws they win: two seeded 24-particle
runs agreed in most fresh JVMs and disagreed in about one in three. What a
seed guarantees today is that every draw comes from the seeded generator and
that a single chain is bit-reproducible; the test asserts exactly that. The
fix is a counter-addressed generator per particle in spindel, keyed by
(seed, particle, draw index) and re-derived for children at every fork, the
way the day kernel already addresses its draws by (seed, person, k). That
needs anglican's `RNG` to be rebindable and spindel to bind it wherever it
binds `*execution-context*`; it is the change that makes the memory model's
forks reproducible independent of scheduling, which is what a counterfactual
comparison under common random numbers requires.



## Fourteenth pass — the segmented kernel, and an aggregate that looked fine because three errors cancelled (2026-09-15)

The three demand classes are implemented (`city.synth.segments`,
`candidates/reduce-dense`) and evaluated on the real city. The headline is not
the fit. It is what the aggregate was hiding.

**The city ratio of 1.037 was three large errors cancelling.** Splitting the
same resident money by the concept's own per-class purchasing power and
pushing each class through the kernel gives, summed over the 23 districts:

| class | predicted ÷ published | in log |
|---|---|---|
| kurzfristig (food, convenience) | 1.156 | +0.145 |
| mittelfristig (clothing, shoes) | **0.564** | −0.572 |
| langfristig (furniture, electronics) | 1.421 | +0.351 |
| all retail together | 1.037 | +0.036 |

These level errors are independent of θ — they are set by the money split, not
by the kernel, and they do not move when the exponents do. So the unsegmented
model's 3.7 % miss was an average of −44 %, +16 % and +42 %. It looked
well-calibrated because the clothing shortfall and the furniture surplus are
nearly the same size. That is Axtell's objection in miniature, inside our own
economic layer, and it is only visible once the aggregate is split.

Each of those three numbers is a mechanism the model does not have, now
measured separately instead of averaged away. Clothing is short by 599 M €,
which is the in-commuter and visitor spending the eleventh pass looked for in
the wrong place. Furniture and DIY are over by 377 M €, which is Stuttgart
residents driving to the region's big-box stores. Food is over by 274 M € for
the same reason at shorter range.

**The kernel part works, and the clothing class is where it pays.** Dividing
each class's own level out leaves the spatial error the kernel is actually
responsible for:

| class | one kernel, β = 2.0 | own kernel | |
|---|---|---|---|
| kurzfristig | 0.172 | 0.196 | β 2.6, d₀ 400 |
| mittelfristig | 0.407 | **0.191** | β 1.3, d₀ 800 |
| langfristig | 0.361 | 0.347 | β 2.0, d₀ 600 |
| unsegmented, all retail | 0.242 | | β 2.0, d₀ 500 |

A flat kernel on comparison goods halves that class's shape error, from 0.407
to 0.191, which is better than the unsegmented model manages on all retail at
once — and it does so while food keeps its own steep kernel. That is the
trade-off the twelfth and thirteenth passes could not make: one kernel had to
choose, three do not. Food's optimum is near β = 2.0 rather than the 2.6 tried
here; these are two hand-picked points, not a fit.

**Expected straight-line shopping distance is now per class**, which is what
makes the mobility survey usable as a check rather than a compromise: 2.81 km
for food, 3.68 for clothing, 3.10 for furniture under one kernel. Combining
them into the survey's single 3.6 km average needs the share of *trips* each
class takes, which is a mobility-survey quantity we do not have yet, and it is
deliberately not invented. Until it arrives the distance check stays per class.

**The fused evaluator paid for itself immediately.** `reduce-dense` computes
the same expectation as `table-dense` without materialising the CSR — a test
asserts they agree to 1e-6 — and all three segments evaluate in **1.4 s**
against about 11 s for one unsegmented table build, because the 1.0 GB cdf
write is what dominated. Three segments therefore cost less time and the same
memory as one did, and the likelihood went from 23 observations to 69.

**Two things the plumbing turned up.** The world was throwing the assortment
away: `:type` collapses licence type, storefront category and place category,
and for Stuttgart the register's section name wins, so all 3,637 retail firms
read `G Handel; Instandhaltung und Reparatur von Kraftfahrzeugen`. The fine
category is now kept beside it as `:category`. And the retail flag admits
about 9 % non-retail — 132 marketing agencies, because `retail-place-re`
matches `market` inside *marketing*, plus gastronomy already counted as food.
Those firms are currently destinations a shopper can be sent to.

**Next.** The non-resident layer, whose size the table above now fixes per
class: in-commuter spending anchored at the workplace cell, resident leakage
out of the city concentrated in `langfristig`, and visitor spending in the
centre. The check is that all three class balances reproduce themselves per
district and the city-level 0.96 falls out rather than being imposed.

## Fifteenth pass — the MH kernel was not one, and now is (2026-09-15)

Every random-walk MH result in this log up to the fourteenth pass was
repeated prior sampling. spindel addresses random choices by a hash chain
whose cursor the engine reseeds at body start and restores at every
track/await resume; the inference checkpoint was the one continuation in
the system that carried no such snapshot, and its replay never rewound the
cursor. Each re-execution therefore minted fresh addresses for every site it
re-ran, the trace filled with dead entries, most proposals landed on a dead
site and were accepted as no-ops (acceptance read 95–100 % while the chain
sat still), and the sites that did re-run were drawn fresh from the prior.
`dev/mh_address_bug.clj` (not in the published repository) was the reproduction; it measured the candidate set
growing 3 → 4 → 7 on a three-sample model.

Three more defects surfaced while fixing it. Replay cleared every checkpoint
but the resume site, so a proposal on an upstream site fell back to the
earliest survivor and its new value was written to the trace but never
executed — the first sample of any program could not move. Checkpoints were
ordered by map-key order, which is program order only up to eight entries.
And the accept ratio was a pure likelihood ratio with a stale prior density,
so a step outside a bounded prior was never seen as −∞.

The fix follows the engine's own invariant (continuation-owned environment):
a checkpoint captures its slice state and every resume restores it, upstream
checkpoints survive a replay, checkpoints carry a sequence number, and the
random-walk ratio is the joint with the proposed site's density recomputed.
spindel's new `inference/mcmc_test.clj` checks the three replay properties,
recovers the analytic posterior of a conjugate model with both the random-walk
and the single-site kernel, and rejects proposals outside a bounded prior.

**What the working sampler says about the tiny world.** Six seeded chains of
60 moves reach a log-likelihood within 0.1 nats of the truth's 6.92 at β
anywhere between 1.4 and 3.4. Five districts' shares do not identify β; the
chains find the ridge, not the point. That is the twelfth pass's finding in
miniature, and it is why the city test now asserts the likelihood ceiling
rather than |β − 2|. The prior-kernel posteriors and the fourteenth pass's
segmented numbers are unaffected: forward execution never replays.

**The rejuvenation run, on the real city, with the working kernel.** Eight
chains of twenty random-walk moves from prior draws, σ = 0.25, step 0.15,
seed 1: 168 evaluations, 1,878 s, acceptance 0.59. Every chain converged to
one region:

| α | β | d₀ | log-lik | misplaced | Mitte | shop-km |
|---|---|---|---|---|---|---|
| 0.81 | 1.60 | 321 | 1.95 | 0.072 | 0.86 | 3.47 |
| 0.81 | 1.60 | 339 | 1.94 | 0.071 | 0.86 | 3.49 |
| 0.86 | 1.57 | 296 | 1.86 | 0.068 | 0.87 | 3.50 |
| 0.77 | 1.46 | 263 | 1.85 | 0.072 | 0.86 | 3.64 |
| 0.81 | 1.62 | 243 | 1.84 | 0.078 | 0.84 | 3.33 |
| 0.77 | 1.62 | 259 | 1.61 | 0.083 | 0.83 | 3.35 |
| 0.90 | 1.57 | 375 | 1.06 | 0.062 | 0.89 | 3.61 |

Posterior mean (0.82, 1.58, 302 m). Compare the prior-kernel run of the
thirteenth pass, whose best survivor scored −0.37 and whose posterior mean
was (0.78, 1.76, 812 m): the chains found a mode the 48 prior draws never
reached, a full 2.3 nats higher. **Correction, same day:** these were not
eight independent chains. `kernel-infer`'s default barrier policy resamples
at every observe, replays included, so this was a resample-move population
of eight — a valid sampler, but one whose rows above are partly copies of
one another (two share θ to three decimals), and whose segmented sibling
below ended with all eight particles bit-identical. Chains now run with
`:barrier-policy :none`; a test with thirty barriers guards it. It is the eleventh pass's hand-tuned kernel, β = 1.6, recovered by
inference — with α a little under 1 and d₀ around 300 m rather than 500. At
the mode the RMS log residual is 0.22, at the floor the landscape measured,
so the kernel is now fitted as well as this observation model allows and the
rest of the miss is the register's placement error and the missing segment
structure, which is what the fourteenth pass split out.

The holdout does not move: 3.3–3.6 km straight-line against MiD's 3.6 km
door-to-door, still above the ~2.9 km a detour factor implies. That is the
segmentation's job, not the kernel's.

**The joint fit, turnover plus distance, prior kernel.** 48 particles, σ =
0.25 on turnover and a second observe on the expected straight-line shopping
distance at 3.6 km ÷ 1.25 = 2.88 km, σ 0.3 km; 535 s, 16 distinct θ, ESS 17.9.
No survivor scores above −3.9 on the joint objective, while the MH mode above
would score about +0.3 on it (its 3.47 km costs 1.9 nats against the distance
term) — the prior kernel never reached the mode, as in the thirteenth pass.
What it does show is the tension as two families in one posterior:

| family | β | shop-km | misplaced | Mitte |
|---|---|---|---|---|
| steep, satisfies the distance | 2.2–2.7 | 2.5–3.1 | 0.09–0.12 | 0.73–0.86 |
| flat, satisfies the turnover | 1.5–2.0 | 3.7–3.9 | 0.05–0.08 | 0.85–0.93 |

One kernel cannot be in both rows. Running MH on this joint objective would
only pick the compromise point between them; the resolution is the
segmented program, where the short-term class takes the steep row and the
medium-term class the flat one, and that run is next.

Cost is the number to fix next: 168 serialised evaluations at 11 s each on
the unsegmented table. The segmented evaluator does three classes in 1.4 s,
so the same run on the nine-parameter program is minutes, not half an hour.

## Sixteenth pass — inference on the segmented program (2026-09-15, evening)

Four runs of the nine-parameter program against the 69 published
(district, class) turnovers, σ = 0.25, 8 particles × 20 random-walk moves,
168 evaluations each. Trace size held at exactly the site count throughout
(78, or 81 with levels), which is the spindel fix holding on the real
program.

| run | chains | best log-lik | distinct | shape RMS short / medium / long |
|---|---|---|---|---|
| kernels only | resample-move | −4.24 | 1 | 0.182 / **0.526** / 0.373 |
| kernels only | independent | −61 | 8 | 0.201 / 0.378 / 0.311 |
| + free levels, N(0, 0.5) | independent | −8 | 8 | 0.276 / – / – |
| + free levels, N(0, 0.5) | resample-move | **+3.27** | 2 | 0.217 / 0.370 / 0.308 |

Hand-split from the fourteenth pass, for reference: 0.196 / 0.191 / 0.347.

**Three things this says.**

*Independent chains from prior draws do not get there in 20 moves.* In nine
dimensions at 26 % acceptance they were still descending (−61 to −526) where
the resample-move population had reached −4 and then +3 on the same
evaluation budget. Resample-move is the right tool for finding the mode with
an expensive serialised simulator; its final set is copies, so it is not a
posterior sample, and `run` now records which policy ran. The real fix for
both is the batched evaluator: 168 evaluations is nothing on a device.

*Without a level term the segmented likelihood distorts the kernels.* The
resample-move optimum without levels put clothing at β 3.05 with a shape
error of 0.526 — worse than the hand-picked flat kernel's 0.191 — because a
−0.57 log level on clothing, set by the money split and untouchable by any
kernel, is best reduced in Σr² by bending the shape. That is a misspecified
likelihood doing what misspecified likelihoods do.

*A free level helps, and its prior width is now the knob.* With N(0, 0.5)
levels the best particle reaches +3.27 and the level posterior reads
clothing +0.22, furniture −0.43, food ≈ 0: the right signs and roughly half
the measured magnitudes (+0.57, −0.35, −0.15), because the prior shrinks
them and the kernel still absorbs the rest — clothing's shape error is 0.37,
not 0.19. A wider or flat level prior would let the level take the whole
bias and leave the kernel the shape alone; the principled version is the
non-resident layer, where those levels are not free parameters but the
in-commuter, visitor and leakage flows sized by the fourteenth pass's table.
That is the next modelling step, and it is what turns the levels from a
nuisance into a measurement.

## Seventeenth pass — the day on the device, and what routing actually costs (2026-09-16)

**The base case is the day, not the expectation.** The requirement: simulate every inhabitant for a day, commute included, and test
interventions on that. The unrouted day already does this — 936,597 people,
854,041 with diaries, 195,484 residents commuting to a city workplace and
326,153 in-commuters entering at the edge, 426,499 work episodes, 272,045
store visits, 109,635 restaurant visits — in about two seconds on the JVM
once the tables exist. What kept it off a device was the retail choice
table, 1.5 GB and ten seconds per θ. The expectation used for the likelihood
this week is that day's exact mean, and stays the right variance-free
estimator where it is provably the mean; it is not the base case.

**A table-free day kernel, bit-faithful.** `city.sim.kernel` writes the
retail half of the day in raster's dialect: a store episode in cell `c` walks
the 3,637 candidates, computes each weight from coordinates on the spot, and
stops where the running sum passes `u · Z_c`; the same counter-addressed
draws as `day/uniform`. Inputs are 38,000 coordinate pairs and one number
per candidate. Checked three ways: 2,000 of 2,000 single draws land on the
table's candidate across three kernels; hand-built diaries count and place
every visit; and on the whole city, seed 1, with the reference isolated by
differencing a `step-day` run against one with the retail table emptied,
**every one of the 272,045 store visits lands on the same venue at the same
hour** — on the JVM and on the Intel Arc alike.

| | JVM, one thread | Arc, Level Zero, fp64 | Arc, fp32 |
|---|---|---|---|
| Z_c for 34,650 cells (126 M weights) | 19.9 s | **0.23 s**, rel. diff 1.7e-15 | 2.8 s |
| retail day, all inhabitants | 81.8 s | **15.7 s**, 0 visits differ | 17.8 s, 5,821 differ |
| `step-day` + table build, for reference | 2 s + 10 s | | |

Two readings. The normaliser pass — which is also exactly the segmented
likelihood's inner loop — runs at 550 M weight evaluations per second on an
integrated GPU, so a class's expected allocation is ~0.25 s there against
~0.5 s on the CPU and it batches over particles. The day kernel runs at
63 M per second: same arithmetic, nine times slower, because every thread
walks a different number of candidates and a subgroup waits for its longest
walk. That is the divergence to remove, not the arithmetic: order each
cell's candidates so the mass comes first, or compute the walk as a
segmented scan. fp32 as compiled today is slower, not faster, because the
kernel's literals are doubles and every expression promotes; and it moves
2.1 % of draws at boundaries, which the float32 table already did silently.

**What raster needed, and got.** Four things surfaced, one fixed. The C
emitter left bare `unchecked-*` operators as symbols inside a helper with
integer parameters (fixed, raster `1c47d3e3`, with a regression test).
Redefining a `deftm` in a live REPL leaves the previous overload in the
dispatch table and the previous walked body in the registry, so the compiler
built the old kernel three times over (evicted by hand; fix pending). A
scalar hoisted from an `(Array long)` read is typed with the kernel's
element dtype — `:int` under double, `:float` under float — rather than
long. And a `^:const` var reaches the emitter as a bare symbol. All four are
REPL-workflow defects, not correctness defects, and every one produced a
loud compiler error rather than a wrong number.

**Routing, researched.** `doc/sources/routing-algorithms.md`, 110 sources,
with measurements on our own graph. The decisive fact: customizable
contraction hierarchies computed 20 M shortest paths on metropolitan
Stuttgart in 7.7 s on four 2015 cores, re-customizing six times along the
way. Our 2.5 M daily queries are about a second on the CPU; routing is not
the GPU's problem, and raw GPU shortest-path methods lose to one CPU core on
road networks. Measured here: A* at 38.7 ms per query, detour factor mean
1.227, and — the result that matters for what we did this week — the
calibrated power kernel is robust to crow-flight distance (total variation
0.084 against network distance) while the exponential neighbourhood classes
are not (0.199). Ranked: fix the boxing priority queue in A* (hours, 10–30×);
route the exponential classes on the network; CCH through RoutingKit for the
day's impedance; headway-aware transit wait, the largest fidelity gain per
line of code; CCH partial customization for road-closure scenarios at
microsecond cost; CSA for transit later; WGSL milestones as an investment in
the whole simulation moving to the device, honestly a single-digit multiple
over a CPU that is already fast enough. (Refuted in part in the eighteenth
pass: a primitive heap did not speed A* up, so the first ranked item is wrong;
the cost is the search size, and the recommendation of a hierarchy stands.)

**Next, in order.** Money on the day (class of each shopping episode, spend
per visit, in-commuter and leakage flows), so that the day is economic and
interventions are paired days. The remaining classes and the commute in the
same kernel form. The A* heap fix. Then the divergence fix and float
literals for the device, and the particle dimension.

## Eighteenth pass — money on the day (2026-09-16)

The day is now economic. `city.sim.kernel/spend-day!` draws each store
episode's demand class from the trip shares, its venue from that class's
kernel, and carries the person's class spend into a per-venue, per-hour
revenue array in integer cents. Same draws, same 854,041 diaries and 272,045
store visits as `step-day`; 176,806 / 54,447 / 40,792 visits by class at the
assumed 0.65 / 0.20 / 0.15 trip shares; 12.6 M € of revenue on one weekday.

**The denominator was the whole problem.** The spend per visit is potential
over expected visits per year, 365 · E_t · π_s, with E_t the store episodes
per day a person's type makes in the diary pool. Normalised per person the
day recovered 83 % of the resident potential, a uniform 0.82 in every class
and every district — the money of people whose type never shops in any
diary, children first. Money is a household quantity: the potential is now
pooled per household and spent through the members who shop. The synthesis
numbers households within a census cell, so the id is the (cell, index) pair,
620,795 households.

| | short | medium | long |
|---|---|---|---|
| spend per visit, € | 60 | 59 | 145 |
| annualised day, M € | 2,477 | 739 | 1,377 |
| expectation (fourteenth pass), M € | 2,507 | 752 | 1,392 |
| ratio | 0.98 | 0.98 | 0.98 |
| Mitte, day / expectation, M € | 404 / 406 | 557 / 567 | 385 / 394 |

The 2 % is 70 M € of households with no shopping member, 1.5 %, reported as
unspent rather than lost, plus one day's Monte Carlo noise. A test pins the
identity: for every household with a shopper, Σ spend × expected visits
equals its potential, children's money included.

**What is still assumed.** The trip shares π. The class split of shopping
*trips* is a mobility-survey quantity, MiD's everyday-needs versus other
shopping, and until it is fetched every result that uses π carries the
placeholder with it. In-commuter spending and residents' leakage out of the
city — the two flows the fourteenth pass sized at +599 and −377 M € — are
not on the day yet; they are the next two lines in the kernel.

**The two non-resident flows, on the day.** A resident's class-s purchase
leaves the city with probability ℓ_s = (potential − turnover)/potential
where positive, 0.11 for food and 0.28 for long-term goods, placing no visit
and no money; in-commuters, who already shop at their workplace anchor,
carry a per-visit spend equal to the class's net inflow over their expected
class visits per year, 87.50 € a clothing visit. Sizes measured, attribution
assumed and stated. The city totals per class are then reproduced by
construction — 2,200 / 1,341 / 994 M € against 2,169 / 1,332 / 980 — and
the per-district distribution is the test that is not:

| class | RMS log by district | Mitte, day ÷ published |
|---|---|---|
| short | 0.186 | 0.84 |
| medium | **0.227** | **0.96** |
| long | 0.371 | 0.66 |

Clothing at 0.227 with Mitte at 0.96 is the closest any run has come on
that class: kernel-only inference put it at 0.526, free levels at 0.37, the
hand split 0.19 on shape alone. Long-term goods remain the worst class and
the centre is under-served there; that is where the leakage attribution is
most likely wrong, since furniture and DIY leakage is to the region's
big-box stores and not uniform across residents. 240,953 visits placed,
31,092 leaked, 272,045 store episodes as before, 92 s on the JVM.

**And on the device.** The same economic day — class draw, leakage draw,
venue draw, spend in cents — compiled through Level Zero and ran for all
936,597 inhabitants on the Intel Arc in **17.0 s**, with every count, every
visit and every cent identical to the JVM run: 0 visits differing, 0 cents
differing, out of 240,953 placed visits and 12.4 M € of revenue. The day
kernel's 63 M weight evaluations per second and its divergence are
unchanged; what changed is that the whole economic base case now has one
definition that runs, bit for bit, on both.

**Routing: the queue was not the cost.** The routing report attributed A*'s
38.7 ms per query to a boxing priority queue. A primitive binary heap gives
39.5 ms, and an equirectangular heuristic in place of the haversine 44 ms;
sixty random routes match a reference Dijkstra's cost exactly either way. A
query touches about 50,000 of the 428,737 nodes. The cost is the search
size, and only a hierarchy changes that — the report's central
recommendation stands, its first ranked item does not.

## Nineteenth pass — the intervention under the posterior, in the explorer (2026-09-16)

The demo's question became concrete: close the Milaneo, a large shopping
centre near the main station, or rebuild its floors in another district, and
say what happens to the city's retail in the model, with the uncertainty the
data left, not a point estimate. `city.sim.scenario` lifts `intervene` to the three
demand classes and evaluates a venue-set change under a *set* of θ:

```
    footprint  the 103 candidates within 170 m of Mailänder Platz:
               2,071 / 19,302 / 2,425 m² of short / medium / long floor
    close      A_s[j] ← 0 for every class s and every j in the footprint
    move       the closure, plus one candidate with the footprint's per-class
               floor at the target district's population centroid
    outcome3   per class, reduce-dense with bucket = candidate: expected euros
               at every venue, no cdf materialised, ~1 s a class on the JVM
    across3    baseline and scenario under every posterior particle, pmap'd;
               delta3 is scenario − baseline *per particle*, so the credible
               band is over the effect
    report     weighted mean and 5/50/95 % quantiles by district and venue,
               the posterior predictive next to each observed (district, class)
               turnover, the particles themselves and their prior ranges
```

In the model, under the eight-chain MH posterior (superseded by the 48-chain
posterior described in [doc/model.md](model.md) §9), closing it moves 91.2 M €
a year of modelled resident money away from the footprint; in the model half
of it is re-absorbed inside Mitte and half goes to the other districts, and
the modelled expected clothing trip *shortens* by 24 m (band 12–35 m), because
the model's centre was pulling residents past nearer shops. Rebuilt at
Zuffenhausen's population centre, the same floors capture 87 % of that money
there in the model, and Mitte keeps 10 %. These numbers predate the
correction of the purchasing-power weights on 2026-09-16 and will change when
the scenarios are re-run. Every euro is conserved in every particle; all 3,637 candidates lie inside the 23
districts, so nothing "leaves" in this expectation — leakage is a class
balance in the money day, not a move here. 15 s and 27 s for the two
scenarios with eight particles. The 48-particle resample-move run that was meant
to replace them ended with two distinct θ (resampled clones share their address
cursor and propose identically), so the published scenarios use 48 independent
random-walk chains instead; see `doc/model.md` §9.

**In the explorer.** `/sim/scenarios` lists what a run carries,
`/sim/scenario?scenario=close-milaneo` returns one report; the console adds
a policy-scenario picker, a `scenario` overlay (rings by √|Δ|, green gains,
coral losses, hollow for the closed set, solid for the opened venue), four
outcome metrics, and an evidence section that shows the posterior as
particles on each parameter's prior range, the calibration band per
district and class against the observed turnover, the district-by-district
effect with its 5–95 % band, and the venues that move most. A scenario is
read, never computed, by the UI.

**Trips ×10.** The explorer's stride-20 request now meets a stride-20
trace: `dev/demo` (since replaced by `city.demo.stuttgart`) traces it in the background of the loaded JVM and installs
it under `[:trips 20]`, replacing the alias; `max-legs` and the viewport
filter keep any one response at the same size as before, so the gain is
density when zoomed in, not bytes.

