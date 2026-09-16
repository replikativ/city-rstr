# HTTP API

Two read-only services, both bound to 127.0.0.1.  The explorer builds its
requests in `city.ui.catalog/requests` and, for a static export, maps each to a
file with `city.ui.catalog/static-path`.

## Evidence store, port 8090 (`city.web`)

| request | payload |
|---|---|
| `/api/areas?city=stuttgart&level=stadtbezirk\|stadtteil` | GeoJSON polygons with `eid`, `name`, `code`, `counts`, `population` |
| `/api/cells?city=stuttgart` | GeoJSON points of the 100 m cells with `eid`, `population`, `rent`, `area-eid`, `area-name` |
| `/api/points?kind=<kind>&area=<eid>[&year=<year>]` | observed records of one kind in one area |
| `/api/summary?area=<eid>` | counts and categories of the observed records in an area |
| `/api/entity/<eid>` | one entity with its source receipts |
| `/api/firms?area=<eid>&year=<year>` | resolved firms in an area |

## Simulation, port 8092 (`city.sim.serve`)

Every request except `/sim/layers` takes `area=<run-key>`; the Stuttgart run's
key is `stuttgart`.  `bbox=west,south,east,north` filters the point and leg
layers to a viewport.

| request | payload |
|---|---|
| `/sim/layers` | published run keys and layer names |
| `/sim/meta` | the run's seed, configuration, resolved kernels, person and firm counts, publication time |
| `/sim/visits[&bbox]` | GeoJSON venues with daily visits and 24 hourly counts |
| `/sim/revenue[&bbox]` | GeoJSON retail venues with visits and annual revenue per demand class, from the economic day |
| `/sim/trips&stride=<n>[&bbox]` | legs with `pid`, `purpose`, `mode`, `path`, `timestamps`; at most 20,000, thinned uniformly; a stride the run was not traced at is answered with the nearest traced stride |
| `/sim/stops[&bbox]` | GeoJSON transit stops with routes, departures and headway |
| `/sim/areas` | per-Stadtteil aggregates and the origin–destination matrix of the traced legs |
| `/sim/econ` | the economic scorecard: every registered quantity against its published target |
| `/sim/scenarios` | the policy scenarios published with the run: `key`, `label`, `question` |
| `/sim/scenario&scenario=<key>` | one scenario: particles and priors, calibration against observed turnover, district and venue deltas with 5/50/95 % quantiles, expected distance per class, and the paired money day's visit changes |
| `/sim/firms[&bbox]`, `/sim/series` | the firm snapshot and the monthly firm series of runs that carry one; the Stuttgart run carries none |
