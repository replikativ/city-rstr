# Data

The repository ships code, not data.  Every input the Stuttgart model reads is
obtained separately and placed under `data/raw/` (as downloaded) or
`data/derived/` (after extraction), both of which are ignored by git.  Each
derived file is accompanied by a receipt, `<file>.receipt.edn`, written by
`city.intake.core/acquire!` (downloaded, with URL and SHA-256) or `adopt!` (a
file already on disk, with the source it claims).

This file lists every source, what the model uses it for, how it is obtained
today, and the licence and attribution it requires.  "Manual" means the file
was downloaded by hand; "extracted" means figures were read from a published
document into a JSON file, with no parser in this repository.  Reproducing the
demo from nothing currently requires the manual and extracted steps; scripts
for them are open work.

The [weekday build recipes](resources/city/weekday-builds.edn) enumerate the prepared inputs consumed by the four supported explorer runs. Run `clojure -M:weekday-build --city vancouver --describe` to resolve the regional recipe against local files. The detailed inventory below also covers earlier experiments. Commands for retired workbench features, including terrain, roof sections and ballot analysis, are preserved at [the archived workbench revision](https://github.com/replikativ/city-rstr/tree/ebaecc15f7d583633580b7009137393e4be892d8).

## Checking the preview sources

The [weekday source register](public/sources/weekday.json) names the two saved run IDs,
the studies behind their population and travel models, and the role of each study.
Its SHA-256 values identify the local archives or extracted files named alongside
them. These fingerprints were computed against the available archive during
preview preparation. The original releases did not sign this source register.

Run `python -m scripts.preview_sources --check --archive ../Simulations/city`
to verify the referenced run manifests, the public source page and the archived
files. To refine a citation, edit the register and run
`python -m scripts.preview_sources` to regenerate the page. Record a new run
ID when a changed input is used to compute a new weekday.

## Sources

| source | used for | obtained | licence and attribution |
|---|---|---|---|
| Statistisches Bundesamt (Destatis), **Zensus 2022**, 100 m grid (population, age groups, households, rent) | cell populations and the synthetic population's marginals (`city.synth.stuttgart`, `city.load.census`, `scripts/zensus_grid.py`) | manual zip download; the script unzips and filters | Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0). "© Statistisches Bundesamt (Destatis), Zensus 2022" |
| Destatis, **Zensus 2022** Gemeinde- and Regionaltabellen | employment by age, vacancy (constants in `city.synth.stuttgart`) | manual; figures written into the code with their table references | dl-de/by-2-0 |
| Statistische Ämter des Bundes und der Länder, **Regionalstatistik** (GENESIS tables 12411-04-02-4, 13111-01-03-4, 52111-*) | sex ratio, employees and establishments by sector (`city.synth.stuttgart`, `city.synth.stuttgart-firms`) | manual CSV export | dl-de/by-2-0 |
| **Statistik der Bundesagentur für Arbeit**: Gemeindedaten, Pendlerdaten | commuting shares, in-commuter origins (`city.synth.stuttgart-firms`, `city.sim.cityworld`) | manual xlsx download | Free use with attribution "Quelle: Statistik der Bundesagentur für Arbeit" |
| **Landeshauptstadt Stuttgart**, Kleinräumige Gliederung | Stadtbezirk and Stadtteil boundaries (`scripts/stuttgart_klgl.py`) | manual zip download | as published by the city's open data portal; attribution "Landeshauptstadt Stuttgart, Statistisches Amt" |
| Landeshauptstadt Stuttgart, open data (population by age, employees by district) | validation of the synthetic population, firm allocation | manual CSV download | as published per dataset; check each dataset's licence |
| Landeshauptstadt Stuttgart, **Einzelhandels- und Zentrenkonzept 2024**, Teil 2 (Junker + Kruse) | retail turnover, resident purchasing power and floor area per district and demand class: the likelihood's observations (`city.synth.retail`, `city.synth.segments`) | extracted from the published PDF | no open licence: individual figures are cited with the source; the extracted table set is not redistributed |
| Landeshauptstadt Stuttgart, **Statistisches Jahrbuch**, table 6.5.2 (IFH Retail Consultants purchasing power by district) | purchasing-power level per district (`city.econ.household`) | extracted from the published PDF | IFH data republished by the city: cite; do not redistribute the values |
| **Statistics Canada, Time Use Survey 2022**, public-use microdata file | activity diaries for every synthetic person (`city.synth.timeuse`) | manual download (registration-free) | Statistics Canada Open Licence; attribution "Source: Statistics Canada, Time Use Survey 2022, Public Use Microdata File" |
| infas / BMDV, **Mobilität in Deutschland** 2017 (Stuttgart report) and 2023 (Gemeindedaten) | trip rate 2.861, mode shares, mean shopping trip length (`city.synth.tripgen`, `city.sim.cityworld`) | extracted from the published reports | figures cited with the source |
| **OpenStreetMap** (Overpass extracts, building footprints, street network) | venue footprints, the street graph for routing (`city.intake.overpass`, `city.load.stuttgart`, `city.sim.network`, `scripts/pull_buildings.sh`) | partly scripted; some pulls were made by hand | Open Database Licence 1.0. "© OpenStreetMap contributors". Databases derived from OSM and published are ODbL as well |
| **Overture Maps Foundation**, Places (release 2026-08-19.0) | firms and venues with categories (`city.intake.overture`, `scripts/overture_places.py`) | scripted query (DuckDB over the public S3 release) | CDLA-Permissive-2.0 for Places. "© Overture Maps Foundation" |
| **NVBW**, GTFS timetable Baden-Württemberg (includes VVS) | transit stops, routes and headways (`city.intake.gtfs`) | manual download | as published by NVBW's open data offering; check the current terms |
| **MobiData BW**, bicycle counters | optional validation targets (`city.intake.stuttgart-counts`) | scripted download | dl-de/by-2-0 |

Not used, and not to be redistributed:

- **hystreet.com** pedestrian counts were read for a comparison in the lab
  notebook; the service's terms do not allow republishing, and no values are
  reproduced.
- Employer headcounts from crawled or compiled sources (industry association
  lists, supplier awards, chamber rankings) were used only to cross-check a few
  anchor employers; they are not part of the model's inputs and carry no licence
  for redistribution.
- The papers collected under `data/raw/papers/` for the literature survey.

## The published explorer

The static explorer (`city.demo.stuttgart/export-static!`) publishes model
outputs, not inputs: simulated visits, revenue and scenario differences per
venue and district, the district and cell geometry, and the published turnovers
the model is compared with (cited from the EZK 2024).  Venue names are removed
from the export, because a simulated turnover next to a real business's name
reads as a fact about that business.  The observed IFH purchasing power is
omitted from the exported scorecard.  Positions and footprints derived from
OpenStreetMap remain subject to the ODbL.

Map tiles are loaded at runtime from the tile provider configured in the
explorer and must be used under that provider's terms.

## Vancouver material from the early prototype

The source inventory below also covers retired experiments. Their code and
reproduction commands are available in the [workbench archive](https://github.com/replikativ/city-rstr/tree/ebaecc15f7d583633580b7009137393e4be892d8).
The [weekday register](public/sources/weekday.json) identifies the sources cited by
the current explorer.

The earlier city checkout at `../Simulations/city` retains local inputs under
`data/derived/`. Its Git commit `af0c795f0^` (the parent of the Stuttgart-only
change) contains the earlier loaders. The files below are candidates for a new
Vancouver model. The historical synthesis and its comparison with Stuttgart
are described in [the two-city notebook](doc/history/cities.md).

| Archived observation | Coverage and proposed use |
|---|---|
| `vancouver_da_boundaries.jsonl`, `vancouver_da_profile.jsonl` | The 2021 census extraction has 1,017 boundary records. The early pilot used this extract. The municipal atlas now selects the City of Vancouver subdivision from the raw 2021 Census Profile index and verifies all 1,016 areas against the Geographic Attribute File. The separately derived `vancouver_da_marginals.jsonl` also has 1,017 rows. |
| 2021 Census hierarchical public-use microdata, `data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv` | Join people in Vancouver CMA (933) by household ID. Within each age band, person weights estimate the regional share living with a child under 15. The weekday model transfers those shares to local areas. See the accompanying Statistics Canada hierarchical PUMF user guide for the private-household universe and variable definitions. |
| `vancouver_commuting_flows.jsonl`, `vancouver_incommuter_origins.jsonl` | Candidate origin and destination controls for the commuter population. Reconcile their geographic units and reference population before combining them with resident diaries. |
| `vancouver_gtfs_stops.json` | TransLink stop locations with mean weekday headways from 07:00 through 19:00. Recover the feed and service calendar for departures at a specific time. |
| `vancouver_ped_counts_mp.json` | Fifteen weekday intersection studies around Mount Pleasant, dated 2021–2024. Seven record five-minute intervals and eight record hourly intervals. The archived extractor discarded all-zero hours because some sheets contained padding. The full-roster replay checks the original five-minute rows for Ontario at 1st, 5th and 10th and for Alberta at 12th, including Alberta's gap between survey periods. It also checks the four pedestrian approach columns for the reserved 08:00–09:00 and 16:00–17:00 periods at Fraser and Prince Edward on Broadway. Together these supply 44 observed intersection-hours. [Full-roster comparison](doc/vancouver.md#full-roster-pedestrian-counts-at-six-intersections) |
| `vancouver_firm_size_m2.json` | Building-footprint area allocated among firms sharing a building. Treat floor area available to shoppers as a separate quantity when modelling retail attraction. |

The SHA-256 hashes of the archived boundary, profile, stop and pedestrian-count
files matched their adjacent receipts on inspection. Those hashes establish file
identity. The underlying feed dates, geographic coverage and measurement
definitions determine which comparisons the files support.

The grocery pilot uses the 2025 Mount Pleasant storefront inventory for candidate IDs 37 and 6070, and the issued, geocoded 2025 records from all 22 local-area business licence extracts for competitor addresses and employee-weighted work locations. The reserved pedestrian checks read the 08:00 and 16:00 rows directly from the Fraser & Broadway and Prince Edward & Broadway workbooks. Inventory year, geography, selection rules and mixed-vintage limitations are documented in the [pilot specification](doc/vancouver.md#two-site-grocery-pilot).

The citywide atlas reads the provincial 2021 Census Profile, national DA boundaries, Geographic Attribute File and City local-area boundaries, the 2021 hierarchical Census PUMF (CMA 933), and the fitted urban BC 2022 Time Use Survey weekday pool. The archived synthetic roster is used only to quantify the earlier geographic error. Build inputs, reconciliation rules, synthetic IDs and activity coverage are described in the [atlas specification](doc/vancouver.md#citywide-population-atlas).

The atlas includes a reduced copy of the City of Vancouver park polygons under the Open Government Licence – Vancouver. The map uses the archived 2021 Statistics Canada cartographic boundaries and the local OpenStreetMap highway extract for the coastline, bridges and street grid. The park snapshot was retrieved on 2026-11-21. To refresh it, download the municipal GeoJSON export and run `python -m scripts.vancouver_basemap data/vancouver-parks.geojson`. The reduction uses UTM zone 10N and a three-metre simplification tolerance. [Park polygon dataset](https://opendata.vancouver.ca/explore/dataset/parks-polygon-representation/) · [GeoJSON export](https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/parks-polygon-representation/exports/geojson) · [Open Government Licence – Vancouver](https://opendata.vancouver.ca/pages/licence/)

The regional build reads the full 2021 British Columbia Census Profile, geographic starting-row index and DA polygons from `data/raw/statcan`. The index identifies the parent census subdivision for each DA. Campus membership uses the university's legal boundary. Geometry for buildings on campus comes from UBC's building inventory at revision `885732d`. Roads and North Shore building footprints come from the Vancouver BBBike OSM extract downloaded November 21, 2026. The build caches the downloads locally because the live boundary and OSM URLs can change. [UBC legal boundary](https://services2.arcgis.com/NlsizNmbMFiinWw4/ArcGIS/rest/services/Vancouver_Campus_Boundary/FeatureServer/1) · [UBC building inventory](https://github.com/UBCGeodata/ubc-geospatial-opendata/tree/885732d332a20a59143f655c83fb15e1367ebe4d/ubcv/locations) · [Vancouver OSM extracts](https://download.bbbike.org/osm/bbbike/Vancouver/)

The regional vehicle schedules use `data/raw/probes/transit_translink_gtfs_static.zip`, feed `26SEP_20260909`. The release stores the selected date, route patterns, station positions, stop times and destination signs. Service includes trips that board or alight at a stop inside any of the four added areas. [TransLink GTFS](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs)

The timetable-based work commute replay uses the same archive and service date. Its timetable also includes routes serving City of Vancouver stops and retains the feed's pickup and drop-off permissions. The transfer build preserves GTFS stop IDs and the feed's stop-pair rules. Its report pins the timetable and street releases. [TransLink GTFS](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs)

The incoming-commuter coverage comparison adds the complete dated TransLink feed and walkable streets from the archived `data/region/vancouver.osm.pbf`. It selects the walking envelope from commute endpoints and scheduled stops and records the raw PBF digest in the walking release. The published report pins the wider timetable, the original weekday and reservations, and the earlier coverage comparison. [Coverage method](doc/vancouver.md#walking-and-transit-coverage-at-commuter-origins)

Fixed-window work trips use the same dated stop times and transfer rules. The builder reads `transit_translink_tspr2025_bus_peakload_yearlinedaytypeseasontimerangedirection.csv` and `transit_translink_tspr2025_bus_yearline.csv` from `data/raw/probes` for route-level bus capacity proxies. The work release pins the selected weekday, atlas, streets, timetable, and compatible discretionary release whose transit legs reserve space first. [Work transit method and replay](doc/vancouver.md#transit-to-and-from-work) · [TransLink service performance review](https://www.translink.ca/tspr)

The flexible transit replay layers revised diary templates on the same atlas and places. It preserves the baseline transit reservations and uses the published discretionary tour and short-walk intervals to protect those activities. The release pins the baseline transit assignment, revised clock and matched trips. The Raster report compares the revised individual schedules with grouped execution. [Flexible time at home](doc/vancouver.md#flexible-time-at-home)

The personal transit release uses the same timetable and bus-load inputs. It reserves the published flexible work trips, added outings and on-site work rides before assigning recorded trips outside paid work. The release indexes street walks to stops, between vehicles and onward to the next stop in the diary. [Personal transit method and replay](doc/vancouver.md#scheduled-transit-for-school-shopping-and-other-activities)

The bus-load check reads `data/raw/probes/transit_translink_tspr2025_bus_peakload_yearlinedaytypeseasontimerangedirection.csv`. The release records the SHA-256 `1a1b314e51c9a1b17fff349139934de478b05178aad8cb04a0d6ae81e58611a5`. It uses fall 2025 weekday rows with published peak loads and factors. [TransLink 2025 TSPR, seasonal peak loads](https://www.translink.ca/tspr)

The capacity scenario also uses `data/raw/probes/transit_translink_tspr2025_bus_yearline.csv` for routes with an annual 2025 peak-load ratio and no fall weekday ratio. Its SHA-256 is `c72d50755f330c3107fc75ad0e8b5715bdcab6b6d82502cdc3fda39749168962`. The report stores the limit and source category for every bus route in the replay. [TransLink 2025 TSPR, annual bus indicators](https://www.translink.ca/tspr)

The campus demand check uses UBC’s fall 2025 person counts in Tables 2.1 and 2.3. The archived report’s SHA-256 is `eef069af5f617ef82907b84188260bb7d7ffe4c1d030116f99eaf82ee91cd815`. The model records the printed totals separately from the mode components to preserve published rounding. Campus transit passengers use the same dated GTFS as regional vehicle playback. [UBC 2025 Transportation Status Report](https://planning.ubc.ca/sites/default/files/2026-06/UBC2025-TransportationStatusReport-FINAL.pdf)

The external campus attendance scenarios use Table 4 of UBC’s 2025/26 enrolment report, p. 15 of the 2026 AMS survey and the employee origin shares and headcounts in UBC’s 2022 housing studies. Counts are transcribed with their population definitions in the [attendance specification](doc/vancouver.md#external-campus-attendance-and-caf%C3%A9-catchments). The weekday time and attendance priors use the same 2022 Statistics Canada survey as the resident model, including the main-file EDC_10 attendance and ED_05 attainment codes. Site reach uses the regional pedestrian graph and UBC building inventory. The source PDFs are supporting references. Regeneration reads the locally archived survey, campus geometry and published regional day.

The Vancouver grocery catchments use Statistics Canada’s 2021 Survey of Household Spending, provincial average expenditure per household on food purchased from stores by before-tax income quintile. The builder selects BC and 2021 from the English full-table CSV, caches the archive under `data/economics`, and records its SHA-256 in the output. The 2021 Census Profile for BC supplies 2020 income brackets for the approximate provincial thresholds. Retail addresses are from the 2025 municipal inventories. [Spending table 11-10-0223-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110022301) · [Household catchment specification](doc/vancouver.md#household-grocery-spending-within-walking-distance)

The population atlas reads local held-out commute and household income cells and housing value and shelter-cost estimates from the BC Census Profile and its geography index. Municipalities use their published rows and neighbourhoods use matched dissemination areas. See the [held-out measures](doc/vancouver.md#local-tests-of-household-income-and-usual-commuting-mode) and [housing denominators](doc/vancouver.md#housing-values-and-costs).

Synthetic municipal household housing estimates use `SHELCO`, `TOTINC_AT`, `VALUE` and `PRESMORTG` from the archived 2021 hierarchical Census PUMF v2. Local means and held-out medians use Census Profile rows 1482, 1486–1490, 1494 and 1495. The grocery sensitivity pins that housing release and verifies all catchment sizes and baseline food budgets against the existing household-market output. [Housing model and grocery scenario](doc/vancouver.md#housing-values-and-costs)

Municipal passenger matching uses the archived `transit_translink_gtfs_static.zip` in `data/raw/probes`, release 26SEP_20260909. The independent checks read `transit_translink_tspr2025_bus_yearline.csv` (2025 average Monday–Friday boardings by bus route) and `transit_translink_tspr2025_skytrainavgalightsbrdgs_yearstationdaytypehourly.csv` (2025 MF, hourly boardings and alightings at six Downtown stations). The figures cover all riders on the reported service. [TransLink performance review and data](https://www.translink.ca/tspr) · [Transit assignment and comparison](doc/vancouver.md#downtown-rush-hour-and-municipal-transit)

The municipal incoming-worker cohort uses the full source extract `data/derived/vancouver_commuting_flows.jsonl` (Statistics Canada 98-10-0459-01, 2021, usual workplace in Vancouver) and the BC Census Profile and DA boundary files. The public-use person fields `POWST`, `DIST`, `GENDER`, `AGEGRP`, `MODE`, `PWLEAVE`, `PWDUR` and `WEIGHT` supply conditional commute attributes. Workplace weights use City of Vancouver 2025 business licences and the City’s 2020 Downtown Social Indicators Profile, p. 6, for the 2016 usual-workplace counts (136,625 Downtown, 240,820 elsewhere). The 64% attendance input comes from the 2023 Vancouver Transportation Survey, Table 22. [Census commuting flows](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901) · [City profile series](https://vancouver.ca/people-programs/research-and-data-toward-a-healthy-city-for-all.aspx) · [City transportation survey](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The outbound-workplace comparison reuses the census workplace-flow extract, DA characteristics 2600–2602 and the household PUMF workplace field `POWST`. Its held-out mode check reads `98100462.csv` from the official 2021 table ZIP, filtered to Vancouver CSD, total gender and counts for all ages and six disjoint age groups. It sums the three destination columns outside the home municipality. Published walking and cycling counts are combined. Archive SHA-256 is `32c9920bb8ee22b34c4f5971f5614d1571aacb54b93fdbbe59632ca3a20e51e0`. [Statistics Canada table 98-10-0462-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046201)

The optional neighbourhood mode fit uses the all-age external counts from that table as calibration inputs. It reserves the six age-specific rows for evaluation. Its other controls are the six usual commute mode counts from Census Profile characteristics 2605–2610 for workers with a usual workplace or no fixed workplace. The adapter sums the published DA cells by home neighbourhood. DA 59154026 lacks the six counts and contributes no observations. The nearest whole-person targets use each neighbourhood’s modelled commuter total. [2021 Census Profile for Vancouver](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/page.cfm?Lang=E&DGUIDlist=2021A00055915022)

The municipal cycling network uses the archived OSM Overpass highway ways in `data/raw/osm-overpass/vancouver_highways.json`. The graph release stores the source SHA-256, underlying street release, node count and way count in `source.json`. The outbound workplace build regenerates the cycle graph and pins its version in the fitted commute report. Walking and cycling times use the same nominal speeds as the original municipal day. The route build and the browser read the same graph files. [Street travel budgets](doc/vancouver.md#fitting-active-commutes-to-the-street-network)

The municipal trip geography comparison uses Tables 1 and 18 of the 2023 Vancouver Transportation Survey. The archived GeoJSON `data/mobility/taz-gvrd.geojson` has SHA-256 `3b8f6ba3c0daea9637807c8eb4c6b4cba72755682c655023be09800d2647538f`. It groups 372 Vancouver traffic-analysis polygons by the `gh` field. The regional subarea map supports the nine-group correspondence. The vintage and exact correspondence to the 2023 survey boundaries are unverified. The browser release contains derived statistics. [City survey](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF) · [TAZ_GVRD source item](https://www.arcgis.com/home/item.html?id=31b1106ca5fb4c91b303e26f446eb173) · [Regional subarea map, Figure 2.2](https://metrovancouver.org/boards/RegionalPlanning/RPL-2025-09-11-AGE.pdf#page=67)

The 2023 TransLink Trip Diary dashboard shows municipality-level origins and destinations with filters for mode and purpose. It suppresses destinations with small samples. TransLink’s public request log records request 2025-466 for the traffic analysis zone boundaries and origin–destination tables, including transit and auto where available. The log says TransLink released the records in full on December 4, 2025. The dashboard’s export menu offers image, PDF and PowerPoint formats. The released tables would support checks at a finer geography. [Public Trip Diary dashboard](https://public.tableau.com/app/profile/translink/viz/Trip_Diary_2023/TripDiary) · [TransLink request log](https://www.translink.ca/-/media/translink/documents/about-translink/freedom-of-information/past-non-personal-access-requests/foi-requests-received-in-2025.pdf)

The disclosure log contains the request summary. TransLink's Information Access Department is the contact for the release package for request 2025-466. The analysis needs the zone geometries and lookup, the origin–destination tables, and definitions of modes, time bands, purposes, weighting and suppression where supplied. [TransLink Information Access](https://www.translink.ca/translink/about-us/about-translink/freedom-of-information-requests)

**Copy request for foi@translink.ca, subject 2023 Trip Diary release package 2025-466**

> Hello, could you share the records released under request 2025-466 on December 4, 2025? We are looking for the 2023 Trip Diary traffic analysis zone boundaries and lookup, the origin–destination tables, and any accompanying field definitions, weighting and suppression notes, and reuse terms. If the package has time-of-day, mode, or trip-purpose breakdowns, please include those tables as supplied. Thank you.

The Downtown transit booking audit uses the published resident transit input and bookings, the Census-fitted incoming homes and work windows, and the dated TransLink GTFS and pedestrian network releases. The companion station-count comparison supplies the external reference for passenger events. [Demand and booking audit](doc/vancouver.md#downtown-transit-demand-and-bookings)

The resident trip demand release uses 2023 survey Table 16 for mode shares by home zone and Figure 36 for citywide shares by purpose. The comparison of trip rates uses Figure 46's published purpose volumes and rounded mode shares together with the 584,700 adult residents in Section 1.3. The source gives the joint counts at city scale. Diary purposes use the first activity at the destination. [City survey](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The combined weekday timing comparison holds out the 2025 survey’s three two-hour departure periods. Figures 19–21 supply rounded purpose shares and expanded trip volumes. Table 2 supplies the 609,000 adults in private households. The builder counts the published resident schedules, their reconstructed short walks and both legs of fitted shopping tours. [2025 survey figures](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=47) · [Population table](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=23) · [Timing method](doc/vancouver.md#trip-purpose-before-and-during-rush-hour)

The bicycle timing comparison pins the combined weekday, its cycling graph and the original peak-period counts. It carries the two actual bicycle endpoints and the shopping stop through the retiming, and verifies the change in occupancy with Raster. The 16:30 transit slack calculation uses the already booked weekday riders and their published timetable. [Bicycle timing method](doc/vancouver.md#spreading-bicycle-shopping-departures)

The shopping-walk scenario takes its citywide volume from Figure 46 and draws on walking tours from the Canadian 2022 time-use public-use microdata already used in the diary comparison. It matches named retail destinations in the archived Overture inventory to the published weekday addresses. Holdout counts use the original municipal intersection studies listed above and the same circle-based counting rule as the main pedestrian comparison. The browser publishes only the added synthetic journeys and aggregate checks. [Shopping-walk release method](doc/vancouver.md#vancouver-weekday-shopping-walks)

The paired grocery catalogue admits fitted stops whose time-use donor recorded in-person goods shopping. It applies the original catalogue’s 40% grocery share, the same dated grocery licences and candidate storefronts, and the same travel budget. Its archive retains the exact base catalogue and fitted outing identities. The combined weekday variant also pins the joint release and its census workplace assignments. [Paired grocery opening method](doc/vancouver.md#grocery-openings-with-fitted-shopping-demand) · [Combined market comparison](doc/vancouver.md#grocery-openings-on-the-combined-weekday)

The combined municipal weekday pins the Census workplace fit, 2026-09-15 TransLink timetable, incoming worker roster and fitted shopping release. It reuses the independent 2025 SkyTrain observations and six Vancouver pedestrian studies for scoring. The matched passenger shards and street walking index describe synthetic residents. [Combined weekday method](doc/vancouver.md#commutes-and-shopping-on-the-same-weekday)

The hired-ride replay uses the published citywide share and the March 2025 operator totals for B.C. Passenger Transportation Region 1. The publisher records both source references, the roster and weekday releases, the street graph version and the driving profile digest. Its passenger assignments are synthetic. [2025 City survey, Figure 24](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=51) · [B.C. Passenger Transportation Board](https://www.ptboard.bc.ca/data-newsletters/november-2025)

The dispatch comparison uses first-quarter 2025 occupancy to size its reference fleet at the busiest modeled hour. It compares resulting waits with the September 2024 medians and shows 2024 five-kilometre fare ranges for context. Its release pins the hired-trip cohort and the road speed profile and includes both sets of dispatch decisions. [Occupancy](https://www.ptboard.bc.ca/data-newsletters/june-2026-newsletter) · [Pickup waits](https://www.ptboard.bc.ca/data-newsletters/march-2025) · [Fares](https://www.ptboard.bc.ca/data-newsletters/may-2025)

The regional bridge benchmark reads the B.C. Traffic Data Program’s March 2025 monthly hourly volume export for Second Narrows station P-15-2EW from `data/mobility/ironworkers-2025-03.csv`. The published release records the file’s SHA-256, `4ec082757c8d9a6e6ec3be818364cd07d3d2d020b48310c8cbcaf0ad36447f86`. Save the CSV from the source link at that path, or pass it to the builder with `--ironworkers`. The workplace comparison uses both directions from the same Census extract as the incoming worker build. [Province CSV](https://tradas.th.gov.bc.ca/reports/AllYears/2025/03/MV03/MV03P_Second%20Narrows%20P-15-2EW%20-%20NY3-2025.csv)

The regional commute check reads the 2021 Census table 98-10-0479 from `data/mobility/98100479-eng.zip` or the path passed with `--census`. It extracts the usual-workplace counts by home municipality, main commute mode, departure band and duration band. The published extract preserves suppressed cells and records the ZIP's SHA-256, `a2b357e6fab812fb37655c8dc7b3dc68f5b8ca5fdf5b52be2e5698a3a6f37460`. [Statistics Canada table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810047901) · [ZIP export](https://www150.statcan.gc.ca/n1/tbl/csv/98100479-eng.zip)

The incoming commuter duration check reads `data/mobility/98100461-eng.zip`, SHA-256 `c7029e573cc3ff410d73eea7e0dbd9f50a96878e31a121c3a8639f1a0e879930`. It uses complete public-transit duration cells for each origin municipality and straight-line commute distance, summed over departure times. The Census universe includes workers with usual workplaces at any destination. The comparison weights these cells to the simulated origin and distance mix. [Statistics Canada table 98-10-0461-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101) · [ZIP export](https://www150.statcan.gc.ca/n1/tbl/csv/98100461-eng.zip)

The fixed-shift Downtown booking experiment reuses that duration table and the combined weekday's pinned GTFS, walking, home and booking releases. Both the Census duration distributions and TransLink station counts are used to score the sensitivity settings. [Method and REPL entry point](doc/vancouver.md#booking-with-fixed-work-shifts)

The incoming home fit reads characteristics 2603 and 2607 from the British Columbia Census Profile. These are the main-commute-mode total and public-transit count for each dissemination area. They cover usual workplaces at all destinations and workers with no fixed workplace. The builder uses them as a geographic prior for where otherwise similar synthetic incoming workers live. The released report contains the observed cells, target counts and fitted counts for each area. [2021 Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)

The incoming driving comparison reads `data/raw/statcan/vancouver_city_boundary.geojson` and `data/raw/probes/counts_vancouver_arcgis_TCSPermanentCounts_sample.json` in the source archive, plus the same regional bridge CSV for Ironworkers. The report pins all three file hashes, the paired home assignment and the metro graph. The resident driving and bus report reuses the same named road cuts, graph and observations, and pins the combined weekday’s workplace assignments and timetable. City hourly values represent an average weekday in the indicated month. The Ironworkers values average the 21 weekdays in March 2025. [City boundary](https://opendata.vancouver.ca/explore/dataset/city-boundary/table/) · [Permanent count stations](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations)

The published Downtown rush-hour benchmark reuses those vehicle counts and the 2025 TransLink weekday SkyTrain station counts. It records the City’s record ID, reference month and year by direction, the SkyTrain station names, and the modeled commuter and timetable release IDs. [Benchmark method and build](doc/vancouver.md#published-downtown-rush-hour-benchmark) · [Permanent count stations](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations) · [TransLink station counts](https://www.translink.ca/tspr)

The municipal outbound road build reads `data/region/vancouver.osm.pbf`, the same archive as the metro drive graph. It registers mapped workplace coordinates to the 2021 Census dissemination-area subdivisions and `data/mobility/vancouver-tracts-2021.geojson`. The `Usual place of work` rows in `data/mobility/98100498-eng.zip` supply tract weights. The release keeps the allocated municipality from the 2021 commuting flows and records the Census and OSM file hashes. [Census workplace income table ZIP](https://www150.statcan.gc.ca/n1/tbl/csv/98100498-eng.zip) · [Outbound road model and build](doc/vancouver.md#resident-road-commutes-to-external-workplaces)

The municipal outbound transit build uses the same Census workplace and OSM point inventory, the incoming-worker release’s full regional GTFS timetable and walking graph, and the resident and incoming vehicle reservations. It executes the bulk timetable scan with Numba. The duration audit and timetable clock comparison read the same Statistics Canada archive as the incoming duration check and use the City of Vancouver origin and the booked home-to-work distance mix. The clock uses the six published departure bands and pools duration when comparing departure shares. [Outbound transit method](doc/vancouver.md#resident-transit-commutes-to-external-workplaces) · [Census departure and duration table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101)

The paired regional workplace build reads the 16 cells for residence and work in Vancouver, City of North Vancouver, District of North Vancouver and West Vancouver from Statistics Canada Table 98-10-0459-01. It accepts the original CSV from the zip or the header and selected rows in `data/mobility/workplace-matrix-2021.csv`. The selected file has SHA-256 `7ebe3d4c6d3df721874a6c723f1b8e8e34b54363227d1f2414ac89ecec9a3929`. [Statistics Canada source archive](https://www150.statcan.gc.ca/n1/tbl/csv/98100459-eng.zip)

The regional incoming-worker build uses all origins for the same four workplace destinations in `data/mobility/regional-incoming-workplaces-2021.csv`. Extract the header and the four workplace rows per origin from the source archive's `98100459.csv`. The selected file has SHA-256 `4817a369ad6f672bfa4fc06f5af57f9c0564e517addeaea70f05b35110c81727`. The builder also reads the 2021 Profile by home DA, the public-use household census records, the time-use diaries, the regional OSM workplace extract and the workplace tract sources above. [Statistics Canada source archive](https://www150.statcan.gc.ca/n1/tbl/csv/98100459-eng.zip)

The weekday's displayed driving paths use a speed file with one pair of directional values per way in its street release. Build both study areas with `python -m scripts.vancouver_drive_profile ../Simulations/city`. The builder checks the way order and topology against the street release before publishing. It reads `maxspeed` and directional overrides from the same OSM archives that supplied the published streets and records the source hash and class defaults in the profile.

After building the profile, `node scripts/vancouver_overview_routes.mjs public/data/vancouver` prepares every hour of the municipal sample. Pass `public/data/vancouver/region` for the regional day and append its paired weekday hash to prepare the workplace scenario. The exporter and browser worker use the same routing code. The data files carry the atlas, day, street and speed source versions.

The independent workplace inventory check uses `98100498-eng.zip` (SHA-256 `75ef15a63ec7dc59600decd737b136264b02fe0ac0905ea9e1750d586b477e28`) and all 535 Vancouver CMA tracts in the 2021 cartographic layer. It joins the usual-place-of-work count by tract of work to the tract DGUID. Regenerate the comparison from the repository root using the existing 2025 Vancouver licence archive. [Statistics Canada table 98-10-0498-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801) · [2021 cartographic tract layer](https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer/11)

```sh
curl -fL https://www150.statcan.gc.ca/n1/tbl/csv/98100498-eng.zip -o data/mobility/98100498-eng.zip
curl -fL -G 'https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer/11/query' \
  --data-urlencode "where=CTUID LIKE '933%'" --data-urlencode 'outFields=CTUID,DGUID' \
  --data-urlencode 'outSR=4326' --data-urlencode 'geometryPrecision=6' --data-urlencode 'f=geojson' \
  -o data/mobility/vancouver-tracts-2021.geojson
python -m scripts.vancouver_workplace_tracts ../Simulations/city
```

The resident departure comparison reads Census Profile characteristics 2617–2623 from the archived BC CSV and its geographic starting-row index. Characteristic 2617 supplies the denominator, including employed workers aged 15+ with a usual workplace or no fixed workplace address. The last two Profile categories split at noon. The hierarchical PUMF variable `PWLEAVE` used for incoming workers splits at 16:00. The departure comparison uses the six Profile categories. Its versioned report records the source catalogue, characteristic IDs, population version and replay version. [2021 Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)

The household-clock alternative joins the hierarchical 2021 Vancouver CMA PUMF `PWLEAVE` field to the published synthetic household roster and reads complete 2022 urban BC weekday training diaries with their original survey weights. The release identifies both parents and records changed roster positions and donor templates. The census Profile timing observations are reserved for comparison. Rebuild the two longer-trip sensitivities by adding `--allow-longer-trips` to the clock build, also adding `--all-matches` for the unrestricted matching rule. [Method and release comparisons](doc/vancouver.md#matching-a-complete-weekday-to-household-commute-times)

The held-out bicycle counts use the City's January 9, 2024 Arbutus and West 10th turning movement survey and January 31, 2024 Powell Street midblock survey. The adapter reads `counts_vancouver_tmc_arbutus_w10th_2024-01-09.xlsx` and `counts_vancouver_midblock_700_powell_2024-01-31.xlsx` in the archive's `data/raw/probes` directory. Each published report carries the source filenames and SHA-256 digests, survey windows, weather and approach counts. [City traffic count program](https://vancouver.ca/streets-transportation/traffic-count-data.aspx) · [Model comparison](doc/vancouver.md#bicycle-counts-on-city-streets)

The municipal bikeway preference uses the City’s Bikeways GeoJSON export retrieved on November 21, 2026 (SHA-256 `3fdcb1cc3f2a4c34d3e5f44a775c06fe6645a0167e045ee9723f047a33b7c83f`). To acquire the snapshot from the current catalogue, run `curl -fL https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/bikeways/exports/geojson -o data/mobility/vancouver-bikeways.geojson`. The catalogue can change. The published profile records the source hash and parent bicycle graph. The additional 2023 observations come from the Bicycle (“Bike”) tabs and corresponding movement rows in the City’s July 12 Ontario and 5th and April 5 Prince Edward and Broadway attachments, archived under `data/raw/vancouver-arcgis`. The adapter reads each workbook’s declared survey windows and stores its hash in the count report. [City bikeway inventory](https://opendata.vancouver.ca/explore/dataset/bikeways/) · [Municipal open data licence](https://opendata.vancouver.ca/pages/licence/) · [Survey attachments and replay](doc/vancouver.md#a-paired-test-of-bicycle-route-choice)

The wider bicycle comparison uses published summer daily averages at Point Grey Road, the David Lam Park seawall, and the Creekside Community Centre seawall. The adapter records each average and its publication year alongside the corresponding location from the City's 2025 counter inventory release. [2024 Transportation Snapshot](https://vancouver.ca/files/cov/2024-transportation-snapshot.pdf#page=12) · [2023 Transportation Snapshot](https://vancouver.ca/files/cov/2023-transportation-snapshot.pdf#page=9) · [2021 Transportation Snapshot](https://vancouver.ca/files/cov/2021-transportation-snapshot.pdf#page=9) · [Counter locations, FOI 2025-873](https://vancouver.ca/files/cov/2025-873-release.pdf)

The City also reports 1,097,789 public bicycle-share rides across 2025, about 3,008 per calendar day over the whole network. That measure covers station rentals across the year. The replay uses the City’s street counts for corridor comparisons. The bicycle-share operator publishes monthly trip files under its own redistribution terms. [City transportation totals](https://vancouver.ca/streets-transportation/walk-bike-and-transit.aspx) · [Operator system data and licence](https://www.mobibikes.ca/en/system-data)

The Granville Island visitor replay uses the South False Creek streetcar study’s tourist volume estimate, tourist interviews and Anderson Street mode count. The hotel source is `data/mobility/vancouver-hotels-2025.json` with SHA-256 `6b90ac09ac711695d0bb12ab0f8ef2841488a96a4061b6f390a42494d1017530`. The archive contains 94 issued 2025 licences in the City’s “Hotel or Motel” category with a mapped point. The query selects the licence ID, names, address, local area, point and number of employees. The mapped rack comes from the project's OpenStreetMap extract. [South False Creek streetcar study](https://vancouver.ca/files/cov/2025-020-release.pdf#page=147) · [City hotel licences](https://opendata.vancouver.ca/explore/dataset/business-licences/) · [Mapped rack](https://www.openstreetmap.org/node/1692226725)

The municipal grocery comparison uses Statistics Canada’s 2010 General Social Survey Cycle 24 main, episode and bootstrap files. Place and activity together distinguish buying groceries from other goods. The published market records the archive hash, contributing stops and respondents, weighted shares and sampling intervals. The 2022 Time Use Survey supplies a separate check on shop hours. City transportation surveys supply independent shopping-mode benchmarks for 2019 and 2024. [2010 microdata and user guide](https://www150.statcan.gc.ca/n1/en/catalogue/12M0024X) · [Source definitions and reproduction](doc/vancouver.md#survey-based-grocery-demand-and-shop-hours)

The local walking scenario uses the public 2024 Canadian Food Environment Dataset v2 archive (SHA-256 `fad07b23513eb2c170694f989a9d1ea51c081c44590cc91dfcd5e88fb67768a2`) and the 2021 Geographic Attribute File (SHA-256 `918aa8502d9d95b1ae5ce437ed9674e0977ec55977c08b8d01822a9dab6fe5da`, obtained from the Data for Canada archive). Census block counts are summed within each DA. DARPLAT and DARPLONG identify its representative point. Both distances use the positive grocery and chain-grocery classes from Can-FED. The 15-minute walking limit and speed come from the City's 2025 food access study. [Data and builds](doc/vancouver.md#walk-to-a-local-grocer)

The East Hastings opening comparison joins the archived Can-FED access rows to the combined weekday by census area. The build checks the municipal footprint, the incumbent store catalogue and the walking graph. The access rows and the modeled visits measure store proximity and simulated shopping occasions respectively. [Method and comparison](doc/vancouver.md#east-hastings-demand-and-access)

### Vancouver terrain

Natural Resources Canada publishes the HRDEM Mosaic and the Canadian 30 m MRDEM under the Open Government Licence – Canada. The street map uses the bare-earth Digital Terrain Model from each product. The archived extracts and adjacent request URLs are in `data/region/terrain`. The immutable tile manifest records the SHA-256 of each extract, the vertical datum, the geographic bounds and the pixel coverage by source. Running the build with the archive needs NumPy, SciPy, Pillow and tifffile. Add `--fetch` to fill a new archive over HTTPS with WCS extracts and `gdalwarp` range reads from the 30 m GeoTIFF. Source updates can change the resulting version. [HRDEM Mosaic](https://open.canada.ca/data/en/dataset/0fe65119-e96e-4a57-8bfe-9d9245fba06b) · [MRDEM](https://open.canada.ca/data/en/dataset/18752265-bda3-498c-a4ba-9dfe68cb98da) · [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)

```sh
python -m scripts.vancouver_terrain
```

The municipal bicycle hill profile pins the terrain release, the directed bicycle graph and the parent City bikeway preference. It checks the raw raster and OSM hashes before sampling. Its parameters use a distance approximation to the commute coefficients from the Portland GPS route-choice study. The Vancouver street counts provide an independent check. [Bicycle route comparison and build](doc/vancouver.md#hills-in-bicycle-route-choice) · [Broach, Dill and Gliebe](https://doi.org/10.1016/j.tra.2012.07.005)

### Vancouver building heights

The height overlay uses 165 paired one-metre LidarBC surface and bare-earth rasters catalogued under the 2025 survey. The inputs are in NAD83(CSRS) UTM zone 10N (EPSG:3157) with CGVD2013 heights. The builder reads the existing city and regional street releases for their footprints and courtyard holes. The overlay manifest records the survey tile names, source URLs, SHA-256 digests and counts by previous height basis. The cached rasters take about 1.6 GB under `data/region/building-elevation`. [LidarBC catalogue](https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/LiDAR_BC_S3_Public/FeatureServer) · [Open Government Licence – British Columbia](https://www2.gov.bc.ca/gov/content/data/open-data/open-government-licence-bc) · [Height method and coverage](doc/vancouver.md#lidar-building-heights)

Run `python -m scripts.vancouver_building_heights --fetch` to fetch any missing inputs and build both overlays. With the archive present, omit `--fetch`. In addition to the Python dependencies used for terrain, the build uses Matplotlib for containment tests and PROJ's `cs2cs` to work in the raster's coordinate system.

With Shapely 2.1 installed, run `python -m scripts.vancouver_roof_sections` to fit separate roof levels from the same archive. The resulting release pins the existing flat-height overlay. It records the fitted building count, the minimum vertical separation and footprint area per section, and the elevation error on raster cells withheld from both fitting and model selection. [Example of footprint-based roof reconstruction](https://isprs-annals.copernicus.org/articles/V-4-2021/169/2021/) · [Vancouver method and coverage](doc/vancouver.md#lidar-building-heights)

### Vancouver bridge decks

Run `python -m scripts.vancouver_decks --fetch` after acquiring the road and terrain inputs. The command archives five Natural Resources Canada HRDEM DSM extracts in `data/region/bridge-elevation/` and writes a content-addressed release to `public/data/vancouver/bridge-decks/`. Omit `--fetch` to use the saved rasters and request URLs. The default road input is `data/region/work/roads.jsonl`, prepared from OpenStreetMap by the regional builder. The fitted profiles use the CGVD2013 datum, with individual source hashes and the OSM road archive hash recorded in `decks.json`. [Natural Resources Canada HRDEM](https://open.canada.ca/data/en/dataset/0fe65119-e96e-4a57-8bfe-9d9245fba06b) · [Bridge playback and limits](doc/vancouver.md#bridge-decks)

### Highway 1 travel times

The regional traffic comparison reads Binnie file 22-0616-05, prepared for the B.C. Ministry of Transportation and Infrastructure. Archive the report as `data/mobility/ironworkers-travel-times-2022.pdf` with SHA-256 `87a78e7cd6b5627523956c4b5f1e9a727a03a212d6b2bbd5a356ec7f64f10e31`. The builder uses Poppler's `pdftotext` to read only the 2022 median column from Tables 5-1 through 5-8. It matches the cuts in Figure 3-4 to the archived OSM mainline and pins the study and free-flow profile by digest. The independent March 2025 vehicle counts continue to come from the provincial Ironworkers station and the City's permanent Lions Gate counter. [Study PDF](https://www.vmcdn.ca/files/nsnews/files/binnie-iwmb-travel-time-study-final-rev0.pdf) · [Comparison and build commands](doc/vancouver.md#observed-highway-1-travel-times)

### Vancouver arterial travel times

Save the CAA and CPCS report as `data/mobility/caa-bottlenecks-2015.pdf` with SHA-256 `20e98df5ac5e8ab64185c7d1ef2c882cc27c720784e50a99cc9d4c68c42e01fd`. The builder uses `pdfimages` and Pillow to read the three posted Figure 14 curves from the archived page raster. It rounds speeds to the nearest km/h and matches Figure 13's limits on the same published graphs used by the weekday. The two resulting releases pin the graph, the source PDF and the base speed profile by digest. The regional version also reads the previously built Highway 1 time profile. [CAA and CPCS report, figures 13–14](https://www.caa.ca/app/uploads/2021/01/16170_Canadian_National_Bottlenecks_Study_EN_1_4_17.pdf#page=23) · [Replay and comparison](doc/vancouver.md#observed-travel-times-on-vancouver-streets)

### Vancouver census-block homes

Use the 2021 Geographic Attribute File already stored as `data/mobility/2021_92-151_X.zip` and the Census cartographic dissemination block shapefile stored as `data/mobility/ldb_000b21a_e.zip` with SHA-256 `1ed137476d6c071472177e4c47e9a45020a28b3f580d6c60dabd2341b083f14c`. The Data for Canada archive mirrors the official StatsCan boundary download. The builder uses `DAUID_ADIDU` and `DBUID_IDIDU` to reconcile the roster with the Census geographic hierarchy. `DBURDWELL2021_IDRHLOG2021` supplies occupied private dwellings and `DBPOP2021_IDPOP2021` supplies residents. It uses the residential ways and declared levels in `data/region/work/buildings.jsonl`, which the regional build prepares from OpenStreetMap. The versioned audit records all three SHA-256 digests. [Geographic Attribute File](https://www150.statcan.gc.ca/n1/en/catalogue/92-151-X) · [Census block boundaries](https://www150.statcan.gc.ca/n1/en/catalogue/92-163-X2021001) · [Boundary archive mirror](https://data.source.coop/dataforcanada/d4c-datapkg-statistical/archive/statcan/boundaries/2021/ldb_000b21a_e.zip)

### Vancouver property assessments

Use the City's 2021 property tax roll and the City's November 2026 parcel point export. Join `land_coordinate` to `tax_coord` as strings and assign parcel points to the municipal atlas's local-area boundaries. The publisher validates that the roll year is uniform and folios are unique. It records the input digests and publishes aggregate counts and distributions. MountainMath's division of assessments into land and improvements informed the choice of measures. [City assessment file](https://opendata.vancouver.ca/explore/assets/property-tax-report/) · [City parcel data](https://opendata.vancouver.ca/explore/assets/property-parcel-polygons/) · [MountainMath assessment analysis](https://doodles.mountainmath.ca/posts/2016-04-01-on-dirt-and-houses/) · [VancouvR export reference](https://mountainmath.github.io/VancouvR/reference/get_cov_data.html)

```sh
mkdir -p data/civic
curl -fL -G 'https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/property-tax-report/exports/csv' \
  --data-urlencode "where=report_year='2021' and tax_assessment_year='2021'" \
  --data-urlencode 'select=folio,land_coordinate,legal_type,zoning_classification,current_land_value,current_improvement_value,report_year,tax_assessment_year' \
  -o data/civic/vancouver-property-assessment-2021.csv
curl -fL -G 'https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/property-parcel-polygons/exports/csv' \
  --data-urlencode 'select=tax_coord,geo_point_2d' \
  -o data/civic/vancouver-property-parcel-points.csv
python -m scripts.vancouver_property_assessments
```

To include strata in other zoning classes, archive the 2021 `tax_levy` export and match its folios to the roll. A record qualifies when its levy is within one cent of the 2021 Class 1 total of $2.92250 per $1,000 of full assessment. The comparator also accepts the total including the 2021 additional school levy. Some properties have different taxable bases. This provides an explicit inference from the bill and the assessment. [City of Vancouver 2021 rates](https://vancouver.ca/files/cov/2021-property-tax-rates.pdf) · [Provincial school levy in force for 2021](https://www.bclaws.gov.bc.ca/civix/document/id/hstats/hstats/1482258268)

```sh
curl -fL -G 'https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/property-tax-report/exports/csv' \
  --data-urlencode "where=report_year='2021' and tax_assessment_year='2021'" \
  --data-urlencode 'select=folio,tax_levy,report_year,tax_assessment_year' \
  -o data/civic/vancouver-property-levies-2021.csv
python -m scripts.vancouver_property_assessments --levies data/civic/vancouver-property-levies-2021.csv
```

For historical comparisons of commuting and housing, MountainMath provides reproducible census analyses and tools for aligning changing census and polling district boundaries. The 1996–2016 Metro Vancouver commuting series has modes, durations and departure times by municipality. Keep each observation's geography and Census universe alongside it when comparing it with a simulated weekday. [Commuter Growth](https://doodles.mountainmath.ca/posts/2019-10-29-commuter-growth/) · [CensusMapper access](https://mountainmath.github.io/cancensus/) · [Geographic correspondence](https://mountainmath.github.io/tongfen/)

The joint municipal weekday also has a held-out comparison of trip modes by income. The builder uses the printed shares in Figure 54 of the 2022 Vancouver Transportation Survey and the income concept from question B9. The report pins the existing atlas and joint weekday, and sums individual Census before-tax incomes within their original private households. [Transportation survey and questionnaire](https://vancouver.ca/files/cov/2022-transportation-panel-survey.pdf) · [Comparison and build](doc/vancouver.md#travel-modes-by-household-income)

### North Shore workplaces

The downtown fit uses Table 20 of the municipalities' 2023 North Shore Transportation Survey. Save the report as `data/mobility/north-shore-transportation-survey-2023.pdf` with SHA-256 `fea241ceae3da2b6f909e4f58203e95dc0ef2bb8ae8ba951a8db41ad6ae768a0`. The model transfers the municipality-specific proportion of Vancouver and UEL jobs located in CBD/West End. The report records the parent weekday, digest of the road profile and dated GTFS release used for checking proposed exchanges. The March 2025 bridge counts are held out from the allocation. [Survey PDF](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF) · [Model and build](doc/vancouver.md#downtown-workplaces-for-north-shore-commuters)

The resident trip-demand comparison uses the same PDF. Tables 3 and 4 supply populations aged 15+, Table 7 supplies rounded purpose shares, Table 8 supplies mode counts, section 3.1.2 supplies the peak-hour departure counts, and Table 11 supplies southbound destinations across Burrard Inlet. Each report is pinned to the atlas and weekday. Any reconstructed-walk evidence also pins the street network. [North Shore travel demand and build](doc/vancouver.md#north-shore-resident-travel-demand)

Archive the optional 2025 North Shore Transportation Survey as `data/mobility/north-shore-transportation-survey-2025.pdf` with SHA-256 `1899c623fc7e9cdd1d94fb1c655c33baa0be34bbaf3ca141ebbe2bedc8825be6`. Figure 23 and Table 21 supply trip totals and populations aged 15+. Tables 26–29 supply purpose counts and rounded shares, Figure 29 and Table 30 supply mode counts, and Table 35 supplies southbound destinations. These trip observations are held out from calibration. The publisher checks the PDF hash and includes its provenance in the release. [2025 North Shore Transportation Survey](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The same PDF supplies the eight home and work zones. The publisher uses `pdfimages` from Poppler to extract the Figure 2 raster. It identifies the eight outlined regions from their blue fills and registers the figure to the official 2021 cartographic Census boundaries in NAD83 / UTM zone 10N. Tables 3 and 54 supply the age-15+ denominators and weekday commute counts. The optional 2025 workplace fit uses Table 54 and preserves the independent Table 35 destination totals and bridge-counter checks. [Zonal workplace fit](doc/vancouver.md#workplace-destinations-by-north-shore-home-zone)

Recreational walks use section 5.3 and Figure 31 as separate demand margins. The timing prior comes from 2022 urban BC weekday exercise episodes with detailed activity code 1001 in a neighbourhood or outdoors. The published walk release pins the pedestrian graph and the concurrent outing, short-walk and flexible-transit inputs. [Recreational walks from home](doc/vancouver.md#recreational-walks-from-home)

The school escort scenario uses Figures 4 and 5 in Appendix B of the City of North Vancouver’s Safe and Active School Travel Program Refresh. It matches public elementary school coordinates and names from the B.C. directory already used to build the weekday, at `data/raw/probes/anchors_bc_k12_schools.csv` in the source archive. The release pins the weekday, road profile, and concurrent outings, recreation, short walks and flexible transit. [2021 school travel survey figures](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Safe-and-Active-Schools/Safe-and-Active-School-Travel-Program-Refresh-Appendices.pdf) · [School escort model and build](doc/vancouver.md#school-drop-off-and-pickup)

The on-site work scenario uses Tables 49–54 from the same 2025 survey and the matched Vancouver CMA households in the 2021 Census Hierarchical PUMF v2 already used for the atlas. It reads `POWST`, `PWLEAVE`, `PWDUR` and the atlas's `MODE`. The release pins the street and bicycle graphs, dated transit and bus capacity inputs, and the concurrent schedule layers. [Work attendance model and build](doc/vancouver.md#moving-a-home-working-shift-on-site)

### Vancouver advance voting

Save the public catalogue API response as `data/civic/vancouver-voting-places-2025.json`. The build uses voting place IDs 200, 24, 4, 9 and 13 and records the source digest. The published input returned 26 records with SHA-256 `f30a6affe6c0d9a10ab0828f636305d6466a72f19ea7f8dd42d56c72b063b5b2`. The City review supplies opening hours, staffing for March 26 and April 1 and the relative neighbourhood turnout weights. The City statement to local media supplies preliminary daily ballots cast. The ballot account supplies the final combined advance volume. [Catalogue](https://opendata.vancouver.ca/explore/dataset/voting-places-2025/table/) · [City review](https://council.vancouver.ca/20250520/documents/r3.pdf) · [Preliminary counts by date](https://vancouver.citynews.ca/2025/04/02/vancouver-byelection-advance-voting-record-turnout/) · [Official ballot account](https://council.vancouver.ca/20250415/documents/r9.pdf) · [Scenario and build](doc/vancouver.md#advance-voting-access)

The schedule comparison reads home leisure and household-task episodes from the 2022 Time Use Survey donors carried by the released atlas. The one-hour limit on rescheduling housework is a model assumption. The report pins the atlas, combined weekday, street network, transit timetable and protected workplace lunch release. [Time Use Survey microdata](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001) · [Activity scheduling method](https://doi.org/10.1007/s11116-022-10330-8)

The detour comparison uses mapped one-mode walks and drives ending at home on the same combined weekday. It reads the paired census workplace assignment for municipal jobs and protects the diary's next commitment, with at most 30 minutes of immediately following free time available for the stop. Regional trip diary evidence motivates the trip pattern. The available voting data measure ballot totals and give no routes to polling places. [TransLink trip diary analysis](https://www.translink.ca/-/media/translink/documents/about-translink/customer-service/trip-diary/2011-metro-vancouver-regional-trip-diary--analysis-report.pdf)

Save the 2025 anonymous ballot CSV as `data/civic/2025MunicipalBy-ElectionAnonymousBallotMarking.csv` and run `python -m scripts.vancouver_ballots`. The archived browser download has SHA-256 `5b5e293263cee3f96d4410a09556393641078c67fa021d683429dd589b4880df`. The build reconciles the general, advance and mail volumes and each of the 13 candidate totals against the official report. It publishes aggregate mark and candidate-pair counts with the input hash. Voting-place locations describe where people cast ballots under Vote Anywhere. Ballot records omit home addresses. The 2025 by-election was a two-seat contest. The 2022 general election had ten council seats and separate contests for mayor and other offices. Keep those contests separate when comparing mark counts. [2025 anonymous ballot CSV](https://webtransfer.vancouver.ca/OpenData/csv/2025MunicipalBy-ElectionAnonymousBallotMarking.csv) · [Official ballot account](https://council.vancouver.ca/20250415/documents/r9.pdf) · [MountainMath's 2022 analysis](https://doodles.mountainmath.ca/posts/2022-12-17-analyzing-ballot-composition-in-vancouver/)

```sh
mkdir -p data/civic
curl -fL 'https://opendata.vancouver.ca/api/records/1.0/search/?dataset=voting-places-2025&rows=40' \
  -o data/civic/vancouver-voting-places-2025.json
```
