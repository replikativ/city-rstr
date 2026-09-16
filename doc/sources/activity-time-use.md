# Daily activity, time use, mobility counts (probe report 2026-09-10)

Samples saved under `data/raw/probes/` (prefixes timeuse_, travel_, transit_, counts_, anchors_, matsim_, osm_).

## Ranked
| Source | Gives | Coverage | Licence | Recipe |
|---|---|---|---|---|
| StatCan Time Use Survey 2022 PUMF (GSS C37) | 168k episodes / 12.3k diaries: 4-digit activity, 18-class ACTIVITY, LOCATION (29 codes incl. mode), start/end minutes, who-with, bootstrap weights | Canada, province + urban/rural | StatCan Open Licence, no login | `https://www150.statcan.gc.ca/n1/pub/45-25-0001/cat7/TU_ET_2022.zip` (187 MB). 2015 C29: `.../cat7/c29_2015.zip`. Use shipped Stata .dct (PDF positions wrong) |
| MiD 2017 Stadt Stuttgart Grundauswertung (PDF tables) | trip rates 3.2/person/day, mode share (walk 29, bike 8, car-driver 31, ÖPV 23 %), purpose split, start-time distributions, cross-tabs | Stadt Stuttgart n=6,252 trips | public PDF | `vm.baden-wuerttemberg.de/.../MID2017_Stadt_Stuttgart.pdf` |
| TransLink TSPR 2023–2025 | bus route × day-type × hour-bin boardings; SkyTrain station × hour boardings; stop × line daily boardings 2019–2024 | Metro Vancouver | OGL-TransLink | `translink.ca/.../tspr/csv-data/2025/*.csv` (browser UA); ArcGIS `services7.arcgis.com/WpS8F3vcmrEQUG8m/.../TSPR_OpenData_Archive/FeatureServer` |
| Mobidata BW Eco-Counter | hourly bike counts, ~15–19 Stuttgart sites since 2013 | Stuttgart (bikes) | dl-de/by-2.0 | `mobidata-bw.de/dataset/eco-counter-fahrradzahler` → `v2/fahrradzaehler_stundenwerten_{yyyymm}.csv.gz` |
| MATSim Stuttgart v2.0 10 % plans | ~150k persons with activity chains (home/work/leisure/shopping/errands/business/educ_*), times, EPSG:25832 coords, modes; no demographics | Region Stuttgart | CC BY 4.0 | `svn.vsp.tu-berlin.de/.../stuttgart-v2.0-10pct/input/matsim-stuttgart-v2.0-10pct.plans.xml.gz` (422 MB); facilities.xml.gz 39 MB |
| City of Vancouver ArcGIS GDH traffic services | ~2,600 intersection turning-movement studies 2011–2024 (5-min, **pedestrian crosswalk counts**); midblock hourly; 1,173 tube segments; 55 permanent stations | Vancouver | OGL-Vancouver | `maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer` (xlsx attachments); `MidblockCrossSectionCounts`, `Short_Term_Directional_Segment_Counts`, `TCSPermanentCounts` |
| BC Child Care Map; BC K-12 schools | 553 Vancouver childcare points with hours flags; 171 schools with capacity | BC | OGL-BC | BC Data Catalogue CSVs |
| OSM opening_hours | Mount Pleasant 54 % of shops/food have hours; Stuttgart-Mitte 71 % | both | ODbL | Overpass (use `overpass.kumi.systems` mirror when main is rate-limited) |
| Eurostat HETUS 2020 (tus_20startime, tus_20loc) | participation by 10-min slot × activity, location, DE | Germany | CC BY 4.0 | `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tus_20startime?geo=DE` |
| Destatis ZVE 2022 Statistischer Bericht (xlsx) | mean minutes by activity × sex/age/HH type, weekday/weekend | Germany | dl-de/by-2.0 | destatis download |
| ATUS 2023 (fallback) | 153k episodes with where codes | US | public domain | bls.gov geo-blocks DE; use web.archive.org id_ mirror |
| MiT 2023 (BASt) | MiD 2023 cross-tabs via JSON API, xlsx export | Germany / BW | open | `POST mobilitaet-in-tabellen-2023.bast.de/Tables?action=login {"password":""}` |
| GTFS: NVBW BW-wide (56 MB, 61k stops), VVS feed (113 MB), TransLink (16 MB, no key) | schedules | both | open | see files |
| ActivitySim prototype_mtc configs | tour scheduling alternatives and coefficients | US, parametric | BSD-3 | github ActivitySim |
| Restricted/weak | ZVE 2022 PUF (FDZ registration, 10-min slots with location); MiD 2017/2023 microdata (Mobilithek registration); TransLink trip diary (request); hystreet (API token, plans from €700/yr; free page has monthly totals for 6 Stuttgart sites); no pedestrian counts on Stuttgart open data; Eco-Counter Vancouver API closed |

Popular-times proxies: none open. Foursquare OS has no visit signal; OSM/Overture timestamps are edit dates; Mapillary timestamps are a weak day/night proxy.

## Minimal activity-model inputs
Vancouver: TUS 2022 episodes (chains by age/sex/employment) → trip diary headline aggregates + TSPR station-hour boardings for calibration → anchors: childcare, schools, community centres, licences as workplaces/destinations, OSM hours → TransLink GTFS → validate with GDH intersection pedestrian counts and midblock profiles.
Stuttgart: MATSim plans resampled per Stadtbezirk + HETUS/ZVE time-of-day curves (ZVE PUF if demographic conditioning needed) → MiD 2017 Stuttgart tables → OSM anchors + Stadtbezirk workplace totals + MATSim facilities → NVBW/VVS GTFS → validate with Eco-Counter hourly bikes and hystreet monthly totals.
