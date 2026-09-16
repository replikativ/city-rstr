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
