# The two cities (2026-09-12)

Vancouver and Stuttgart run through **the same modules**. Nothing in
`city.sim.*` is city-specific except two lookup tables: which street pull the
graph is built from, and which transit feed the stops come from
(`serve/city-routing`). Everything else that differs is *evidence*, not code.

That is the point of having two. Vancouver has a business register, a
person-level census microdata seed and per-area commute modes. Stuttgart has
none of those and has things Vancouver lacks. Each gap forced a named
substitution, and the substitutions are what this file is for: when a number
looks wrong in one city, the first question is which of these it came through.

## Side by side

| | **Vancouver** | **Stuttgart** |
|---|---|---|
| persons | **670,883**, synthesized by iterative proportional updating on a *person-level microdata seed* (census public-use file, metro area 933) fitted to dissemination-area marginals | **610,444**, synthesized from **aggregates only** — Germany publishes no microdata seed at city level. Zensus 2022 100 m grid + municipal tables + regional statistics. Within 0.1 % of the resident register, district error 1.2 % |
| in-commuters | 94,960, from the census commuting table | 326,153, from labour-agency totals — **35 % of the simulated population**, against Vancouver's 12 % |
| commuter origins | census names 109 subdivisions; the 21 largest, covering 97 %, geocoded | labour-agency municipality file (1,301 origins) joined to the federal commuter atlas for coordinates; 1,251 matched, 95 % of the flow |
| firms | **89,965** from a real register: 545,000 business licences 1997–2026, plus a storefront inventory, map places and points of interest, resolved into clusters by string similarity with an LLM adjudicating the residue | **24,849** map places only. No establishment register is public. Sector employment from the business register is *allocated* across them |
| **is employment observed?** | **yes** — a licence declares a headcount | **no** — every count is an allocation. This is why firms carry `:emp-observed`, and why a synthesized number must never outrank a measurement |
| venue size for destination choice | declared licence employment where present, street-density proxy otherwise. Footprints acquired, not yet wired | **building footprints raked to measured retail floor area** per district (`city.synth.retail`) |
| daily schedules | Canadian time-use survey, all provinces, 7,017 diaries | **the same Canadian diaries**, as a documented transfer — **but this is now fixable**: ZVE 2022 is free as a Public Use File after registration (see below). Germany's expenditure survey has no sub-state signal |
| trip rate | tilted to **2.9** per person-day (bracketed by a 2011 regional diary at 2.77 and the city's own 2023 panel at 3.03) | tilted to **2.861**, the 2023 national survey's small-area estimate for the city |
| travel modes | census journey-to-work, **per dissemination area** | one **city-wide** profile — the German survey publishes nothing below the city |
| street graph | 232,290 nodes | 428,737 nodes |
| transit | TransLink feed | state feed, whose calendar is all zeros and needs a service-date workaround |
| scored targets | ~2,600 intersection pedestrian counts; business survival from 29 years of licences | 18 bicycle counters; 6 pedestrian sensors of unpublished location; **retail centrality for 23 districts** from a 2021 establishment census |

## What the pipeline does, in order

Identical for both; only the inputs above change.

1. **Intake.** Every fetch is content-addressed with a receipt recording source,
   URL, checksum and time. Nothing enters the database without one.
2. **Store.** Datahike with history; every entity references the receipt it came
   from, so any claim traces back to bytes on disk.
3. **Resolve.** Sources are reconciled into single firms by spatial blocking,
   string similarity, and an LLM for the ambiguous residue. Vancouver needs this
   heavily (four overlapping sources); Stuttgart barely (one source).
4. **Synthesize.** Population, activity chains, trip rates, firm ages, and now
   venue sizes. This is where the two cities diverge most.
5. **Build the world.** Two blocks of parallel primitive arrays, persons and
   firms. Commuting roles from the census, workplaces by a gravity draw against
   firm capacity, in-commuters placed at the city edge on the side they come
   from.
6. **Step a day.** One pass over every person, reading compressed-sparse-row
   tables, drawing destinations from a gravity kernel, writing a visit
   histogram. Counter-based hashing, so a run is reproducible and no agent
   depends on another.
7. **Trace a day.** The same pass again, routing each leg on the street graph
   and emitting polylines. This is the expensive step and the only one that
   costs an hour.
8. **Score.** Against whatever that city publishes.
9. **Publish and serve.** Runs live in one JVM's heap and are served to the
   console as map layers.

## Where each city is weakest

**Vancouver's** population rests on a real microdata seed and its firms on a
real register, so its weakness is elsewhere: no measured venue size, no retail
floor area, no small-area sales, and a commuting table from a pandemic census
in which 47 % of employed residents report no fixed workplace.

**Stuttgart's** population and firms are both reconstructions. The population
reconstruction validates well — the retail census's own implied populations
agree with ours to within 4.7 % per district. The firm reconstruction does not:
map places are biased toward consumer-facing businesses, so office and
industrial firms are under-counted, and the allocated employment was wrong
enough to send the model's shoppers to a knitting shop in a suburb. That is now
repaired on the destination side by measuring floor area, but the firm *count*
remains distorted, which is what made the firm kernel double the city's firms
over twenty simulated years.

The employment distortion is now diagnosed precisely, and it is not the size
draw. Each (Stadtbezirk × WZ-section) cell is raked to an employment target, so
where the target says a cell holds a plant and Overture holds no object for that
plant, the jobs land on whoever is present: Untertürkheim's 17,668 manufacturing
jobs sit on three wineries, and the Mercedes and Bosch names together carry 1,241
jobs across the whole city. `doc/sources/employers.md` (not in the published repository) had the evidence, the
anchor sources, and the eight-step repair.

### Correction, 2026-09-12: German time-use microdata *is* obtainable

This file previously said Germany's time-use microdata was not obtainable. That
was **wrong**. **ZVE 2022** (EVAS 63911, DOI `10.21242/63911.2022.00.00.4.1.0`)
is free as a Public Use File after a self-service registration at
`https://campus-file-fdz.nrw.de/` — no fee, no signature, no institutional
countersignature. It must be registered for personally, since the account is
bound to usage terms (Adressatenbindung, Zitationspflicht).

What it buys over the Canadian transfer:
- **Three diary days per person** instead of one, so activity chains can be
  sampled as person-level repertoires rather than independent day draws. This is
  the biggest methodological gain.
- **Location and travel mode on the same 10-minute grid as the activity**
  (`tb4_*`: `11 zu Hause`, `13 eigener Arbeitsplatz`, `15 Restaurant`,
  `16 Geschäft`, plus `21 zu Fuß`, `23 Fahrrad`, `25 PKW`, `33 Stadtbahn`…). Our
  synthesiser currently has to *infer* where an activity happens; ZVE observes it.
- German institutions — same school day, shop opening hours, Feiertag calendar.
- 19-band household net income (`hd17bx`), finer than the Canadian banding.
- Per-worker commute minutes (`pc18x`) and km (`pc172x`).

Structure: 4 linked CSVs, 7,819 households (80 % subsample), 144 × 10-min slots
running 04:00→04:00, 255 activity codes in 3 levels. Weight `hrf_t80` for
anything touching the diary — unweighted analysis is materially biased (mean
household size 2.5 unweighted vs 2.0 weighted). Details in
`data/derived/zve2022_structure.json`.

**What it does not fix.** The PUF's only geography is `gebiet`: West (6,148
households) / Ost (1,671). Bundesland, Gemeindegrößenklasse and siedlungs-
struktureller Kreistyp are all deleted for anonymisation, so **Baden-Württemberg
cannot be isolated and Stuttgart certainly cannot.** Stuttgart's schedules stay a
national-to-city transfer — just a German one rather than a Canadian one. Note
the uncomfortable corollary: on geography the *Canadian* file is richer, since it
resolves province and a large-urban-centre flag. Deeper geography exists only via
the on-site SUF route, which is a paid, contracted application.

## The honest summary

Vancouver is the better-instrumented city for **who people are and where they
work**. Stuttgart is the better-instrumented city for **where they shop and what
it is worth**, because German municipalities publish retail censuses and
Canadian ones do not. Neither is the "reference" city, and the transfers run in
both directions: Canadian diaries drive German schedules, and a German retail
study is about to tell us what Vancouver's venue sizes should look like.
