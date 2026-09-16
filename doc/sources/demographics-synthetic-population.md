# Demographics and synthetic population inputs

## Canada / Vancouver (CMA 933, CSD 5915022)
| Source | Geography | Variables | Access |
|---|---|---|---|
| 2021 Census Profile bulk: `…/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=006_BC_CB` (BC DAs, 300 MB), GEONO=007 (CTs), 025 (BC CSDs) | DA, CT, CSD | ~2,600 characteristics: age×sex, household size/type, dwelling type, tenure, income deciles, labour status, NAICS, NOC, commute mode/duration/place of work | Open (downloaded: `data/raw/statcan/census2021_profile_BC_DA.csv.zip`). Random rounding to 0/5; DA suppression <40 |
| 2021 Census PUMF individuals `…/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip`; hierarchical (households→persons) `…/cen21_hier_98M0001X_rec21_hier.zip` | province + CMA (933) | 2.7% / 1% samples, ~130 vars | Open (hierarchical downloaded) |
| Boundary files `…/2021/geo/sip-pis/boundary-limites/files-fichiers/lda_000b21a_e.zip` (DA), `lct_000b21a_e.zip` (CT), `ldb_000b21a_e.zip` (DB) | DB/DA/CT | geometry + DGUID | Open (DA downloaded) |
| Commuting flows 98-10-0460-01 (CMA × mode × duration), 98-10-0459-01 (CSD→CSD) `https://www150.statcan.gc.ca/n1/tbl/csv/98100460-eng.zip` | CSD/CMA OD | flows | Open |
| Labour Force Survey PUMF (monthly CSV) | province + large CMAs | NAICS, NOC, hours, wage, tenure | Open |
| Canadian Business Counts (33-10-xxxx) | CSD/FSA | establishments by NAICS × size | Open |
| synpopCanada (Prédhumeau & Manley) github.com/maprdhm/synpopCanada, Zenodo 10.5281/zenodo.7572117 | DA, all Canada | persons + households | CC-BY — benchmark |
| Metro Vancouver Open Data (ArcGIS Hub) | region | Landuse 2016 (parcel), industrial/office inventories, urban centres | OGL |
| Restricted: Metro Vancouver Trip Diary microdata (TransLink agreement); BC Assessment (named users) | | | |

## Germany / Stuttgart (Gemeinde 08111000)
| Source | Geography | Variables | Access |
|---|---|---|---|
| Zensus 2022 Gitterdaten `https://www.destatis.de/static/DE/zensus/gitterdaten/<file>.zip` | 100 m / 1 km / 10 km INSPIRE grid (ETRS89-LAEA) | population, age (5/10-yr), nationality, marital status, household size/type, family type, dwellings by building type/size/rooms/area/year/ownership, owner rate, vacancy, mean Nettokaltmiete | Open, dl-de/by-2.0; cell-key noise at 100 m (downloaded: Bevoelkerungszahl, Alter_5er, Haushaltsgroesse, Nettokaltmiete, Gebaeude_Baujahr) |
| Zensus 2022 Regionaltabellen (xlsx) + Zensusdatenbank API (registration) | Gemeinde | age×sex, households, education, Erwerbsstatus × Wirtschaftszweig | Open / Reg |
| Zensus 2011 Gitterdaten (100 m, has age × sex) | 100 m | long format Merkmal;Auspraegung;Anzahl | Open |
| opendata.stuttgart.de: Einwohner nach Altersgruppen/Stadtbezirken, Privathaushalte, Familien, SvB am Wohnort, Unternehmen & SvB am Arbeitsort, Wohngebäude/Wohnungen, Wanderungen (Stadtteile) | 23 Stadtbezirke, some Stadtteile | | CC-BY 4.0 |
| Kleinräumige Gliederung `https://www.stuttgart.de/medien/ibs/OpenData-KLGL-Generalsisiert.zip` (gpkg) | Stadtbezirk/Stadtteil/Stadtviertel boundaries | | Open (downloaded) |
| Bundesagentur für Arbeit Gemeindedaten SvB (`statistik.arbeitsagentur.de/Statistikdaten/Detail/<yyyymm>/iiia6/beschaeftigung-sozbe-gemband/…`), Pendlerverflechtungen, Pendleratlas | Gemeinde, Kreis | employment by WZ, commuter OD | Open, attribution |
| Regionalstatistik.de (12411, 13111, 31231), Statistik BW GENESIS | Gemeinde/Kreis | | Open tables; API registration |
| Mikrozensus CAMPUS file (teaching) / Scientific Use File (FDZ contract) | Land / Regierungsbezirk | joint microdata seed | Reg / Restricted |
| MiD 2017/2023 (BASt MobilityData-Campus) | RegioStaR / Gemeinde in B2/B3 | trip diaries | Restricted (research application); aggregates open via MiT |
| MATSim Stuttgart v2.0 (VSP) `svn.vsp.tu-berlin.de/repos/public-svn/matsim/scenarios/countries/de/stuttgart/` | region | 10% plans, facilities, network, transit | CC-BY 4.0 |
| eqasim-bavaria / synpp (github.com/eqasim-org) | pipeline template | Zensus grid + Regionalstatistik + BA commuters + MiD → persons/households/activities | Open |

## Working no-login recipes found 2026-09-11 (Stuttgart)
| What | URL | Gives |
|---|---|---|
| Zensus 2022 Regionaltabellen (Gemeinde) | `https://www.destatis.de/static/DE/zensus/gitterdaten/Regionaltabelle_<Bildung_Erwerbstaetigkeit\|Demografie\|Bevoelkerung\|Gebaeude_Wohnungen>.xlsx` (the directory itself 404s; the files do not) | Erwerbsstatus, Erwerbstätige × Alter (15–19/20–29/…/60–67/68+) × Geschlecht, × ISCO, × WZ; Schulform/Klassenstufe; Bevölkerung × Alter (11 bands) × Geschlecht × Staatsangehörigkeit × Familienstand. **No age × sex cross at Gemeinde level in any of them.** |
| Regionalstatistik 12411-04-02-4 | `…/genesis/online?operation=download&code=12411-04-02-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2022` | Bevölkerung × Geschlecht × **single year of age** (79), Kreis, Fortschreibung — the age-specific sex ratio |
| Regionalstatistik 13111-01-03-4 | same pattern | SvB am Arbeitsort × Geschlecht × Nationalität, Kreis, 2020–2025 |
| **BA Gemeindedaten** | `https://statistik.arbeitsagentur.de/Statistikdaten/Detail/<yyyymm>/iiia6/beschaeftigung-sozbe-gemband/gemband-dlk-0-<yyyymm>-xlsx.xlsx` (202306, 202406 as xlsx; 202206 only as `-zip.zip`, contents `.xlsb`) | per Gemeinde: SvB am Wohnort/Arbeitsort, Wohnort=Arbeitsort, **Ein- und Auspendler**, Betriebe. Stuttgart 30.06.2024: 267,688 / 442,289 / 165,914 / 276,247 / 101,756 / 17,336 |
| Not reachable | `beschaeftigung-sozbe-krpend` (Pendlerverflechtungen) under every `<region>`/`<format>` pattern tried; the site's Einzelheftsuche renders its result list client-side. Zensus 2011 100 m grid (`csv_Bevoelkerung_100m_Gitter.zip`) 303→400 at zensus2011.de and 404 at the destatis gitterdaten path | |

## Recommended synthesis
Vancouver: DA marginals (age×sex, HH size/type, dwelling, tenure, income, labour, NAICS, NOC, commute) + CT controls; seed = hierarchical PUMF for CMA 933; workplaces from commuting flows + Business Counts + land use; validate against synpopCanada and LFS.
Stuttgart: Zensus 2022 100 m marginals with 1 km totals + Stadtbezirk tables + Gemeinde joint tables (age×sex×Erwerbsstatus); seed from Mikrozensus SUF if accessible, else IPF/Gibbs from joint tables with 2011 grid sex ratios; workplaces from BA Pendler + SvB by WZ; travel from MiD or MATSim plans. Reuse the eqasim/synpp structure.
