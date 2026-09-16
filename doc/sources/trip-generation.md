# Trip generation: what the model is missing and where the data is

Probe report 2026-09-11. The largest single term in the error budget is that
people make about half the trips a travel survey counts. This file is what the
deficit actually is, measured, and which sources can close it.

## The deficit, decomposed on the published runs

Not a uniform shortfall. Two thirds of it is people who never leave home.

| | Stuttgart model | Stuttgart observed | Vancouver model |
|---|---|---|---|
| trips per person per day | 1.83 | **2.86** | 1.92 |
| share of people who make any trip | 0.61 | **0.838** | 0.63 |
| trips per mobile person | 3.00 | 3.41 | 3.02 |
| residents / in-commuters | 2.12 / 1.38 | — | — |

Observed values are the MiD 2023 small-area estimate for Stadt Stuttgart
(`MiD23_SAE_..._Gemeindedaten.xlsx`, GKZ 8111000): 2.861 trips, 33.31 km,
92.21 min, Mobilitätsquote 83.79 %, mode shares walk 31.1 / bike 9.5 / car
passenger 11.3 / car driver 24.7 / transit 23.4.

**The target was wrong in this repo until now.** Earlier passes calibrated
against 3.2, which is the *2017* Stuttgart figure. The German trip rate fell
over the series: 3.3 (2002), 3.4 (2008), 3.1 (2017), **2.9 (2023 national)**,
2.86 for Stuttgart. The gap is a factor of 1.56, not 1.9.

## The deficit is in the instrument, not in the code

The diary pool itself — StatCan TUS 2022, BC urban weekday, 1,117 diaries
weighted — yields **2.00 travel episodes per person-day** at a mobile share of
**0.70**. The simulator delivers 1.83 of those 2.00. A time-use survey records
travel only when the respondent reports it as its own episode, so short and
chained trips are absorbed into the activity around them; a travel survey asks
for each trip by name. No model change recovers what the questionnaire never
asked. The pool is also thin: 53 person types over 1,117 diaries is ~21 diaries
per type, and 56 % of mobile person-days come out as one trip out and back.

## Two structural faults, independent of the data choice

1. **In-commuters never commute in.** External workers are appended with no
   home and start their day at their workplace: 326,153 people in Stuttgart
   (1.38 trips each against residents' 2.12) and 94,960 in Vancouver. They
   contribute nothing to the morning peak or to through traffic, which is where
   the pedestrian counts are weakest. Vancouver can be fixed today — the
   commuting table already names 110 origin municipalities with flows (Burnaby
   22,005, Surrey 16,025, Richmond 13,575). Stuttgart needs the BA
   Pendlerverflechtungen matrix.
2. **The diary pool is filtered to one province** (`:provinces #{59}`). Dropping
   the filter multiplies the pool roughly tenfold at no cost. It will not change
   the trip *rate* — that is a property of the instrument — but it will change
   chain variety.

## German sources, ranked by what they cost

| Source | Gives | Access | Verified |
|---|---|---|---|
| **MiD 2023 SAE Gemeindedaten (xlsx)** | Stuttgart's own trip rate, daily km, travel time, Mobilitätsquote, 5 mode shares; 1,601 municipalities | free, no login: `mobilitaet-in-deutschland.de/pdf/MiD23_SAE_Regionalisierung-von-MiD-Ergebnissen_Gemeindedaten.xlsx` (Kreisdaten too) | parsed, values above |
| **MiT 2023 "Mobilität in Tabellen"** | a live cross-tab engine over MiD 2023 microdata: datasets HH/P/W/REISE/AUTO, ~60 trip variables (purpose, start/arrival time, duration, distance, mode, intermodality) crossed with age, sex, Tätigkeit, employment, household type, car availability, and geography `BLAND` / `RegioStaR7` / `RegioStaRGem5` | free, **empty password**, `mobilitaet-in-tabellen-2023.bast.de` | ran end to end, see recipe below |
| **MiD 2017 Stadt Stuttgart Grundauswertung (PDF, 163 pp)** | the only *city-level* source with all four of: trips/person/day by person group (P32), purpose (W2), start time by purpose (W7), duration (W9), distance (W12), mode by purpose (W10.5) | free: `vm.baden-wuerttemberg.de/fileadmin/redaktion/m-mvi/intern/Dateien/PDF/MID2017_Stadt_Stuttgart.pdf` | n = 1,869 persons / 6,252 trips — thin cells; BW version (239 pp) stabilises them |
| **MATSim Stuttgart v2.0, 10 % plans** | ~150k persons as activity chains with coordinates, times, modes; measured on a 200-person sample at **3.11 trips/person, 0.89 mobile** | free, no auth, 403 MB: `svn.vsp.tu-berlin.de/repos/public-svn/matsim/scenarios/countries/de/stuttgart/stuttgart-v2.0-10pct/input/` | **licence unverified** — the GitHub repo calls itself "partly open" and carves out per-file licences; demand provenance undocumented. An iterated *output* population: filter `selected="yes"` or double-count |
| MiD microdata, Package A | the absolutely-anonymised file behind MiT 2023 | BASt MobilityData-Campus, `mobilitydatacampus@bast.de` | buys nothing MiT 2023 does not already serve |
| MiD microdata, Packages B1/B2/B3 | full socio-demography; B3 reaches 500 m grid cells | same, but restricted to universities and publicly-funded institutes, individual review, signed contract | **B3 is the only tier worth applying for** |
| Deutsches Mobilitätspanel (MOP) | one-week diaries | **no longer free** — project ended 2024-01-31, now via the same BASt route | 1,957 persons, spatial *types* only: unusable at city level |
| SrV 2023 (TU Dresden) | modal split, trip rate, mobile share per city | free reports | **Stuttgart does not participate** (BW: Mannheim, Karlsruhe, Heilbronn) |

The Clearingstelle Verkehr at DLR no longer exists; access now goes through the
BASt MobilityData-Campus.

### MiT 2023 recipe (works from curl)

```sh
curl -c jar -X POST '…/Tables?action=login' -H 'content-type: application/json' -d '{"password":""}'
curl -b jar -X POST '…/Tables?action=getdatasetdescription' -d '{"type":"W"}'   # variable tree
TAB=$(curl -b jar '…/Tables?action=gettabid' | jq -r .identifier)
curl -b jar "…/Tables?action=gettable&tabid=$TAB&type=W&rowp&a=hwzweck2&b=P_TAET&filter=RegioStaRGem5"
```

`a` is the column variable, `b` the row variable, `filter` splits into one table
per category; `rowp`/`colp`/`mean` choose row-%, column-% or means. Filtering on
`RegioStaRGem5 = Metropole` gives a far better-powered Stuttgart analogue than
the 1,869-person 2017 city PDF. Output is HTML.

## The trap: every survey counts a different thing

Published rates across North America run from 2.1 to 4.2 trips per person per
day, and most of that spread is **definition, not behaviour**. The Toronto
survey excludes stops under 15 minutes and counts linked trips; Calgary's panel
counts every leg of a multi-mode journey separately; some surveys count
home-to-home loops and some do not; walk trips are captured unevenly. Seattle
reports 4.10 where the national US survey reports 3.37 for the same period.

Our simulator emits **legs between activities**, with a transit trip's access
and egress walk as separate flagged sub-legs. Excluding those stubs — which is
what every number in this file does — a model leg is a *linked trip*, matching
the German `Weg` and the Toronto trip. Any future comparison must state which
of the two it counts. This is the most likely way to get a calibration
confidently wrong.

## Canadian and US sources

Canada has **no national travel survey**. Confirmed by grepping StatCan's full
catalogue of 8,270 cubes: what matches is tourism (Travel Survey of Residents),
vehicle-kilometres (Canadian Vehicle Survey), and time use (45-10-0104/0105,
durations and participation only, no trip counts). Nothing reports non-work
trip rates. The census journey-to-work tables give one commute pair per
employed person with a usual workplace and say nothing about the other three
quarters of trips.

| Source | Gives | Access |
|---|---|---|
| **TTS 2022 trip generation report** (U. Toronto DMG, 145 pp) | the best free trip-generation handbook on the continent: daily rates by age, gender, work status, student status, licence, transit pass, household composition and density class, each **crossed with purpose** (home-based work / school / discretionary / non-home-based), plus a negative-binomial model with published coefficients | free, no login, `dmg.utoronto.ca/.../2022-TTS-Trends-in-Trip-Rates-v2.5.pdf` |
| **City of Vancouver transportation panel** | the only annual City-of-Vancouver rate series: 3.73 (2019), 2.71 (2020), 2.85, 2.90, 3.03, **3.17 (2024)**, adults 18+ | free PDFs on vancouver.ca |
| **TransLink 2011 Trip Diary analysis report** | the only Metro Vancouver report with published rates: **2.77 trips/person** (5+), and by life stage full-time employed 3.0, part-time 3.1, full-time student 2.5, non-worker 2.5, each split across five purposes; per-municipality profiles in Appendix A | free, 13 MB PDF |
| **TransLink 2023 trip diary** | 15,879 households / 35,252 persons / 96,193 trips; ~8.8 M weekday trips, +9.5 % against +13 % population, so the rate fell ~3 % | rates only on a Tableau dashboard, export disabled, transcription legal under the Open Government Licence – TransLink (commercial use permitted) |
| **TransLink 2023 technical report** | its own **under-reporting correction factors** for exactly our problem: non-home-based auto ×1.49, NHB transit ×1.28, NHB active ×1.31, home-based transit ×0.88 | free PDF |
| **NHTS 2017 (US)** | 923,572 trips, free microdata, metropolitan identifiers including Seattle (n=343) and Portland (n=228) as Vancouver analogues | free, no registration, 84 MB |
| NHTS 2022 | 31,074 trips, 2.08 trips/person against 2017's 3.37 | free, but the drop is a design artefact: **transfer 2017, not 2022** |
| TransLink trip-diary microdata | — | not published; `tripdiary@translink.ca` or freedom-of-information, weeks, may be refused |
| TTS cross-tab system | per-record queries | free registration at `drs.dmg.utoronto.ca/register`, manual approval, no redistribution |
| Montréal, Edmonton, Burnaby, North Shore, Coquitlam surveys | comparison rates | free reports; Montréal 2023 microdata is for agencies only |

Metro Vancouver neighbours for context: Burnaby 2.28 (2024), North Shore 3.12
(2023), Victoria 2.63 (2022), Edmonton 3.51 (2015, counts legs).

## Still open

- A **MiD 2023 Stuttgart Grundauswertung** probably exists: the Methodenbericht
  lists "Zweckverband Personennahverkehr Stadt Stuttgart" and "Region Stuttgart"
  among the regional oversample partners, and the 2017 one was published. Not on
  the ministry's path yet. Ask ZVPNV Stuttgart / Verband Region Stuttgart.
- Whether Package B3 is open to this project, and what it costs. No price is
  published anywhere.
- Vancouver's sources (TransLink trip diary, TTS, NHTS) — separate probe.

## In-commuter origins (acquired 2026-09-11)

Needed to place external in-commuters at the edge of the city on the side they
come from (`city.sim.cityworld/place-externals!`).

**Vancouver** — census table 98-10-0459 already names 109 origin census
subdivisions with flows; the top ten carry 87 %. The 21 largest (97.1 % of
94,960 in-commuters) were geocoded to municipality centroids via Nominatim,
written to `data/derived/vancouver_incommuter_origins.jsonl`. Statistics
Canada's own subdivision boundary files are **dead links** — every
`lcsd000*21a_e.zip` under `.../geo/sip-pis/boundary-limites/files-fichiers/`
302s to a 404 page — and the dissemination-area file we hold carries no
subdivision identifier, which is why geocoding was the route.

**Stuttgart** — two sources, and they measure different populations:

| | Bundesagentur für Arbeit | Pendleratlas der Länder |
|---|---|---|
| population | sozialversicherungspflichtig Beschäftigte | all employed, incl. Beamte and Selbständige |
| in-commuters 2024 | 276,250 | 318,695 |
| origins listed | 1,483 (no cutoff) | 63 (flows ≥ 1,000 only) |
| coordinates | no | yes, 6,866 municipal centroids |

So the flow *shape* comes from the BA file, which has the whole long tail, and
the *coordinates* from the Pendleratlas centroid layer, joined on the first
five and last three digits of the regional key (the BA uses an 8-digit AGS, the
Pendleratlas a 12-digit ARS whose middle four digits are the Verbandsgemeinde).
1,251 of 1,301 municipal rows match, covering 263,200 of 264,220 listed
in-commuters. Written to `data/derived/stuttgart_incommuter_origins.jsonl`.

Do not mix the two totals in one figure. Also note the Pendlerrechnung is not
comparable with the pre-2020 "Berufspendler in Baden-Württemberg" series, which
capped at 87 km and assumed daily commuting.

Dead ends, confirmed, do not retry: `statistik-bw.de/SRDB/` is decommissioned
(404 throughout), `daten.statistik-bw.de/genesisonline` hangs or 50x's on every
`operation=` query, and its REST service refuses anonymous access.
