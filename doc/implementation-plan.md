# One city simulator and explorer

The release target is a single Clojure/Raster simulation interface and a single ClojureScript map application. A city supplies versioned geography, controls, observations and choices of model components. The first two acceptance datasets are Stuttgart and Vancouver including UBC, North Vancouver and West Vancouver. A small data-only fixture exercises the engine independently of either producer.

```mermaid
flowchart LR
  A[Archived sources and checksums] --> B[Versioned city release]
  B --> D[Datahike run and evidence library]
  D --> P[Prepare selected inputs once]
  B --> P
  P --> S[Schedules and choices]
  S --> R[Routing and event intervals]
  R --> O[Occupancy, trips, visits and spend]
  O --> V[Validation and paired scenarios]
  O --> U[Shared map and resident inspector]
  V --> U
```

## Implementation and acceptance

1. **Storage and computation.** Preserve complete release manifests in the browser Datahike library, including model-specific parameters and artifact IDs. Backfill existing indexed releases when their manifests are available. Materialize selected data as ordinary values and dense arrays before a simulation phase starts. Large city shards can be decoded during preparation. A kernel takes numeric inputs and a backend. Selecting, seeking, stepping and comparing a prepared day must remain possible after the database connection closes. Verify with a real memory database, retries, a second release, and a small data-only city.
2. **Reusable producers.** Make release selection, schedule preparation and presence evaluation independently callable. Preserve both historical producers while migrating population, household and work anchors, whole-day diaries, household coordination and destination/mode choice into shared components. Each component declares required inputs and produced columns. Stable resident and cohort IDs, clock origin, units, currency, jurisdiction, seed and service date belong to the run. Preserve source-specific fitting methods and separate Stuttgart's exact retail expectation from sampled shopping trips. Compare minute-area counts, resolved stops, leg order, visits and money against pinned runs at each migration.
3. **Regional science.** Reconcile the current regional roster with the corrected municipal census areas before combining their behaviours. Report resident, incoming, outgoing and campus cohorts separately. Fit household and neighbourhood controls, then score Downtown flows by hour, direction and mode, including transit transfers, bridge counts, cycling and walk access. Record geography, date, denominator, uncertainty and fit or held-out role for each marginal. Evaluate East Hastings store visits and diversion separately from Stuttgart district turnover. See [sources](../public/sources/weekday.json), [marginals](marginals.md) and [Vancouver validation](vancouver.md).
4. **One explorer.** Move both entry pages onto a shared CLJS map owner, clock, scene layer registry, pick/follow, overlays, scenario controls and evidence panel. Preserve old query strings, saved experiments and article links. Gate each layer on release capabilities. Validate street trajectories, selection identity, camera and time across city changes. Offer sampling and coarser visual steps independently of the number simulated. Stage faithful street geometry and interactive movement after the overview and scenario contracts work.
5. **Execution and publication.** Compare Raster JVM and GPU on identical prepared arrays for the full day, measure preparation, kernel, memory and rendering separately, then evaluate coarse-grained alternatives. Retain seed pairing across interventions. Use Spindel for inference over requested outputs. Package both cities and the transitive dependencies of pinned scenarios, test a clean preview under /city/, document source and validation gaps, and keep historical links reproducible before publishing.

The shared numerical products are minute-by-area resident presence, hourly trip ends and paired origin–destination counts. Routing, diary generation and intervention estimation still use city-specific producers. The regional Vancouver roster and the municipal combined shopping/commuting release are separate published inputs. The shared clock and replay controls are in place. The default explorer now owns one map for both cities. The historical Stuttgart page remains available. The retired Vancouver workbench is preserved at revision `ebaecc1`. Merged regional behaviour and device-level parity for the remaining model phases are still pending.

## Implemented path

After this two-city implementation is complete, revisit the [deferred freight implementation plan and source inventory](sources/urban-freight.md).

The browser run library installs each complete pinned manifest in Datahike. Older run entities gain their manifest on the next catalogue load. The library preserves artifact checksums, model parameters and scenario outcomes. A pinned Vancouver replay resolves its manifest at startup and uses the returned values throughout playback. Bulk geometry, roster and schedule shards retain their release-specific URLs.

On the JVM, `city.weekday/prepare` resolves the producer from `resources/city/datasets.edn`, consumes all schedule batches and returns packed integer arrays. `city.weekday/execute` consumes these arrays and permits repeated evaluations after releasing the source database. Holding all packed batches costs more preparation memory than streaming a single pass. The resident-presence product checks population conservation at each minute, plus exact source-matrix equality where the release supplies a reference. The optional trip-end product counts transitions into and out of the travelling state by hour and area. The hours start at the release's day origin. Outside and unresolved areas retain distinct columns where supplied.

```clojure
(require '[city.experiment :as experiment] '[city.weekday :as weekday])
;; At the REPL, db is a Datahike value with an indexed published manifest.
(def manifest (experiment/release-manifest db "vancouver" release-id))
(def prepared (weekday/prepare manifest))
(def counts (weekday/execute prepared :jvm #{:presence :trip-ends}))
```

The JVM products describe resident diaries. Vancouver reads the atlas and base day named in the manifest. Additional joint-day, commuter and route overlays need their own phase migration. Stuttgart generates a day from its local source archive and posterior. Its packaged scenario results remain pinned to the published export.

The first end-to-end checks covered 610,444 Stuttgart residents over 155 area/state columns, and 867,776 regional Vancouver residents over 1,440 minutes. The regional test reproduced the archived presence matrix. A third data-only city exercised two releases after deleting its database. The common entry point, `explorer.html`, owns the MapLibre map and its area, road and moving-person layers. Switching cities keeps the local clock and loads geography, trace samples and available scenarios from the selected release. The same inspector displays neighbourhood totals, between-area flows and scenario-specific units. Stuttgart retail outcomes use district geography and posterior intervals. Vancouver remote work uses minute-level neighbourhood differences, and municipal East Hastings openings use daily visits by residence. Use the archived Vancouver workbench and its corresponding data for earlier street experiments.

Each release ships a checksummed, portable pack of weighted resident schedules. Use `city.weekday/prepare-release` to rerun the numerical products without generating either city again. The pack preserves area itineraries and weights. Individual identities and paths come from the separate routed sample. Hourly OD cells pair the departure and arrival on each completed journey and exclude journeys with an unknown endpoint from the displayed between-area totals.

For a local release build, run `npm run release`, then `npm run preview:bundle` with the data in `public/data`. Each bundle contains a SHA-256 inventory. Serve it with `python3 -m scripts.preview_local --directory dist/city-previews/current`. Run `python3 -m scripts.preview_sources --check --archive ../Simulations/city` to check the cited source files.

### Downtown diagnostic

On municipal base day `309376fc6e41dadaa98a` the shared trip-end calculation gives 11,102 arrivals and 15,246 departures at Downtown stops between 08:00 and 09:00. On regional day `803724fb5af012e0a0c7` it gives 6,468 and 13,011. During 17:00–18:00 the regional counts are 11,070 arrivals and 5,920 departures. These are all-purpose trip ends for roster residents. Within-Downtown trips can contribute both ends. A Downtown cordon comparison needs origin–destination pairing, external commuters, network crossing times and observed directional counts by mode. Keep the base-day result available when evaluating those additions.

### Regional roster reconciliation

A comparison of the archived regional atlas `f03720031a3d2801b7fc`, the corrected municipal atlas `59b3bcac4137ca1483c9` and the regional census boundary extract identifies 320 campus and North Shore areas containing 205,513 residents. They have no dissemination-area IDs in common with the corrected municipality. The regional core omits 59150891 (526 residents) and 59153586 (1,105) and includes 59150952 (677), 59154012 (593) and 59154013 (376) outside the corrected municipal scope. Within the shared municipal areas the aggregate population difference is zero. Combining the corrected municipal and regional-extension scopes gives 867,761 residents in 1,336 areas. Preserve the historical roster for saved runs. For the successor release, declare the coverage of adjacent jurisdictions explicitly and fit each observed marginal to its stated geography.

### Device execution

On the Intel Arc OpenCL device, regional Vancouver presence matched both the JVM and the archived matrix in every area and minute. The producer supplied 1,334 nonempty census-area batches. Combining identical area schedules across shard boundaries with a limit of 8,192 distinct paths per batch yielded 41 packed batches. One local run took 30.0 seconds to prepare, 9.8 seconds for JVM presence and 36.0 seconds for OpenCL presence. These are wall-clock observations during concurrent work, including first-use costs. The numerical reduction is exact for area counts. Money, routes, household decisions and resident identity require their own contracts. The current GPU path creates a device session for each packed batch. Reusing a compiled session and device buffers is a concrete next performance experiment within city-rstr.

The candidate regional atlas is now `375f36b370354124860a` and its generated day is `f520bb4a06394d06b11e`. They contain 867,761 residents and 389,140 occupied private dwellings. The shared engine reproduced the candidate’s full 1,440-by-28 reference matrix and counted 1,659,539 arrivals at modeled area/state destinations. Construction copies the original regional-extension and corrected municipal roster shards, verifies compatible schemas and diary templates, and records both inputs in the coverage metadata. To reproduce both artifacts from the repository root:

```sh
python3 -m scripts.vancouver_region ../Simulations/city \
  --rebase-atlas f03720031a3d2801b7fc 59b3bcac4137ca1483c9 --candidate-day
```

The candidate's held-out income, usual commute and housing comparisons are in `public/data/vancouver/region/atlas/validation-375f36b370354124860a.json`. Among the 1,327 areas with comparable usual-commute counts, the synthetic roster assigns cycling to 6,457 of 325,541 classified commuters (1.98%). The census records 12,580 of 298,155 (4.22%). These are usual commute modes, with different modeled and observed commuter totals. They give the mode-choice migration a measurable discrepancy to address before changing the default regional release.

The generated Stuttgart weekday also matched between JVM and Intel Arc OpenCL across all 1,440 minutes and 155 area/state columns (610,444 residents, 51 packed batches). Its hourly trip-end reduction counted 1,342,416 arrivals.

### Full-population movement display

The shared map reads one position history per person in roster order, independently of the weighted area kernel. Stuttgart includes residents and modelled inbound commuters. Vancouver includes the published resident roster and, on the municipal combined release, its 58,826 attending inbound workers. The position file records the starting anchor and changes of stop at local simulation minutes. In the combined release, incoming home anchors use the published home-fit moves and their day uses the cohort’s commute and shift durations. The shared resident counts continue to use the base day selected by the run.

The numeric limit samples across the entire roster in a deterministic order. **Show all agents** submits one GPU instance per agent. The full-population frame updates by minute. Where a published route is available the frame places its agent on the path. Other travellers hold their last reached stop until arrival. Dots at the same modelled place overlap. **Routed journeys** offers subminute movement, paths, selection and follow for the published sample. District connections link areas and are weighted by paired hourly journeys. Stuttgart’s surrounding municipality boundaries use the BKG VG250-EW extract joined to the 2024 inbound register by AGS. The boundary layer reports the published employment count for each matched municipality.

The default shared map is monochrome. The optional presence overlay measures residents currently present in each area. The density overlay divides the same count by the polygon area in km², excluding interior holes. The two use separate scales. Journey trails cover the six simulated minutes preceding the clock and finish at the moving marker. They appear in the routed sample and on the identifiable routed subset of the full roster.

The historical Stuttgart export retained thinned street waypoints and whole-minute vertex timestamps. The shared replay rebuilds the intervening geometry on the original undirected OSM graph using distance-weighted A*, skips legs without a connected path, and interpolates subminute time by cumulative street distance between the published departure and arrival. Alternative paths between retained waypoints are possible. Neither this reconstruction nor the original shared street graph enforces mode-specific turn restrictions. A Stuttgart transit trace uses the model’s street-based representation of transit.
