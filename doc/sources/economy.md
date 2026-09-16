# Economic-layer sources (probe report 2026-09-12)

Verified by fetching. Everything below is free and needs no registration unless
said otherwise. The ranking at the end is against the first two scored targets:
median household income by small area, and total retail sales by category.

## The find: Stuttgart publishes a retail census by district

**Einzelhandels- und Zentrenkonzept 2024, Teil 2** (Stadt Stuttgart, 12.5 MB
PDF): `https://www.stuttgart.de/medien/ibs/einzelhandels-_und_zentrenkonzept_2024_-_teil_2_stadtbezirke_komprimiert.pdf`

Per **Stadtbezirk** and per **16 goods groups**, from a full 2021 establishment
census: number of shops, **Verkaufsfläche in m²**, turnover in € million,
local purchasing power in € million, and **Zentralität** — the ratio of the two.

Stuttgart-Mitte, food alone: 215 shops, 28,100 m², €237.5 M turnover against
€73.8 M of local purchasing power, **Zentralität 3.22**.

Three things at once, and each is something the model currently lacks:

1. **Measured retail floor area by district and goods group** — the size
   variable the destination kernel needs, and an independent check on the
   OpenStreetMap footprint route (`doc/sources/README.md`).
2. **Retail turnover by small area** — the second scored target of
   `doc/history/economy.md`, at a finer geography than Vancouver can manage.
3. **Zentralität is a direct measurement of the thing the model fails at.** A
   ratio above one means a district's shops sell more than its own residents
   can buy, so the surplus is drawn from outside. Stuttgart-Mitte at 3.22 says
   the centre draws three times its own purchasing power. Our destination model
   sends nobody there. That is now a calibration target rather than an anecdote
   about a pedestrian sensor.

It is a PDF, so it costs parsing. It is worth it.

### Parsed, and it validates against our own population

Extracted 2026-09-12 to `data/derived/stuttgart_retail_districts.json`: retail
floor area, floor area per inhabitant and retail centrality for all **23
Stadtbezirke**. The PDF names districts inconsistently, so names were assigned
by document order and then **checked by implied population** — floor area
divided by floor area per inhabitant — against our synthesized residents:

| check | result |
|---|---|
| districts | 23 of 23 matched |
| worst population disagreement | **4.7 %** |
| total retail floor area | 774,650 m² |
| implied city figure | 1.27 m²/inhabitant against the document's stated 1.29 |

Two validations fall out of one parse. The name assignment is right, and **our
population synthesis agrees with an independent retail study district by
district to within 5 %**, which is a check we did not previously have at this
geography.

### How the parse was checked

The centrality is stated only in prose, never in a labelled table row, so it
cannot be read off positionally. Each district states it once just after its
floor-area box and usually a second time in the narrative. Both mentions were
extracted and compared:

| | districts |
|---|---|
| stated twice, both mentions agreeing | 20 |
| stated once | 2 (West, Degerloch) |
| **stated twice and disagreeing** | **1 (Nord)** |

Nord's first mention is 0.41 and describes "der Standort"; the second says
plainly *"Die Zentralität des Stadtbezirks ist mit 0,29 niedrig"*. The
explicitly district-scoped figure is taken, **0.29**, and the row carries
`confirmed false` so the disagreement travels with the data. Mitte's second
number, 36.11, is a *centre* rather than the district and is not used.

This mattered: an earlier pass of the same parse silently assigned Nord 0.41,
Degerloch nothing, and Hedelfingen's value to the wrong row, because it searched
a fixed window rather than the district's own section.

### The centrality target

| district | centrality |
|---|---|
| **Mitte** | **10.54** |
| Wangen | 1.36 |
| Feuerbach | 1.20 |
| Untertürkheim | 0.83 |
| Bad Cannstatt | 0.72 |
| … | … |
| Süd | 0.34 |
| Nord | 0.29 |
| Plieningen | 0.28 |
| Birkach | 0.17 |

Only **3 of 22** districts sell more than their own residents can buy. The
centre sells **ten and a half times** its residents' purchasing power, on
13.13 m² of shop floor per inhabitant against a city average of 1.29.

This is the destination model's proper target, and it is far better than the
pedestrian sensor it replaces: 22 observations rather than one, at district
geography, measured by an establishment census rather than a camera whose
location is unpublished, and it measures draw rather than passing footfall.

### How the two size sources compose

The measured floor area is a **district total**; building footprints give the
**within-district shape**. Neither alone is enough — the census cannot tell a
department store from the shop next door, and a footprint cannot know what
share of the building is shop. Use the footprint for relative size inside a
district and rake to the measured district total, which is the same layering
the population synthesis already uses: shape from one source, level from
another.

## Corrections to `doc/history/economy.md`

- **Retail sales for Vancouver: use 20-10-0056**, monthly, `Vancouver CMA` as a
  geography member, 30 NAICS categories, 2017–2026:
  `https://www150.statcan.gc.ca/n1/tbl/csv/20100056-eng.zip`. June 2026
  Vancouver CMA total $5,046,932k, food and beverage retailers $863,190k,
  clothing and accessories $477,808k. Restaurants are a separate survey
  (21-10-0019) and are **British Columbia only, no metropolitan area**.
  The table the design implied, 20-10-0008, **went inactive in December 2022**.
- **Commercial rent: my claim that it is unpublished was right for Canada and
  wrong for Germany.** Canada has only a price *index* (18-10-0255). Stuttgart's
  chamber of commerce publishes actual levels: office by sub-city area
  (Stadtkreis €15.47/m² net, City €23.38, Vaihingen €14.86, Bad Cannstatt
  €12.56, series 2017–2026) and **retail by location quality** — city centre
  prime €25.80–187.50 with a mean of €90.10, secondary €47.10, other €17.30.
- **Residential rent for Stuttgart is already on disk.** The Zensus 2022 100 m
  grid file we hold carries average net rent per square metre:
  **9,914 Stuttgart cells, median €9.82/m²**. That dominates the Mietspiegel
  spatially, which is a PDF of a three-step additive formula. Take the
  Mietspiegel's *Methodenbericht* later for rent formation, since it publishes
  the full regression including the sitting-tenant discount (−0.81 at 6–11
  years, −1.54 at 11–21).
- **Stuttgart's vacancy rate exists**, which the landlord loop needs and which
  I had only for Vancouver: Zensus `Regionaltabelle_Gebaeude_Wohnungen.xlsx`,
  Gemeinde 08111 — rent €10.39/m², **vacancy 3.46 %**, owner rate 31.15 %,
  mean dwelling 79.76 m², plus a ten-band rent distribution.
- **Vancouver rent is finer than CMHC in data we already hold**: census
  characteristic 1495, average monthly shelter cost for rented dwellings, is
  populated at dissemination-area level. CMHC's survey zones (City of Vancouver
  is zones 1–10, October 2025 average $1,914–$2,385) remain the source for
  **vacancy and turnover**, which the census does not carry.

## Income, which is target 1

- Vancouver: census characteristics already on disk (see `doc/history/economy.md`).
- **Stuttgart now has a counterpart**, which it did not before: the city
  publishes taxable income per Stadtbezirk
  (`opendata.stuttgart.de`, `steuerpflichtiges-einkommen`, CC BY 4.0), and the
  labour agency publishes **median earnings on a 1 km grid** by place of
  residence — 196 Stuttgart cells covering 253,660 employees, median of cell
  medians €5,000. Kreis-level disposable income is €31,390 per inhabitant
  (2023, regionalstatistik `82000-07-01-4`).
- Median gross earnings by sector, Stuttgart 2025, place of work: overall
  €5,550.70 over 290,786 employees; manufacturing €7,513.70, finance €6,843.20,
  **retail €4,411.40**, hospitality €2,852.30. By requirement level: helper
  €3,250.60, skilled €4,790.50, specialist €6,218.60, expert €7,154.70.
  Annual spreadsheet, free, no key, at `statistik.arbeitsagentur.de`.

## Baskets

- Canada: Survey of Household Spending, table **11-10-0222** by category and
  **11-10-0223** crossed with income quintile, both with British Columbia;
  363 category members in a 7-deep hierarchy reconstructible from the metadata
  file in the same zip. The public microdata file is genuinely free and
  immediate, but its only geography is the province. **Vancouver as a geography
  does not exist after 2009.**
- Germany: no household consumption exists below Bundesland, stated by both
  statistical offices as a sample-design property. The scientific use file is
  closed to a non-academic project by statute, not by price. Use the 2-digit
  classification by Bundesland (about 80 line items, Baden-Württemberg as a
  column) and adjust for urbanity with the European survey's
  degree-of-urbanisation table, which is the same method the Canadian side uses
  with its "population centre over 1,000,000" row.

## Inter-industry flows

- Canada: supply-and-use tables by province including British Columbia
  (36-10-0438 summary, 36-10-0478 detail), national symmetric tables to 2024.
  Industries are a Statistics Canada classification, not plain NAICS, and **no
  maintained concordance file exists** — longest-prefix matching resolves 222
  of 231 business codes and the remaining nine need a hand table.
  **BC Stats publishes regional multipliers for Greater Vancouver**: 221
  industries with output, gross domestic product, jobs, average income,
  location quotient and import leakage, free.
- Germany: national tables only, 72 industries by 72 product groups, published
  as spreadsheets with a tidy long-format sheet inside each workbook.
  **No German regional input-output table has ever existed**, confirmed from the
  state office's own methodological article. Regionalising it is ours to do, and
  the district-level anchor is only about thirteen sectors deep with no
  manufacturing split.

## Budgets

Vancouver: operating budget spreadsheets exist for 2019–2024 only and stop
there; 2025 and 2026 are PDF. The better structured route is the provincial
local-government statistics series, one row per municipality per year,
schedules 401 revenue and 402 expenses, 2005–2024. Vancouver 2024 revenue
$3,164,278,000 against expenses $2,303,644,000.

Stuttgart: PDF only, a 960-page adopted double budget for 2026–2027. It is not
on any open-data portal and the dataset that looks like it is a citizen survey
about spending priorities. The extractable part is the product-oriented
cross-section: 2026 total net resource requirement −€743,583 thousand, of which
childcare −€410,094 and personnel −€1,088,571.
