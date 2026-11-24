# A Vancouver weekday

This research log records the experiments, data sources and findings of the
[archived Vancouver workbench](https://github.com/replikativ/city-rstr/tree/ebaecc15f7d583633580b7009137393e4be892d8).
Workbench controls and reproduction commands below refer to that revision.
For the current release see the [regional model](../public/vancouver-methods.html)
and [evidence](../public/vancouver-model.html).


The first market question is how opening a grocery at either of two Mount Pleasant storefronts changes trips and shopping visits. The first executable component models the day that creates those trips. It assigns a resident a complete sequence of activities and estimates the time spent in each activity, by hour, for Vancouver and its 22 local areas. Destination choice, routing, household coordination and store visits are subsequent components.

## Current municipal weekday

The City of Vancouver release covers all 1,016 dissemination areas in census subdivision 5915022. It contains 662,248 residents. Intact donor households account for 649,690 residents in 305,336 occupied private households. The other 12,558 have a roster entry and a schedule, with household membership unresolved. The replay contains 1,271,556 diary travel bouts between 04:00 and the following 04:00. Each minute accounts for every resident across the neighbourhood, travelling and unresolved-location categories. The atlas checks the Census Profile geography index against the independent Geographic Attribute File. The daily schedule and the market scenario use the same roster. [Population footprint](http://127.0.0.1:8187/population.html?boundary=1) · [Weekday](http://127.0.0.1:8187/cityday.html)

The earlier release included three Musqueam 2 areas and omitted two municipal areas. The corrected release adds 526 residents in Dunbar-Southlands and 1,105 in the West End. Both now have residential coordinates and inspectable diaries. Stored shop experiments keep their original population and day. For the 08:00–20:00 East Hastings opening with survey bicycle access, historical grocery shares and local grocery walking, the corrected day yields 305 visits, of which 121 divert from existing grocers. Its predecessor yields 306. These are scenario outputs. [Reopen the earlier market](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&marketRun=70240246d263c349137a6b570dcef51595eba25c4284119fbff4298e31a40dde) · [Current opening](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&grocery=bc2010&localWalk=1)

Earlier experiments and counts below describe the releases on which they were run. The held-out 2021 usual commuting comparison on the corrected roster puts 65.1% of modelled commuters in the driver category and 2.0% on bicycles. The corresponding census shares are 50.8% and 5.3%. Those differences describe the usual mode recorded for employed residents. At Ontario Street and 5th Avenue, the municipal baseline routes 26 bicycle passages over the 12 surveyed hours, compared with 3,021 observed. The neighbourhood commute-mode fit yields 42. The simulated counts here cover city residents, whereas the counter includes riders from any origin. [Inspect the held-out comparison](http://127.0.0.1:8187/population.html?check=commute)

## Reference population and clock

The baseline uses the City of Vancouver geography and 2021 census age composition. A dissemination area belongs to the local area assigned in the archived extraction. People aged 15 and over have diary evidence. The baseline uses the sum of rounded census age cells as its denominator. The diary survey samples people living in private households. Applying its schedules to the full census age counts transfers behaviour to residents of collective dwellings as well. A Mount Pleasant result describes its residents wherever they spend the day. A count at a Mount Pleasant intersection observes people from any origin.

The behavioural reference is an urban BC weekday in the 2022 Canadian Time Use Survey. A diary runs from 04:00 local time through 04:00 the following morning. Each primary episode has a start minute, duration, activity and location category. The donor sequence preserves the timing of work, studying, eating, shopping, household tasks, care, socialising, exercise, leisure, civic activity, travel and sleep. Unclassified minutes retain an unknown category. Simultaneous secondary activities and the schedules of other family members would need additional evidence.

## Executable activity model

For each of seven age bands, draw one intact training diary with probability proportional to its person survey weight. The REPL entry point is `city.vancouver.weekday/draw-weekday`; the caller supplies the age band and a seeded random generator. For area totals the scorecard computes the exact expectation of that draw. For activity *k* and clock hour *h* it reports

```text
minutes(area, k, h) = sum over age bands a of
    (residents(area, a) / residents(area, 15+))
    × sum over diaries d in a of
        (person weight(d) / total person weight(a)) × minutes(d, k, h)
```

To inspect a seeded day in the REPL, load the diaries and draw from an age band.

```clojure
(require '[city.vancouver.weekday :as van] '[city.synth.timeuse :as tu])
(def pools (van/split-diaries (tu/load-diaries :project-root "../Simulations/city")))
(van/draw-weekday pools :a35-44 (java.util.Random. 42))
```

The hourly vectors start at midnight. An episode spanning an hour boundary contributes its overlap to both hours. Every complete diary accounts for 1,440 minutes, including 60 in each clock hour. The baseline can be calculated before any random draw or route search. Drawing an individual day and inspecting a citywide expectation use the same distribution.

### Running and reading the scorecard

Pass a project root containing the archive layout described in [the data inventory](../DATA.md). The first argument is optional when the inputs are under this checkout's `data/`. The command emits aggregate JSON to standard output.

```sh
clojure -M -m city.vancouver.weekday ../Simulations/city > /tmp/vancouver-weekday.json
```

| Evidence | Geography, period and unit | Role |
|---|---|---|
| Census Profile age characteristics 14–23 and 25–29 in `data/derived/vancouver_da_marginals.jsonl` | 2021 Vancouver dissemination area, rounded residents by age | Population weights for the baseline and its comparison |
| TUS main and episode public-use files and their Stata layouts in `data/raw/statcan/timeuse/` | 2022 BC weekday respondents aged 15+, larger urban population centres; primary minutes per person-day | Whole-diary donor pool, using `WGHT_PER` once per respondent |
| Withheld TUS respondents | Same survey domain, reweighted to the same local age counts | Check transfer between respondent samples. A Vancouver-specific validation requires independent local observations. |
| TransLink Regional Trip Diary | Metro Vancouver, fall 2023, trips by purpose, origin, destination and mode | Future mobility targets after matching age range, geography and linked-trip definitions. [TransLink survey](https://www.translink.ca/plans-and-projects/data-and-information/research-and-insights/trip-diary-survey) |
| Archived weekday pedestrian studies in `data/derived/vancouver_ped_counts_mp.json` | 15 Mount Pleasant intersections, 2021–2024, crossings by surveyed interval | The replay includes four workbook-verified comparisons. Recover coverage and zero-count intervals from each workbook and reserve entire sites for evaluation. |
| Storefront inventory and business licences | Vancouver address, use category, survey or licence year | Candidate store locations and competition on a specified baseline date. Verify door location, trading status and hours for the pilot sites. [Storefront inventory](https://opendata.vancouver.ca/explore/dataset/storefronts-inventory/map/) |
| Merchant observations | Entries or transactions per storefront and trading interval | Future retail validation. Record whether a measure counts customers, door crossings or receipts. |

Within each age band, the scorecard sorts respondent IDs, shuffles with a fixed seed, and holds out every fifth respondent beginning with the first. Both pools use their own survey weights. Each activity has fitted and held-out minutes per resident-day and 24 hourly values for each. The error is fitted minus held-out minutes. The age-blind comparator uses the same training people and survey weights, pooling all ages. Effective sample size is the squared sum of weights divided by the sum of squared weights. It describes weight concentration. The single split supplies no sampling interval.

With the archived inputs, the scorecard includes 1,017 dissemination areas, of which 47 are assigned to Mount Pleasant. The rounded age-band sums for residents aged 15+ are 591,085 citywide and 33,565 in Mount Pleasant. The donor split is 889 training diaries and 228 held out. Only eight of the held-out diaries are from people aged 15–24. Neighbourhood differences in this baseline come entirely from age composition.

## Which shopping episodes can lead to a grocery visit?

The reader keeps `ACTIVITY=0260` as primary shopping and uses the detailed activity `TUI_01` to distinguish in-person goods (0261), in-person services (0262), online shopping (0263), purchase research (0264), and unspecified shopping (0269 or missing detail). For the grocery scenario, the candidate pool requires both in-person goods and `LOCATION=3306`, the survey category for a grocery, other store or mall. In-person goods reported elsewhere or with unknown location have a separate count. Travel to a shop and accompanying someone there are distinct diary activities.

`city.vancouver.shopping/candidate-episodes` selects the eligible episodes from a drawn weekday and retains their start time and duration. Each eligible episode counts once even if it spans two hours. One person can report multiple episodes, and members of a shopping party can report the same outing. Converting these person-episodes into grocery visits requires a grocery share and a rule for shared outings.

The 1,117 urban BC weekday diaries contain 380 primary shopping episodes, of which 282 satisfy the activity and location criteria, before weighting. Mount Pleasant estimates use all resident-days aged 15+, including days with no shopping. They describe its residents shopping anywhere.

| Mount Pleasant estimate | All shopping episodes per 100 resident weekdays | In-person goods at a store per 100 resident weekdays |
|---|---:|---:|
| Age-only model | 24.9 | 19.6 |
| Held-out BC diaries with the same local age mix | 29.6 | 23.2 |
| Age and household model with Vancouver metro household shares | 26.0 | 20.7 |

The scorecard gives episodes and minutes per resident weekday for all six categories in each area's `shopping-per-resident-weekday` and under `household-model.projected-shopping-per-resident-weekday`. The category minutes sum to the model's primary shopping time. The detailed goods code includes groceries, gasoline, clothing and other goods. It leaves the grocery share unresolved.

## From an activity diary to a shop opening

1. **Fix a dated world.** Give synthetic households a home and budget, workers and students an anchor, and each store a location, category and hours. Establish the vintage of each input. Draw workers and visitors entering the corridor from regional origins. Record unplaced destinations and trips whose endpoints fall outside the routing graph. Check that a route requested for an external origin actually begins there or at its declared entry boundary. The early implementation demonstrates why that check matters. [Routing diagnosis](simulator.md#the-three-rules-and-their-parameters)
2. **Choose a shopping occasion.** Use the activity and location together. Shopping time can include online purchases, services and product research. Even an in-person purchase of goods needs a category before it can become a grocery visit. For shopping with a household member, the unit of demand is the household shopping party. Represent a shared purchase once. Initially keep the occasion, previous activity and next fixed commitment the same in all scenarios.
3. **Choose a feasible store.** For a person travelling from A to their next commitment B, compute the extra minutes for visiting store j as `travel(A,j) + dwell(j) + travel(j,B) − travel(A,B)`, using the mode and departure times of each leg. Require an open store, enough time and an affordable basket. Allow delaying the errand or shopping outside the corridor. A first comparator selects the feasible store with the lowest extra travel time. A probabilistic alternative weights feasible choices by store attractiveness and extra minutes. Estimate those effects only as local evidence permits.
4. **Compare paired days.** Baseline, site A and site B share households, diaries, demand, random choices and competing stores. Each intervention opens one specified store with its own hours and entrance. Report changed visits by hour and origin, displaced visits at competitors, deferred errands and the distribution of extra minutes. State assumptions for the new store's appeal and vary them. Monetary estimates additionally need basket values and a household spending budget.
5. **Publish the trip behind the result.** Give a shopping occasion and its resulting journey stable synthetic IDs across the three runs. The shop count, 2D playback and eventual street view can then refer to the same changed trip. A citywide aggregate and a sampled street scene should reconcile at their declared sampling weights.

## Evidence for richer behaviour

The household extension tests whether knowing that someone lives with a child under 15 improves their predicted daily activity. Ages 0–14 can be identified in both sources. In the TUS, `CHH0004C` and `CHH0514C` identify members of the household in these age ranges. A positive flag establishes presence. Two zero flags establish absence. Other combinations without a positive flag have unknown status. The childcare outcome measures minutes of **primary care for household members aged 17 or younger**. Household membership alone gives no information about school pickup duties.

For each age band and known household status, the model mixes the matching training diaries with the original age-only pool. The matching pool receives probability `effective-n / (effective-n + 5)`. Five is a fixed modelling choice. Each pool draws whole diaries by person survey weight. An empty matching pool, or an unknown household status, uses the full age band. In the REPL, `(van/draw-weekday pools :a35-44 true (java.util.Random. 42))` draws a day conditional on a child under 15 in the home.

The scorecard evaluates the conditional mean on the original 228 held-out urban BC respondents. Each prediction uses just that respondent's age and household flag. The loss is the square root of the person-weighted mean squared difference from their recorded activity minutes. This comparison is exploratory because the childcare discrepancy in the original split motivated the extension. The household model has 60 matching training donors aged 35–44 with a child under 15 and zero aged 75+ with a child under 15.

| Primary activity | Age-only error (min/day) | Age and household error (min/day) |
|---|---:|---:|
| Household childcare | 73.7 | 66.4 |
| Paid work | 217.1 | 215.7 |
| Travel | 67.8 | 68.4 |
| Shopping | 50.4 | 50.2 |

For geographic projections, the 2021 hierarchical census public-use file links household members by `HH_ID`. The reader selects Vancouver CMA (933), checks the roster for ages 0–14 and sums individual `WEIGHT` for residents aged 15+ by their own age band and household status. A roster with a masked age and no identifiable child has unknown status. The scorecard reports its eligible person weight separately where present and estimates the share living with children among known statuses. The input is `data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv` under the project root. Without that file the survey comparison still runs and the geographic household projection is omitted.

Each local area's census age counts are combined with the **same metro-wide household shares within each age band**. Under that transfer, expected primary childcare in Mount Pleasant is 43.9 minutes per resident aged 15+ per weekday, compared with 51.6 under age alone. This is a model estimate. The hourly and daily projections appear under `household-model.projected-minutes-per-resident-weekday`. The next spatial test needs local person counts jointly classified by age and presence of a child or an independent local time-use measurement. Assigning coordinated school, work and pickup trips additionally needs linked household schedules.

An engine experiment becomes meaningful once both shop placements can run at full corridor detail. Group more distant origins, keep the same activity and choice rules, and measure runtime and the change in the difference between the two sites. Check visits, minutes and the site ranking alongside conservation of population and spending.

## Mount Pleasant walking replay

The seeded route export reuses the age-only training diary sampler. Within each census dissemination area and age band it draws one person per 12 residents within 2.6 km of Ontario and 10th and one per 90 elsewhere, rounding sample sizes up. Each synthetic person carries their stratum population divided by its sample size. These weights apply before selection for walking or passing a site. The household-conditioned scorecard remains a separate experiment.

Homes use census-area centroids. For a walk, the provisional destination lies in a uniformly sampled direction, 60 metres per recorded minute from the preceding stop. For other arrivals, a directly following return walk can constrain the distance from home. Otherwise a 0.4–5 km uniform displacement from home supplies the prior. The closest matching Overture venue supplies a destination where the diary location has a venue class. Homes and repeated workplaces stay fixed. The model routes between nearby nodes of the largest connected pedestrian-permitted OSM network using node IDs and distance-weighted A*. It interpolates progress by distance over diary time. Transit transfers, ambiguous endpoints, same-node trips and walks faster than 2.5 m/s are omitted. Site geocoding, inferred destinations, omitted trips and mixed input vintages all affect this comparison.

The 476 walkers retained in this run have 907 routed legs available for inspection. Each person's itinerary includes their other routed walks elsewhere in the city. Of the walkers, 283 live in Mount Pleasant and 193 elsewhere in Vancouver. The model uses City of Vancouver resident origins. Travel by residents of other Metro Vancouver municipalities is still missing.

At Ontario and 10th the July 12, 2023 workbook confirms three contiguous survey periods from 07:00 to 19:00. Its four pedestrian columns contain 144 complete five-minute rows. A model passing is the closest interior point of a routed walk within 22 m of the geocoded site, with both endpoints outside the buffer. The model records at most one passing per leg. The 12 sampled passings in the survey window expand to 237, including about 84 from neighbourhood residents. The survey recorded 2,021 crossings. The observed count played no role in destination choice or weighting. Sampling variability and the difference between a passing and a counted crossing limit interpretation of the gap. [City survey workbook](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/9997/attachments/11177)

### The same weekday at four intersections

The same simulated routes and weights are scored at each site before cropping the replay to the neighbourhood. The exporter reads the count periods from each workbook, reconciles the four pedestrian columns against the archived total and keeps all five-minute intervals inside those periods, including measured zeros. Alberta and 12th has a seven-hour break between its two counts.

| Site and workbook | Survey date | Hours observed | Observed crossings | Weighted model passings | Sampled walks |
|---|---|---|---:|---:|---:|
| [Ontario & 10th](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/9997/attachments/11177) | July 12, 2023 | 07–19 | 2,021 | 237 | 12 |
| [Ontario & 5th](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/10002/attachments/11182) | July 12, 2023 | 07–19 | 3,273 | 118 | 11 |
| [Ontario & 1st](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/9998/attachments/11178) | August 9, 2023 | 07–19 | 4,363 | 278 | 24 |
| [Alberta & 12th](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/418/10613/attachments/11793) | October 30, 2024 | 07–09 and 16–18 | 108 | 69 | 6 |

On July 12 the City measured 565 crossings in the noon hour at Ontario and 5th, compared with 163 at Ontario and 10th. The model puts one sampled passing at each, giving about 11 and 12 respectively. At 17:00 the observed ordering narrows to 301 and 267, and the model again has one sampled passing at each. This run misses both the daily volumes and the local contrast at lunch. With only 6–24 sampled walks per site over the full windows, repeated simulated weekdays would help separate sampling variability from systematic differences before fitting destination or travel-mode effects.

### How sensitive is the lunchtime comparison to the simulated weekday?

The repeat experiment fixes the model, census strata, sample sizes, training diaries, road network and survey windows. Each of 12 seeds (2023–2034) redraws a diary for each synthetic resident and the directions and distances used to place destinations. Both Ontario Street sites use the same draw each time. The comparison is the weighted passings at 5th minus those at 10th between 12:00 inclusive and 13:00 exclusive. The two July 12 observations give a difference of 402 crossings.

Seed 2023 supplies the animated replay. For the other seeds the exporter can skip pathfinding when the distance from each endpoint to a survey centre, added together, exceeds the maximum walkable distance in the recorded time plus two buffer radii. Such a route could never both enter that buffer and pass the replay's speed check. This filter runs after destination selection. The resulting hourly counts retain the original survey windows, including measured hours with zero sampled passings.

| July 12, noon–13:00 | Observed crossings | Mean modelled passings | Model range across 12 seeds |
|---|---:|---:|---:|
| Ontario & 5th | 565 | 8.1 | 0 to 22.9 |
| Ontario & 10th | 163 | 23.8 | 0 to 97.6 |
| 5th minus 10th, paired by seed | +402 | −15.8 | −97.6 to +10.0 |

Two seeds put more lunchtime passings at 5th, nine put more at 10th, and one tied at zero. Across the full survey windows, the three Ontario Street counts each exceed every simulated run. At Alberta and 12th, the observed 108 lies inside the seeded range of 22–186. Seed 2023 reproduces the earlier single replay. A separate full routing run for seed 2024 reproduced all 40 hourly estimates from the faster survey-only calculation.

The ranges in the explorer describe variation across these draws under a fixed model. Real weekday variation, uncertainty about the survey, and uncertainty about destination or mode-choice rules would each require additional evidence.

## Two-site grocery pilot

**Decision and geography.** The intervention opens the same hypothetical grocery at either A, 1731 Manitoba St (storefront ID 37), or B, 68 W Broadway (ID 6070). Both were listed as vacant in the 2025 municipal inventory. Each scenario uses the geocoded storefront snapped to the pedestrian network. A recent vacancy observation, approximate street entrance and an illustrative shop design are sufficient for this experiment. Site availability, permissions, prices, rent and commercial viability require separate evidence. [City storefront inventory](https://opendata.vancouver.ca/explore/dataset/storefronts-inventory/)

**Demand and competition.** The experiment retains an in-person goods episode in a store only when the immediately preceding and following diary episodes are walks and the stops on both sides have locations. At least one of the two fixed stops must lie within 1,200 m (straight line) of either candidate under either tested workplace rule. This gives baseline, A and B the same pool across all five profiles for a given seed. A census-weighted person-occasion contributes 0.4 times its weight as expected grocery demand. The 40% grocery share is an explicit assumption. Multiplying it uniformly changes totals proportionately. Differences in that share by age, neighbourhood or trip purpose could change the ranking. The observational unit is an individual walking occasion, including trips that start outside Mount Pleasant. Spending, shopping parties, induced demand and purchases reached by other modes are outside this calculation.

Each existing alternative is a distinct address with an issued, geocoded 2025 City licence in the Grocery Store class. The broader competition profile also admits Retail Dealer - Food addresses. The exporter reads all 22 local-area extracts, selects the latest revision per licence within each area, deduplicates stores by street address and searches citywide. General food retailers can include shops with a narrower assortment. Store hours are assumed. [City business licences](https://opendata.vancouver.ca/explore/dataset/business-licences/)

**Paired choice.** Hold the episode's departure, shopping duration, next stop, next commitment and walking speed (80 m/min) fixed. Compute shortest pedestrian-network distances to the store and on to the next stop. Both walks together get at most 45 minutes and must fit into the recorded travel allowance. Early arrivals can wait for opening. Shopping must finish by closing, and walking onward must finish by the next commitment. Baseline chooses the feasible incumbent with earliest completion, or defers when there is none. The intervention adds one store. Ties favour the incumbent. The standard hours are 08:00–20:00. Each sensitivity changes one assumption: a 3-minute choice advantage for the entrant, entrant hours of 10:00–18:00, broader competitors, or licensed workplace locations. The choice advantage changes the ranking after feasibility checks. It confers no extra travel time.

**Accounting and inspection.** New-shop visits equal visits diverted from an incumbent plus previously deferred visits made feasible. Reachable occasions include those still choosing an incumbent. For diversions, the model reports the displaced address and change in walking minutes. Origin, age band and arrival-hour totals describe expected visitors. Examples retain the seed, synthetic person and diary episode, both routes, and the next commitment. The replay shows one changed occasion at a time. The sidebar aggregates across the seeded weekdays.

**Movement experiment.** Compare the original workplace placement with an alternative that chooses among geocoded, issued 2025 licences within 500 m of the provisional employment destination, weighting locations by positive reported employee counts. The original business placement supplies a fallback where there are no reported jobs nearby. All subsequent destination draws use the same random numbers. Licence counts represent positions reported at business addresses and can miss public institutions, remote work and actual attendance. The trace follows the subset of synthetic people with a walking diary. It counts known stationary locations within 400 m at 11:30, paid work there, subsequent departures on foot before 13:00, and arrivals at stores or restaurants on those departures. The overlapping circles are evaluated separately.

The reserved observations are the 08:00–09:00 and 16:00–17:00 workbook rows at Fraser & Broadway (May 4, 2023) and Prince Edward & Broadway (April 5, 2023). They were excluded from the four-site diagnostic and from fitting either rule. The exporter verifies date, site, hourly spacing and four pedestrian columns, then reconciles the selected rows with the archive. Each model predicts the same two hours at each site. The passings proxy and partial walking population are the same as in the earlier checks. [Fraser and Prince Edward survey archive](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer)

### Pilot result

Across seeds 2023–2034 the standard rule has 593.8 expected grocery occasions per simulated weekday in the defined catchment. Existing stores can accommodate 392.4, leaving 201.4 deferred. These numbers are the model's weighted walking subset. The 2025 licence extract supplies 73 geocoded grocery addresses citywide, expanding to 664 under the broader retail definition.

| Assumption | A visits | B visits | A leads (of 12 seeds) |
|---|---:|---:|---:|
| Shortest feasible trip | 57.1 | 19.3 | 11 |
| Employee-weighted workplaces | 53.8 | 14.9 | 12 |
| Entrant favoured by 3 minutes | 76.9 | 27.8 | 12 |
| Entrant open 10:00–18:00 | 7.5 | 4.5 | 10 |
| Include other food retailers | 52.7 | 6.7 | 12 |

**A attracts more modelled visits under all five assumptions. B creates more access under the standard rule.** All 57.1 visits at A come from existing stores. At B, about 15.8 are diverted and 3.4 were previously deferred. The paired standard-rule difference ranges from −2.5 to +72.2 visits across seeds. The choice of outcome matters for interpreting the site comparison. Neither store-entry counts nor transactions validate the visitor estimates. The archived movement checks below give further reason to withhold a real-world site recommendation.

**Lunchtime diagnosis.** In the walking-diary population, the employee-weighted placement raises the mean number doing paid work at 11:30 within 400 m of Ontario and 5th from 140 to 245. Immediate standalone departures on foot to a store or restaurant before 13:00 average 2.8 with original placement and 1.8 with the alternative, across all known starting activities in that catchment. Noon passings stay at 8.1 against 565 observed crossings. Around Ontario and 10th, paid work rises from 130 to 163 and noon passings stay at 23.8 against 163. Changing where work occurs does little for the locally generated midday walks in these diaries. This diagnoses the model's mechanism. The field counts alone cannot identify what share of real crossings came from workers, through-trips or transit users.

| Reserved site and hour | Observed crossings | Original passings | Job-weighted passings |
|---|---:|---:|---:|
| Fraser & Broadway, 08–09 | 229 | 19.6 | 22.3 |
| Fraser & Broadway, 16–17 | 449 | 11.4 | 16.1 |
| Prince Edward & Broadway, 08–09 | 156 | 31.2 | 26.6 |
| Prince Edward & Broadway, 16–17 | 403 | 28.6 | 16.1 |

The workplace alternative slightly reduces both errors at Fraser and increases both at Prince Edward. It remains a sensitivity in the shop pilot. Absolute local demand remains uncertain under either placement.

## Citywide population atlas

The atlas has one synthetic record per 2021 City of Vancouver resident. Its hard geographic controls are Census Profile characteristics 1 (resident count) and 5 (private dwellings occupied by usual residents), applied separately to every dissemination area. The City local-area polygons group the census areas into 22 neighbourhoods. A location on this map is a home area. The weekday display counts what its residents are doing wherever the activity takes place.

**Reconciliation.** The early roster had 670,883 person rows. Downtown DA 59154026 alone contained 8,032 against 58 census residents. The early IPU implementation began all seed-household weights at one, skipped zero-target constraints and lacked a hard resident-total constraint during integerization. This area reports two occupied private dwellings but zero after census rounding in the private-household size and person tables. Also, the old roster's size code 5 means five or more. A roster of six with that code is internally consistent.

The atlas prioritizes the unrounded resident and occupied-dwelling counts. It clips the rounded private-household person target (56) to the feasible interval from one person per occupied dwelling up to the total population and the supported donor household sizes. It allocates the reconciled private total to intact households. Other residents receive individual identities and an unresolved household status. This residual includes effects of rounding and differing census universes as well as residents outside private households. The data do not identify their living arrangement. The Downtown example now has 58 residents, two one-member synthetic households and 56 unresolved household memberships.

**Household fit.** The 2021 hierarchical Census PUMF supplies intact Vancouver metropolitan household rosters (CMA 933). The household prior uses the weight on the first roster member. Start with census private-household size frequencies, expand the 5+ bin using the weighted donor tail, then transfer counts between adjacent sizes until both hard totals match. Within each required size, fit donor probabilities with exponential calibration, bounded coefficients and a quadratic penalty. The controls use broad age groups, tenure, private-household gender composition, labour status and personal income bands. Long-form shares use published denominators. Where available, the 100% private-household adult count defines the adult target for labour and income. Size-specific systematic resampling draws integer households. Residual residents draw age bands from positive area-level age deficits; other economic and household attributes remain unavailable. Missing income stays distinct from zero income.

Employment rates and the share earning at least $100,000 by gender use joint counts excluded from calibration. The employment check informed a revision to include the directly observed private-household gender margin. The income-by-gender comparison was added before scoring that revision. These are internal checks against other census cells. Geographic reporting aggregates comparable numerators and denominators over areas with published, positive reference denominators. The UI exposes large dissemination-area discrepancies and their denominators. Individual attributes and especially fine local joint distributions remain uncertain.

**A synthetic day.** Each resident references a continuous chain of activity and location categories covering minutes 240 through 1680. Adult schedules are intact draws from the 889 urban BC weekday training diaries, weighted by their survey weights. Match on age band and, when possible, worker, student or nonworker role, with age-only fallback for unsupported cells. An unresolved household implies age-only assignment where role is unavailable. For masked ages with adult fields the fallback uses a role-conditioned pool across ages. Children aged 10–14 use an illustrative school-day chain. In the 0–9 band the local share aged 5–9 sets the probability of the school-day template versus home care. A masked age with child-only evidence uses the local share aged 5–14 among children. School timing is assumed. Household members do not yet coordinate pickups or shopping, and activity/location categories do not identify particular buildings, street paths, or vehicles. The Mount Pleasant grocery experiment retains its separately validated sampling design.

**Data contract.** The generator writes a content-addressed directory under `public/data/vancouver/atlas/` and atomically switches `current.json` after completion. In that directory `atlas.json` contains metric names, coverage, boundaries, DA and neighbourhood totals, the episode library and per-geography template frequencies. Each DA roster is fetched separately. Entries in `homes` are [zero-based first person, roster length, tenure code]. Entries in `people` follow the `fields` array in the manifest, with labour encoded as 0 unknown/outside universe, 1 employed, 2 unemployed, 3 outside the labour force. Other census codes follow the hierarchical PUMF codebook; income is in 2020 Canadian dollars or null. The final person field indexes the episode library. Household members occupy contiguous slots, followed by residents with unresolved household membership. IDs combine the DA with H or P and the one-based slot. Pin the version to use the same identity across scenario runs. New model versions can change the synthetic person occupying a slot.

**Audit of the previous municipal release.** Every one of the 1,017 dissemination areas matches its headline resident and occupied-dwelling counts. The resulting 662,263 residents include 649,706 members of 305,026 private households and 12,557 residents with unresolved membership. The working-day assignment has 593,257 people with survey-derived schedules and 69,006 with illustrative school or home-care schedules. Household, economic and day-plan assignments are synthetic. Exact geographic counts establish an accounting identity and do not validate the individual schedules.

| Cross-tab excluded from fitting | Model, city | Census, city | Largest neighbourhood gap |
|---|---:|---:|---|
| Employed share, women+ | 57.8% | 58.9% | 3.6 pp, Strathcona |
| Employed share, men+ | 65.5% | 65.1% | 3.8 pp, Strathcona |
| 2020 individual income at least $100k, women+ | 9.3% | 10.5% | 2.6 pp, South Cambie |
| 2020 individual income at least $100k, men+ | 17.9% | 17.4% | 2.0 pp, South Cambie |

The percentages use the eligible private-household population aged 15+ in each published universe. Sampled household correlations, rounded census cells, differing long-form denominators and integer household selection can produce appreciably larger errors at DA level. “Largest held-out differences” lets the reader inspect those cells and their counts.


**Coastal map.** The atlas dissolves the archived 2021 *cartographic* census dissemination-area polygons across the visible Lower Mainland and simplifies the resulting land outline at 10 metres in EPSG:3347. The City local-area polygons are clipped to that land for rendering and hit-testing. The northern shore, Point Grey, Stanley Park, Richmond and other land outside the coloured neighbourhoods give geographic context. Major roads and bridges come from the archived Vancouver OpenStreetMap highway extract. Land, water, roads and neighbourhood fills use a common projection. The shoreline layer is independent of the population roster and requires no tile service.

### Citywide spatial weekday

The overview draws sampled travellers with a resolved street or scheduled route. Walk, bike, motor travel and matched transit use separate colours. **Show trip trails** draws the recent path behind the dot. Click a traveller to inspect the same route. The displayed count gives the share of the moving sample with a mapped position. The population totals still cover every resident and include journeys whose position is unresolved. The worker prepares paths off the UI thread and the ClojureScript timeline also used in Stuttgart clips the trails at the playback clock.

Driving A* uses travel time on the directed streets. The speed profile reads mapped directional and general speed limits from the archived roadways, with defaults by road class where those are missing. A legal faster road can therefore beat a shorter local street. The geometry must fit the diary's travel allowance, including both endpoint connections. The overview and resident follower use the same driving calculation. The trip readout shows the model's drive time and the diary allowance, and playback spaces vertices according to their estimated time along the path while preserving the diary's start and end. The standard replay uses free-flow speeds. The regional bridge panel also offers measured Highway 1 travel times and preserves the selected metric when following a counted crossing.

The regional weekday provides a check against the distance-based approach used in Stuttgart. For one 08:00 synthetic drive from the North Shore, both searches use the same directed street graph and endpoints. The fastest free-flow route uses the Trans-Canada Highway and Ironworkers, covering 33.95 km in 29.42 modeled minutes. The shortest route goes via the Stanley Park Causeway, West Georgia and Kingsway, covering 32.47 km in 38.08 minutes under the same speed assumptions. The diary allows 30 minutes. [Follow the synthetic driver](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&da=59150012&person=305&minute=492&follow=1)

```sh
node scripts/vancouver_corridor_check.mjs public/data/vancouver/region 7d51ae012e0578f94822 --compare-distance 59150012 305 480
```

#### Observed travel times on Vancouver streets

**Evidence → Observed driving times** shows the 24-hour profiles and lets the same weekday run with the observations. It covers West Georgia between Seymour and West Pender, Granville between West Broadway and West 16th, and approximately West 57th to Southwest Marine Drive on Granville. The report blends 40 weekdays of 2015 GPS observations. The builder digitizes the three curves from the published figure to the nearest km/h, treats chart hour 1 as 00:00–01:00, and applies the single curve shown for each reach to both permitted directions. At 08:00, traversing West Georgia between the two cuts takes 4.2 minutes using the measured speed of about 19 km/h, versus 1.6 minutes at free flow. Granville between Broadway and 16th takes about 1.7 minutes versus 0.9. [CAA and CPCS report, figures 13–14](https://www.caa.ca/app/uploads/2021/01/16170_Canadian_National_Bottlenecks_Study_EN_1_4_17.pdf#page=23)

Each recorded driver leg uses the conditions for its departure hour. On the matched directed edges, the router scales time by the ratio of estimated observed to free-flow minutes, with a minimum of one. The regional replay also includes the separately measured 2022 Highway 1 travel times near Ironworkers. Other streets and the Highway 1 hours outside that study use free flow. Existing scenario legs that were scheduled and published using free-flow costs keep their archived routes. The selected profile affects route choice and feasibility for resident-driver playback. The trip clocks and demand remain fixed, and traffic volumes do not feed back into speeds. The bridge counter panel keeps its own route benchmark and source. [Replay the regional observations](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&roadTraffic=780aaf6b1c7d420aea5c&roadSection=georgia&minute=480#road-traffic)

For the base municipal weekday, the comparison holds each trip in the 6,621-resident animation sample to its original origin, destination and diary budget. Of 1,038 morning driver legs with a feasible free-flow path, 75 used a measured section before rerouting and 64 changed paths. From 16:00 to 18:00, 87 of 1,207 feasible driver legs used those sections and 77 changed paths. All retained feasible routes. Mean modeled delay among these affected legs was about 9 seconds in either period. The small average reflects motorists' ability to divert onto roads that still use free flow. These are model sensitivities to historic inputs. They leave validation against contemporary city street counts and travel times open. [Follow an affected municipal driver](http://127.0.0.1:8187/cityday.html?roadTraffic=bcc29ece6795ac643929&roadSection=georgia&minute=500&da=59150505&person=239&follow=1#road-traffic)

On the 2025 workplace-fit weekday, the 8,683-resident animation sample includes 1,311 feasible morning legs. Of the 163 using measured streets in free flow, 63 reroute and one exceeds its diary budget under the combined profile. In the afternoon 222 of 1,492 feasible legs originally used those streets and 108 reroute. An affected driver with a 20-minute diary window takes 13.5 modeled minutes with the observations, up from 10.7. These samples cover resident legs with complete single-mode driving records. Incoming workers and scheduled scenario trips have separate estimates. [Follow the afternoon driver](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&roadTraffic=780aaf6b1c7d420aea5c&roadSection=georgia&minute=968&da=59150336&person=140&follow=1#road-traffic)

```sh
python -m scripts.vancouver_corridor_times
node scripts/vancouver_overview_routes.mjs public/data/vancouver
node scripts/vancouver_corridor_check.mjs public/data/vancouver
node scripts/vancouver_overview_routes.mjs public/data/vancouver/region 7d51ae012e0578f94822
node scripts/vancouver_corridor_check.mjs public/data/vancouver/region 7d51ae012e0578f94822
```

The location generator pins the atlas version. It assigns each synthetic private household a shared point sampled from unique municipal property coordinates in its dissemination area. Those points include mixed-use and nonresidential parcels. People with unresolved household membership receive an individual area anchor. The generator falls back to a point on the census polygon when an area has no address point. Every DA in this build has at least one address point.

The model groups each diary into stationary stops and intervening bouts of travel. A resident returns to one assigned home, school and workplace throughout the day. The K–12 prior uses nearby provincial school points by education level, splitting the published age bands at school transitions. Older learners use geocoded higher education venues. Workplaces use the employee counts from the 2025 municipal licence archive to choose among candidate places close to a mode- and duration-based target. Other stops use Overture venue classes. These are synthetic city-contained destination choices. The place catalogue mixes census and contemporary data vintages. Regional commuting, household escorting, school capacity, workplace capacity and transit timetables are open calibration tasks.

The day exporter sums interval changes at each minute and checks conservation of the entire roster. Each person occupies one of 22 local areas, a travelling bucket or an unresolved-location bucket. The dot sample is stratified by home DA and carries its inclusion weight. The atlas choropleth continues to count activity by home. The city day instead uses assigned destinations.

The street network retains OSM node connectivity and separate forward/reverse motor and walking access. Entrances use short straight connections to the graph. Walking and driving controls use the same network as the overview. The street scene uses closed OSM building ways in the archived tiles. Explicit heights take precedence over reported levels, then a height prior. Turn restrictions, signals and queues remain open work.

#### Homes by census block

The paired weekday fits synthetic households to the official 2021 count of occupied private dwellings in each dissemination block within their original census area. The solver assigns whole households and places people whose household membership is unresolved as individuals. If the resident and dwelling marginals conflict with the available household sizes, the solver minimizes resident error subject to the exact dwelling totals. Among equally close fits it prefers block household-size mixes near their census area's size mix. This preserves the roster, every household's composition, every diary and all non-home destinations. [Census geographic counts](https://www150.statcan.gc.ca/n1/en/catalogue/92-151-X) · [Census block definitions and boundaries](https://www150.statcan.gc.ca/n1/en/catalogue/92-163-X2021001)

Within each block, the model uses mapped residential building footprints weighted by footprint area and declared floor count. Where no residential footprint is available, it reuses a point from the original placement if that point is within the same block. Blocks without either source use an interior point. Residents whose household is unresolved also use the interior point of their fitted block. The fitted block totals describe agreement with census controls. Building-level occupancy remains synthetic, and missing or incomplete building tags can concentrate assigned homes at the available points.

Open **Evidence → Homes by census block** to compare occupied homes or residents for one census area. A blue block has a shortfall, an orange block an excess, and a green block matches the selected census count. **Replay census-block homes** loads the archived paired day. The comparison keeps the selected resident and clock. A scenario that uses a different day release must be rebuilt against the fitted homes before combining the two.

| Weekday | Households | Occupied blocks with exact household counts | All blocks with exact resident counts | Original households assigned to blocks with zero occupied dwellings |
|---|---:|---:|---:|---:|
| Vancouver | 305,336 | 4,096 of 4,096 | 4,470 of 4,562 | 8,864 |
| Vancouver, UBC and North Shore | 388,830 | 5,377 of 5,377 | 5,938 of 6,049 | 10,008 |

In the fitted regional day, mapped residential footprints receive 297,876 households. Prior address points receive 77,674 and block reference points receive 13,280. One Mount Pleasant block with 979 occupied dwellings had 535 synthetic households in the original replay. The fitted day places 979 there. [Compare that census area](http://127.0.0.1:8187/cityday.html?homeBlock=59154174&minute=300#home-placement) · [Fitted regional weekday](http://127.0.0.1:8187/cityday.html?coverage=region&dayRun=32705d15d4fafaf1cbdca5ddeb30e9dd93a7ab912ca97d60d604078152167458&homeBlock=59154174&minute=300#home-placement)

In the walking grocery scenario, both placements keep the same 4,827 modeled shopping occasions, the same 73 existing grocers and the same 08:00–20:00 hours for the Kingsway storefront. The original placement gives the new store 45 visits, including 29 newly feasible purchases. The fitted placement gives it 40 visits, including 32 newly feasible purchases. Those counts describe sensitivity to home location under the model's walking and store-choice assumptions. [Original Kingsway opening](http://127.0.0.1:8187/cityday.html?dayRun=4f711d78c7e0f40698dd7dd0c10df51d85429318e20d12572de0bebaa5cc88a5&shop=4654&hours=full&minute=600) · [Opening with fitted homes](http://127.0.0.1:8187/cityday.html?dayRun=bf8df2e0ba0f4bb219ea496cb59cc26cd507c0dbf3ea496269182546bbd7dd1b&shop=4654&hours=full&minute=600)

The advance-voting scenario also uses the fitted locations. It estimates 1,552 ballots with City Hall alone and 1,729 with City Hall and four community centres. The original home placement yields 1,551 and 1,754 under the same staffing and opening-hour assumptions. [Advance voting with fitted homes](http://127.0.0.1:8187/cityday.html?dayRun=bf8df2e0ba0f4bb219ea496cb59cc26cd507c0dbf3ea496269182546bbd7dd1b&votingRun=012dc79a801651e81c74&votingLayout=centres&minute=1020)

The builder prints the new municipal and regional day IDs. Pass those IDs to the archive publisher and the replay builders. [Input files](../DATA.md#vancouver-census-block-homes)

```sh
python -m scripts.vancouver_block_homes
clojure -M -m city.run-catalog vancouver-block-homes e4ccbf0b371fead49783
clojure -M -m city.run-catalog region-block-homes 1aaba5e10256b777d594
node scripts/vancouver_overview_routes.mjs public/data/vancouver e4ccbf0b371fead49783
node scripts/vancouver_overview_routes.mjs public/data/vancouver/region 1aaba5e10256b777d594
python -m scripts.vancouver_street_walks --day e4ccbf0b371fead49783
python -m scripts.vancouver_street_walks --region --day 1aaba5e10256b777d594
python -m scripts.vancouver_market ../Simulations/city --day e4ccbf0b371fead49783
```

#### Street terrain

Pitched views show the regional ground surface at natural vertical scale. **Terrain** overrides automatic activation and stores the choice in the URL. The flat overview is the default for reading trip patterns. Both city extents use the same local elevation tiles. [Lynn Valley street view](http://127.0.0.1:8187/cityday.html?coverage=region&place=lynn&street=drive&at=-123.039500,49.337300,35)

The elevation mosaic uses high-resolution NRCan ground heights where available, sampled in Web Mercator at about 10.5 m on the ground at Vancouver's latitude. It fills gaps with the Canadian 30 m model in the same vertical datum, CGVD2013. The two sources together cover every finest-zoom pixel inside the published bounds. The output uses 256-pixel MapLibre DEM tiles at zoom levels 9 to 14. The bare-earth raster supplies the ground and water surface beneath elevated streets. [NRCan HRDEM access guide](https://download-telecharger.services.geo.ca/pub/elevation/dem_mne/HRDEMmosaic_mosaiqueMNEHR/HRDEM_Mosaic_WCS-WMS_instructions_EN.pdf) · [NRCan MRDEM access guide](https://download-telecharger.services.geo.ca/pub/elevation/dem_mne/MRDEM_MNEMR/CanElevation-MRDEM-Usage-Guide.pdf) · [Data and build instructions](../DATA.md#vancouver-terrain)

#### Bridge decks

The street scene fits road-deck elevations on Lions Gate, Ironworkers, Burrard, Granville and Cambie bridges using Natural Resources Canada's surface model. The fitted road profiles reach approximately 67, 63, 32, 41 and 18 metres above the CGVD2013 datum, respectively. The build samples the raster along each mapped way and rejects local outliers. On Burrard it interpolates under the truss from the visible road sections and their grades. Adjacent paths at deck level use the road profile for height. Deck widths, towers, railings and piers are schematic. [NRCan surface data](https://open.canada.ca/data/en/dataset/0fe65119-e96e-4a57-8bfe-9d9245fba06b) · [Lions Gate reconstruction](https://www.tac-atc.ca/wp-content/uploads/Matson.pdf) · [Build instructions](../DATA.md#vancouver-bridge-decks)

The vertical placement uses the person's current routed street edge. Routes along the ground beneath a bridge retain their ground heights. The same fitted deck supports the eye-level player, the raised camera, nearby street bodies, and the followed driver and trip line. Deck elevations are independent of the clock, speed profiles and lane scenarios. **Link to this street** records the deck release while the player is on a modeled bridge. [Drive across Lions Gate](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&decks=b90d91ccc87929d229c6&street=drive&camera=eye&at=-123.139263,49.314678,31&minute=480) · [Cycle across Ironworkers](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&decks=b90d91ccc87929d229c6&street=bike&camera=eye&at=-123.026129,49.295792,-1&minute=480)

### Opening a grocery on the citywide weekday

The full-roster scenario uses the same resident IDs, stationary places and trip windows as the city day. Each alternative opens one shop at a 2025 City storefront recorded as vacant. There are 964 distinct mapped IDs across the 22 local areas. Two source rows for ID 8850 give different addresses for the same point. Both address labels appear on one alternative. The competition set contains 73 distinct addresses with issued, geocoded grocery licences.

The survey detail for in-person goods at a store survives the diary export. A qualifying stop consists of that single goods episode, reached and left entirely on foot, with a located non-store commitment on either side. This restriction makes a rerouted stop independent of the other modelled purchases. A stable draw keyed by resident and stop assigns 40% of qualifying occasions to groceries in expectation. The same realised occasions are evaluated at every site. All competition uses 08:00–20:00 hours. A new shop can also be tested at 10:00–18:00.

The walking graph supplies shortest distances from each retailer to the snapped origin and onward destination, including straight access connectors. Each leg must fit its own diary window at 80 m/min. Together they can take up to 45 minutes. The complete shopping episode must fall in opening hours. Choose the feasible store minimizing walking minutes, retaining the incumbent on ties. A deferred grocery purchase leaves the original generic retail stop in the day. The resident's timeline and other commitments stay fixed when an alternative opens. The reference census and weekday diary remain available in the atlas.

| One simulated weekday | Existing grocers | 1731 Manitoba St | 68 W Broadway |
|---|---:|---:|---:|
| Feasible purchases citywide | 2,063 | 2,066 | 2,064 |
| Visits to the new shop | — | 21 | 16 |
| Diverted from an existing grocer | — | 18 | 15 |
| Newly feasible purchases | — | 3 | 1 |
| Visits if the new shop opens only 10:00–18:00 | — | 4 | 3 |

These values arise from 4,828 grocery occasions drawn from 11,975 qualifying walking occasions among the 662,263 residents. One realised day supplies the citywide experiment. The earlier Mount Pleasant sensitivity study samples multiple weekdays and permits reallocating walking minutes between the two legs. Results depend on those model choices. An optional user-entered basket value multiplies modelled captured visits to give illustrative gross sales. Customer surveys, transactions, operating costs, nonresident visitors, other travel modes and shopping-party aggregation would be needed to infer total demand or business viability.

### Opening the same shop with census workplaces

The city-only and census-workplace runs share the same 662,263 residents, weekday diaries, grocery draw and retailer inventory. The draw selects 4,873 person-occasions. In the census run, 249 touch a paid-work stop outside the municipality whose street address is unknown, and 45 have another missing endpoint. That leaves 4,579 occasions with two located commitments. Of these, 1,930 can reach an incumbent grocer and 2,649 defer the purchase. The city's observed grocery share, store preferences and walking speed have yet to be fitted to shopper data.

| One storefront opened at a time | 1731 Manitoba St | 68 W Broadway | 2541 Kingsway |
|---|---:|---:|---:|
| Visits with city-only workplaces, 08:00–20:00 | 21 | 16 | 45 |
| Visits with census workplaces, 08:00–20:00 | 20 | 15 | 36 |
| Of those, diverted from existing grocers | 17 | 14 | 12 |
| Of those, newly feasible purchases | 3 | 1 | 24 |
| Visits with census workplaces, 10:00–18:00 | 4 | 3 | 13 |

Changing workplace coverage affects the visit count at 680 of the 964 candidate sites. The local workplace rules preserve the adjacent walking commitments in this release, so all five census-workplace rules share one set of retail choices. The exporter checks the actual endpoints when deciding whether a new release can share choices.

The clock counts customers from the start of their shopping episode until they leave. Blue dots show the incoming and outgoing walks for customers of the selected shop, including customers outside the overview's population sample. Both the dot and the individual inspector follow the same walking graph. Opening or closing the shop updates the minute-by-neighbourhood population and Downtown walking crossings for the replayed weekday. Selecting **Existing grocers only** compares the same customers and diary times against the incumbent stores. [Try the Kingsway site at 10:00](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&shop=4654&minute=600)

### Independent city travel check

The City’s fall 2023 transportation panel covers weekday trips by residents aged 18 and older in private dwellings. Compare rates and shares with the synthetic private-household population. A uniform within-band age prior contributes two fifths of the model's 15–19 band to the 18+ estimate. Exclude masked ages and count residents who stayed home in the denominator. For this comparison only, group consecutive travel records into a single bout and apply the City's primary-mode hierarchy. Taxi and ride-hail map to passenger, motorcycle to driver, and unidentified modes remain a separate residual. The time-use survey only records activities at its measurement resolution. Changes of place with no intervening mobile episode do not appear as trips in this check. [City report, Sections 6.1 and 6.3](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The current roster produces 1.98 recorded travel bouts per adult weekday against 3.0 reported by the panel. The age-20+ sensitivity result is 1.96. For ages 45–49, the respective figures are 1.85 and 3.9. Walking accounts for 12.3% of the modelled adult bouts and 28.8% of panel trips. The travel checks remain independent of fitting. These discrepancies affect the sampling frame for the grocery comparison before any storefront choice is made.

The City playback also offers inferred short walks. For a diary change of location without a travel episode, both endpoints must be known and more than 25 m apart. Walking the shortest pedestrian route, including access to the street, must fit within ten minutes at 80 m/min. At least half of each neighbouring stationary episode is retained. Of 312,785 candidate changes, 14,440 pass these checks. With these walks enabled the model yields about 2.00 trips per adult weekday and a 13.3% walking share. The survey gap persists. The travel comparison can switch back to the original diary and replay the same person.

#### Taxi and ride-hail

**Evidence → Taxi and ride-hail** runs a paired mode assignment on the same weekday. The municipal diary model has 1,904 age-weighted primary taxi trips out of 1,108,609 adult trips and zero primary ride-hail trips. The taxi records come from one donor diary. The 2025 City survey puts the combined share at 1.3%, which gives a target of 14,412 trips on the model's trip denominator. The B.C. Passenger Transportation Board reports 565,000 completed taxi trips and 2.8 million completed ride-hail trips in its Lower Mainland and Whistler region in March 2025. Their ratio supplies an approximate service mix for the scenario. Operator reports count completed orders across the region and all days of the month. The City survey counts adult residents' weekday person trips. [City survey, Figure 24](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=51) · [B.C. Passenger Transportation Board, November 2025](https://www.ptboard.bc.ca/data-newsletters/november-2025)

The model keeps original taxi diaries and draws from known-age residents aged 20 and older with a single-mode passenger trip and two resolved endpoints. A deterministic ordering selects candidates, and directed free-flow routing requires a mapped street segment and both address connections within the diary budget. In the municipal run, 12,508 of the first 12,991 candidates pass. Of these, 516 take a taxi and 11,992 use ride-hail. Total trips, trip purposes, activity times and places stay fixed. The fitted 1.30% is a calibration result. Departure timing, neighbourhood differences, income effects and the taxi-versus-ride-hail split have no independent local validation. The regional variant fits only Vancouver residents in the census areas shared with the municipal atlas. Two municipal DAs lack a match in that regional roster.

The overview paints hired rides lavender. Street mode reuses the same roadway model and shows a vehicle for each nearby feasible synthetic hired trip. The baseline still shows the feasible original taxi trips. The scenario models occupied passenger journeys with the diary clock. It leaves pickup waits, empty running, vehicle availability and fares open. [Try the municipal replay](http://127.0.0.1:8187/cityday.html?hiredRides=fit#hired-rides)

```sh
python -m scripts.vancouver_hired_rides
python -m scripts.vancouver_hired_rides --region --day 7d51ae012e0578f94822
```

#### Dispatch and fleet availability

**Evidence → Taxi and ride-hail → What happens with fewer vehicles?** applies two dispatch policies to the same full roster of located hired trips. Each rider requests pickup when their diary trip starts and must reach the original destination by the diary arrival. Riders approach and leave a mapped curb at 80 m/min. The vehicle drives the directed free-flow graph empty to pickup and with the passenger to drop-off. Seeding spreads initial vehicles across candidate pickup locations. Between jobs, each vehicle stays at its last drop-off. A dispatcher can reserve a vehicle before it completes its previous ride. The earliest feasible boarding wins, with less empty driving breaking ties. Requests expire after 15 minutes or at the latest pickup that fits the diary. These conditions distinguish diary windows too short even with a vehicle at the curb from failures to match an available vehicle in time.

The reference divides the busiest hour's potential occupied roadway time by the B.C. region's January–March 2025 occupancy rate and rounds up to a whole fleet. The reduced case removes every fourth vehicle from the same staging locations. Vehicle capacity is fixed throughout the day. Reported all-day occupancy uses every scheduled vehicle-hour. The wait comparison uses vehicle arrival at pickup among served rides. The regional September 2024 medians are 5 minutes 32 seconds for taxis and 4.6 minutes for ride-hail. Both evidence sources cover the Lower Mainland and Whistler. The fare references describe typical 2024 five-kilometre trips. The experiment leaves transaction prices, driver shifts and passenger choices after an unmatched request open. [Occupancy report](https://www.ptboard.bc.ca/data-newsletters/june-2026-newsletter) · [Wait-time report](https://www.ptboard.bc.ca/data-newsletters/march-2025) · [Fare report](https://www.ptboard.bc.ca/data-newsletters/may-2025)

The dispatch decisions include all requests in the fitted hired-ride release. The browser can replay the same request under both fleet sizes, jump to boarding, or switch to an eye-level view near the curb. This overlay uses the original day clock. The rest of the weekday keeps its fitted activities. The link pins the passenger and dispatch releases. [Open the dispatch comparison](http://127.0.0.1:8187/cityday.html?hiredRides=98db64253e37743ef867&dispatchRun=042b07d23c4730666f53#hired-dispatch)

In the municipal comparison, 776 ride-hail vehicles serve 10,403 of 11,992 requests. With 582 vehicles, 10,036 requests are served, and the median wait among served rides rises from 80 to 101 seconds. The reference taxi fleet serves 939 of 2,304 requests. The fixed schedules produce 6.9% all-day ride-hail occupancy and 3.8% taxi occupancy, far below the region's 54% and 39%. The synthetic demand is highly synchronized. Of 2,683 ride-hail calls between 17:00 and 18:00, 1,941 occur at exactly 17:00, and that hour accounts for 1,028 of the reference's 1,521 missed dispatches. The original taxi donor creates other sharp peaks. This comparison measures sensitivity to supply under the published diary clock. Matching observed waits and utilization jointly will require a less synchronized request clock and time-varying fleet availability.

```sh
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver
python -m scripts.vancouver_dispatch
python -m scripts.vancouver_dispatch --region --day 7d51ae012e0578f94822
```

#### Spreading simultaneous departures

**Evidence → Spread simultaneous departures** compares the same residents and activity sequences at different minute-level start times. Statistics Canada collects episode durations in minutes and includes activities as short as five minutes. The comparison assumes a sensitivity window of at most seven minutes on either side for road and active travel starting on five-minute marks, bounded by the original departure hour. It uses one deterministic rank per resident across their eligible trips. Paid work, study, sleep and care windows remain fixed. Road and active travel retain their duration and endpoints. Immediately adjacent flexible activities can absorb a shift if they retain five minutes, and a short wait can separate a trip from a fixed event. The pairing leaves transit legs and illustrative child schedules at their original times. [Statistics Canada’s 2022 diary method](https://www150.statcan.gc.ca/n1/pub/89-652-x/89-652-x2024003-eng.htm)

Among 662,248 municipal residents, 650,795 trips belonging to 343,055 people change minute. The regional workplace-fit run changes 844,598 trips among 443,800 people. Every modeled hourly departure count by mode stays the same. The complete population remains accounted for at every minute, and the street index follows the same retimed trips as the overview and population diary. In the municipal hired-ride cohort, one diary supplies 1,887 of the original 1,941 ride-hail requests at 17:00. The spread clock produces 254 requests at exactly 17:00 and still has 2,683 between 17:00 and 18:00. The clock comparison holds destinations, passenger assignments, fleet size and staging fixed in dispatch. [Replay spread departures](http://127.0.0.1:8187/cityday.html?departureClock=39872889b958b822f512&hiredRides=12031b3dfea5e8562f5e#spread-departures)

The municipal day gains 3.02 minutes of inferred waiting per resident on average. The reallocated time comes mostly from meals, housework and personal care. Daily travel, work, study, child care and sleep durations are identical across the pair. The change tests sensitivity to exact departure times within each hour. The width and distribution of the shifts remain assumptions.

With identical reference fleets, municipal ride-hail completes 10,698 requests instead of 10,403, and taxi completes 1,516 instead of 939. Ride-hail dispatch misses between 17:00 and 18:00 fall from 1,028 to 753. The ride-hail median pickup wait among served trips rises from 80 to 81 seconds, and the 90th percentile rises from 363 to about 419 seconds. Fleet shifts and geographic availability remain open for calibration. [Compare the same fleet under the spread clock](http://127.0.0.1:8187/cityday.html?departureClock=39872889b958b822f512&hiredRides=12031b3dfea5e8562f5e&dispatchRun=56c9e9ff911aa6d8295f#hired-dispatch)

The regional reference fleets complete 9,945 ride-hail requests instead of 9,697 and 1,349 taxi requests instead of 833. The regional ride-hail median among served trips changes from 103 to 102 seconds. The comparison preserves the original demand and capacities. [Compare the regional fleets](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&departureClock=33f20d3ea8c275eeb4f8&hiredRides=5f3a1a617d965e48d7c6&dispatchRun=2dca42367295ade1bdc7#hired-dispatch)

The paired municipal grocery replay keeps 4,827 shopping occasions and their scored storefront choices. Approach or departure times change for 3,884 of those occasions. Posted opening hours still apply to the fixed shopping episode. Opening a shop during play can change a shopper's plan only before they start walking. At 3304 Kingsway, activating at 11:15 yields 37 visits on the original clock and 27 on the spread clock. [Original timing](http://127.0.0.1:8187/cityday.html?marketRun=4614fc4e7623f4a46b7aa5b2d575bbfbdb2b07c8a81c4d5dd78711ec2ced66a5&shop=1387&hours=full&shopPlay=1&opened=675&minute=675#market) · [Spread timing](http://127.0.0.1:8187/cityday.html?marketRun=0c2044fda1bc9e7726a1036cb0a2101edd31ba5d5b98148df80178a2e9fc7790&shop=1387&hours=full&shopPlay=1&opened=675&minute=675#market)

```sh
python -m scripts.vancouver_departure_clock
python -m scripts.vancouver_departure_clock --region --day 7d51ae012e0578f94822
python -m scripts.vancouver_dispatch --clock spread
python -m scripts.vancouver_dispatch --region --day 7d51ae012e0578f94822 --clock spread
```

### Full-roster pedestrian counts at six intersections

The municipal replay compares two versions of the same 662,263-resident weekday against 44 observed intersection-hours. The city-only column uses the recorded modes and city-only places. The census-workplace column uses the external workplace assignments, neighbourhood commute modes and census tract jobs. Both use the original shopping stops. Ontario at 1st, 5th and 10th each have 12 observed hours. Alberta at 12th has four. The two Broadway sites retain the preselected morning and afternoon hours from the earlier pilot. All observations come from the archived City workbooks. Each site in the inspector links to its own count sheet. [Explore the intersection evidence](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&crossing=1&minute=720)

| Intersection and interval | Observed crossings | City-only passings | Census-workplace passings |
|---|---:|---:|---:|
| Ontario & 5th, 12:00–13:00 | 565 | 1 | 1 |
| Ontario & 10th, 12:00–13:00 | 163 | 12 | 12 |
| Ontario & 1st, 12:00–13:00 | 433 | 5 | 6 |
| Alberta & 12th, 16:00–17:00 | 26 | 29 | 27 |
| Fraser & Broadway, 08:00–09:00 | 229 | 9 | 11 |
| Fraser & Broadway, 16:00–17:00 | 449 | 21 | 11 |
| Prince Edward & Broadway, 08:00–09:00 | 156 | 11 | 9 |
| Prince Edward & Broadway, 16:00–17:00 | 403 | 26 | 24 |

The walk must have two known places. The replay router finds a shortest pedestrian path between them, including the connections from the places to the graph. A through-passing occurs when both endpoints lie outside 22 m of the survey location and some interior point of the path lies within 22 m. Distance along the route determines the clock time. Each walk counts at most once per site. The general speed ceiling is the pilot's 150 m/min. Adjusted workplace walks must also fit the commute model's 75 m/min. For each site the inspector reports a stricter 80 m/min comparison and a separate 44 m radius sensitivity. The wider radius can encompass an endpoint and exclude a short local walk under the same through-passing definition.

The independent route check uses SciPy Dijkstra and the pilot's passing-time calculation. It uses the replay's lowest-network-ID rule when several walking nodes are equally close to a place. At one assigned place near Ontario & 1st, two graph nodes have identical coordinates and different connections. Choosing the other node moves several routes from 13.4 m to 78.7 m from the counter. The resulting difference is one passing in each of eight hour-and-model cells at this site. The Ontario & 5th and Broadway results in the table are insensitive to this tie.

At Ontario & 5th, the wider radius still gives one noon passing. Adding inferred short walks to the city-only day raises its noon count to two. The tract assignment increases the number doing paid work within 400 m at 11:30 from 460 to 3,230. In both runs seven of those residents leave that job on foot before 13:00, including one who goes straight to a store or restaurant. More nearby employment alone did little for the supply of simulated lunchtime walks. Work-linked walking and cycling trips retain their original job sites under the tract assignment.

The workbooks count crossings on four approaches on different field days in 2023 and 2024. A resident passing through a circle on one synthetic weekday is an approximation to that measurement. Nonresident workers and visitors are absent from these counts. Selecting a model count opens a synthetic resident on their walking leg.

#### Walking to and from scheduled transit

The city-only comparison can replace a matched diary journey with its pedestrian and vehicle legs. The resident leaves the previous commitment on foot, waits to board if necessary, rides a direct scheduled service, then walks from the alighting stop to the next commitment. A passing uses the same pedestrian graph, survey radius and clock as the individual replay. Among the 18,449 matched journeys, 1,373 had walking as the longest recorded mode. The comparison removes each of those whole-journey walking paths before adding the actual station walks. Inferred short walks between stationary commitments remain a separate option. The census-workplace column retains its own mode and workplace assignments.

Across the 44 intersection-hours, the city-only count rises from 581 to 619 passings. There are 37 passings on the way to stops and 16 after alighting, and the corresponding scheduled rides displace 15 passings previously counted on whole-trip walks. At Ontario & 10th from 07:00 to 08:00 the estimate rises from 22 to 37 against 104 observed crossings. At Ontario & 5th from noon to 13:00 it stays at one against 565 observed. Direct transit access accounts for part of the morning traffic and leaves the lunchtime discrepancy at that site unexplained.

| Surveyed hours | City-only diary | To stops | From stops | Replaced | With matched rides | City count |
|---|---:|---:|---:|---:|---:|---:|
| Ontario & 10th | 202 | 20 | 7 | 7 | 222 | 2,021 |
| Ontario & 5th | 120 | 4 | 0 | 2 | 122 | 3,273 |
| Ontario & 1st | 125 | 8 | 8 | 6 | 135 | 4,363 |
| Alberta & 12th | 67 | 1 | 0 | 0 | 68 | 108 |
| Fraser & Broadway | 30 | 3 | 0 | 0 | 33 | 678 |
| Prince Edward & Broadway | 37 | 1 | 1 | 0 | 39 | 559 |

The original stop matcher and the replay could choose different street nodes at equal distance from a stop or venue. This made 538 of 36,900 walking legs exceed their assigned time or distance in the replay. Both now break ties by the lowest network node ID, using squared distance for the integer map coordinates. Relative to the earlier municipal run, 1,039 matched journeys change only their walking times and 55 change their ride or boarding/alighting positions. Two no longer fit and one newly fits. The pedestrian build checks all 36,898 resulting walking legs, including those outside the survey area and hours. The route index uses the same boarding and alighting times as the replay.

A route selection shows the full cohort of matched city residents currently walking to or from stops for that service. Purple dots are boarding walks, orange dots are alighting walks, and selecting either follows that resident's day. The 99 B-Line illustrates the effect of reusing diaries. At 07:30, 267 synthetic residents start walking to its stops. All are on their way to assigned jobs, and 228 use the same survey diary template. Two other riders are walking from stops at that minute. That spike describes the simulated day. Validating its shape would require departure or boarding observations at a comparable time resolution. The link from an intersection count retains the timetable and pedestrian comparison used to produce it. [Watch the 99 B-Line at 07:30](http://127.0.0.1:8187/cityday.html?service=99&minute=450) · [Compare the intersection counts](http://127.0.0.1:8187/cityday.html?crossing=0&transitWalks=1&walks=diary)

### UBC and the North Shore

The regional view adds 320 census dissemination areas. Its 867,776 synthetic residents include the same 662,263 City residents available in the municipal view. Each has a full weekday and a stable ID. The regional map animates a stratified sample of 8,683. Scrubbing the clock shows population counts computed for the entire roster at each minute.

| Added geography | 2021 usual residents | Dissemination areas |
|---|---:|---:|
| UBC Vancouver campus | 15,103 | 27 |
| City of North Vancouver | 58,120 | 79 |
| District of North Vancouver | 88,168 | 133 |
| West Vancouver | 44,122 | 81 |

Each North Shore municipality reconciles independently to its published population and occupied private dwellings. Separate census subdivisions, including reserves, fall outside those municipal totals. For UBC we select Electoral Area A dissemination areas with at least half their land area inside the legal campus boundary. Every selected area overlaps by at least 89%. This is a residential geography. Commuting students, staff and visitors require separate origin and attendance estimates. Four added DAs have suppressed demographic detail. Three have zero population. The fourth retains its 37 residents and 13 occupied dwellings, with unpublished household and age details recorded as unresolved where necessary.

Campus geometry and building uses come from UBC's inventory. Across the added areas, household placement first uses mapped residential buildings or residential addresses. Where these are unavailable the model can use unclassified building footprints, then a point inside the census area. The published regional day uses unclassified footprints in 18 DAs and the point fallback in 16 DAs home to 6,979 residents. Regional workplace choices give each additional mapped workplace a unit weight. Enrolment, building capacity, employment by site and observed origin–destination flows remain calibration targets. The regional day recomputes destinations across the expanded set of places, so the same City resident can have different trip endpoints in the two views.

Regional transit playback covers 47 routes with 5,261 scheduled runs serving the added areas during the simulation day beginning at 04:00 on September 15, 2026. Vehicles follow dated TransLink stop schedules and route shapes. When stops cannot be matched to a shape within 150 m, the display joins scheduled stops in order. Counts refer to scheduled service. Synthetic passengers, crowding and ridership have yet to be assigned. The City travel survey and grocery experiment continue to use the municipal study population. [Regional input sources](../DATA.md)

### UBC weekday demand and scheduled riders

The regional weekday integrates fall 2025 counts from UBC’s five approach roads. Tables 2.1 and 2.3 provide a daily two-way total and independent morning and afternoon directional checks. The model counts recorded journeys between known assigned places on opposite sides of the UBC legal boundary. It approximates crossing time by the instant of arrival at or departure from the inside endpoint. The two geographies, transit service years, and populations differ. Trips wholly internal to campus and unresolved trips are excluded from the crossing count. Each complete stop contributes a minute-by-minute presence count by activity and home area. Someone travelling is excluded from stationary presence. [UBC 2025 Transportation Status Report, Figure 1.1 and Tables 2.1 and 2.3](https://planning.ubc.ca/sites/default/files/2026-06/UBC2025-TransportationStatusReport-FINAL.pdf)

| Weekday person trips | Resident model | UBC fall 2025 |
|---|---:|---:|
| Both directions, all modes | 77,482 | 151,900 |
| Both directions, transit | 9,967 | 81,400 |
| Inbound, 09:00–10:00 | 4,287 | 8,283 |
| Outbound, 09:00–10:00 | 785 | 3,217 |
| Inbound, 17:00–18:00 | 1,750 | 4,971 |
| Outbound, 17:00–18:00 | 6,438 | 9,175 |

At noon, 28,491 regional residents are at assigned places on campus. Of those, 17,981 live in other study areas. Across the day, 34,463 distinct residents from those areas have a campus stop. The panel compares counted journeys, which a person can make several times. UBC’s separate estimate of campus population uses student, staff and faculty full-time equivalents. It cannot be read as a midday occupancy observation. Differences between simulated and observed travel combine destination choice, mode assignment, diary coverage and trips from outside the roster.

A synthetic transit bout can use a direct scheduled ride if both pedestrian access paths, waiting time, the scheduled ride and egress fit the original diary window. Access includes connectors to the nearest walking-network nodes and is capped at 800 m each way at 80 m/min. Mixed transit bouts containing a mode other than walking or transit retain the diary interpolation. The assignment chooses the earliest achievable destination arrival, breaking ties by the least walking. In playback, remaining slack after alighting is spent at the stop before the final walk, preserving the diary’s activity start and end. The passenger and vehicle share the same GTFS pattern, stop times and position calculation. This matches 607 of the 9,967 simulated campus transit trips. Local transit requiring transfers or other routes, crowding, vehicle capacity and service reliability remain unresolved. A feasible match describes a possible synthetic itinerary. TransLink vehicle positions and UBC’s independent counts do not establish individual ridership.

### External campus attendance and café catchments

The café view projects two external populations onto the resident weekday. Each alternative adds one population from municipalities beyond the resident study area. The lunch count is the number of distinct people assigned to a location within a 400 m pedestrian-network walk of the café for any part of 11:00–14:00. The clock also shows the number present at the selected minute. Multiple stops count once per person for lunch. The reach calculation includes straight connectors between mapped locations and their nearest walking nodes, uses 80 m/min, and considers campus destinations only. The three cafés are existing geocoded locations. A person within reach may stay in their building or choose a different café.

**Student scenario.** The 2025/26 Vancouver headcount includes 49,165 undergraduate and 11,144 graduate students. The 1,806 health residents listed separately have a different attendance and employment context. Of 2,146 respondents to the 2026 AMS Academic Experience Survey, 55% reported living off campus. Among off-campus respondents 11% each reported commuting from Richmond and Burnaby. Applying those shares to the headcount gives 3,649 student profiles in each municipality after rounding. This projects survey respondents' housing patterns onto enrolment. Survey participation, health placements, multiple campuses and seasonal attendance affect the estimate. The remaining origins are outside this scenario. [UBC Annual Enrolment Report, Table 4](https://scs-senate-2021.sites.olt.ubc.ca/files/Item-7-UBC-Annual-Enrolment-Report-2025-26.pdf) · [AMS Academic Experience Survey, p. 15](https://bog3.sites.olt.ubc.ca/files/2026/09/9c2_BOG_StudentAMSSurveyReport_-OPEN_20260923_Rev0.pdf)

**Employee scenario.** UBC's housing plan background tables count 4,087 faculty and deans and 11,762 staff, including research associates and postdoctoral fellows. HR residence shares of 7% for Richmond, 6% for Burnaby and 5% for Surrey give 1,109, 951 and 792 profiles respectively. The figures describe the earlier housing study population. The model treats people from the three cities as a cohort under those conditions. UBC employees can also enrol as students. The interface compares each alternative separately. [Employee counts, Tables 1–2](https://planning.ubc.ca/sites/default/files/2024-03/CV_2050_Housing_Action_Plan_Background_Information.pdf) · [UBC employee origins](https://planning.ubc.ca/sites/default/files/2024-03/2022-11-10_-_UBC_Faculty_and_Staff_HNA_and_Programs_Review_-_FINAL.pdf)

**Attendance and location.** Each external profile draws one intact weighted urban BC 2022 weekday diary from the atlas training split. A student donor currently attends school and has at least a high-school qualification (EDC_10 and ED_05). Working students remain eligible. An employee donor reports work as their main activity. A continuous stay at the work-or-school location is assigned to campus if it contains study or paid work, respectively. Breaks at that location remain part of the stay. Home study, remote work and absence contribute zero campus presence. Outside these intervals the person’s whereabouts are unspecified. This release projects attendance only and leaves the observed transit comparison independent.

The student training set has 35 eligible diaries, of which eight include on-site study (33.5% weighted). The held-out nine diaries yield 55.1%. For employees, 250 of 434 training diaries include on-site work (58.6% weighted), compared with 46.5% in the 107 held-out diaries. These differences indicate material uncertainty in transferring general BC weekdays to UBC. The holdout is a separate respondent sample. Each profile has a stable building assignment sampled by gross floor area among completed UBC buildings inside the legal campus boundary. Students draw academic and research buildings. Employee assignments also include administrative, service and operations buildings. This proxy does not resolve class timetables, room capacity or staff by department.

| Distinct people within a five-minute walk, 11:00–14:00 | Regional residents | Additional students | Additional employees |
|---|---:|---:|---:|
| Great Dane Coffee | 3,889 | 38 | 65 |
| Mercante | 683 | 291 | 249 |
| Bean Around The World | 1,248 | 82 | 60 |

In this seeded weekday, 2,429 external students attend at some point (1,523 at noon). The separate employee alternative yields 1,679 attendees (1,403 at noon). The hourly and site results are conditional on the geographic coverage, donor schedules, assigned buildings and walking network. They cannot establish sales, purchases, pedestrian counts at the entrance or economic impact.

### Raster weekday execution

The Vancouver day builder supplies stable resident IDs, diary intervals and assigned locations. Raster executes a phase over these schedules for three policy settings. A worker must be employed, have the published Census PUMF NOC21 value 2 (business, finance and administration), and have a complete home–travel–job–travel–home tour. The job stop must contain paid work and have a known, distinct location. The baseline preserves all episodes. For an accepted offer, the worker spends both journey windows and the intervening job stop at their home. Their remaining schedule is identical. A fixed hash of the home dissemination area and within-area resident index assigns about half the eligible workers to the first offer group. All eligible workers take up the full offer. These are illustrative interventions. Eligibility and assumed uptake have yet to be calibrated against employers’ policies or telework preferences.

One phase invocation visits a schedule interval for every active work item. Each emits signed integer changes into time and area bins covering the whole weekday, including travelling and unresolved states. The per-agent representation assigns one item and unit weight to each resident. The grouped representation combines people with the same diary template, baseline area states, possible intervention shifts and offer group. Both use the same Raster kernel. Resident identity and detailed geometry stay available to the map. The grouped representation is sufficient for these additive area counts and this specific policy. Building-level motion, retail demand and interactions between people need additional state.

The backend keeps schedule columns on the device for the full sequence of timestep-independent interval passes and policy levels. The host integrates the small array of returned changes over 1,440 minutes. Before publication, the counts for every area, minute and policy are compared to the detailed schedule reference, including population conservation and cancellation of terminal changes. The optional `--verify-agents` run also dispatches the per-resident representation and compares it to the same independent reference. The browser reads version-matched results and shows the selected resident’s paired location. Street navigation, estimates for outside visitors and separate retail experiments retain their own inputs and semantics.

| Study area | Residents | Weighted itineraries | Workers in half-offer case | Commute legs removed |
|---|---:|---:|---:|---:|
| City of Vancouver | 662,263 | 194,593 | 11,281 | 22,704 |
| Vancouver, UBC and North Shore | 867,776 | 225,026 | 14,553 | 29,314 |

In the regional full-offer case, 28,784 eligible people make 57,952 fewer commute legs on the simulated weekday. The scenario directly reallocates diary travel time. It does not model subsequent household responses, employer productivity, transit crowding or altered purchasing. The area comparison uses the recorded spatial weekday, before optional short-walk reconstruction or storefront alternatives.

### Household grocery spending within walking distance

The municipal scenario compares each of 964 surveyed vacancies independently against 73 licensed grocers. From each assigned home, the walking distance includes both access connectors and the shortest path on the pedestrian network. Five, ten and fifteen minutes correspond to 400, 800 and 1,200 metres. Each catchment reports all private households within reach, those with a closer option than their existing reachable grocer, and those gaining their first reachable grocer. Existing shops retain distance ties at millimetre precision. Shops outside the municipal inventory can affect results near the city boundary.

Annual food purchased from stores averages $6,360, $6,843, $7,450, $9,068 and $11,313 across the five BC before-tax household income quintiles in the 2021 spending survey. For each synthetic private household, total 2020 income is the sum over members aged 15 and older. We approximate quintile thresholds by interpolating within the published BC Census household income brackets, giving $41,212, $69,648, $103,854 and $156,793. These thresholds approximate the survey’s ranks. The 7,889 households with incomplete income use BC’s all-household mean of $8,208. The 305,026 private households each count once per candidate site. [Statistics Canada spending table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110022301) · [Survey guide](https://www150.statcan.gc.ca/n1/pub/62f0026m/62f0026m2023001-eng.htm)

The spending control assigns a user-selected fraction of each household’s annual food-from-stores budget to its nearest walkable grocer. It applies only to households for which the proposed shop would become nearest. The denominator includes purchases from other kinds of food retailers. Spending is in 2021 Canadian dollars. Preferences, prices, opening hours and observed store receipts would be needed to estimate realized revenue. The diary-based shopping scenario separately computes visits subject to opening hours and trip time.

The Raster phase aggregates integer counts by site, walking limit, access change and income group. Groups share the same home anchor and income band for a given candidate. The builder compares every count to a NumPy reference. Running with `--verify-households` additionally dispatches each household–site pair with unit weight. For this release, 4,911,765 grouped rows and 12,469,269 household–site pairs give identical totals on the Intel GPU.

### Local tests of household income and usual commuting mode

The 2021 Census Profile tables for household total income in 2020 (characteristics 260–280) and main commuting mode (2603–2610) are excluded from the population fit. The comparison uses the complete synthetic private-household rosters. Children below 15 contribute no personal income to a household sum. A missing applicable income leaves the household unresolved. Commute mode describes the usual commute at census time. The comparison counts residents with a reported mode in the hierarchical PUMF, combining motorcycles and other modes in the final category. The census denominator covers employed people aged 15 and over with a usual or no fixed workplace. Individual amounts, mode choices and travel on a particular weekday are separate variables.

| Held-out City of Vancouver measure | Synthetic roster | Published census | Original metro donor households |
|---|---:|---:|---:|
| Private household income below $50,000 | 30.5% | 29.7% | 25.5% |
| Private household income $150,000 or higher | 21.2% | 22.4% | 23.8% |
| Usually drives | 65.1% | 50.8% | 68.6% |
| Usually commutes by transit | 16.6% | 22.9% | 14.2% |
| Usually cycles | 2.0% | 5.3% | 1.7% |

The income comparison has 297,137 model households with complete income and 7,889 unresolved. The published denominator is 305,335. The commute comparison contains 254,708 synthetic commuters and 233,960 estimated census commuters. The mean absolute gap is 0.84 percentage points across four income categories and 4.99 across six commute categories. Using the original metro household donor pool with its sampling weights gives 2.07 and 6.43 points respectively. These errors describe one seeded roster. Both data products originate in the 2021 Census.

Municipal comparisons use the directly published municipality. Neighbourhoods, UBC and the combined study region use matched dissemination areas with all required reference cells and positive denominators. The model and census omit the same unavailable areas for each comparison. Counts use the published denominator even where independent rounding prevents shares from adding to 100%. Local discrepancies can be large. In Grandview-Woodland cycling accounts for 11.0% of published usual commutes and 2.4% of the synthetic roster’s. The corresponding Kitsilano figures are 10.2% and 2.3%. These are checks on usual commute attributes, distinct from the travel modes assigned by the weekday diaries. [Statistics Canada Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)

### Housing values and costs

The atlas shows 2021 average owner-estimated dwelling value, percentage of owners with mortgages, average monthly tenant shelter costs and percentage of tenants spending at least 30% of their income on shelter. The Profile tables cover owner and tenant households in non-farm, non-reserve private dwellings (1482, 1483, 1489, 1490, 1492, 1495). The local-area mean weights each available DA value by its corresponding published owner or tenant count. Published coverage can differ by measure. For example, the estimated average owned home in Shaughnessy was $5.26 million and 40.6% of owners had a mortgage. Estimating home equity would require ownership shares and outstanding loan balances. [2021 Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)

The municipal atlas also assigns each of the 305,336 synthetic households a shelter cost from a matching Vancouver metro census microdata household. The match uses the same roster attributes and tenure used to build the synthetic population. Where those attributes admit several donors, it draws among them using Census weights. Owner dwelling value and mortgage presence come from the same draw. Household after-tax income sums members’ annual after-tax income in the same donor household. The model has a complete estimate for 297,580 households. Each DA and tenure group scales its costs to the corresponding Census mean where at least 25 observed and ten synthetic households support it. Owner dwelling values use the same calibration. Smaller or suppressed groups use the municipal scaling factor. [2021 Census PUMF v2](https://www150.statcan.gc.ca/n1/pub/98m0001x/) · [Explore neighbourhood dwelling values](http://127.0.0.1:8187/population.html?area=Shaughnessy&housing=1&map=dwelling)

The citywide owner dwelling mean is $1.73 million after calibration. The model median is $1.22 million against $1.45 million in the Census. The model’s median monthly tenant shelter cost is $1,491 against $1,570. The medians check the synthetic distribution independently of the calibrated means. The original microdata top-codes high shelter costs and values. Atlas housing values describe synthetic homes and their local distribution. Individual parcels, sales and loan balances would require separate evidence.

#### Assessed property values by neighbourhood

The City’s 2021 assessment roll contains 213,627 distinct folios. Of these, 110,391 are land or strata records in one-family, two-family or multiple-dwelling zones with positive assessed land and improvements. Joining the roll to current parcel points places 109,470 of the selected records in the 22 City neighbourhoods. The other 921 lack a unique geographic match. The release retains the count and middle half of the total assessed value distribution, with separate medians for land and improvements. [Downloads and filters](../DATA.md#vancouver-property-assessments)

In the selected residential zones, the median strata assessment is $851,000 in Kitsilano across 6,328 records and $524,000 in Grandview-Woodland across 3,778. The filter omits comprehensive-development zones, which removes most Downtown strata records. Land records can include several homes. Mortgage balances, ownership shares and other assets would be needed to estimate household wealth. [Inspect Kitsilano](http://127.0.0.1:8187/population.html?area=Kitsilano&assessments=3dc21e03354171d4713d) · [Inspect Grandview-Woodland](http://127.0.0.1:8187/population.html?area=Grandview-Woodland&assessments=3dc21e03354171d4713d)

An expanded release adds strata in other zoning classes when their published levy agrees within a cent with the 2021 residential rate on their full assessment, with or without the additional school tax. Of 94,377 eligible strata tested in other zones, 71,591 match the rate and 71,518 have a unique neighbourhood. Downtown contributes 31,213 matched strata records with a median assessment of $763,000 and a middle half from $613,000 to $1,071,000. Actual taxable values can differ from full assessments. The result is a sample with a reproducible rate match, and mortgage debt and occupancy are outside this evidence. [Downtown assessments](http://127.0.0.1:8187/population.html?area=Downtown&assessments=6053d3054c912eb89abf) · [2021 rates](https://vancouver.ca/files/cov/2021-property-tax-rates.pdf)

#### Shelter costs and grocery budgets

For each of the 964 grocery storefronts, the housing comparison uses the same directed walking distances, household identities, nearby competitors and 2021 BC income-band food budgets as the household reach model. Choose an increase in tenant shelter costs of 5%, 10% or 20%. For tenants with positive after-tax income and measured shelter cost, the sensitivity holds food spending proportional to the cash left after shelter. It floors the denominator at the baseline food budget and caps the reduction at that budget. Tenure code 2 includes rented and provided housing. Food expenditure uses the Survey of Household Spending, after-tax income is from 2020, and shelter uses the 2021 Census. [2021 BC household spending](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110022301) · [Census definition of shelter cost](https://www12.statcan.gc.ca/census-recensement/2021/ref/dict/98-301-x2021001-eng.pdf)

Within a ten-minute walk of the Kingsway example, 1,317 of 3,481 households are in the tenant group, of which 1,285 have the inputs for the sensitivity. A 10% shelter-cost increase reduces their combined annual store-food budgets by about $679,000. At an assumed 1% capture share among households for whom the new shop would be the closest, estimated annual spending at the shop changes from about $220,882 to $215,977. These are conditional budget estimates. Visits and scheduled opening use the grocery day’s trip model. [Replay higher shelter costs at Kingsway](http://127.0.0.1:8187/cityday.html?shop=4654&housingRun=dd2b618d51e61a158a99&shelterShock=10)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_household_housing ../Simulations/city
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_housing_market
```

### Downtown rush hour and municipal transit

For September 15, 2026, the TransLink GTFS feed contains 69 routes and 10,616 runs that serve at least one stop within the City of Vancouver during the 04:00–04:00 simulation day. For every resident trip containing a transit episode, the matcher tests direct runs, stop order, pickup/drop-off permissions, all scheduled departure and arrival times, and shortest walking paths including off-network access at both ends. Walks are limited to 800 m per end at 80 m/min. A suffix minimum over arrivals permits overtaking. The chosen journey minimizes arrival time and then walking time. It respects the next diary activity. Early arrivals wait at their destination. When the transit panel is open the selected municipal passenger follows the vehicle, while the overview continues to use its sample display.

Of 90,105 bouts involving transit, 18,449 fit a direct scheduled trip across 54 routes. Another 45,141 lack a feasible direct service in the available time, 17,141 lack reachable stops, 4,103 lack a located endpoint, 2,710 have coincident endpoints and 2,561 include another vehicle mode. The 99 B-Line serves 699 matched city-resident trips, compared with an independent 34,653 average weekday boardings across the entire route in 2025. Visitors, transfers, crowding, service delays and unrecorded trips can affect this comparison. [TransLink GTFS](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data) · [Transit Service Performance Review](https://www.translink.ca/tspr)

The rush-hour panel counts a located trip as arriving in the Downtown local area if its origin was outside, and leaving if its destination is outside. Counts use the arrival or departure hour respectively, the dominant diary mode and the resident’s home neighbourhood. These are endpoint trips by city residents and omit external commuters. Downtowner-to-Downtowner trips and through trips are excluded. Directional person trips measure a different quantity from vehicle congestion or traffic measured at a bridge.

| Time | Resident trips arriving / leaving Downtown | Six stations, observed alightings / boardings | Six stations, matched alightings / boardings |
|---|---:|---:|---:|
| 07:00–09:00 | 8,327 / 14,785 | 25,677 / 7,557 | 60 / 29 |
| 16:00–18:00 | 15,376 / 12,688 | 16,579 / 29,796 | 19 / 25 |

The six stations are Burrard, Granville, Stadium-Chinatown, Vancouver City Centre, Waterfront and Yaletown-Roundhouse. Observations sum TransLink’s 2025 average Monday–Friday hourly SkyTrain boardings and alightings. Matched counts use actual scheduled stop times for the synthetic direct rail journeys and include trips within Downtown. The resident-wide flow points out of Downtown in the morning, while observed SkyTrain passengers predominantly alight there. The city-only workplace/destination assignments and limited transit matches need further calibration. The separate 2021 CSD commuting flow table contains 94,960 people living outside the city with a usual workplace somewhere in Vancouver. Converting this municipal workforce stock into Downtown trips requires workplace geography and attendance days. [Statistics Canada commuting flows](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901) · [TransLink performance data](https://www.translink.ca/tspr)

### Traffic across five bridges

The bridge comparison reads the City’s archived permanent-counter records for Burrard, Granville, Cambie and Lions Gate bridges. Each direction has 24 hourly averages for the month and year shown in the panel. The archive contains observations from different months, so comparisons are directional rather than totals for a single date. Eastbound on the Lions Gate counter means toward downtown. [City counter programme](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations) · [Direction convention](https://vancouver.ca/files/cov/2019-05-02-update-on-w-georgia-complete-street-planning-project.pdf)

The comparison uses each driver's simulated endpoints and time window to count crossings of named bridge-deck edges on the directed street graph. Both endpoints must be within 500 metres of a road node and the route must fit the travel window. The constant-speed benchmark uses 380 metres per minute and places the crossing in the diary window according to the fraction of route distance to the bridge. The regional road-speed benchmark instead uses estimated travel time, including both access connectors. The resident variants share a population and day. They compare original diaries, the census-workplace and commute fit, and that fit with the survey-access cycling outings. The incoming work cohort uses the wider regional road graph, its assigned home census areas and licensed workplaces. Other drive trips from outside the model, commercial traffic and buses contribute to the observed counts. Lane capacity, queues and counterflow are outside this crossing calculation.

The regional comparison uses the same Lions Gate counters and includes Ironworkers Memorial Bridge. Each Ironworkers hour averages the 21 Monday–Friday records in March 2025 from the B.C. station. The two March benchmarks use the same month and both count motor vehicles. Eastbound on Ironworkers heads from the North Shore toward Vancouver. The routed screen is on the named bridge deck. [B.C. hourly report](https://tradas.th.gov.bc.ca/reports/AllYears/2025/03/MV03/MV03P_Second%20Narrows%20P-15-2EW%20-%20NY3-2025.csv) · [B.C. station diagram](https://tradas.th.gov.bc.ca/siteDiagrams/61340P.pdf)

The regional replay draws car-driver legs from the complete weekday of 867,776 residents in Vancouver, UBC and the North Shore, including work and other travel. The municipal and regional weekday models overlap. The regional road graph extends across Metro Vancouver, so routes can use alternate crossings. Select a populated hour to follow a driver at the calculated crossing time. The report is keyed to the atlas, weekday and road releases. [Regional Lions Gate comparison](http://127.0.0.1:8187/cityday.html?coverage=region&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am) · [Ironworkers comparison](http://127.0.0.1:8187/cityday.html?coverage=region&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am)

| Lions Gate window | Direction | March 2025 counter | Municipal residents and incoming work drivers | Regional residents |
|---|---|---:|---:|---:|
| 07:00–09:00 | Toward downtown | 5,425 | 148 | 611 |
| 07:00–09:00 | Toward the North Shore | 2,961 | 0 | 2,020 |
| 16:00–18:00 | Toward downtown | 3,666 | 1 | 3,267 |
| 16:00–18:00 | Toward the North Shore | 5,055 | 143 | 1,396 |

The regional weekday accounts for more crossings in both windows and puts the dominant flow in the opposite direction from the counters in both. The road graph can place both trip endpoints within 500 metres for 939,420 of 1,010,809 regional car-driver legs. Endpoint placement alone leaves open how the model assigns workplaces, trip times and routes. The counter observes all motor vehicles, while the regional replay covers resident car-driver legs.

| Ironworkers window | Direction | March 2025 counter | Regional residents |
|---|---|---:|---:|
| 07:00–09:00 | Toward Vancouver | 8,483 | 1,176 |
| 07:00–09:00 | Toward the North Shore | 9,096 | 4,089 |
| 16:00–18:00 | Toward Vancouver | 9,335 | 4,060 |
| 16:00–18:00 | Toward the North Shore | 9,508 | 2,466 |

Of the 6,109 simulated northbound crossings at both bridges from 07:00 to 09:00, 5,341 are direct drives from Vancouver homes to paid work. Assignment already favours that direction before routing. The weekday sends 44,583 employed City of Vancouver residents directly from home to a paid-work site in one of the three North Shore municipalities. It sends 10,253 in the reverse direction. Each employed person counts once, using their first located direct trip from home to paid work. The 2021 Census counts 7,745 usual workplaces in the former direction and 11,445 in the latter. Both workforce comparisons include all modes and use City of Vancouver boundaries. The census covers usual workplace stock, while the weekday covers people actually scheduled to travel. [Statistics Canada Table 98-10-0459-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

Across both bridges, 4,780 assigned direct drives from home toward a paid job in Vancouver or UBC depart from 07:00 to 09:00. Of those, 1,433 fit their assigned travel time and cross. Toward North Shore jobs, 4,984 of 17,723 drives fit and cross. These figures use departure hour. The crossing tables use the hour a driver passes the bridge screen, so their counts can differ. The comparison identifies an excess of City residents assigned across the inlet and a shortfall in travel time for trips in both directions.

#### Census workplace destinations

The paired regional weekday conditions each municipality's synthetic direct commuters on the published 2021 workplace shares between Vancouver, the City of North Vancouver, the District of North Vancouver and West Vancouver. Each census row is normalized across those four workplaces, then rounded to the number of employed residents in the original replay with a direct trip to a paid job in one of the four municipalities. This transfers relative destination shares from usual workplaces to the weekday cohort. UBC and other workplaces outside these four municipalities fall outside the fit. The workday keeps the atlas, housing, diary, travel modes and time windows of the original day. [Statistics Canada workplace matrix](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

The allocator moves surplus jobs into municipalities with a shortfall. It uses existing assigned work addresses as candidate sites and checks every measured leg touching the paid job. For road trips across Burrard Inlet it checks directed distances through the bridges, including access connectors at both ends. Other legs use straight-line distance as a screening bound. Workers with an unresolved anchor, several different job addresses or an untimed boundary between workplace and other activities keep their original plans. Where it can make several changes, the allocator starts with original links that exceed the travel bound. It reports the remaining difference from the targets.

The new day moves 48,855 workplaces among 226,803 scheduled workers. Vancouver to the North Shore falls from 44,583 to 10,045, against a conditional target of 9,932. The reverse rises from 10,253 to 13,536, its conditional target. The remaining 113 excess jobs are in West Vancouver. Every minute accounts for the same 867,776 residents. The bridge panel keeps the counter and the selected hours fixed when switching between weekdays. [Replay the paired comparison](http://127.0.0.1:8187/cityday.html?coverage=region&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am)

| Bridge and hours | Direction | Observed | Original workplaces | Census workplaces |
|---|---|---:|---:|---:|
| Lions Gate 07:00–09:00 | Toward downtown | 5,425 | 611 | 1,126 |
| Lions Gate 07:00–09:00 | Toward the North Shore | 2,961 | 2,020 | 809 |
| Lions Gate 16:00–18:00 | Toward downtown | 3,666 | 3,267 | 1,671 |
| Lions Gate 16:00–18:00 | Toward the North Shore | 5,055 | 1,396 | 2,293 |
| Ironworkers 07:00–09:00 | Toward Vancouver | 8,483 | 1,176 | 1,829 |
| Ironworkers 07:00–09:00 | Toward the North Shore | 9,096 | 4,089 | 1,688 |
| Ironworkers 16:00–18:00 | Toward Vancouver | 9,335 | 4,060 | 2,071 |
| Ironworkers 16:00–18:00 | Toward the North Shore | 9,508 | 2,466 | 3,693 |

At constant speed, the weekday with census destinations matches the dominant direction in both Lions Gate peaks. Ironworkers has near-balanced morning flows in the replay and in the counters, with a small difference in which direction leads. Volumes in both directions remain low. Toward Vancouver and UBC, 2,669 of 5,699 direct drives departing in the morning window fit the travel budget and cross either bridge, compared with 1,433 of 4,780 before. Departure times, mode choice, local job sites and missing travel from beyond the model's roster can still affect the remaining gaps.

```sh
python -m scripts.vancouver_bridge_traffic ../Simulations/city
python -m scripts.vancouver_bridge_traffic ../Simulations/city --region
python -m scripts.vancouver_regional_workplaces ../Simulations/city
```

#### Downtown workplaces for North Shore commuters

The municipal workplace fit matches flows between census subdivisions. It still assigns only 2,788 of 14,877 scheduled North Shore workers with a Vancouver or UBC workplace to Downtown or the West End. Table 20 of the 2023 North Shore Transportation Survey gives 18,930 usual workplaces in the CBD/West End and 11,610 in the rest of Vancouver and the University Endowment Lands. The downtown scenario transfers the conditional shares separately for each of the three North Shore municipalities to the synthetic weekday. The comparison uses private-household residents with known age 15 or older and a located direct paid-work arrival. Downtown and the West End approximate the survey's downtown peninsula. UBC workplaces stay fixed and contribute to the non-downtown denominator. [North Shore Transportation Survey, Figure 1 and Table 20](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

Pairs of North Shore and Vancouver residents exchange their existing Vancouver workplaces. The allocator searches within the same broad occupation group. It preserves each workplace's number of assigned workers by occupation and the municipality-to-municipality flows. Each worker retains their home, other destinations, travel modes and full activity clock. A move requires all travel touching the workplace to fit. Cars use directed street times with the observed Highway 1 profile. Walks and bicycle trips use their directed graphs with speeds of 75 and 220 metres per minute. Transit uses the dated September 15, 2026 timetable with up to one transfer and street access of up to 800 metres. The swap check assumes seats are available. Unknown occupations, repeated jobs at different sites and workplaces with no recorded journey at a change of location are ineligible for a swap. A seeded search tries nearby and sampled alternatives. It may leave a residual even when a more extensive matching search could find additional pairs.

The weekday exchanges 6,081 pairs across 12,162 residents. The number of North Shore workers assigned to Downtown or the West End rises from 2,788 to 8,869 of 14,877, or 18.7% to 59.6%. The City of North Vancouver stays 209 assignments below its conditional target. Each minute still accounts for 867,776 residents and the day keeps all 1,659,843 travel bouts.

| Home municipality | Survey share | Municipal fit | Downtown fit |
|---|---:|---:|---:|
| City of North Vancouver | 70.2% | 11.6% | 65.4% |
| District of North Vancouver | 58.2% | 12.2% | 58.2% |
| West Vancouver | 55.2% | 40.5% | 55.2% |

The March 2025 bridge counts are held out from the workplace fit. With observed Highway 1 times and the same incoming worker cohort, the Vancouver-bound morning count improves at Lions Gate and falls further below the observed count at Ironworkers. The combined Vancouver-bound morning count across both bridges moves from 6,367 to 6,354, against 13,908 observed. The workplace fit mainly shifts traffic between the bridges in that window. The counters include all vehicle trips. [Replay the morning comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1)

| Bridge and hours | Direction | Observed | Municipal fit | Downtown fit |
|---|---|---:|---:|---:|
| Lions Gate 07:00–09:00 | Toward Vancouver | 5,425 | 2,938 | 4,366 |
| Lions Gate 07:00–09:00 | Toward the North Shore | 2,961 | 4,667 | 4,667 |
| Lions Gate 16:00–18:00 | Toward Vancouver | 3,666 | 4,730 | 4,749 |
| Lions Gate 16:00–18:00 | Toward the North Shore | 5,055 | 5,918 | 6,826 |
| Ironworkers 07:00–09:00 | Toward Vancouver | 8,483 | 3,429 | 1,988 |
| Ironworkers 07:00–09:00 | Toward the North Shore | 9,096 | 5,836 | 5,836 |
| Ironworkers 16:00–18:00 | Toward Vancouver | 9,335 | 5,692 | 5,673 |
| Ironworkers 16:00–18:00 | Toward the North Shore | 9,508 | 6,551 | 5,651 |

The North Shore survey also estimates 3.12 trips per private-household resident aged 15 or older. The equivalent age and household scope on the parent weekday yields 1.95 recorded travel bouts per person. The survey includes recreational trips that return to their starting point without a separate stop. The weekday also restricts assigned places to Vancouver, UBC and the North Shore, while the survey observes trips as far as the Fraser Valley. The workplace fit changes only the destinations of existing workers. [North Shore Transportation Survey, Table 3 and sections 3.2 and 3.4](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

```sh
python -m scripts.vancouver_downtown_workplaces
```

#### Workplaces in Burnaby and New Westminster

This weekday follows North Shore residents to paid work beyond Vancouver and UBC. It uses the same resident atlas and the wider street coverage already present in the regional OpenStreetMap extract. An expanded map shows the workplaces, local streets and both Burrard Inlet crossings.

The model conditions 2021 usual-work flows from each North Shore municipality on the destinations covered by the replay. It uses the Vancouver, North Shore and Metro Vancouver A census rows for the covered destinations and adds separate Burnaby and New Westminster rows. Metro Vancouver A approximates the campus workplace group. It applies the relative flows to private-household residents aged 15 or older with a located direct home-to-work arrival in the downtown-fit weekday.

The allocator draws from 5,361 mapped job locations inside the two census subdivision boundaries. Each 2021 tract's observed workplace count weights its mapped addresses. Staffing and occupation-specific openings at individual businesses remain unknown. It draws residents from existing job groups according to their relative sizes, including a separate Downtown and West End group. Each recorded journey adjacent to the moved workplace must fit its original travel window. Driving uses the hourly Highway 1 profile, walking and cycling use their directed graphs, and scheduled transit uses the September 15, 2026 timetable with up to one transfer. The transit fit assumes available passenger space. [Statistics Canada usual workplaces by origin and destination](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901) · [Statistics Canada workplaces by tract](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801)

All six home–workplace targets fit. The weekday assigns 3,619 workers to Burnaby and 393 to New Westminster. The outward trip uses the recorded driving mode for 3,497, car passenger for 209, transit for 285, cycling for 19 and walking for two.

| Home municipality | Burnaby | New Westminster |
|---|---:|---:|
| City of North Vancouver | 1,178 | 98 |
| District of North Vancouver | 1,914 | 207 |
| West Vancouver | 527 | 88 |

The paired replay includes 4,031 assigned southbound trips to eastern workplaces across all modes. The North Shore travel survey reports 11,540 trips to these cities across all modes and trip purposes. The March 2025 bridge counters provide a separate check on the resulting flows and measure all vehicle crossings. The comparison uses a common map frame and the same incoming cohort. Reconstructed short walks and the 65,652 discretionary outings can play on the expanded weekday. [North Shore Transportation Survey, Table 11](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF) · [Open the Ironworkers comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=c1b31a9daf40041dcb73&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1)

Southbound morning trips increase across the two bridges, from 6,354 to 7,605 against 13,908 observed. The larger change is at Ironworkers. The afternoon return flows also shift toward Ironworkers.

| Bridge, direction and hours | Downtown fit | Eastern workplaces | March 2025 count |
|---|---:|---:|---:|
| Lions Gate, southbound 07:00–09:00 | 4,366 | 4,073 | 5,425 |
| Ironworkers, southbound 07:00–09:00 | 1,988 | 3,532 | 8,483 |
| Lions Gate, northbound 16:00–18:00 | 6,826 | 6,560 | 5,055 |
| Ironworkers, northbound 16:00–18:00 | 5,651 | 7,007 | 9,508 |

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_eastern_workplaces
```

#### Workplace destinations by North Shore home zone

**Work commutes by home zone** shows the survey and model estimates per 1,000 residents aged 15 and over. The replay counts the first located direct home-to-paid-work commute for each employed adult. The publisher recovers the eight zones from Figure 2 of the survey with an approximate geographic join. The registered outline has a mean error of about 36 m along the Census perimeter. It flags homes near the internal zone lines, where the survey figure's resolution matters. [2025 North Shore Transportation Survey, Figure 2 and Tables 3 and 54](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The 2025 workplace fit applies the rounded weekday workplace shares to the located direct workers in each home zone. Suppressed cells keep their parent count. Workers with a surplus destination can move to a mapped job site in a destination with a deficit only when all adjacent directed journeys fit the original diary windows. Roads use estimated hourly Highway 1 times. Transit checks service with up to one transfer. This isolates work geography from attendance, mode and departure assumptions. The base replay has 50,344 located direct commuters among 158,899 adults, while the survey estimates 65,200 people who commuted among 174,600 residents aged 15 and over. This difference in modeled coverage and definition remains when comparing absolute numbers. The survey's all-purpose southbound destinations and observed bridge traffic remain independent checks. [2025 North Shore Transportation Survey, Tables 3, 35 and 54](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The paired release reassigns 10,874 workers. It reduces the summed absolute discrepancy across the eight home-zone rows and fitted destination groups from 28,902 workers to 7,154 under the same synthetic commute totals. The North Vancouver city core shifts from 1,548 to 3,104 workers going to Downtown or the West End. About 17,100 modeled adults live near a mapped zone boundary, so figures for individual zones depend in part on registration. [Replay the 2025 fit and inspect the home zones](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&northWorkplace=Burnaby&bridgeMetric=highway1)

| Work destination | Census-based weekday | 2025 fit | Target at the same synthetic total |
|---|---:|---:|---:|
| Downtown or West End | 8,167 | 11,439 | 11,869 |
| Rest of Vancouver or UBC | 5,531 | 7,433 | 8,283 |
| Burnaby | 3,619 | 3,914 | 4,364 |
| New Westminster | 393 | 393 | 393 from the parent weekday |

The replay's separate all-purpose southbound check rises from 11,071 to 14,349 trips to Downtown or the West End, compared with 22,000 observed in 2025. Trips to Burnaby and New Westminster rise from 4,031 to 4,330 against 12,100 observed. Trips to the rest of Vancouver and UBC rise from 18,704 to 20,453, compared with 19,100 observed. [2025 North Shore Transportation Survey, Table 35](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

Independent March 2025 vehicle counters show closer modeled morning flows for both bridges. The afternoon fit improves at Ironworkers and moves farther above the observed count at Lions Gate. Both replays include the same incoming-worker cohort and use the same hourly road speeds. [Compare bridge traffic in the paired replay](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1)

| Bridge, direction and hours | Census-based weekday | 2025 fit | March 2025 count |
|---|---:|---:|---:|
| Lions Gate, southbound 07:00–09:00 | 4,073 | 5,472 | 5,425 |
| Ironworkers, southbound 07:00–09:00 | 3,532 | 4,371 | 8,483 |
| Lions Gate, northbound 16:00–18:00 | 6,560 | 7,694 | 5,055 |
| Ironworkers, northbound 16:00–18:00 | 7,007 | 7,847 | 9,508 |

On the JVM, Raster's individual execution for 867,776 residents and grouped execution for 228,943 itineraries both reproduce the minute-level occupancy from the full plans.

##### Transit to and from work

The downtown fit, Census-based eastern weekday and 2025 workplace fit can replay actual scheduled vehicles inside their existing labour diaries. Open **Transit to and from work** to follow an example from the first walk through boarding, a transfer where applicable, and the next activity. You can also select any resident with a matched trip. The panel loads a small set of sampled trips for the overview and a separate set for the selected resident's home census area. [Open the 2025 transit replay](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=1)

The matcher selects walking-and-transit bouts immediately before or after paid work for employed private-household residents aged 15 or older. Each weekday has 51,359 eligible windows, 117 bouts involving another mode, and 3,122 with the same assigned place at both ends. A ride must leave enough time for walks of up to 800 m at either end and a three-minute boarding margin. It tries a direct vehicle first and allows one change under the published transfer rules, with a street walk of at most 250 m. Early arrivals wait for the next activity to start. The September 15, 2026 service preserves the original activity and travel windows. [TransLink GTFS schedules](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data)

Bus assignments share a route-level capacity proxy across every occupied segment. A full run triggers a search for another direct vehicle or a transfer in the same window. The proxy uses the 2025 fall weekday data first, then annual figures and a 24-space fallback. The published shopping and recreation tours reserve their scheduled bus space before work trips are assigned, so both sets can replay together. These spaces remain reserved when the tours are turned off. Additional passengers on buses and the capacities of rail and ferries are open modeling work. [TransLink service performance data](https://www.translink.ca/tspr)

| Weekday | Matched work trips | With one transfer | Feasible before the capacity check, then rejected |
|---|---:|---:|---:|
| Downtown fit | 17,631 | 8,860 | 3,529 |
| Census-based eastern fit | 17,718 | 8,975 | 3,573 |
| 2025 workplace fit | 18,155 | 9,372 | 3,769 |

The 2025 fit matches 13,432 of 32,661 trips toward work and 4,723 of 18,698 trips from work. It reroutes 2,958 trips to keep them within the combined bus budget. The 7,670 reserved discretionary rides and assigned work trips use 4,346 distinct bus runs, of which 106 reach the modeled limit. No combined run exceeds the limit. Time and stop access still leave 23,357 and 6,058 work trips respectively without a feasible itinerary at the current routing limits. Another 20 start and end at identical coordinates.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_work_transit ../Simulations/city
```

###### Flexible time at home

**Allow flexible time at home** compares the recorded windows with an alternative for the 2025 workplace fit. The search borrows at most 30 minutes from adjacent at-home media or leisure, retaining at least 10 minutes of flexible time after reserving existing activities. It protects the original work stop, shopping and recreation outings, inferred short walks, addresses and mode. These time limits define a sensitivity test. The weekday's sampled diaries have eligible home time after work trips and none directly before a morning commute. The matcher keeps previously assigned riders and finds the shortest extension that fits a direct ride or one transfer within the shared bus budget. [Replay flexible home time](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=flex)

Of 3,062 windows adjoining flexible home time, 977 already have an itinerary. The alternative adds 770 return trips to the 4,723 already matched, bringing total matched work trips to 18,925. The median extension is 10 minutes. A further 22,595 trips still lack an itinerary within their applicable window and the model's routing limits. All assigned work and discretionary rides stay within the modeled bus capacities. **Follow a longer return** shows a resident who leaves work at 19:30 and arrives by 21:00 with a transfer from route 4 to route 17. Their original time for getting home was 20:30. Opening their household from the map shows the adjusted diary, with a link back to the same replay.

The independently reconstructed totals conserve all 867,776 residents minute by minute with the discretionary and short-walk layers included. Raster also runs the revised weekday individually and as 229,495 weighted itineraries. Both reproduce the same base occupancy and the two work-from-home policy comparisons.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_flexible_transit ../Simulations/city
```

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_zonal_workplaces
```

##### Scheduled transit for school, shopping and other activities

The 2025 workplace-fit weekday now matches recorded walking-and-transit bouts outside paid work. The extractor uses linked model stops and excludes any bout adjacent to recorded paid work, which belongs to the work matcher. Each assignment keeps its resident, addresses, travel window and next activity. Both street walks, the boarding margin, a direct ride or one transfer, and the final walk must fit. An early arrival waits until the diary's next activity. Riders follow the archived September 15, 2026 vehicle paths and stop times. [TransLink GTFS schedules](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data)

The assignment reserves space for 18,925 work trips, 7,670 added outing journeys and 68 on-site work trips first. The combined modeled load stays within the route-level capacity proxy on all 5,182 assigned bus runs. Rail and ferry space is unconstrained. Of 39,010 eligible travel windows, 12,030 fit, including 2,929 with a transfer. Of the eligible windows left unresolved, 18,836 lack a timetable match, 7,428 lack reachable stops and 716 lack modeled bus space. Before routing, another 4,839 bouts lack a located endpoint and 3,226 involve another vehicle mode. [TransLink bus-load data](https://www.translink.ca/tspr)

| Next diary stop | Eligible windows | Scheduled |
|---|---:|---:|
| School | 7,418 | 6,329 |
| Store | 3,399 | 463 |
| Home | 15,457 | 3,399 |

The city overview includes matched journeys from its fixed sample. Anyone with a match can be followed by resident ID. Street view indexes the access, transfer and egress walks from all matched trips. Open the school example to step through both rides. [Replay personal transit](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=9cec79f1fec091af7db6&personalTransit=b563cceea412bde5eafd)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_personal_transit ../Simulations/city
```

### Incoming workers outside the regional roster

The wider replay adds a separate cohort of 89,800 usual workers from 84 home-to-work flows. They live in Metro Vancouver outside the resident roster and work in Vancouver, the City or District of North Vancouver, or West Vancouver. The builder excludes every home census dissemination area in the atlas. Where a subdivision overlaps the atlas, it apportions the census flow by the published counts of residents commuting out of that subdivision. This adds 307 usual workers from the unrepresented part of Electoral Area A and 13 from the two omitted City of Vancouver census areas in the regional roster. The source also records 4,585 workers from beyond Metro Vancouver. [Statistics Canada commuting flows](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

The four destination municipalities receive 79,202, 4,561, 4,410 and 1,627 external usual workers respectively. Workplace census tracts weight the sampled destinations, with Vancouver business-licence employment and mapped workplace sites supplying candidate addresses. The model draws usual modes, departure times and durations from metropolitan census microdata, then places them on complete survey work shifts. It transfers the City survey's 64% weekday workplace attendance assumption to all four destinations. The seeded weekday has 57,757 attendees. Individual and grouped Raster execution both reproduce the independent per-worker presence clock. [Statistics Canada workplace tract counts](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801)

Among the 88,068 external car-driver legs, 82,490 have endpoints within 500 m of the road graph. Removing the two bridge screens disconnects 8,773 of these legs whose endpoints are otherwise joined by a directed road path through a bridge. Only 363 fit their diary windows at 380 metres per minute. The median assigned duration for those 8,773 legs is 30 minutes and the median shortest routed time at the model speed is about 65 minutes. This comparison depends on the sampled addresses, durations and the constant model speed.

At constant speed the cohort adds five downtown-bound crossings during the Lions Gate morning window and six toward the North Shore in the afternoon window. At Ironworkers it adds 73 northbound crossings in the morning and 80 southbound crossings in the afternoon. The bridge panel shows these counts alongside resident trips in either workplace scenario. A populated hourly cell follows that worker's street route. The breakdown also updates incoming paid-work presence and travel with the simulation clock. [Ironworkers replay](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=5bea5bc3322eb2bbae9f&bridge=Ironworkers&bridgeDirection=1&bridgeWindow=am)

```sh
python -m scripts.vancouver_regional_inbound ../Simulations/city --verify-workers
```

#### Regional routing with road speeds

**Replay road speeds** keeps the selected weekday, bridge, direction and time window. Only the route's costs and time feasibility change. The new comparison pins the archived speed profile by digest. It uses the same free-flow road model as the animation and the same March 2025 observations as the constant-speed comparison. The regional profile uses a posted limit for 40,966 directed ways and a road-class default for 163,551. Of the 8,773 incoming car-driver legs that require a bridge, 6,210 fit at road speeds, up from 363 at constant speed. Median estimated travel time falls from about 65 to 25 minutes. The incoming workers keep the same assigned median travel budget of 30 minutes.

| 07:00–09:00 screen and direction | Observed | Constant speed | Road speeds |
|---|---:|---:|---:|
| Lions Gate toward downtown | 5,425 | 1,131 | 2,936 |
| Lions Gate toward the North Shore | 2,961 | 811 | 4,656 |
| Ironworkers toward Vancouver | 8,483 | 1,832 | 3,431 |
| Ironworkers toward the North Shore | 9,096 | 1,761 | 5,849 |

Both model columns combine residents with census-fitted workplaces and the separate incoming work cohort. The road speeds admit many more crossings and make the North Shore direction dominant on Lions Gate in the morning, where the counter shows a heavier flow toward downtown. Direct drives from Vancouver homes to paid work account for 3,114 of the 4,656 simulated crossings toward the North Shore. Directional travel times and the timing, mode and destination of those work commutes can all affect the gap. [Road-speed replay](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=5bea5bc3322eb2bbae9f&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am&bridgeMetric=time)

```sh
python -m scripts.vancouver_bridge_traffic ../Simulations/city --region --road-speeds
python -m scripts.vancouver_bridge_traffic ../Simulations/city --region --road-speeds --day 7bc1b970083653ba45cd
python -m scripts.vancouver_regional_inbound ../Simulations/city --verify-workers --road-speeds
```

#### Observed Highway 1 travel times

**Replay observed Highway 1 travel times** compares the same drivers and diary windows with the free-flow replay. It matches the four study segments in each direction to the Highway 1 mainline from Lynn Valley Road to McGill Street, including Ironworkers. Table 5-1 through Table 5-8 supply the 2022 median for each of seven departure hours. The observed-to-free-flow travel-time ratio scales the cost of the directed edges in each segment, with a minimum ratio of one so the route never exceeds its free-flow speed profile. Each trip keeps the cost snapshot for its departure hour. The remaining hours, Lions Gate, ramps and other streets use the free-flow graph. [B.C. Highway 1 study, Figure 3-4 and Tables 5-1–5-8](https://www.vmcdn.ca/files/nsnews/files/binnie-iwmb-travel-time-study-final-rev0.pdf)

At 15:00 the four southbound sections total 9.86 minutes in the study, compared with 4.29 minutes in the free-flow graph. In the census-workplace replay, the Highway 1 timing sends more afternoon traffic through Lions Gate and fewer vehicles across Ironworkers. This worsens the Vancouver-bound fit at both bridges. Across all hours, 6,149 of the 8,773 incoming car-driver legs that require a bridge fit their original diary budgets, compared with 6,210 in free flow. Both crossing comparisons use the March 2025 counters. Those counts include trips beyond the synthetic resident and incoming worker cohorts. [Replay the afternoon comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=5bea5bc3322eb2bbae9f&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=pm&bridgeMetric=highway1)

| 16:00–18:00 screen | March 2025 count | Free flow | Observed Highway 1 times |
|---|---:|---:|---:|
| Lions Gate toward Vancouver | 3,666 | 4,543 | 4,730 |
| Ironworkers toward Vancouver | 9,335 | 5,950 | 5,692 |
| Lions Gate toward the North Shore | 5,055 | 5,922 | 5,918 |
| Ironworkers toward the North Shore | 9,508 | 6,547 | 6,551 |

The timing profile transfers historic corridor measurements to the synthetic weekday. Its speeds are independent of simulated volumes. Operating Lions Gate's reversible lane, modeling queues that respond to demand, and fitting arrivals across the wider road network require further calibration. [Province of B.C. counterflow operating description](https://www.tranbc.ca/2019/08/29/how-the-lions-gate-bridge-counterflow-works/)

```sh
python -m scripts.vancouver_highway_times
python -m scripts.vancouver_bridge_traffic ../Simulations/city --region --observed-highway1
python -m scripts.vancouver_bridge_traffic ../Simulations/city --region --observed-highway1 --day 7bc1b970083653ba45cd
python -m scripts.vancouver_regional_inbound ../Simulations/city --observed-highway1
```

##### Vehicles in the active replay

On the 2025 workplace-fit weekday, **Vehicles in this replay** combines recorded resident drivers, incoming work drivers, scheduled buses and drivers from the active school, shopping and recreation, or on-site work layers. It uses the selected bridge, direction and hours. **View bus** moves the clock and map to a scheduled crossing. **Follow a driver** opens the additional resident trip at the bridge.

The bus calculation counts each run once per traversal. It intersects mapped bus shapes with the same bridge cuts as the drive comparison and interpolates between a departure and the next stop arrival. It uses the published timetable for September 15, 2026. Three bus patterns lack mapped shapes and are excluded. The added resident journeys use the roads and clock from their respective scenarios. School escorts count the driver once per leg. The published school and shopping or recreation scenarios serve North Shore destinations and add no crossings at either bridge.

| Bridge and hours | Direction | Recorded resident drivers | Incoming work drivers | Scheduled buses | Added on-site work drivers | Total in replay | March 2025 counter |
|---|---|---:|---:|---:|---:|---:|---:|
| Lions Gate 07:00–09:00 | Toward Vancouver | 5,447 | 25 | 65 | 27 | 5,564 | 5,425 |
| Ironworkers 07:00–09:00 | Toward Vancouver | 4,345 | 26 | 52 | 21 | 4,444 | 8,483 |
| Lions Gate 16:00–18:00 | Toward the North Shore | 7,663 | 31 | 66 | 27 | 7,787 | 5,055 |
| Ironworkers 16:00–18:00 | Toward the North Shore | 7,812 | 35 | 44 | 21 | 7,912 | 9,508 |

With these additions, the morning shortfall at Ironworkers is 4,039 vehicles. Of 9,151 recorded direct drives to work assigned across the inlet from the North Shore and departing between 07:00 and 09:00, 8,826 fit and cross some bridge. Allowing more travel time for the other 325 could only add that many crossings from this departure cohort, even if every one used Ironworkers and reached it in the count window. The 2025 travel survey estimates 12,100 all-purpose southbound trips to Burnaby or New Westminster across all modes and hours. It attributes 95% of those trips to Ironworkers. The weekday assigns 4,330 to those two cities. That comparison isolates a missing destination flow, with no published joint estimate here for purpose, mode and hour. The counters include every motor vehicle, and the replay has limited coverage outside its resident and incoming-work cohorts. [Inspect the Ironworkers replay](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1&bridgePlayback=1&workTransit=flex&outings=fit&walks=fit&recreation=on&schools=on&attendance=on)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bridge_layers
```

##### Alternative bridge routes for the same drivers

**Could drivers use the other bridge?** compares the recorded car-driver trips that start on the North Shore, end at a modeled destination south of the inlet, and belong to North Shore residents. Each trip has the same departure, endpoints and diary time in both scenarios. Directed road times use the mapped speed profile and the existing departure-hour Highway 1 adjustments. To test either bridge, the router removes both bridge cuts, finds the best approach and exit, then joins them using a single southbound crossing. Each end must be within the road profile's connector limit. A route is feasible when the full travel time fits the diary.

The fastest case selects the minimum-time route. The alternative case chooses between feasible routes with weights proportional to exp(−travel minutes / 3). The three-minute scale is a sensitivity assumption. It is independent of the counters and survey. Each route reaches the destination at the recorded end of the trip, with the crossing placed at the corresponding fraction of modeled travel time. Of 30,109 candidate drives, 27,703 fit at least one bridge and 18,878 fit both. The fastest hourly results agree with the existing bridge scorer for the same cohort.

| Southbound, 07:00–09:00 | Fastest route | Allow alternatives | Could use this bridge |
|---|---:|---:|---:|
| Lions Gate | 5,372 | 4,987 | 7,577 |
| Ironworkers | 4,248 | 4,646 | 8,419 |

Allowing alternative routes adds 398 Ironworkers crossings and removes 385 at Lions Gate. The two modeled bridge counts together rise by 13 during the window as crossing times shift. All-day counts retain the same trips. The feasible columns include the same driver at both bridges if both routes fit and both crossings occur during the window. They represent separate upper bounds. The survey's destination breakdown covers daily person trips across modes, including SeaBus. The driver comparison uses it as context for the destination split. Incoming workers, buses, added activities, northbound drives and congestion feedback remain outside this route-choice experiment. [Replay the same resident on both routes](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1&bridgeChoice=6f09a6463ee864dcee5b) · [2025 North Shore Transportation Survey, Table 35](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bridge_choice
```

##### Testing lanes and queues

**Test bridge lanes and queues** replays alternative lane allocations for Lions Gate and Ironworkers. The city clock shows the arrival count, crossings, vehicles waiting and available crossing slots at each minute. The map marks the selected bridge while vehicles are waiting. The chart compares queue lengths across the day. **Jump to the longest queue in these hours** moves the clock to the peak within the selected time window.

The minute inputs use the same directed free-flow routing as the road-speed comparison. The publisher reconciles all 24 hours for each direction to the previous resident and incoming worker benchmarks. It adds buses and the active playable layers using their published crossing times. The model starts with an empty queue at 04:00, adds arrivals at the beginning of each minute and serves up to that minute's lane capacity. A vehicle that cannot cross stays in the queue. The Clojure calculation also runs in the browser through ClojureScript. The experiment keeps each vehicle's chosen bridge and the rest of the weekday fixed. It shows a queue at the crossing and does not model its length along the road or propagate waits into later diary appointments.

The Lions Gate weekday setting sends the centre lane toward Vancouver from 06:00 to 09:30 and toward the North Shore for the rest of the model day. The Province describes the morning change and changes to the afternoon allocation in response to traffic. The fixed schedule approximates that operation. The model uses 1,500 vehicles per hour for one lane and 3,500 for two, based on the historical planning study. Ironworkers uses three lanes per direction and 1,700 vehicles per lane per hour. Its closure scenario removes one southbound lane in the morning window. [Lions Gate operations](https://www.youtube.com/watch?v=EHlODJNkx6o) · [Lions Gate planning study, Figure 2.6](https://www2.gov.bc.ca/assets/gov/driving-and-transportation/reports-and-reference/reports-and-studies/lower-mainland/lions_gate_hwy1_connector_planning_study_summary.pdf) · [Ironworkers lane capacity, Table 4](https://www.highway99tunnel.ca/app/uploads/sites/748/2023/06/APPENDIX-H-Traffic-and-Geometrics-Part-1.pdf)

| Toward Vancouver, 07:00–09:00 | Modeled arrivals | Crossings | Peak queue | Waiting at 09:00 |
|---|---:|---:|---:|---:|
| Lions Gate, weekday counterflow | 5,566 | 5,566 | 525 | 0 |
| Lions Gate, centre lane kept northbound | 5,566 | 3,000 | 2,715 | 2,715 |
| Ironworkers, three lanes | 4,712 | 4,712 | 18 | 0 |
| Ironworkers, one lane closed | 4,712 | 4,712 | 135 | 0 |

The table uses the 2025 workplace fit with the compatible optional layers active, including eastern errands. Some of the Lions Gate queue in the fixed northbound scenario is already present at 07:00. The Ironworkers counter reports 8,483 crossings in the same window. Both Ironworkers lane scenarios finish serving the modeled morning arrivals by 09:00. Adding a capacity limit leaves the missing morning demand unresolved. The Province's separate corridor study estimated through travel at 7% of typical 2017 morning Highway 1 corridor trips. That estimate covers the wider corridor and cannot be used as a current bridge-specific traffic count. [Try holding the Lions Gate centre lane northbound](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&bridge=LionsGateBridge&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1&bridgeQueue=1&lanePolicy=north&workTransit=flex&outings=fit&walks=fit&recreation=on&schools=on&attendance=on&easternOutings=on) · [Provincial corridor study, section 2.4.2](https://www2.gov.bc.ca/assets/gov/driving-and-transportation/reports-and-reference/reports-and-studies/lower-mainland/highway-1-99-north-shore-corridor-study-technical-report.pdf)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bridge_demand
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bridge_layers
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver
```

#### How and when residents commute

**Compare commute modes and times** in the regional bridge panel checks the weekday against the 2021 Census by home municipality. It compares mode shares, departure bands, and travel durations within a mode or departure band. The North Shore combines West Vancouver and the City and District of North Vancouver. The census covers workers with a usual workplace. The simulation counts a private-household employee with a reported usual commute mode if their first paid job stop follows a direct trip from home. That trip uses its diary's dominant travel mode and the duration of the full travel bout. The two populations differ in workplace attendance, multi-stop trips and the reference year. Shares use the published marginal totals, which can differ from the sum of rounded cells. [Statistics Canada table 98-10-0479](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810047901)

| Home and measure | 2021 Census | Simulated direct work trips |
|---|---:|---:|
| Vancouver, share driving | 47.8% | 69.2% |
| North Shore, share driving | 66.3% | 72.4% |
| Vancouver drivers leaving 08:00–08:59 | 27.2% | 22.4% |
| Vancouver transit commutes of 60 minutes or more | 13.8% | 80.7% |

The all-destination simulation margins are identical in the two workplace scenarios. A single diary with a 60-minute transit trip at 07:30 accounts for 9,559 of Vancouver's 16,611 direct transit commutes. The column for trips assigned across the inlet changes with the jobs. In the census-workplace replay, 5,781 of 7,039 direct trips from Vancouver homes to North Shore work sites use a car driver mode, or 82.1%. The census table has no workplace destination breakdown. The across-inlet column shows which weekday assignments could contribute to bridge demand before checking the route. [Inspect Vancouver commute evidence](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=5bea5bc3322eb2bbae9f&bridge=LionsGateBridge&bridgeDirection=1&bridgeWindow=am&bridgeMetric=time&bridgeCommute=1)

```sh
python -m scripts.vancouver_commute_schedule --day 803724fb5af012e0a0c7 --day 7bc1b970083653ba45cd
```

#### Timetable-based transit commutes

Open **Replay commutes timed to transit** from the commute comparison on the census-workplace weekday. The alternate weekday covers the same roster. It checks the first direct work trip for residents whose diary travel bout uses transit and may include walking. The matcher searches the archived September 15, 2026 TransLink timetable for the latest whole-minute departure that preserves the original work start. It uses street walks of up to 800 m at 80 m/min at either end, with at least three minutes between reaching the stop and boarding. The 88 routes cover Vancouver, UBC and the North Shore.

If the resident can leave later, the diary adds time at home between the old and new departures. The work shift, return journey and other activities keep their recorded times and places. The route follower shows the walks, boarding wait, vehicle and any early arrival before the work stop. The comparison measures the scheduled departure-to-work interval, which includes any wait before that work stop.

The transfer scenario permits one change of vehicle at the same GTFS stop or at a stop linked by the feed's transfer table. It checks 5,374 pairs with street walks up to 250 m. It reserves the longer of the published connection time and the street walk plus three minutes. A single-vehicle trip takes precedence when both options depart in the same minute. The example shows a resident leaving at 08:00 for an 08:30 work stop and walking from the 230 to the R2 at Lonsdale Avenue and 3rd Street. [GTFS transfer rules](https://gtfs.org/documentation/schedule/reference/#transferstxt)

| Same 19,903 eligible trips | Original | Single vehicle | Up to one transfer |
|---|---:|---:|---:|
| Later departures | — | 3,508 | 8,768 |
| Departure-to-work intervals of 60 minutes or more | 15,965 | 12,876 | 8,245 |

Of the 8,768 revised trips, 5,819 use a transfer. The builder checks all 1,440 minutes for population conservation. Both scenarios assume on-time service and availability of space on the selected vehicle. [Replay with transfers](http://127.0.0.1:8187/cityday.html?coverage=region&clock=9d719fb51e0efd26e33a&scheduled=1) · [Replay the single-vehicle scenario](http://127.0.0.1:8187/cityday.html?coverage=region&clock=d7129d7ba6fda726f129&scheduled=1)

The replay also sums onboard commuters by bus segment. It estimates route-level capacity by taking the median across fall 2025 weekday observations of average peak passenger load divided by the peak load factor. Among 1,081 runs with a route-level comparison, 45 exceed that estimate using revised work trips alone. The largest modeled load is 528 on one southbound route 10 segment near Granville Street and W 70th Avenue, against about 70 spaces. The estimates describe 2025 routes and give a check on modeled trip concentration. Vehicle assignments and additional passengers would be needed for a 2026 capacity fit. [TransLink 2025 Transit Service Performance Review](https://www.translink.ca/tspr) · [TransLink Transit Service Guidelines, passenger load](https://www.translink.ca/-/media/translink/documents/plans-and-projects/managing-the-transit-network/transit-oriented-communities/transit-services-guidelines-public-summary.pdf)

```sh
python -m scripts.vancouver_transit_commutes ../Simulations/city --workplace-run 5bea5bc3322eb2bbae9f --transfers
```

#### Shared bus space

The bus-capacity replay assigns the same commuter cohort in order of work start, using a seeded draw to break ties. A rider reserves space on each segment of a bus run from boarding to alighting. A transfer receives both reservations together. When one leg is full, the planner searches the dated timetable again for the latest feasible departure via a direct ride or one transfer. The resident keeps the old commute time if every feasible alternative requires leaving at that time or earlier.

The run uses the fall 2025 route-level estimate first and the 2025 annual estimate for routes missing from that table. For the remaining routes it uses 24 spaces, the lowest fall estimate in the input. Fractional estimates round down to whole spaces. All these spaces are available to the revised work commuters in this scenario. The replay sets limits on their bus boardings and retains scheduled train and ferry service. The capacity comparison measures how timing changes under those assumptions. [TransLink 2025 Transit Service Performance Review](https://www.translink.ca/tspr)

| Same 19,903 eligible trips | Transfers without capacity limits | Transfers with bus limits |
|---|---:|---:|
| Later departures | 8,768 | 7,083 |
| Departure-to-work intervals of 60 minutes or more | 8,245 | 9,916 |
| Maximum modeled load on a route 10 segment | 528 | 70 |

The cap uses fall observations for 65 routes, annual observations for six, and the fallback for 12. Of the residents whose preferred itinerary filled, 1,763 could take another itinerary and still leave later, while 1,685 retained their original departure. Across the revised commuters, 63 of 1,203 assigned bus runs reach their limit. The replay follows a worker who switches the connection from route 211 to route 210 after taking route 7. The location readout shows how many timed commuters are aboard the tracked bus and the run's estimated limit. [Replay with bus limits](http://127.0.0.1:8187/cityday.html?coverage=region&clock=25d2b174237ee1eebcfa&scheduled=1)

```sh
python -m scripts.vancouver_transit_commutes ../Simulations/city --workplace-run 5bea5bc3322eb2bbae9f --transfers --bus-capacity
```

### Incoming workers and Downtown's workday

The optional combined weekday adds a municipal workforce cohort to the existing city-resident simulation. The 2021 census subdivision flow extract contains 94,960 people with a usual workplace in Vancouver and a home outside the municipality. Of these, 91,675 live in 27 other Metro Vancouver census subdivisions. The remaining 3,285 have more distant origins and stay outside this daily commute layer. The City of Vancouver and Musqueam 2 are separate census subdivisions in this definition. Switching to the regional resident model changes the population boundary, so the external-worker layer is specific to the municipal replay. [Statistics Canada, Table 98-10-0459-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

Each synthetic worker has a stable index within the home municipality. Home dissemination areas are drawn using the local 2021 counts of workers who commute to a different municipality in the same census division (Profile characteristic 2600). All 27 origins have published support for this distribution. The worker uses an interior point of the home DA for estimating commute distance. This construction preserves the number of workers by origin and uses independently rounded gender subtotals as proportions. The data do not identify the worker’s address or employer.

The City’s 2020 Downtown Social Indicators Profile, “Share of the City” (p. 6), reports 136,625 usual-workplace jobs in Downtown and 240,820 elsewhere in Vancouver in 2016. The corresponding Downtown share is 36.2%. The model transfers that historical destination share to incoming workers. Within each of the two areas it samples 2025 geocoded business licence addresses by reported employees. The municipal day has 4,905 eligible workplace anchors. Without the geographic adjustment, 57.4% of the licence employment weight falls Downtown. Home origin and destination do not identify a particular employer or industry. The historical job share includes resident workers, and its transfer to incoming commuters is an assumption. [City social indicators profile series](https://vancouver.ca/people-programs/research-and-data-toward-a-healthy-city-for-all.aspx)

A second draw uses 3,769 eligible records from the Vancouver CMA hierarchical census public-use file. Donors must work in a different census subdivision within their census division. Within gender and straight-line distance band, person survey weights select a joint age, usual commute mode, home-departure band and commute-duration band. For origins with zero combined published gender cells, the draw pools genders within distance. The specific workplace can influence these attributes through its distance from the home DA. Transit service quality, transfers and destination parking prices are absent from that choice. Taxi and ride-hail use cannot be distinguished in these census commute categories.

For attendance, 64% of participants with a usual workplace outside the home in Vancouver’s fall 2023 survey reported travelling there on their sampled weekday. This city-resident adult rate is transferred to incoming workers. For comparison, all employed participants in the independent urban BC time-use diary split have a weighted on-site-work share of 58.6% in training and 46.5% in holdout. Those broader groups have different workplace arrangements. Within the census departure and duration bands, 226 complete urban BC weekday training commute diaries supply clock times and work-stop sequences. If the joint time cell lacks a diary, the model picks a shift within the departure band and a journey length within the duration band separately. The morning and return legs use the same duration and mode. Within-day gaps between workplace stops stay outside workplace presence. The model repeats a representative weekday across midnight. [City transportation survey, Table 22, p. 87](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

| Weekday window | Resident arrivals / departures | Incoming worker arrivals / departures | Combined arrivals / departures |
|---|---:|---:|---:|
| 07:00–09:00 | 8,327 / 14,785 | 9,658 / 44 | 17,985 / 14,829 |
| 16:00–18:00 | 15,376 / 12,688 | 375 / 9,733 | 15,751 / 22,421 |

The seeded cohort assigns 32,957 jobs Downtown. Across Vancouver, 58,828 of the 91,675 workers attend on this day, including 21,032 assigned Downtown. At noon, 18,536 are in a Downtown workplace stop. The combined flow now points into Downtown in the morning and out in the evening. It counts arrivals and departures at activity endpoints. Incoming transit workers have a usual mode and a travel window; vehicle, station and bridge assignments for these commuters remain unobserved. The independent SkyTrain figures continue to compare station events with the resident riders actually matched to scheduled trains. The next comparison relocates resident workplaces.

The resident-day Raster interval kernel also executes the incoming population clock. Its bins count travelling to work, being at work and travelling home by origin and by workplace inside or outside Downtown. An individual run and a grouped run over 5,591 distinct event sequences matched independent minute-by-minute evaluation of each worker's roster and work intervals on the Intel GPU. Inspecting a worker uses that same roster. Group equality establishes numerical fidelity for the published bins. It does not establish real-world attendance, route choice or spending.

### Resident workplaces outside Vancouver

Under **Rush hour in Downtown**, choose **Include census destinations outside Vancouver**. The clock shows how many city residents are at an external workplace. Choose a destination to inspect a worker or a Vancouver neighbourhood to see the change in its daytime population. The same resident ID links to the population atlas. On a leg with an external endpoint, the replay shows the municipality and diary mode and clears the inferred city street path. The shop-opening, inferred-walk, work-from-home and scheduled-rider experiments use the city-address baseline.

Workplace status comes from the 2021 hierarchical PUMF. The census importer joins each private household to an intact Vancouver CMA donor on tenure and its ordered roster of seven person attributes. For 859 households where multiple different workplace profiles match, it samples one whole profile by survey weight. The usual-workplace pool contains 194,724 employed residents with known gender and a workplace in Canada outside their home. The published positive municipal flow cells sum to 193,970. These counts cover usual workers and do not prescribe daily attendance. [Statistics Canada commuting flows](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

The Clojure model allocates 63,375 external workplaces. Within each gender, dissemination-area quotas follow Census Profile characteristics 2600–2602, bounded by the eligible local population. Missing cells use the citywide outbound rate for that gender. Residents with a cross-municipality donor status get priority. Each destination receives its published total, with its independently rounded gender counts reconciled to that total. Specific destination municipalities are exchangeable within gender after selecting residents. A specific resident’s assigned destination is a draw from that distribution. Metro Vancouver A includes the UBC campus and other places. The original diary supplies the travel times, modes and paid-work stops. Multiple qualifying stops go to the same municipality. The rest of the chain retains its assigned places.

| Modelled outcome | City addresses | Census workplace destinations |
|---|---:|---:|
| Downtown arrivals / departures, 07:00–09:00, including incoming workers | 17,985 / 14,829 | 17,116 / 15,032 |
| Downtown arrivals / departures, 16:00–18:00, including incoming workers | 15,751 / 22,421 | 15,911 / 21,544 |
| Residents assigned external jobs who attend a paid-work stop | 0 | 36,765 |
| Residents at external workplaces at noon | 0 | 30,790 |

At noon the revised geography removes 1,935 residents from the baseline Downtown daytime population. These are changes in where activities happen. The model still needs observations of individual routes, traffic volumes and travel times to validate congestion.

A second census table, held out of the assignment, puts transit at 22.4% among residents with external jobs. The assigned roster has 18.8% usual transit commuters. Among the 33,909 assigned residents with a recorded direct home-to-work leg, 11.8% take transit and 13.1% walk or cycle. The published usual walking-or-cycling share is 3.2%. The two census releases have separately tabulated counts. Usual mode and mode on one diary day also measure different things. [Statistics Canada commuting destination by main mode](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046201)

The Python adapter reads census files and packages the release. `city.vancouver.outbound` owns allocation, the diary comparison and neighbourhood accounting. It uses the existing Raster interval phase to place 3,631 weighted work patterns on the clock. The Intel GPU and JVM reproduced every minute-by-area count. The ClojureScript namespace `city.ui.vancouver.workplaces` renders the release in the browser. A resident is identified within a population release by home dissemination area and roster position. Each scenario refers back to that same resident. The existing Datahike store already gives source entities external IDs and acquisition receipts. A browser store could use those conventions to connect a selected resident, place and scenario to the evidence underlying the replay.

### Paired direct commute modes

The outbound workplace panel can give an existing direct trip between home and a paid workplace the resident’s usual census commute mode. The rule applies in either direction and uses the diary mode when the worker’s usual mode is missing. Stops, trips via school or errands, clock times and incoming workers keep their baseline schedules. Switching the rule updates the selected resident and the hourly Downtown mode counts together. A specific route and the time needed to traverse it remain unresolved. The census records the mode used for the greatest distance on a multimodal commute. Carrying that mode onto a particular weekday and its return journey is a modelling assumption. [Statistics Canada commuting dictionary](https://www12.statcan.gc.ca/census-recensement/2021/ref/dict/98-301-x2021001-eng.pdf)

The comparison counts the first direct home-to-work trip per resident in both replays. The census column covers usual workers with destinations outside Vancouver. Both the all-age and age-specific census mode tables were held out of workplace assignment. Counts below include 215 workers of unknown age in the all-age row. A diary may serve more than one group when age is masked. [Statistics Canada commuting destination by main mode and age](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046201)

| Age | Model workers with a direct trip | Distinct source diaries | Census transit | Diary transit | Usual-mode replay transit |
|---|---:|---:|---:|---:|---:|
| All ages | 33,909 | 229 | 22.4% | 11.8% | 18.1% |
| 15–24 | 3,348 | 4 | 42.8% | 0.0% | 34.7% |
| 25–34 | 8,305 | 24 | 27.5% | 35.1% | 25.1% |
| 35–44 | 8,084 | 55 | 17.7% | 8.9% | 13.4% |
| 45–54 | 6,365 | 66 | 16.4% | 2.5% | 12.5% |
| 55–64 | 6,386 | 63 | 17.3% | 2.1% | 12.4% |
| 65+ | 1,206 | 17 | 15.4% | 4.0% | 14.0% |

Of the 33,909 workers, 15,413 change mode on their first direct trip. Across all direct outbound and return legs, 28,658 change. The combined walking and cycling share falls from 13.1% to 2.9%, versus 3.2% in the census. Cycling alone accounts for 961 diary trips and 372 usual-mode trips. The external-destination census table cannot validate this split. Driving rises from 69.7% to 72.6%, widening the gap to the observed 67.9%. Across the five published categories, total variation distance to the all-age census distribution falls from 12.9 to 4.8 percentage points. This is a comparison of population shares. Predicting a given worker’s trip or travel time requires further evidence.

### Neighbourhood commute calibration

This optional municipal scenario assigns a usual commute mode to the 254,708 private-household residents who already have a known mode. Census Profile counts cover six modes, with walking and cycling reported separately. The adapter sums 1,016 published dissemination areas within the 22 home neighbourhoods. One area has suppressed cells. Independent rounding and differences between the synthetic population and the census produce different worker totals. The fit therefore targets the published proportions within each neighbourhood. [2021 Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/page.cfm?Lang=E&DGUIDlist=2021A00055915022)

The first fit scales the donor mode counts within each neighbourhood by age band, gender and external workplace status, using iterative proportional fitting with a half-person seed per cell. Integer allocation preserves the sizes of these groups and the six neighbourhood mode totals. A second step exchanges mode counts between external and other workers within each neighbourhood until the city's 63,375 external workers also match the five all-age external census proportions to integer precision. It then refits the demographic groups to those counts. Within each group, workers retain their donor mode wherever the integer targets allow. A seeded draw allocates the rest. The external census table combines walking and cycling, so their split for external workers is inferred. [Commuting destination by main mode and age](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046201)

In Grandview-Woodland, the cycling share rises from 2.4% in the donor population to 11.0%, matching the local census control. In Kitsilano it rises from 2.3% to 10.3%. Before incorporating travel times, 44,085 workers change usual mode and 147,130 direct diary legs change mode on the simulated day. The geography and clock times are held fixed across the paired replays.

Fitting neighbourhood totals alone put 27.7% of the 33,909 direct outbound commuters on transit. The joint fit gives 21.6%. The all-age census share of 22.4% is a calibration input for the external worker population. To evaluate how mode shares carry through to the commuting day, the model withholds the age breakdowns from the fit. All rows come from the same census. Across the five published modes, the distance between model and observed shares (half the sum of absolute differences) improves over the original usual-mode replay in five age groups. For ages 65+ it rises from 1.8 to 3.6 percentage points. Attendance, clock times and daily modes still depend on reused diaries.

| Age of outbound commuter | Census transit | Original usual mode on direct trips | Joint fit on the same trips |
|---|---:|---:|---:|
| 15–24 | 42.8% | 34.7% | 39.3% |
| 25–34 | 27.5% | 25.1% | 29.6% |
| 35–44 | 17.7% | 13.4% | 16.6% |
| 45–54 | 16.4% | 12.5% | 15.0% |
| 55–64 | 17.3% | 12.4% | 15.3% |
| 65+ | 15.4% | 14.0% | 17.0% |

The initial diagnostic checked both endpoints of each located, direct commute leg to or from a city job. It compared straight-line distance with the diary travel window at the city model's nominal speed. At 75 metres per minute, 25,784 of 32,923 fitted walking legs exceed that budget (78.3%). At 220 metres per minute, 4,310 of 11,904 fitted cycling legs exceed it (36.2%). The original diary replay exceeds the same budgets for 1,432 of 18,516 walking legs and 34 of 5,273 cycling legs. A street route can require additional time even when a leg passes this check. External jobs lack precise endpoints and are excluded. This motivated the street-network comparison below.

### Fitting active commutes to the street network

For each direct trip between home and a paid workplace in the city, the model compares the diary window with the shortest available walking or cycling route at 75 or 220 metres per minute. Routes include access from each endpoint to the nearest network node. Cycling follows connected OSM ways with directed access, including cycleways and public streets. Explicit bicycle access and bicycle one-way exceptions take precedence. The graph omits steps, dismount sections, motorways without explicit access and unmarked footpaths. The archived ways omit point barriers, turn relations and some paths. Route costs use distance alone, so passing the check establishes feasibility under those assumptions. A rider's preferred route, hills, signals and observed travel speed can change the time needed. [OSM bicycle access](https://wiki.openstreetmap.org/wiki/Key:bicycle) · [Bicycle direction tags](https://wiki.openstreetmap.org/wiki/Key:oneway:bicycle)

The Clojure assignment can exchange mode slots between two or three workers in the same home neighbourhood, age band and gender who use the same diary template. It minimizes how many active commute legs exceed the time available, then minimizes the number of residents who change mode. Each worker retains their home, job, diary, travel windows and attendance. Each cohort retains every mode count, so the hourly citywide mode totals and the age comparison for external workers carry over. The selected mode can change the number of trips by mode crossing the Downtown boundary because workers with the same diary can have different workplaces. Workers with an external job or an unknown endpoint on a direct leg keep the previous assignment.

The municipal bicycle graph has 119,692 nodes and 26,198 ways. The fit exchanges mode assignments for 11,612 residents. The comparison below uses the same 32,923 walking legs and 11,904 cycling legs before and after spatial fitting. A leg can fail because its route is too long or because the network has no connection inside the time budget.

| Direct legs with located city endpoints | Before fitting to routes | After fitting to routes |
|---|---:|---:|
| Walking legs without a route inside diary time | 28,321 (86.0%) | 22,962 (69.7%) |
| Cycling legs without a route inside diary time | 5,914 (49.7%) | 2,467 (20.7%) |

These are fit diagnostics. The remaining walking failures show how much the fixed job locations and diary schedules constrain the result. The optimizer preserves neighbourhood mode counts but can change which household travels by each mode. Bicycle ownership, disability and access to a household car remain unobserved here.

An external comparison gives a different view of the day. Among all modelled residents with known usual modes, including those with external workplaces, direct cycling legs average 32.5 diary minutes and transit legs average 30.9. The City's 2023 survey estimated 24.8 minutes by bicycle and 39.2 minutes by transit for home-based work trips. Those figures come from routing respondents’ trips at the reported time of day. They were excluded from the model fit. The synthetic durations still reflect a modest collection of shared diaries. [Vancouver Transportation Survey, figure 64](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

Both the route inspection and bicycle exploration use the published street graph. A selected fitted active trip that cannot complete its known route in the available time shows its route and reports an unresolved position. For disconnected endpoints it reports that a connected route is unavailable. Regional areas still use their separate published network.

### Matching walking commuters to existing workplaces

The paired workplace scenario uses the fitted walking population. It holds the mode, home, diary and workplace neighbourhood fixed. It can move workers between the 2025 licensed job addresses already occupied by workers in the same broad occupation. Each address keeps the same number of assigned workers in each occupation. Those counts come from the baseline simulation. The licence register supplies locations and employment weights but does not identify which sampled residents work at a specific business.

The model includes all 32,923 direct walking legs with known city endpoints in the comparison. Of the 19,099 workers making them, 11,258 have a known occupation, one job slot and a schedule in which all trips touching work are accounted for by direct home–work travel. Multiple home stops can refer to the same address. An intervening shop or school trip, multiple job slots, or an unrecorded journey across a work-stop boundary makes that worker ineligible for reassignment. Their legs remain in the reported denominator.

Clojure groups eligible workers by their existing workplace neighbourhood and 2021 Census PUMF occupation code (NOC21 groups 1–10). For each group it scores candidate sites using the shortest pedestrian-network distance, including access from both addresses. The cost first minimizes the number of legs exceeding their diary time at 75 metres per minute, then minimizes the number of people changing sites. A candidate that would lose a previously feasible leg is excluded. SciPy solves the resulting linear assignment using each existing job slot once. The scarcity of a specific skill or opening at a business is unknown. On-site staffing at a particular minute can change as the exchanged workers can have different shifts. Home-to-work neighbourhood flows and the Downtown arrival and departure counts remain fixed.

| Walking legs without a route inside the diary time | Legs | Share of 32,923 |
|---|---:|---:|
| Original fitted modes and workplaces | 22,962 | 69.7% |
| After the capacity-preserving assignment | 20,897 | 63.5% |
| Nearest of all licensed sites in the assigned workplace neighbourhood | 18,610 | 56.5% |
| Nearest of all 4,905 licensed sites anywhere in the city | 175 | 0.5% |

The assignment moves 2,362 workers and recovers 2,065 walking legs. A worker can move to free a slot for another worker. The last two rows are optimistic bounds, computed independently for each leg with unrestricted occupation and capacity. They quantify the geographical constraint on this particular synthetic day. They provide no evidence that a particular worker could obtain employment at the nearest site. Testing the residential and workplace zones against the City's observed home-based work trip patterns would address the largest remaining constraint. The survey uses its own zone boundaries. [Vancouver Transportation Survey, section 6.4 and Table 18](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

Select **Compare a workplace change** in the neighbourhood commute panel to follow an affected resident. Switching the commute rule between the fitted modes and matched workplaces compares their assigned addresses at the same minute. The change applies throughout the work stop as well as on its approach and return trip.

### Travel within the home zone

How often do both ends of a trip fall in the zone where the resident lives? The City's 2023 survey reports this separately for direct home–work trips, other home-based trips and trips between two non-home stops. Home–school trips are excluded. The simulation compares one weekday with these 27 held-out shares. For example, a trip from a Downtown workplace to a Downtown restaurant counts as local only if both places are in the resident's own home zone. The other home-based category includes shopping, visits and several other activities. [City survey, Table 18 and footnote 34](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

| Home zone | Work, survey / model | Other home-based, survey / model | Between non-home stops, survey / model |
|---|---:|---:|---:|
| CBD – West End | 29% / 23.2% | 53% / 33.3% | 19% / 12.4% |
| CBD – False Creek | 32% / 5.5% | 47% / 11.5% | 37% / 1.4% |
| Vancouver Broadway | 21% / 5.4% | 49% / 13.1% | 21% / 2.0% |
| Vancouver South | 6% / 20.3% | 40% / 33.5% | 12% / 12.8% |
| Vancouver Kerrisdale | 13% / 32.0% | 46% / 43.4% | 13% / 21.3% |
| Vancouver Kitsilano | 12% / 31.2% | 54% / 38.6% | 19% / 18.6% |
| Vancouver Southeast | 4% / 27.4% | 38% / 44.5% | 9% / 21.2% |
| Vancouver East | 3% / 34.2% | 36% / 49.4% | 4% / 26.1% |
| Vancouver Port | 16% / 11.9% | 41% / 18.1% | 16% / 5.5% |

The estimates use city residents in private households. Residents aged 20 and over have weight one. Residents in the 15–19 age bin have weight 0.4 to approximate ages 18–19. The resulting population is 561,159.6 adult equivalents, including 109 without a classified home zone. Each trip contributes the resident's weight. A direct paid-work leg uses the same diary classification and census external destination as the workplace inspector. An external job is outside every city home zone. Among known home zones, 409,341.2 other home-based trips have classified endpoints and 33,679.6 have an unresolved endpoint. For trips between non-home stops the corresponding counts are 146,962.6 and 22,687.8. The table divides by classified trips. Unclassified trip purposes, open-ended journeys at the diary boundary and residents of unknown age are excluded. The model and survey represent different years.

The zone assignment overlays model addresses on a public traffic-analysis geography. The nine groups resemble the regional planning map, with differences from the City's reported land areas. East covers 21.24 km² in this overlay and 20.10 km² in the survey. Port covers 7.24 km² and 8.08 km² respectively. The optional filter excludes residents and city trip endpoints within 200 m of another group's polygon. Under that filter East's simulated home–work share is 33.8% and False Creek's is 5.1%. The divergent errors persist. Excluding the edge strip cannot resolve a systematic boundary change or survey sampling uncertainty. [TAZ source and regional map](../DATA.md)

The within-neighbourhood workplace reassignment changes the False Creek home–work estimate from 5.1% to 5.5%. Across all city residents, just 8,664 simulated direct trips have a job endpoint in False Creek. Its own residents make 39,425 classified work trips. Even assigning all 8,664 to them would put only 22.0% within their home zone. The survey's 32% would correspond to approximately 12,616 local trips at the modelled volume. An assignment that preserves workplace-zone trip totals therefore cannot reproduce that estimate. This bound concerns trips by city residents. Counting job positions or including incoming commuters would answer different questions.

For shop scenarios, False Creek's low proportion of local non-work trips also makes raw simulated footfall a weak basis for comparing candidate storefronts. [Explore the comparison](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=sites&zones=other)

An independent check compares the day builder’s licence employee weights with people counted by the census at their usual place of work. It uses complete tract counts wherever at least 99% of a tract's mapped land falls in one survey zone. This gives 114 tracts across nine zones. In the eight qualifying False Creek tracts there are 18,245 census workers and 37,360 employees reported on geocoded licences used by the model. In the 20 Vancouver East tracts those figures are 16,825 and 45,957. These are subset totals. The 2021 census reflects pandemic work patterns, while the licence data cover businesses reporting positive employee counts in 2025. The two sources can be compared at a workplace location without assuming that every worker commuted on the simulated day. [Census by workplace tract](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801) · [Reproduce the comparison](../DATA.md)

### Assigning workplaces across census tracts

The original weekday projects a travel distance in a random direction and chooses among the five nearest licensed workplaces, weighted by their employee counts. This can produce very different numbers of workplaces occupied in each tract from those reported in the census. The paired scenario starts with the matched walking workplaces, the fitted commute modes and the same residents' complete schedules. Its input is the 2021 Census count of people with a usual workplace in each tract of work. Applying these shares to city-resident weekday attendees assumes their workplace distribution resembles that of the entire usual-workplace population. The census includes incoming workers and records usual jobs across weekdays. The nine-zone travel-survey shares are reserved for comparison. [Census table 98-10-0498-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801)

The scenario identifies 197,349 city residents in private households with a paid-work day at one located municipal job address. It fits 188,248 across 122 tracts with a licence site, a published count and at least 99% of tract land inside the municipal study area. Four further city tracts have 2,850 census workers between them and no supported site. External jobs keep their assigned municipality. Within the comparison cohort, 57,721 workers keep their addresses because of work-linked walking or cycling, incomplete locations or modes, unrecorded travel between adjacent stops, or ambiguous workplace slots.

The allocator first scales tract totals to the attending cohort, respecting fixed workers in each tract. It then minimizes the distance between origins and destinations of job transfers, using tract centres weighted by licensed employment. For an individual move it draws up to four licence-weighted addresses per destination pass. Among feasible proposals it favours the smallest change to home–work distance. A transfer must fit every known leg touching paid work at the model's nominal speed, or shorten or preserve any leg already over budget. Distances for this check are straight line. The allocator tries remaining surplus and deficit tract pairs in order of distance. Its 87,639 accepted moves leave 6,878 of the constrained target places unfilled. Some feasible assignments may escape this search. Occupation-specific job openings and transit timetable feasibility are unresolved.

Among 176,834 journeys linking a moved workplace to another stop, 6,614 exceed their straight-line travel-time limit at the previous address and 1,689 at the assigned address. Every journey that previously fit still fits this check. The published scenario stores these counts by mode alongside its tract totals and source digests.

| City residents’ trips crossing the Downtown local-area boundary | Matched walking workplaces | Census tract workplaces |
|---|---:|---:|
| Arrivals, 07:00–09:00 | 7,458 | 19,725 |
| Departures, 07:00–09:00 | 14,988 | 12,679 |
| Arrivals, 16:00–18:00 | 15,536 | 14,653 |
| Departures, 16:00–18:00 | 11,811 | 23,832 |

At noon the new assignment places 24,434 additional city residents in Downtown. The rush-hour figures count residents' trips for all purposes and use the diary's arrival and departure times. The geography of the incoming-worker cohort is held fixed if it is added in the inspector. An independent reconstruction from the resident plans reproduced every minute of occupancy and every hourly flow count by mode, direction and home neighbourhood.

The average absolute error across the nine held-out home–work shares falls from 17.7 to 8.4 percentage points, weighting each zone equally. False Creek rises from 5.5% to 21.9% (survey 32%), Vancouver East falls from 34.2% to 17.3% (survey 3%), and Broadway rises from 5.4% to 13.5% (survey 21%). After excluding endpoints within 200 metres of another zone, the new False Creek estimate is 16.8%. Survey sampling, the approximate boundaries and the different reference years matter to interpretation. The large remaining error in other home-based trips persists because their endpoints keep their original addresses. Retail footfall still needs an independent check. [Travel survey, Table 18](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF) · [Inspect a paired weekday](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&zones=work&downtown=am&minute=720)

Of the original 4,828 walking grocery occasions, 1,419 begin or end their shopping outing at paid work. For 249 of those, the census assigns the workplace outside Vancouver and the model lacks the street address needed to evaluate the shop detour. Among the remaining occasions, the tract assignment preserves every shopping outing's adjacent addresses. This is a concrete coverage difference between the original shop experiment and the census-workplace weekday.

### When residents leave for work

Among city residents in private households, 254,708 synthetic workers are employed and report a usual commute mode. On the replayed weekday, 141,167 have a recorded trip from home to their first paid job stop. Of those, 6,020 make at least one intervening stop. Another 107,026 have no stop classified as a paid job away from home and 6,515 have a first job stop without a complete recorded journey from home. Paid work at home or at a location classified as a café or school does not qualify as a job stop here. The model includes people with a masked age when their reported employment and commute mode establish that they belong to the adult census universe.

| Time leaving home | Vancouver 2021 census | Simulated weekday |
|---|---:|---:|
| 05:00–05:59 | 3.9% | 5.5% |
| 06:00–06:59 | 12.7% | 9.4% |
| 07:00–07:59 | 22.0% | 32.3% |
| 08:00–08:59 | 25.2% | 20.0% |
| 09:00–11:59 | 22.3% | 20.5% |
| Noon to 04:59 the following morning | 13.9% | 12.4% |

The census denominator is the published 233,960 usual commuters. The model denominator is the 141,167 traceable departures on one synthetic weekday. Both hour and home geography matter. The 07:00 hour is overrepresented in all 22 neighbourhoods, with excess shares from 6.2 percentage points in Fairview to 13.1 in Shaughnessy. For people living Downtown, the model gives 32.8% during the 07:00 hour and 20.8% during the 08:00 hour. The corresponding census shares are 21.0% and 29.8%. Those results concern the time people leave home for any work destination. The separate Downtown flow panel measures arrivals and departures at Downtown endpoints.

The 07:30 minute alone accounts for 20,935 city commuters. Of those, 9,559 follow the same diary. The browser can follow one of them using the population release, home dissemination area and roster position. The regional build adds UBC and the three North Shore municipalities. Vancouver and each North Shore municipality use their published counts when shown individually as municipalities. For neighbourhoods, campus and the combined regional footprint, both columns use the DAs with a complete, positive published denominator. The regional comparison covers 1,328 of 1,337 DAs. Random rounding can make local shares sum to a value other than 100%.

The census clock measures *usual* departures in 2021. The simulation schedules use individual BC weekday diaries from 2022. The comparison detects an early peak and repeated donor times. It does not identify the true minute-by-minute distribution or establish when a particular resident would leave for work. [City departure comparison](http://127.0.0.1:8187/cityday.html?departures=) · [UBC departure comparison](http://127.0.0.1:8187/cityday.html?coverage=region&departures=UBC%20Vancouver%20campus)

### Matching a complete weekday to household commute times

Select **Match household commute times** under **When residents leave for work**. The comparison shows the original and alternative weekdays alongside the Census Profile. Select a home area to follow a worker whose departure changed. The population atlas opens that person's revised activity diary and links back to the same replay. For example, a Downtown resident leaves at 07:35 in the original day and at 08:30 in the alternative. The regional comparison includes UBC and the three North Shore municipalities. [Inspect the Downtown worker](http://127.0.0.1:8187/cityday.html?clock=2fe13bee5dc4d8d7c840&departures=Downtown&da=59150777&person=504&minute=510) · [Open UBC](http://127.0.0.1:8187/cityday.html?coverage=region&clock=625e434c6613fb2df841&departures=UBC%20Vancouver%20campus)

The model joins each synthetic private household to its 2021 Vancouver CMA microdata donor by tenure and the ordered person attributes already used for workplace status. It transfers the household's joint vector of usual departure bands. Among city households, 1,878 matches permit more than one such vector. These get a seeded draw weighted by the source household weights. The code retains the day of each worker with a traceable commute who already leaves in their household donor's band. For the others it searches the urban BC worker training diaries for the same donor age band, ordered place types, paid job stops, travel connections, main modes and trip durations. It samples a compatible complete day in the requested departure band using the original diary weights.

Within each home neighbourhood, candidates are visited in seeded random order. A substitution takes place while the original time band is overrepresented and the proposed band is underrepresented relative to the household donors of these traceable workers. The published neighbourhood Profile counts enter only in the comparison. Both products come from the 2021 census. The Profile's usual departure bands and a single 2022 diary day describe different quantities. The model assigns days person by person after transferring household information. It has no constraint that synchronizes two household members at school drop-off or at a shared ride.

| City comparison | Original | All compatible matches allowing longer trips | Neighbourhood balance allowing longer trips | Neighbourhood balance with fixed trip lengths |
|---|---:|---:|---:|---:|
| Workers receiving a different diary | 0 | 26,186 | 8,651 | 2,653 |
| Mean absolute error across six Profile shares, percentage points | 3.97 | 4.02 | 3.18 | 3.71 |
| Departures at exactly 07:30 | 20,935 | 20,271 | 19,515 | 20,331 |

Allowing longer trips brought the mean daily travel time of the 8,651 changed workers from 47.4 to 102.2 minutes at the same addresses. The selectable alternative fixes every trip duration. All 22 neighbourhoods improve on the six-band measure. In the expanded region 3,462 residents change diaries and the error falls from 3.75 to 3.48 percentage points. Among the 2,653 changed city residents, mean daily travel stays at 43.3 minutes, mean paid work rises from 527.6 to 540.4 minutes and mean sleep falls from 528.7 to 474.3 minutes. These collateral changes come from adopting another complete diary. Further evidence about sleep and work schedules would be needed to judge their accuracy.

Of 141,167 traceable city workers, 30,786 already match their household band, 103,138 have no compatible diary for that band, and 4,590 have a candidate that the neighbourhood rule retains on the original schedule. Diary 91, a 25–34-year-old worker commuting by transit and returning as a car passenger, has no other worker diary of the same age band with that combination of stops and modes. It accounts for 9,559 city departures at 07:30 in both runs. A richer supply of locally timed travel or activity chains would most directly address that spike. The scheduled transit comparison applies to the original clock.

The city shop calculation reruns the complete walking-grocery evaluation on the revised diaries. The 4,828 grocery occasions, feasible visits and store choices are identical across all 964 potential openings. The changed commuters supply no difference in the modelled walking grocery outings. That result is specific to the model's walk–shop–walk eligibility rule. It does not measure the effect of commuter traffic on walk-in trade. [Open 2541 Kingsway on the matched day](http://127.0.0.1:8187/cityday.html?clock=2fe13bee5dc4d8d7c840&shop=4654)

### Advance voting access

The combined municipal weekday replays March 26 and April 1, 2025, with arrivals from 08:00 to 20:00. Each date compares the single advance poll at Vancouver City Hall with a hypothetical layout that adds the West End, Dunbar, Trout Lake and Killarney community centres. The City operated these four centres on general voting day. The scenarios use the City's reported advance staffing for each date, nine and fifteen registrars respectively. City Hall keeps all staff in the single-site case. Five sites get three each on April 1. On March 26 all sites get one registrar and the four busiest by planned arrivals each receive one more. The registration model uses the City's general-election planning benchmark of 25 voters per staff-hour and assumes five more minutes to mark and cast the ballot. People already in the queue can stay after closing when their diary permits. [City review, Tables 1 and 2](https://council.vancouver.ca/20250520/documents/r3.pdf) · [Official voting locations](https://opendata.vancouver.ca/explore/dataset/voting-places-2025/table/)

The model draws two disjoint cohorts from private-household residents aged 20 and over. Its cohort sizes use the City's preliminary count of 2,876 on March 26 and 4,795 on April 1. These add to 7,671. The official ballot account and anonymous ballot CSV pool the advance dates, with a final total of 7,678. Cohorts use relative neighbourhood turnout from the City's Saturday map as a geographic proxy. The age threshold uses the atlas's first unambiguously adult band. Citizenship, registration status, voting preferences and observed individual polling times are outside the model. [City review, Figure 1](https://council.vancouver.ca/20250520/documents/r3.pdf) · [Official ballot account](https://council.vancouver.ca/20250415/documents/r9.pdf) · [City statement on the daily counts](https://vancouver.citynews.ca/2025/04/02/vancouver-byelection-advance-voting-record-turnout/)

Each visitor seeks a round trip in an uninterrupted block of home leisure or media time. Recorded work, school, care, sleep and trips stay fixed. The route builder also reserves the combined weekday's reconstructed walks, discretionary tours and optional workplace lunch outings. The two layouts for each date use the same preferred arrival minute per person, drawn across opening hours. The model favours a walk of up to 20 minutes each way when it fits. Otherwise it considers driving for residents with a recorded driving episode and direct rides from the combined weekday's September 2026 TransLink timetable. Driving allows up to 35 minutes each way and transit up to 50, including stop access, waiting and egress. Transit assumes room on each vehicle. City Hall's published point attaches to the main pedestrian network 15 metres away. The same facility point marks the map in both layouts.

Registration is first come, first served at each site. A voter whose time budget expires returns home. The model uses the observed counts as workloads. The simulation reconstructs less than one-third of the preliminary volume at City Hall on either date. April 1 loses 2,377 of 4,795 to the schedule and travel-time constraints before entering the queue, and another 1,067 have no route in a modeled mode. March 26 loses 1,428 of 2,876 to the first constraint and 646 to the second. The historical reports do not provide advance queue measurements or individual arrival times. The queue and travel estimates illustrate the effects of those modeled constraints. Raster independently reproduces each occupancy change at individual and grouped fidelity and verifies 662,248 residents at every minute.

| Date | Scenario | Reach a poll | Cast a modeled ballot | Leave before voting | Median travel |
|---|---|---:|---:|---:|---:|
| March 26 | City Hall | 802 | 792 | 10 | 20 minutes |
| March 26 | Five sites | 1,024 | 915 | 109 | 26 minutes |
| April 1 | City Hall | 1,351 | 1,343 | 8 | 18 minutes |
| April 1 | Five sites | 1,717 | 1,562 | 155 | 26 minutes |

Five sites add 222 reachable voters on March 26 and 366 on April 1. Among voters who can attend in either layout, 383 and 678 respectively travel less with five sites. The larger overall median includes the added travellers and changes in mode. Splitting staff raises the modeled peak registration line at City Hall from 78 to 83 on March 26 and from 109 to 164 on April 1. These peaks occur within four minutes of closing in all four simulations. Time-resolved field observations would be needed to verify the peak. Choose a site to follow a voter and inspect live arrivals, ballots and queue length. [Open the combined weekday with five polling sites](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&votingRun=8c4f445fc25f421a7771&votingDate=2025-03-26&votingLayout=centres&votingSite=200&minute=1196#voting)

**Reschedule housework** lets people who could not fit a visit move recorded household tasks by up to 60 minutes. The search uses the same continuous period at home and packs intact tasks around the round trip in their original order. It uses at-home media and leisure minutes for the extra travel and polling time. Work, education, sleep, care, meals, separate trips and protected outings delimit the available periods. The model minimizes the total change in task start times after scheduling registration and the return trip. The shift limit is a sensitivity assumption. The source diaries supply household tasks and their lengths, and published activity-scheduling research motivates testing schedule flexibility. [Statistics Canada Time Use Survey](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001) · [Manser et al. on resolving schedule conflicts](https://doi.org/10.1007/s11116-022-10330-8)

| Date | Layout | Additional people who reach a poll | Modeled ballots with rescheduling | Household tasks moved | Median task shift |
|---|---|---:|---:|---:|---:|
| March 26 | City Hall | 109 | 881 | 148 | 26 minutes |
| March 26 | Five sites | 130 | 997 | 174 | 30 minutes |
| April 1 | City Hall | 159 | 1,483 | 227 | 23 minutes |
| April 1 | Five sites | 191 | 1,684 | 265 | 30 minutes |

With rescheduling, City Hall reaches about 31% of preliminary ballots on either date. In the April 1 cohort, 50 more employed residents can reach City Hall, from 715 to 765 of 3,094. For other residents, 109 more can reach it, from 636 to 745 of 1,701. City Hall’s modeled peak registration line rises from 78 to 110 on March 26 and from 109 to 152 on April 1. These visits all start and end at home. **Follow a rescheduled task** takes the clock to a changed household activity at its original home. Reloading the shared link restores the person, time and schedule setting. [Try the April 1 housework comparison](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&votingRun=4b96089e878ef603a0c1&votingDate=2025-04-01&votingLayout=hall&votingSchedule=flex&votingSite=200&minute=1020#voting)

**Also stop on the way home** searches mapped walks and drives from work, an errand or another diary location that already end at home. It tries these detours for residents who still lack a home-based plan after allowing housework to move. It starts at the original address and departure minute, using the Census-tract assignment for a revised city workplace. The recorded mode applies to both legs. Total polling time and travel must fit inside the recorded trip and at most 30 minutes of immediately subsequent leisure or media time at home. The model keeps the polling site's queue and routes each leg in its actual direction, including one-way streets. TransLink documents this pattern for shopping and other stops. The 30-minute allowance and polling participation are scenario assumptions. [TransLink trip chaining observations](https://www.translink.ca/-/media/translink/documents/about-translink/customer-service/trip-diary/2011-metro-vancouver-regional-trip-diary--analysis-report.pdf)

| Date | Layout | Additional people able to reach a poll | Directly from work | Modeled ballots with detours |
|---|---|---:|---:|---:|
| March 26 | City Hall | 169 | 105 | 1,046 |
| March 26 | Five sites | 195 | 119 | 1,145 |
| April 1 | City Hall | 297 | 187 | 1,766 |
| April 1 | Five sites | 355 | 222 | 1,937 |

The modeled City Hall result reaches about 36% of the reported March 26 count and 37% of the April 1 count. Almost all added trips are drives. This comparison covers mapped City of Vancouver walking and driving legs. Transit and bicycle returns and jobs outside Vancouver remain outside the detour search. The original movement interval is replaced by the new two legs and stop in the city clock and street playback. If a voter can get home early, the replay shows them there during the unused part of the original journey. All variants preserve 662,248 residents at every minute. [Follow a stop on the way home](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&votingRun=f8122d1ddd2dd1e5d1ec&votingDate=2025-04-01&votingLayout=hall&votingSchedule=on-way&votingSite=200&minute=1020#voting)

Under **Recorded ballot patterns**, the anonymous 2025 by-election file provides a citywide reference for ballot choices. Among 67,962 ballots, 65,011 recorded two candidate marks, 2,894 recorded one and 57 had zero recorded marks. The City encodes overvoted ballots with all zeroes, so the last group can also include overvotes. Lucy Maloney and Sean Orr were the most common pair, appearing together on 23,655 ballots, including 2,690 of the 7,678 advance ballots from both advance days. The advance comparison pools those days. Candidate marks have no home geography or household attributes. [City ballot data and encoding](https://opendata.vancouver.ca/explore/assets/anonymous-ballot-marking/) · [Official ballot account](https://council.vancouver.ca/20250415/documents/r9.pdf)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_voting --joint 5ab7efac0ffa7e618e13
python -m scripts.vancouver_ballots
```

### Saved shop openings

Choose **Play a shop opening**, select a storefront and set the clock within its hours. **Open shop now** in the scenario panel records the effective simulation minute. Eligible visits still have to fit the opening hours and both travel legs. The decision applies only when the inbound leg starts at or after the opening minute. A shopper who has set off keeps their destination even if they would arrive after the opening. The simulation preserves the published diary activities and travel windows. The street view updates the cumulative arrivals at the shop as the clock advances.

**Visit from street** places you at the selected storefront’s estimated walking access. You can also walk, cycle or drive up to a sign and select **Inspect storefront**. During opening play, **Open shop here** uses the same simulation clock and saved actions as the scenario panel. It is available within 25 metres along connected streets.

The City’s storefront inventory locates shops at parcel centres. Street access uses a segment permitted for your travel mode with the same name as the civic address, within 80 metres of the parcel centre. That rule locates 907 of 964 candidate storefronts for walking, 907 for cycling and 929 for driving. The median distance from a parcel centre to its estimated access is about 30 metres. Signs mark the estimated access. The market model still uses the original parcel locations for its demand calculation. Sites without a street match can still be inspected and tested in the market panel. [City storefront inventory](https://opendata.vancouver.ca/explore/assets/storefronts-inventory/) · [Visit 2693 East Hastings Street](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&shop=3738&shopPlay=1&minute=720#market)

You can open several shops on the same weekday. Each occasion chooses among the eligible shops that have opened by its departure. The catalogue compares each proposed shop with the existing grocers. Among proposals that beat the incumbent, the model chooses the shortest combined travel time. Ties use opening time and storefront ID. **Reset opening** removes the selected action and recalculates demand for the remaining shops. **End play and compare hours** returns to a single hypothetical opening for the selected shift.

Saving a storefront records its allocated visits and every opening in the playthrough. The record links opening minutes, planned hours, the published market, and resident and visit IDs. The city library restores those choices using the same versioned catalogue. Saved openings remain available after a reset. [Play the East Hastings storefront at noon](http://127.0.0.1:8187/cityday.html?shop=3738&shopPlay=1&minute=720)

Open **Saved shop openings** in the grocery panel and choose **Save this opening**. The save records the storefront, hours, optional basket amount and each predicted visit. A visit refers to the synthetic resident, the diary slot and arrival minute. For a diverted visit it also identifies the grocer the resident would have used before the opening. Saving the same opening and assumptions again updates its saved time. Zero-visit openings can be saved and compared.

The original municipal day gives 45 visitors to 2541 Kingsway at 08:00–20:00 and 13 at 10:00–18:00. Save each opening and select the other in **Compare with**. Thirteen residents appear in both and 32 appear only under the longer hours. **Show shoppers** lets you inspect a resident from either group and follow their visit in the applicable street replay. Counts distinguish people from visits when a resident has more than one shopping occasion. Comparing different population draws shows visit totals because a roster position can designate a different synthetic person in each draw. [Try the Kingsway opening](http://127.0.0.1:8187/cityday.html?shop=4654&hours=full)

For a changed shopping occasion, **Follow this visit** shows the proposed shop. **Replay with existing grocers** opens the same resident and arrival minute in a second tab, using the same grocery catalogue and travel assumptions. It removes every proposed opening from the reference day. A diverted shopper appears at the grocer they would have used. When a purchase is newly feasible by the tested mode, the reference keeps the original activity and uses the model’s original assigned locations. Rewind either clock to inspect the approach.

Datahike persists the experiment in IndexedDB at the browser origin. Its shared Clojure and ClojureScript schema links openings, simulation runs, storefronts, residents and visits through external IDs. The resident ID includes the city, population release, home dissemination area and roster position. The experiment ID includes the scored market release, workplace rule, storefront, hours and basket assumption. The browser loads the database code when the saved-openings panel is first used. Transactions from different tabs take an origin-wide lock and reacquire the persisted head before querying or writing.

A replay link carries the SHA-256 of the scored grocery catalogue. Each archived catalogue identifies its population, weekday, street network and any household clock or workplace assignments. The replay reads those versions directly. The saved result retains its original meaning after the current simulation changes. The city-day map and population atlas can exchange a selected shopper and minute with the same market release. A replay link can open in another browser that has access to the published assets. The list of saved experiments belongs to the browser profile that saved them. Saving and replaying an archived catalogue use HTTPS or localhost for browser storage locks and hashing.

The JVM evidence store continues to hold source records and acquisition receipts. The new browser database covers saved municipal grocery experiments. Population rosters, movement arrays and map geometry are read from their simulation releases. [Shared experiment schema and queries](../src/city/experiment.cljc)

### Setting shop hours and checking diary support

Choose **Custom hours** to set an opening and closing minute, or **24 hours** for continuous opening. A closing time earlier than the opening time falls on the following day. The complete shopping stop must fit within one opening interval. Each surrounding walk still has to fit its own diary time and the combined walking budget. Existing grocers use an assumed 08:00–20:00 schedule. Each alternative can draw a visit outside those hours if its walks fit. The resident keeps the time and length of the original shopping activity. Archived markets scored only for daytime can replay any interval within their original coverage.

At 488 Robson Street the municipal simulation assigns 41 walking grocery visits to the 08:00–20:00 opening, 16 to the 20:00–08:00 opening and 57 to continuous opening. All 16 evening shoppers arrive at 20:10 and stay 30 minutes. Closing at 20:40 admits the entire group. Closing at 20:39 admits none of them. [Follow an evening shopper on Robson Street](http://127.0.0.1:8187/cityday.html?marketRun=7b302c6fe8b3c2f1dafe2145139972aeda8663b7112f5d2d61ee41e41aa19d62&shop=2726&hours=20:00-08:00&da=59150757&person=94&visit=1&minute=1210)

Citywide, 125 of the 4,828 located grocery occasions fall outside the assumed hours of existing grocers. All 125 reuse one urban BC time-use diary. Of those, 123 can reach at least one candidate site. Each site represents a separate experiment on the same people. Opening from 22:00 to 06:00 yields zero visits throughout this run. Real late-night demand remains unmeasured. **Who would visit?** reports how many source diaries supply the shoppers for the selected storefront and hours.

### Exploring a street among resident pedestrians

Enter **Walk here**, **Drive here** or **Cycle here** in Vancouver or the regional replay. The player starts on the nearest permitted street segment and faces along it. Hold **W** or **↑** to move, **S** or **↓** to brake, and use **A** and **D** or the arrow keys to queue a turn. Use **R** or **Turn around** where travel is permitted in reverse. Movement and the simulation clock have separate controls. [Drive along Robson Street at 08:00](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&street=drive&camera=eye&at=-123.117576,49.279893,135&minute=480)

In **Eye level**, drag the map to look around, use **Q** and **E** to look left or right, or **C** to face forward. The camera sits 1.25 m above the routed surface when driving, 1.55 m when cycling and 1.65 m when walking. Switch off **Eye level** for the raised view with a player marker. **Overhead** looks straight down. The eye-level road widths and actor shapes are schematic. Buildings use the same mapped footprints and available heights as the map. Tunnel interiors and slope effects on player movement require separate data and models. [MapLibre camera API](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#calculatecameraoptionsfromto)

Choose **Follow walker**, **Follow cyclist** or **Follow driver** to follow the nearest available resident at the displayed minute. You can also select a nearby body in the eye-level scene. **Return to street** restores the player's directed segment, position, heading and camera at the current simulation time. **Leave street** shows the same location from above. **Link to this street** carries the position, travel mode, simulation minute, camera aim and active scenario. On a segment it also records the direction and queued turn.

Pale green markers show walkers, pink marks cyclists and pale cars face along their routed roads. In **Eye level** the markers become simple 3D bodies. Blue dots identify shoppers approaching or leaving the active shop. The Clojure index reads each resident's diary and assigned places and lists trips under each hour they overlap. The latest municipal weekday contains 778,321 single-mode driver legs and the regional weekdays contain 1,009,542. These index totals include unresolved addresses. The map takes one resident in each group of eight by their synthetic roster ID and shows their driving legs when their directed street route fits the diary window and puts the car within 250 metres. The worker excludes address connectors from vehicle positions. It checks likely nearby paths first and adds other matches as they resolve. The displayed cars are a sample of routed resident traffic. Local traffic counts also include vehicles outside this replay. Collision and car-following dynamics remain open modeling work.

The original day contains 148,860 pure walking bouts with surrounding activity slots in the archived municipal roster and 193,654 in the region. The street view requires two located, distinct endpoints, a connected walking route and enough time to complete it. It interpolates distance along that route over the diary interval. The 150 m/min ceiling matches the pedestrian crossing check. Workplace adjustments use the fitted walking speed where available and grocery walks use 80 m/min. The count responds to opening hours, workplace assignments and the household commute clock.

The street view also shows reconstructed short walks, home-to-home recreation walks, school escorts, shopping and recreation outings, and trips for on-site work from the active replay. Blue outlines on pedestrians and cyclists and blue car bodies identify these additions. **Follow scenario trip** opens the resident at the same time and location. A school walking group shares a marker and contributes each member to the pedestrian count. A car carrying the same household appears once, under its driver. Transit contributes its routed access, transfer and egress walks to the pedestrian count. The vehicle itself continues on its timetable.

The street lookup stores route bounds and movement times for the published scenarios. It loads the original resident and route only if the lookup intersects the player's surroundings. Transit lookups use the timetable and published walking durations. They carry a distance bound for each access or egress walk and the mapped path bounds for transfers. Discretionary road trips use the same route budgets and free-flow driving profile as the resident replay. The Clojure diary index and the scenario occupancy releases retain their original resident identities and count definitions. Street links pin the active movement releases alongside the location and simulation time. [Explore a school walking group at 08:55](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=9cec79f1fec091af7db6&schoolRun=1813a113cd76855c266f&street=walk&at=-123.028586,49.313173,0&minute=535)

```sh
python -m scripts.vancouver_street_scenarios
```

At 20:05 by the evening shop at 488 Robson Street, 17 municipal residents are within range under these rules. The nearest one is on the way to the new shop. At 12:20 by the UBC campus bookmark, the regional weekday has 15 nearby walkers. An independent scan of both complete rosters recovered the same resident IDs in these two scenes. These are model counts based on the assigned diaries, venues and network. [Explore Robson Street](http://127.0.0.1:8187/cityday.html?street=drive&at=-123.117837,49.279749,0&minute=1205&shop=2726&hours=20:00-08:00) · [Walk at UBC](http://127.0.0.1:8187/cityday.html?coverage=region&street=walk&at=-123.2502,49.2664,0&minute=740)

The regional atlas now reconciles the region-wide distribution of diary templates with every dissemination-area roster. An earlier summary combined integer template IDs from the newly drawn regional population with string IDs from Vancouver's JSON release. Serialisation produced duplicate keys. Readers saw 662,287 diary assignments across 867,776 residents. The corrected region-wide distribution includes all 867,776. For example, 154,378 residents are at paid work at 08:00 on the original day, compared with 119,816 in the earlier summary. The correction affects the region-wide activity breakdown. It preserves the roster, assigned diaries, individual plans and area counts. Earlier regional clock links still resolve their original sources.

### LiDAR building heights

The Vancouver street replay uses the 2025 LidarBC surface and bare-earth survey to estimate above-ground building height. It samples aligned one-metre cells within each existing building footprint and avoids courtyards and the first 0.75 m from the edge along each grid axis. A building needs at least seven valid pixels and at least 70% support across the tested area. The estimate is the median surface minus ground height across those cells. The builder keeps the existing height for footprints with unsupported or mixed elevation samples. It preserves explicit height tags and keeps floor-based estimates when their value strongly disagrees with the raster estimate. [LidarBC survey catalogue](https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/LiDAR_BC_S3_Public/FeatureServer)

| Replay | LiDAR height estimates | Previously used a generic height | Previously estimated from floors |
|---|---:|---:|---:|
| City of Vancouver | 110,472 | 102,072 | 8,400 |
| Vancouver, UBC and North Shore | 167,867 | 151,383 | 16,484 |

The municipal release has 8,651 buildings with both an explicit mapped height and a supported LiDAR estimate. The median absolute difference is 0.60 m in this overlap. The comparison describes supported footprints with mapped heights and does not estimate accuracy for every footprint.

For buildings with distinct roof levels, the stepped model fits connected roof sections to the above-ground volumes. It detects clusters of absolute surface elevations, so a slope under a flat roof cannot create an artificial roof step. A raised section must be at least 3.5 m above the lowest fitted level and have a connected area of at least 24 m² in the source raster. The model clips and partitions those shapes again in the map's coordinate system to preserve the original footprint and courtyards. Pitched roofs and detailed exterior surfaces still need a finer model. [Roof partition research](https://isprs-annals.copernicus.org/articles/V-4-2021/169/2021/)

The fit sets aside groups of 2 × 2 m raster cells. One set chooses between the stepped fit and a flat estimate. Another evaluates the selected building shapes after reprojection and clipping. The audit reports mean absolute error by measured cell across the buildings selected for roof sections. These cells come from the same survey as the fit.

| Replay | Buildings with fitted roof levels | Withheld raster cells | Flat height mean absolute error | Fitted roof mean absolute error |
|---|---:|---:|---:|---:|
| City of Vancouver | 1,215 | 79,663 | 5.03 m | 2.10 m |
| Vancouver, UBC and North Shore | 1,939 | 130,481 | 4.76 m | 2.03 m |

Select a building to inspect its height source. **Map → Building heights** lets you compare the separate roof sections, the flat LiDAR fit and the original street inventory. Heights and source versions travel with street links. [Downtown roof levels](http://127.0.0.1:8187/cityday.html?place=downtown&minute=1020&buildingHeights=1c6664a5c10104f0a211) · [Ambleside roof levels](http://127.0.0.1:8187/cityday.html?coverage=region&place=ambleside&minute=1020&buildingHeights=835f66f2b62c18318094)

### Bicycle counts on city streets

The municipal roster contains 11,185 trips made entirely by bicycle between activity slots. The regional roster contains 14,480. A cyclist appears on the street when both places are located and the directed bicycle route fits the diary interval at up to 220 metres per minute (13.2 km/h). On the original weekday 7,473 municipal and 7,606 regional bicycle trips meet those conditions. Selecting an over-budget bicycle trip shows its route and reports the unresolved position. For a mixed-mode diary trip labelled bicycle, the replay reports an unresolved transfer location. A workplace scenario can explicitly reassign a direct commute to cycling. The hourly index, street view and count comparison share the same scenario trip selection. [Follow a cyclist at UBC](http://127.0.0.1:8187/cityday.html?coverage=region&street=bike&at=-123.2502,49.2664,0&minute=514.51487)

The initial comparison used two City survey sheets. At Arbutus and West 10th the count includes all approaches to the junction on January 9, 2024, from 07:00 to 09:00 and 16:00 to 18:00. The model counts a route that passes through the shared junction node. At the 700 block of Powell Street on January 31, 2024, the comparison covers 04:00 to midnight, the part of that civil date within the replay. The model counts an eastbound or westbound crossing of the survey longitude within 22 metres of the survey point in either direction along the north–south axis. Each trip counts once per site on its first crossing. The model estimates the passing minute from distance along the route. [City of Vancouver traffic count program](https://vancouver.ca/streets-transportation/traffic-count-data.aspx)

| Bicycle passages during survey hours | City count | Original municipal weekday | Neighbourhood commute modes with census tract jobs |
|---|---:|---:|---:|
| Arbutus and West 10th | 309 | 67 | 123 |
| 700 block of Powell | 18 | 55 | 121 |

At Arbutus the City counted 60, 88, 71 and 90 cyclists in the four survey hours. The original municipal weekday produces 0, 35, 10 and 22. Of the 309 observed Arbutus passages, 294 came from the east or west. The original replay has 21 from these approaches. Its 67 passages come from eight source diaries, one of which accounts for 23. On Powell all 18 observed and all 55 simulated cyclists arrived from the east. The neighbourhood assignment brings the total closer at Arbutus and further from the count on Powell. The City sheets include residents and visitors on particular winter days. The simulation follows assigned resident trips, reuses survey diaries and chooses routes by distance. Bicycle comfort, weather and visitor trips could each affect these comparisons. The panel exposes hourly totals, approach directions and how many source diaries contribute. Select a simulated count to follow one of its riders. [Explore the Arbutus comparison](http://127.0.0.1:8187/cityday.html?cycleCheck=arbutus&street=bike&at=-123.152989,49.262869,0&minute=508.93747)

The adapter reads the archived City workbooks from `data/raw/probes` under the supplied archive directory and checks the movement records against the workbook totals. To rebuild, first publish the cycling graph and hourly street index for the extent, then compile the Vancouver UI. Run `python -m scripts.vancouver_cycle_counts ../Simulations/city --verify`. Add `--region` for the regional network and `--clock household` for the household-matched weekday. For a saved municipal experiment, pass its archive hash with `--market-run`. Verification independently routes the same candidate legs using SciPy directed shortest-path trees and compares each survey hour and each approach.

#### Summer bicycling on the seawall and Point Grey Road

The count selector also offers three summer daily averages from the City’s Transportation Snapshots. The model counts a resident leg once at its first crossing of a 16-metre cross-section centred at the City’s published counter location, along an edge oriented within 60° of the local bike path. Each cross-section intersects one bidirectional bicycle link on both published networks. City averages include travellers from all origins and may include micromobility. The model column counts routed bicycle legs in one synthetic weekday from 04:00 to 04:00. The hourly rows show the simulation and let you follow a rider. [Open the David Lam Park comparison](http://127.0.0.1:8187/cityday.html?cycleCheck=davidlam) · [City counter locations](https://vancouver.ca/files/cov/2025-873-release.pdf)

| Site | City summer daily average | Shortest routes | Prefer City bikeways |
|---|---:|---:|---:|
| Point Grey Road at Volunteer Park (2024) | 3,900 | 178 | 181 |
| Seawall at David Lam Park (2023) | 4,500 | 1 | 1 |
| Seawall at Creekside Community Centre (2021) | 4,085 | 0 | 0 |

The workplace and neighbourhood commute fit brings Point Grey Road to 510 passages with shortest routes. Both seawall sites remain empty in that scenario. A separate reachability check gives upper bounds of 629, 384 and 385 baseline legs in table order. It sums directed shortest distances from each origin to the beginning of the counted edge, across the edge and on to the destination. It tests both directions and includes the endpoint connections and each leg’s time budget. With the workplace fit the corresponding upper bounds rise to 2,739, 2,225 and 2,541. Bounds apply to one site at a time and count each eligible leg once. Both the trip assignments and the difference in who and what is counted matter for interpreting the shortfall. [2024 Transportation Snapshot](https://vancouver.ca/files/cov/2024-transportation-snapshot.pdf#page=12) · [2023 Transportation Snapshot](https://vancouver.ca/files/cov/2023-transportation-snapshot.pdf#page=9) · [2021 Transportation Snapshot](https://vancouver.ca/files/cov/2021-transportation-snapshot.pdf#page=9)

With shortest routes and survey-based bicycle access, switching feasible driver outings to bicycles raises the three counts to 738, 2 and 0. With universal access they reach 1,091, 7 and 0. Combining survey-based access with the fitted workplaces and the bikeway preference gives 1,332, 0 and 0. The switches route bicycle legs between the outings’ existing destinations. The City’s fall travel survey also counts recreation rides that start and end at the same place. [Compare the combined scenario](http://127.0.0.1:8187/cityday.html?cycleCheck=pointgrey&cycleTours=access&workplaces=census&commute=tracts&bikeRoutes=bikeways) · [City travel survey, section 6.2 and Figure 46](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

#### Recreational bike rides from home

The municipal replay can add home-to-home rides for residents with bicycle access. It uses 13% of the City's 152,900 recreational trips to estimate recreational cycling of all kinds. The North Shore survey found that home-to-home recreation accounted for 4% of all trips and that all recreation purposes accounted for 22%. Applying the ratio of those two shares to Vancouver's recreational cycling and scaling to the model’s private-household residents aged 20 and older gives a scenario target of 3,408 rides. The transfer assumes the same home-loop fraction across modes and from the North Shore to Vancouver. The scheduler apportions targets by adult headcount across the city's neighbourhoods and uses the existing survey-based bicycle access assignment. [Replay recreational bike rides](http://127.0.0.1:8187/cityday.html?recreation=on) · [Vancouver survey, Table 1 and Figure 46](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF) · [North Shore survey, section 5.3](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

Rides reuse flexible media and leisure time at home. The scheduler reserves reconstructed short walks and keeps existing journeys, sleep, work and care. It draws weighted start times and durations from outdoor sports episodes of 20–120 minutes in the 2022 Time Use Survey’s urban Canadian weekday sample. The sports category includes activities such as cycling, hiking and kayaking. Starts can move up to one hour to fit the recipient's diary. Each route uses a directed street path before and after a chosen bicycle link, returns to the same home and fits a 120–220 m/min average pace. The route score favours mapped greenways and penalizes retracing. Connectors from homes to the bicycle graph may be up to 80 metres. [Statistics Canada Time Use Survey microdata](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001) · [City leisure routes](https://vancouver.ca/streets-transportation/cycling-routes-maps-and-trip-planner.aspx)

The earlier scheduler drew among donors available to each resident. This changed the citywide timing mix as a side effect of fitting home time. In that run 869 riders departed in the 21:00 hour. The current scheduler first assigns quotas by weighted donor start and duration, then fits all 3,408 rides to the same 45 sports bouts from 42 respondents. The 21:00 hour now has 102 departures and the 17:00 hour has 837, matching their quotas. Starts vary by up to an additional seven minutes around the feasible start within the source hour. Select **Survey and routes** to compare targets and fitted counts. Raster reproduced the per-minute population changes both as individual riders and as 2,623 weighted itineraries. [Replay the weighted timing fit](http://127.0.0.1:8187/cityday.html?recreationRun=b514d255b12003c6e5f5#recreation-loops)

The count records passages on the matched bicycle link. An out-and-back ride can contribute once in each direction. Select an added count to follow a rider as they cross.

| Site | City summer daily average | Baseline shortest routes | Passages added, earlier timing | Passages added, weighted timing |
|---|---:|---:|---:|---:|
| Point Grey Road at Volunteer Park | 3,900 | 178 | 499 | 696 |
| Seawall at David Lam Park | 4,500 | 1 | 47 | 41 |
| Seawall at Creekside Community Centre | 4,085 | 0 | 49 | 35 |

Repeating the earlier scenario with the same target and ten BC donor bouts produces 931, 46 and 27 additional passages respectively. Route demand at Point Grey Road is sensitive to the timing and length of the simulated rides. These site observations supply daily averages pooled across travellers and can include other devices. Both timing rules leave a large gap on the two False Creek seawall sections. [Replay the earlier national donor run](http://127.0.0.1:8187/cityday.html?recreationRun=d4c460d01d5e44ea8f12#recreation-loops) · [Replay the earlier BC-only donor run](http://127.0.0.1:8187/cityday.html?recreationRun=4e27a705c2612b32a7d7#recreation-loops)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bike_recreation ../Simulations/city
```

Add `--unbalanced` to reproduce the earlier national run. Add `--unbalanced --bc-donors` for the BC sensitivity run.

The spread-departures clock has a separate recreation release. Reusing the earlier original-clock routes would overlap 130 rides with activity or travel in the retimed diaries. The spread build reads the retimed diary of each affected resident, fits the same 3,408 quotas and verifies the population change against the spread clock. Its added route passages are 664 at Point Grey Road, 51 at David Lam Park and 37 at Creekside. The clock control keeps the recreation layer active and loads the release built for the new clock. [Replay the spread clock with recreation](http://127.0.0.1:8187/cityday.html?departureClock=39872889b958b822f512&recreationRun=977258f9bb07a941be8f#recreation-loops)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bike_recreation ../Simulations/city --departure-clock 39872889b958b822f512
```

### Tourists cycling to Granville Island

The South False Creek streetcar study estimated about 1.3 million annual tourist visits to Granville Island from the 2019 island count and a tourist share inferred from 2024 interviews. Two of 120 tourist interviews in the wider study area reported cycling. Applying that fraction to the annual estimate gives an illustrative 59 bicycle visits on an average calendar day. The two responses and wider interview geography make the mode estimate uncertain. [City study, Table 6.4](https://vancouver.ca/files/cov/2025-020-release.pdf#page=147) · [Interview characteristics, FOI page 238](https://vancouver.ca/files/cov/2025-020-release.pdf#page=238)

The routed cohort draws from 54 eligible hotel locations. The model uses the number of employees on each 2025 licence as a proxy for hotel size and treats every sampled cyclist as leaving a hotel. Directed cycle trips go to a mapped rack near the Public Market, followed by a one-minute walk to the market. The return follows legal directions back to the same hotel. Each visitor spends an assumed 45–90 minutes at the market. Arrival times are sampled within the regular operating hours with room for the full visit. The visitor panel reports trips and presence at the market. [Hotel licences](https://opendata.vancouver.ca/explore/dataset/business-licences/) · [Market hours](https://granvilleisland.com/public-market) · [Mapped bicycle rack](https://www.openstreetmap.org/node/1692226725)

The replay peaks at 15 of these visitors at the market at once. The model counts 52 incoming passages at its Anderson Street entrance approach. The City study reports 49,454 cyclists via Anderson in the 31 days from June 12 to July 12, 2024, or about 1,595 daily across all riders. The source names the entrance and the model places its cross-section on the mapped approach. The same hotel routes contribute zero at the David Lam Park, Creekside and Point Grey Road counters. [Try the visitor replay](http://127.0.0.1:8187/cityday.html?granvilleRun=d70e844604797bb4e66f#granville-visitors) · [Counts by entrance in Table D.5](https://vancouver.ca/files/cov/2025-020-release.pdf#page=274)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_granville_visitors
```

### A paired test of bicycle route choice

In **Bicycle counts on city streets**, choose **Prefer City bikeways**. The municipality, residents, venues, modes and diary clock are the same as in the shortest-distance replay. Selecting an hourly count follows a rider at the crossing. Switch the route rule while following to inspect the same person at the same minute. The nearby street crowd uses the active rule too. **Highlight matched bikeways on the map** shows which street segments received the preference. [Compare routes at Arbutus](http://127.0.0.1:8187/cityday.html?bikeRoutes=bikeways&cycleCheck=arbutus)

The City inventory contains 3,774 features. For the January 2024 comparison, 3,560 were active with known construction before 2024 and no recorded upgrade in 2024 or later. We matched 3,230 of those features to 288.12 km of distinct physical edges on the municipal bicycle graph. For each directed edge we check three locations along its length. All must lie within 10 m of an eligible City segment with a compatible name, a bearing within 25 degrees of parallel and a bikeway recorded for the travel direction. Unnamed graph edges can match by geometry. OSM access rules determine which directions a rider can take. In the full City inventory, 80 records labelled one-way have facility types populated in both directional columns. The preference uses the directional columns wherever OSM permits travel, so the preferred direction is uncertain on those records. Parallel paths, changing infrastructure and grade separations introduce uncertainty. The available snapshot also reflects more recent removals. The North Shore and UBC use their own regional graph and are outside this City inventory. [City of Vancouver bikeways](https://opendata.vancouver.ca/explore/dataset/bikeways/)

The scenario gives each metre off the matched network a cost of 1.25 metres on it. We chose this coefficient to test a moderate preference. The maximum physical detour from a shortest path is 25%. If the preferred path would exceed the diary time at 220 metres per minute, the rider takes the physically shortest route that fits. Time along a trip depends on actual distance. On the original municipal weekday both policies admit exactly the same 7,473 trips. Of these, 5,359 take a path more than one metre longer. Mean extra distance is 111 m, and the share of ridden distance on matched bikeways rises from 18.0% to 51.5%. In a Metro Vancouver study of 50 utilitarian bicycle trips, riders averaged roughly 400 m more than their shortest routes. The published sample and the simulated day cover different people and trip purposes. [Winters et al., study results](https://cyclingincities-spph.sites.olt.ubc.ca/files/2011/10/TRB_Shortest-route_2.pdf)

| Bicycle passages in the survey windows | City count | Shortest | Prefer bikeways | Most resident trips that could pass |
|---|---:|---:|---:|---:|
| Arbutus and West 10th | 309 | 67 | 127 | 826 |
| 700 block of Powell | 18 | 55 | 4 | — |
| Ontario and 5th | 3,021 | 30 | 261 | 898 |
| Prince Edward and Broadway | 287 | 20 | 8 | 806 |

Arbutus and Powell motivated this test. The Ontario and Prince Edward bicycle counts were then evaluated with the same coefficient, using weekday sheets with a unique shared junction node in the bicycle graph. The counts cover 07:00–19:00 on July 12 and April 5, 2023 respectively. Ontario improves substantially and Prince Edward moves further from the observed count. At Arbutus, 116 of 127 simulated passages now approach from east or west, compared with 21 of 67 originally and 294 of 309 observed. Each observed total includes everyone who passed on that date. The simulation covers located resident cycling trips on a synthetic weekday. [Ontario and 5th count workbook](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/10002/attachments/11182) · [Prince Edward and Broadway count workbook](https://maps.vancouver.ca/server/rest/services/GDH/Short_Term_Intersection_Movement_Counts/MapServer/33/10162/attachments/11342)

The final column is an upper bound on distinct trip legs for each junction considered separately. Two directed shortest-path trees give the fastest possible ride from the origin to the junction and from there to the destination, including access at both ends. Count a trip once if its possible passage interval overlaps any surveyed hour. This allows speeds up to the model ceiling and waiting en route. Powell uses a midblock screen line rather than a single junction, so this column is omitted there. Even sending all 898 eligible trips to Ontario and 5th leaves a shortfall of 2,123 against the City count. With neighbourhood commute modes and tract jobs, the corresponding upper bound rises to 2,976 and the preference routes 417 passages there. Changes in who cycles, where they travel, visitor coverage and time or season can affect this gap.

There is also a citywide trip-generation discrepancy. The baseline adult private-household comparison finds 11,374 primary-cycling bouts among an estimated 1,108,479 travel bouts (1.03%). In the City’s fall 2023 survey, the bicycle group accounted for 7.9% of trips. Figure 43 assigns 6.1% of all trips to personal non-electric bicycles, 1.4% to personal e-bikes, 0.3% to bikeshare and 0.1% to other micromobility. The diary model has one bicycle category. Multiplying the City’s rounded trip rate and share gives about 0.24 bicycle trips per adult weekday, compared with 0.020 in the baseline. The primary-mode comparison includes some mixed-mode trips and uses the survey’s adult population definition. The street count requires a feasible bicycle route. [Vancouver Transportation Survey](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

To reproduce the comparison from the project root, fetch the municipal inventory as described in DATA.md, then run the commands below. The two builds use the same count workbooks and cycling graph. Each independently checks hourly counts and approach directions using directed Dijkstra trees. Older releases may contain only the Arbutus and Powell comparison.

```sh
python -m scripts.vancouver_bikeways
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver
python -m scripts.vancouver_cycle_counts ../Simulations/city --extra-sites --verify
python -m scripts.vancouver_cycle_counts ../Simulations/city --extra-sites --bikeways --verify
```

#### Hills in bicycle route choice

Choose **Prefer bikeways and gentler hills** to compare with the same bikeway preference on the same weekday. Both policies keep the trip endpoints, diary windows, legal cycling directions and physical distance budget. The extra preference applies only uphill. Playback still distributes the diary travel time by distance along the selected route. [Open the hill comparison](http://127.0.0.1:8187/cityday.html?bikeRoutes=hills&cycleCheck=ontario5)

The model measures rise over run from the NRCan terrain along each bicycle-permitted OSM way. For short segments it uses a window of about 40 m on that way where possible. Ways shorter than 25 m, mapped grade-separated or covered ways, conflicting estimates on shared edges and edges lacking an elevation sample receive no hill cost. The published municipal graph has estimates for 223,240 of 243,506 directed arcs. Of these, 48,532 are uphill at 2% or more.

Following Broach, Dill and Gliebe's Portland GPS study, the positive grade bands are 2–4%, 4–6% and at least 6%. The study's commute distance slope implies first-order increments of 0.317, 0.792 and 1.448 weighted metres per metre in those bands. The model adds these increments to the existing bikeway costs. This approximation uses one set of route preferences for all trip purposes. The Portland estimates give a sensitivity scenario for Vancouver. Bike type and individual climbing preferences are unknown in these diaries. A preferred path beyond the physical distance budget falls back to the shortest legal route. [Broach et al., Tables 1–3](https://web.pdx.edu/~jbroach/537/readings/costs/Broach_etal_2012_TrA_WhereDoCyclistsRide.pdf)

On weekday release `dbd7a101357f3c27976f`, both policies route 7,353 bicycle legs. This weekday is newer than the one in the preceding bikeway comparison. Adding hills changes 4,253 paths and reduces mean uphill distance at grades of 2% or more from 897 to 788 m per trip. The same preference closes part of the gap at Powell, with the largest deterioration at Ontario and 5th. The four count sites give a mixed validation result. A more recent Vancouver study also estimated substantial differences in rider preferences using 1,590 observed utilitarian cycling trips. [Pinned replay](http://127.0.0.1:8187/cityday.html?dayRun=4f711d78c7e0f40698dd7dd0c10df51d85429318e20d12572de0bebaa5cc88a5&bikeRoutes=e5c4c2839c9d2c528382&cycleCheck=ontario5) · [Vancouver GPS route-choice study](https://link.springer.com/article/10.1007/s11116-026-10745-7)

| Bicycle passages in survey hours | City count | Prefer bikeways | Bikeways and gentler hills |
|---|---:|---:|---:|
| Arbutus and West 10th | 309 | 129 | 127 |
| 700 block of Powell | 18 | 5 | 9 |
| Ontario and 5th | 3,021 | 253 | 201 |
| Prince Edward and Broadway | 287 | 8 | 9 |

Combining fitted workplaces with survey-based bicycle access still leaves a large gap at Ontario and 5th. With these trip assignments, the comparison gives 553 passages with the bikeway preference and 426 when hills enter the route cost. Both policies route the same 33,180 legs across the city.

```sh
python -m scripts.vancouver_bicycle_grades ../Simulations/city
python -m scripts.vancouver_cycle_counts ../Simulations/city --extra-sites --hills --verify
```

The same count command accepts `--clock household` for the re-timed weekday, `--cycle-tours` for the bicycle access scenarios, and `--cycle-tours --combine-workplaces` to include the fitted commute destinations and modes. Each comparison uses its existing bikeway report as the reference.

### Resident trip demand by home zone

The current municipal weekday’s travel survey panel follows an estimated 561,275.2 adults in private households, including residents who stay home. A link such as `cityday.html?demand=360&tripMode=Cycling` opens the Kitsilano comparison. Select a purpose to follow an example at the midpoint of its recorded travel bout. The mode shown in playback must agree with the survey-mode classification and both assigned endpoints must be distinct and located for a trip to serve as an example. The published totals also count bouts without a located path.

Table 16 of the 2023 survey gives mode shares for all trips by residents of nine zones. On the original weekday, bicycles account for about 1% of trips in False Creek, Kitsilano and Vancouver Port. The survey reports 3%, 12% and 13% respectively. About 465 of the model’s cycling trips are classified as shopping and come from one template. None are classified as dining, recreation or social visits. [City travel survey, Table 16](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

**Compare trip rates with the City survey** shows citywide counts per 1,000 adults for the five purposes that can be paired with Figure 46. It compares five survey modes and uses 584,700 private-household adults aged 18+ as the survey denominator. For paid work it weights the shares for usual workplaces and other work trips by their respective published volumes. The estimated mode counts use rounded shares. Figure 46 omits return-home trips and gives no breakdown by home zone. [Open the cycling comparison](http://127.0.0.1:8187/cityday.html?demand=all&tripMode=Cycling&demandRates=1#trip-demand) · [City travel survey, Section 1.3 and Figure 46](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF#page=63)

For a selected mode, the panel first applies the survey mode share to the existing number of simulated trips for each purpose. The difference from the model rate is the mode-share component. The remaining difference from the survey rate is the trip-volume component. This arithmetic describes the gap under one reference share. Changing trip assignments can affect both components. With the current base day, about 39 of the 47 missing cycle trips to paid work per 1,000 adults are attributed to the mode share under this calculation. For shopping by bicycle, about 11 of the 22 missing trips are attributed to trip volume. Walking to shops shows a shortfall of about 117 trips per 1,000 adults, with about 70 attributed to trip volume and 47 to mode share.

The destination proxy uses the first stationary activity after a linked travel bout. Shopping requires a shopping activity. Dining requires eating or socializing at a restaurant. Recreation covers sports and leisure outings. Social visits cover remaining socializing destinations. Unclassified travel modes stay in the headline counts and are excluded from the Figure 46 comparison. Unmapped homes contribute to the whole-city result. The nine home zones use the same pinned regional traffic-zone boundaries as the workplace comparison. The survey includes home-to-home recreational loops and counts micromobility under cycling. The model uses the bicycle mode in its original time-use diary and the Figure 46 comparison excludes optional scenarios. [City travel survey, Sections 2.1 and 6.2](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

Rebuild with `python -m scripts.vancouver_trip_demand` and `clojure -M:ui -m shadow.cljs.devtools.cli release experiments`. The builder checks all six mode totals and the adult denominator against the published mobility release. Opening the comparison indexes the aggregate cells and their synthetic resident examples in the browser’s existing Datahike store. Counts are stored in fifths to preserve the age-band weights. Examples share resident identities with saved openings. The release identity includes the city, atlas, weekday and aggregate content version.

#### Trip purpose before and during rush hour

On the combined weekday, open **When do residents travel by purpose?** under the City travel survey. It compares the published schedule with the 2025 survey in three two-hour departure periods. The model counts all roster bouts, including travel with unlocated endpoints. The combined column adds the surviving reconstructed short walks and both legs of the fitted shopping tours. The rates use 561,275.2 adult equivalents in the model and 609,000 adults in the survey. The City supplies rounded purpose shares and estimated volumes. Optional scenarios are outside this comparison. [Peak-period report](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=47) · [Open the afternoon comparison](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&tripTiming=pre-pm#trip-timing)

| Departure period | All trips, model / survey | Shopping | Dining | Recreation |
|---|---:|---:|---:|---:|
| 07:00–09:00 | 440.9 / 426.9 | 5.9 / 8.5 | 14.4 / 8.5 | 26.4 / 34.2 |
| 14:00–16:00 | 427.8 / 423.2 | 48.6 / 80.4 | 1.3 / 16.9 | 17.9 / 29.6 |
| 16:00–18:00 | 619.1 / 589.8 | 68.2 / 70.8 | 17.0 / 35.4 | 36.1 / 53.1 |

Each cell gives departures per 1,000 adults. The mid-afternoon total is close to the survey, while the mix of trips differs. The model has 27,273 shopping departures between 14:00 and 16:00, including 1,636 fitted shopping walks. The survey rate implies roughly 45,100 at the same population. It also implies about 9,500 dining trips, compared with 757 classified as dining in the combined weekday. The source diaries classify trips by the first destination activity. Another 8,158 recorded departures in this window end with eating at a store and count under **Other or unclear**. In the 16:00–18:00 window, 28,466 end with eating at a place recorded as **Elsewhere**. These diary records lack the restaurant location used to classify model dining trips. The survey asks about the purpose of each trip, including passenger drop-offs and recreational loops.

Between 16:00 and 18:00, the model concentrates 8,751 shopping departures at 16:30. That is nearly 23% of modeled shopping departures in the period. The survey comparison only supports the two-hour total. Use the clock button to inspect that simulated minute, or follow a fitted shopper on foot. The builder independently checks the full-day adult denominator and recorded purpose counts against the existing trip-demand release. Rebuild with `python -m scripts.vancouver_trip_timing 5ab7efac0ffa7e618e13`.

##### Spreading bicycle shopping departures

The repeated 14:40 cycling diary supplies 7,804 of the 7,809 modeled shopping departures that minute. Its cyclists leave a recreational activity, shop for 90 minutes and cycle home. Both directed bicycle routes fit the existing travel windows for 1,602 residents at 220 m/min. The comparison balances those tours across a 15-minute departure window, and moves 1,495 of them. It holds their addresses, two travel durations, shopping dwell and the original departure hour of each leg fixed. Adjacent recreation and home activity shift by up to seven minutes. The hour and time buffers and the balancing rule are scenario assumptions. The City survey supplies two-hour totals. [Replay the bicycle timing comparison](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&tripTiming=pre-pm&shoppingClock=c6801b54c385fd18a504#shopping-clock-info)

The modeled count at 14:40 falls to 6,314. The period still has 27,273 shopping departures. The concentration that remains includes residents whose original routes cannot both fit, so their diaries keep the original clock. Both the overview and nearby cyclist layer use the shifted schedules. Raster checks every minute of the occupancy change using both grouped and resident-level execution. At 16:30, a repeated paid-work-to-shopping transit diary supplies 7,806 departures. Only 1,475 of those legs have a scheduled match and only 315 matched legs can leave at least a minute later with a three-minute boarding margin. The variant leaves those trips on their recorded schedules.

Rebuild the peak-period comparison before running `python -m scripts.vancouver_shopping_clock 5ab7efac0ffa7e618e13`.

### Vancouver weekday shopping walks

**Add walks to shops** replays 39,112 additional resident outings, each with one walk to a named shop and one walk home. The citywide model records 109,027 classified shopping trips, compared with about 211,954 if the simulated adult population travelled at the survey rate. Applying the survey’s 38% walking share to the difference sets the target for this scenario. Walking arrivals rise from 15,070 to 54,182, compared with about 80,543 at the survey rate. All recorded trips keep their existing times and modes. [Replay the shopping walks](http://127.0.0.1:8187/cityday.html?outingsRun=7af6c79abfad095959f2#discretionary-outings) · [City survey, Figure 46](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF#page=63)

The fit uses adults aged 20+ with no recorded shopping trip and an uninterrupted period of media or leisure at home. It keeps existing diary stops as well as the intervals used in the published short walks, voting layouts and base-clock recreational rides. Population-proportional neighbourhood targets and departure-hour targets derived from 76 complete walks in 75 Canadian urban weekday diaries all fit. The diary sample is small. Real shop hours are represented by a shared 08:00–20:00 window, and the model favours shorter routes among up to eight nearby named stores. Both legs must fit inside the donor’s travel time and within 1.6 km on the street network. The fit assigns visits to 3,457 of 4,320 matching Overture shops. Its outcome measure is visits. [Statistics Canada time-use data](https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm) · [City survey, Section 6.4.3](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

Raster reproduces every minute of the change in neighbourhood occupancy on both the 39,112 individual schedules and their 17,520 grouped schedules. In the six independent intersection studies, added shopping walks raise modeled passages from 604 to 755 during the measured hours. The city counted 11,002 passages across those same hours. At Ontario and 1st, the model rises from 131 to 205 against 4,363 observed. The model columns count recorded resident walks, reconstructed short walks and the new shopping trips. The published report includes the counts by site and hour. [Source workbooks and full-roster method](#full-roster-pedestrian-counts-at-six-intersections)

Rebuild the scenario with `python -m scripts.vancouver_shopping_outings ../Simulations/city` after publishing the municipal trip demand and pedestrian comparisons. The replay uses the same household and address records as the base day.

### Grocery openings with fitted shopping demand

The grocery scenario can use the fitted shopping walks on the original municipal day. Of 39,112 outings, 36,426 inherit an in-person goods stop from the 2022 time-use donor. The scenario applies the same assumed 40% grocery share as the original walking market. Its repeatable draw selects 14,665 occasions, of which 2,059 fit one of the 73 existing licensed grocers. The draw is an assumption about shopping purpose. Visits are illustrative market outcomes. [Try 3304 Kingsway with fitted shopping demand](http://127.0.0.1:8187/cityday.html?marketRun=5e64c5b3be27cd6304d7c965ca7f318c857c7705e213e7abf1ba41c38d572b01&shop=1387&hours=full#market) · [2022 Statistics Canada time-use data](https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm)

Both releases use the same weekday, stores, 964 proposed sites and original 4,827 grocery occasions. Each fitted shopper keeps their departure time, dwell and return-home window. A proposed grocer must fit both walks and the complete visit, and it must be closer than the best incumbent for an already feasible occasion. When a player opens a grocer during the simulation, only shoppers still at their origin can adopt it. An added outing that cannot reach any grocer keeps its assigned retail destination. The street view and resident inspector use the chosen shop for both legs.

| 3304 Kingsway timing | Visits from recorded diaries | Added visits from fitted walks | Total with fitted walks |
|---|---:|---:|---:|
| Open for the full 08:00–20:00 shift | 37 | 52 | 89 |
| Open for the full 10:00–18:00 shift | 16 | 46 | 62 |
| Open at 11:15 with an 08:00–20:00 schedule | 37 | 45 | 82 |
| Open at 15:00 with an 08:00–20:00 schedule | 26 | 23 | 49 |

The archive pins the original market and the fitted outing release. Saved opening records include that outing release, and links to fitted shoppers reopen the same visit. Run `python -m scripts.vancouver_shopping_market ../Simulations/city` after building the walking grocery catalogue and the fitted outings. The release retains all recorded-diary choices and publishes its own comparison link.

#### Grocery openings on the combined weekday

The combined weekday with the repaired census workplaces already contains 20,584 fitted shopping outings. **Score fitted shopping walks as well** lets those trips compete for grocers on the same day, alongside the recorded diary trips. The time-use donors identify 19,385 fitted stops as in-person goods shopping. The existing 40% draw selects 7,846 grocery occasions, of which 1,097 fit an existing licensed grocer. Trips that cannot reach an incumbent or an open candidate keep their assigned retail destination. The market comparison holds the outing times, workplace assignments and recorded grocery choices fixed. [Statistics Canada time-use diaries](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001)

At **2693 East Hastings Street**, opening at noon with an 08:00–20:00 schedule gives 34 visits from recorded diaries and 17 from fitted walks. At **2541 Kingsway** the same timing gives 16 and 39. The effect depends on the storefront and on how much of the day remains after opening. The fit uses travel-survey totals and a goods-to-grocery assumption. The visit counts illustrate the effect of those assumptions on a shop opening, and would need observed store entries or transactions for validation. [Compare the noon opening at East Hastings](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&marketRun=3598077aa029fad2e37564393b0c3a1494d8568f7db7e9d5f10213dbb91381aa&shop=3738&shopPlay=1&opened=720&minute=720#market)

The combined market archive records the joint weekday, its workplace assignments and the fitted shopping release. Datahike can compare two saved openings of the same shop and show which residents visit in either case. Rebuild this comparison with `python -m scripts.vancouver_shopping_market ../Simulations/city --joint 5ab7efac0ffa7e618e13`.

##### East Hastings demand and access

Open **Demand and evidence → East Hastings demand and access** for the 2693 East Hastings opening. Both market releases use the same recorded diary occasions, workplace assignments, shop candidates and incumbent choices. The second also includes fitted shopping walks. The tests use the replay's opening rule with closing at 20:00. A scheduled opening is known in advance. At noon or 15:00, only people who have yet to set off can change their plans. [East Hastings replay](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&marketRun=3598077aa029fad2e37564393b0c3a1494d8568f7db7e9d5f10213dbb91381aa&shop=3738&shopPlay=1&opened=720&minute=720#market)

| Opening | Recorded diaries | With fitted walks | Diverted | Newly feasible with fitted walks |
|---|---:|---:|---:|---:|
| Scheduled at 08:00 | 83 | 104 | 11 | 93 |
| Activated at noon | 34 | 51 | 8 | 43 |
| Activated at 15:00 | 34 | 44 | 8 | 36 |

All 17 visits added by fitted walks at noon come from Hastings-Sunrise. The remaining 34 include 26 visitors from Grandview-Woodland and eight from Hastings-Sunrise. Twenty-four of the 51 noon visits reuse the same diary. Under the full-day opening, ten of the eleven diverted visits come from Caffè La Tana, which lists both café service and retail pasta and pantry goods. The model compares travel times to all licensed grocers and assumes identical incumbent opening hours. Competition by assortment, basket price and actual retail hours remains unmeasured. The table shows sensitivity to assumptions about demand and the opening, and site-level visit observations are still needed. [Caffè La Tana](https://caffelatana.ca/pages/caffe) · [City retail district study](https://vancouver.ca/files/cov/city-of-vancouver-small-business-study-2020.pdf)

The Can-FED comparison uses the same 73 incumbent addresses and street graph as the market. Can-FED finds a grocer within 1 km of 54 of the 58 Hastings-Sunrise census representative points in the corrected city footprint, compared with 19 in the model. The opening gives 15 points their first modeled grocer within 1 km. Can-FED already finds access at all 15. All 43 newly feasible noon visits also come from home areas where Can-FED finds a nearby grocer. A feasible diary occasion depends on the actual previous and next stops and the time available. Can-FED measures store proximity from home-area reference points. Its result challenges the incumbent inventory and access assumptions, and the two sources still differ in store definitions and routing. [Can-FED 2024](https://www150.statcan.gc.ca/n1/pub/13-20-0001/132000012025001-eng.htm) · [City food retail access study](https://vancouver.ca/files/cov/equitable-access-to-healthy-food-retail-report.pdf)

```sh
node scripts/vancouver_market_sensitivity.mjs public/data \
  9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f 3738 \
  ac3c70346e4aef0e111c15e0f5f5217a44f2b06fbd13cb8fdf8b09bfc1c718b2
```

Load the report at the Clojure REPL via `city.vancouver.market-scorecard/load-experiment`. Its `scorecard` uses the shared calibration evaluator for census-point access and reports the opening sensitivities separately. The downloadable report links the catalogue releases and includes all arrival hours, home neighbourhood totals and incumbent diversions.

### Commutes and shopping on the same weekday

This municipal replay combines the census tract workplace fit, fitted commute modes, 39,112 shopping outings and 14,206 reconstructed short walks on the same clock. The builder drops 77 reconstructed walks whose endpoints changed under the workplace fit. It checks that added walks and shopping outings occupy different intervals for each resident. Minute-by-minute occupancy conserves all 662,248 residents, including people assigned to workplaces outside the mapped city. [Replay the combined weekday at 08:00](http://127.0.0.1:8187/cityday.html?jointRun=9cab148ddcd5e85ed706&downtown=am&commuters=combined&minute=480#joint-weekday)

The direct transit matcher uses the revised endpoints and assigned modes. It matches 30,780 of 118,807 transit bouts to one scheduled vehicle on September 15, 2026. The original current release matches 17,886 of 90,018 bouts. At the six Downtown SkyTrain stations from 07:00 to 09:00, the fitted replay has 999 alightings and 346 boardings, compared with the observed 2025 weekday averages of 25,677 and 7,557. The simulated station counts cover direct rides by City of Vancouver residents. The observed counts include all riders and transfers. [TransLink service performance review](https://www.translink.ca/tspr)

Across all modes from 07:00 to 09:00, resident trips change from 4,109 arrivals and 16,059 departures at Downtown endpoints to 19,361 arrivals and 12,769 departures. Including the separately estimated incoming work cohort gives 29,100 arrivals and 12,812 departures. These are modeled person trips. From 16:00 to 18:00, the combined resident and incoming cohort has 14,888 arrivals and 32,871 departures.

Across the 44 measured hours at six pedestrian intersections, the comparison rises from 604 passages with original locations and reconstructed walks to 783 on the combined weekday. The City counted 11,002. At Fraser and Broadway the model rises from 30 to 71, compared with 678 observed. The combined figures count recorded legs with fitted work endpoints, retained short walks, direct transit access and egress, and new shopping walks. The same ClojureScript workplace resolver supplies playback and the count builder. Grouped SciPy shortest-path trees independently reproduce every modeled count hour scored by the browser network. [Inspect Fraser and Broadway](http://127.0.0.1:8187/cityday.html?jointRun=9cab148ddcd5e85ed706&jointSite=4#joint-weekday) · [Pedestrian count method](#full-roster-pedestrian-counts-at-six-intersections)

Rebuild with `python -m scripts.vancouver_joint_weekday ../Simulations/city` once the original municipal roster, workplace fit, pedestrian observations, transit network, incoming workers and shopping outings are available. The joint release pins each parent and publishes the matched passenger and occupancy data with the held-out evidence.

#### Travel modes by household income

The folio and Census evidence describe homes and households. This separate travel check measures what members of each income bracket do during the day. It compares the original and combined municipal weekdays with Figure 54 of Vancouver's fall 2022 survey. Model household income sums before-tax individual amounts from 2020 for the roster's private households. The survey asked for the previous year's before-tax household income. The five-mode reference uses the figure's rounded percentages. The model counts the other and unspecified trips in its denominator and displays their share. [City survey, Figure 54 and question B9](https://vancouver.ca/files/cov/2022-transportation-panel-survey.pdf)

The comparison uses estimated adults age 18 and older. The 15–19 age band contributes two fifths of each person and trip. People without complete household income remain visible in an unresolved group. The primary mode follows the city trip comparison's mode rules. The combined weekday adds fitted work modes, reconstructed short walks, and round trips for the shopping outings. It scores 1,158,121 adult trips with known household income, compared with 1,068,968 on the original replay.

| Household income and mode | Original | Combined | 2022 survey | 2023 survey |
|---|---:|---:|---:|---:|
| Below $25,000, auto driver | 67.8% | 58.2% | 22% | 41% |
| Below $25,000, transit | 5.5% | 6.3% | 44% | 27% |
| At least $150,000, auto driver | 67.3% | 60.7% | 48% | 45% |
| At least $150,000, transit | 7.8% | 8.8% | 7% | 10% |

The commute and walking adjustments improve the driving share in both brackets. Low-income transit use remains below either survey. The 2023 chart labels its second bracket $30,000–49,999, so the table shows a dash beside the model's $25,000–49,999 row. The City also publishes household vehicle availability by income in its 2022 report. [Inspect all income brackets](http://127.0.0.1:8187/cityday.html?jointRun=414d1c1c2b95a51d126d&incomeBand=0#income-trip-modes) · [2022 survey, Figures 25 and 54](https://vancouver.ca/files/cov/2022-transportation-panel-survey.pdf) · [2023 survey, Figure 55](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The archived time-use donor pool has only 51 urban B.C. weekday respondents aged 15 or older who live alone and have before-tax income below $25,000. That includes 44 fitting and seven held-out diaries, with 36.7 effective donors across both groups. After weighting their linked trips, 64.7% are by car driver and 7.3% are by transit. The subgroup uses individual income as household income because these respondents live alone. The time-use file's family income refers to census families. Across multiple-person homes it can omit the income of other members of the same household. The donor figures cover a broader geography, a different age range and one-person homes, so they help diagnose the model's inputs and cannot replace the Vancouver survey comparison. [2022 Time Use Survey public-use file and codebook](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001)

Rebuild with the compiled ClojureScript workplace resolver from the combined weekday.

```sh
clojure -M -m city.vancouver.atlas-diaries ../Simulations/city --income-comparison > target/vancouver-timeuse-income-diaries.json
python -m scripts.vancouver_income_travel 414d1c1c2b95a51d126d --diary-evidence target/vancouver-timeuse-income-diaries.json
```

#### Fitting whole diaries to the 2023 income benchmark

The calibration starts with the original resident roster and donor probabilities within each age and activity group. It adjusts the probabilities of whole 24-hour diaries to approach the 2023 survey's five mode shares within each comparable income bracket. A quadratic penalty limits large changes in the weights. The fit also targets the original trip rate, other-mode counts and average paid work, study and sleep time. It keeps a resident's original diary wherever the old and new probabilities allow the same draw. Residents with an unresolved income and those in the mismatched lower-middle income bracket retain their original diaries. [2023 survey, Figure 55](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The replay changes 117,477 diaries across 662,248 residents. All household members stay at the same homes, and residents whose diaries stay the same keep every original destination. The map uses the same sample of residents. In the lowest income bracket the recorded driver share falls from 67.8% to 40.6% and transit rises from 5.5% to 25.8%. Average sleep, study and paid work each change by less than one minute per adult in that bracket. Effective donors fall from 360 to 189 across its age and activity groups. The 2023 mode shares were fitting targets. The comparison to the 2022 survey shows sensitivity to the survey year. [Replay the income-fitted weekday](http://127.0.0.1:8187/cityday.html?dayRun=38f7fa1b9ad367725b2bc36a6eb1d93b25b6fee57dd0123c791f7c65b2671c5b#diary-fit)

On the same dated timetable, residents with feasible direct trips increase from 17,886 trips among 90,018 recorded transit bouts to 34,695 among 165,788. This timetable check uses the original destination allocator, including unlocated and coincident endpoints. Its remaining gap includes trips that need connections and trips whose destinations or windows are infeasible. This fit is a paired experiment against the original weekday and does not include the later workplace and shopping assignments.

Allowing one scheduled transfer with the same fitted diaries and destinations adds 20,405 journeys, for 55,100 of 165,788 transit bouts. The 34,695 direct trips keep their original itineraries. The search finds 5,306 more connections that fit the clock but cannot be booked under the bus capacity limits. It adds riders to segments with room and carries the existing 68 overloaded modeled bus runs forward as background. Among those trips with a scheduled itinerary, matched morning alightings at six Downtown stations rise from 29 to 212. [Follow a connection on the fitted weekday](http://127.0.0.1:8187/cityday.html?dayRun=38f7fa1b9ad367725b2bc36a6eb1d93b25b6fee57dd0123c791f7c65b2671c5b&riderRun=fa40eaabfb02c02dc832&da=59150363&person=48&minute=480.1&follow=1#diary-fit)

Among adults in households earning under $25,000, the router finds 5,069.2 direct and 2,239.4 connecting journeys after applying the same fractional age weights as the diary comparison. Together they account for 9.8% of all linked trips in that bracket. The diaries assign 25.8% of those trips to transit, so many recorded bouts still lack a reachable and available scheduled itinerary.

The Census workplace overlay can now run on the income-fitted weekday. It allocates 87,499 workers to different tracts, cutting shortfalls against its conditional Census targets from 95,308 to 7,809 jobs. Morning Downtown driver arrivals rise from 1,777 to 10,866 while morning driver departures fall from 7,121 to 5,521. In the evening, driver departures rise from 3,486 to 12,496. These are resident trip endpoints under the workplace model. This overlay still uses the original scheduled-rider comparison until transit is rematched to the fitted workplace addresses. [Compare the fitted Downtown commute](http://127.0.0.1:8187/cityday.html?dayRun=38f7fa1b9ad367725b2bc36a6eb1d93b25b6fee57dd0123c791f7c65b2671c5b&workplaces=census&commute=tracts&downtown=am#downtown)

The combined income-fitted release rematches transit to the fitted workplaces and adds 44,062 shopping outings and 13,640 reconstructed walks. It schedules direct rides for 46,964 of 178,717 transit bouts. Over the measured hours at six intersections it produces 1,234 pedestrian passages, up from 1,182 with the income-fitted diaries and reconstructed walks. City counters recorded 11,002. An independent shortest-path calculation reproduces the simulated passages. [Open the combined income-fitted weekday](http://127.0.0.1:8187/cityday.html?jointRun=dbb94469221ab02f3f94&jointSite=4#joint-weekday)

```sh
python -m scripts.vancouver_diary_fit 59b3bcac4137ca1483c9 target/vancouver-timeuse-income-diaries.json --archive ../Simulations/city
clojure -M -m city.run-catalog vancouver-diary-fit a8f67bddf390804f864a
python -m scripts.vancouver_diary_transfers ../Simulations/city 1e4e72301329a70fb075
```

#### Fitting income and home-zone travel together

The next paired weekday uses the same households, addresses and map sample and changes 216,211 intact diaries. It fits the 2023 mode shares by household income and home zone together, and targets the citywide rate of 3.03 daily trips per adult. A regularized fit adjusts the prior probabilities within each age and activity group. It also targets the original citywide mean hours of paid work, study and sleep. Effective donors drop from 332 to 133 across the fitted adult population, increasing the importance of a smaller set of diaries. [2023 survey, Table 16 and Figure 55](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF) · [Historical trip-rate series, Figure 13](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=40)

Against the held-out 2025 mode shares, mean absolute error across nine home zones and five comparable modes falls from 13.2 percentage points for the original weekday to 6.1 for the income fit and 2.4 for the joint fit. In the West End the original diaries assign 12.0% of comparable trips to walking, the income fit assigns 23.4%, and the income and home-zone fit assigns 51.8%, compared with 46% in the survey. In Southeast Vancouver the income and home-zone fit assigns 58.3% to driving, compared with 59% observed. The joint fit generates 3.02 trips per adult, compared with 3.09 reported for 2025. These comparisons score the assigned diaries before checking whether addresses and timetables can accommodate their trips. [Open the home-zone comparison](http://127.0.0.1:8187/cityday.html?dayRun=1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796#diary-zone-check) · [2025 transportation survey, Table 14](https://vancouver.ca/files/cov/2025-transportation-survey-report.pdf#page=54)

The direct timetable matches 59,027 journeys among 287,947 transit bouts at the original addresses for these diaries. A second replay books space on each bus segment in order of diary windows ending, with seeded ties. It keeps 50,223 journeys, reroutes 6,928 to another direct service inside the same window and leaves 1,876 pending. All 190 previously overloaded bus runs with a capacity estimate now fit their proxy limits. The benchmark compares occupancy from simulated city residents. Other riders and live service variability affect real loads. [Replay the booked direct journeys](http://127.0.0.1:8187/cityday.html?dayRun=1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796&riderRun=1d48021d464eefbbf1f6#diary-fit)

Allowing one change of vehicle adds 29,480 journeys and keeps all 57,151 direct bookings, for 86,631 of 287,947 diary transit bouts. Of the 1,876 direct journeys rejected for lack of space, 368 find a feasible connection. The replay includes stop access walks, the timetable’s transfer rules, and a check of available space on all bus segments with a capacity estimate. It adds zero overloaded runs. Another 13,168 potentially schedulable journeys remain without space under the model. [Follow a rider through both legs](http://127.0.0.1:8187/cityday.html?dayRun=1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796&riderRun=68f78fafbb26a28734d2&da=59150337&person=426&minute=480.1&follow=1#diary-fit)

For adults in households below $25,000, 26.0% of trips are assigned to transit in the fitted diaries. Matched scheduled journeys cover 9.3% of all adult trips in the same bracket. The gap measures how many transit-assigned trips still lack complete modeled journeys at the original addresses and times.

The six pedestrian count sheets from 2023–24 provide a check on where and when this extra walking occurs. Using the same sites, recorded hours and routing rule, the baseline weekday generates 604 passings including inferred short walks. The income-only fit generates 1,182 and the income and home-zone fit generates 2,403, compared with 11,002 observed. At Ontario Street and 1st Avenue the home-zone fit reaches only 622 of 4,363 observed crossings. At Alberta Street and W 12th Avenue it generates 238, compared with 108 observed. The comparison counts paths reconstructed for city residents and the street counts cover everyone passing the intersections. [Compare the crossings and follow a resident](http://127.0.0.1:8187/cityday.html?dayRun=1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796&crossing=2#pedestrian-check)

The model was fitted to home-zone mode shares. A separate survey table gives the share of trips that stay in the home zone by trip purpose. Across nine home zones, mean absolute error for other home-based trips falls from 17.6 to 9.7 percentage points. For commutes it moves from 17.5 to 17.2 points, and for trips between non-home stops it rises from 12.5 to 14.8. In False Creek, only 27.2% of the modeled other home-based trips stay local, compared with 47% in the survey. This tests the locations of both endpoints as well as the composition of the diaries. [Compare trip locality](http://127.0.0.1:8187/cityday.html?dayRun=1fa75ab09e40f61cb1eb2a40a0e4b6006c3a48e5c0a00e918e0dcaec0f347796&workplaces=census&commute=sites&zones=other#survey-zones) · [2023 survey, Table 18](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

The shopping fit adds 20,584 outings by residents without a shopping trip in their assigned diary. The grocery scenario carries 7,846 of those outings into the same store-choice calculation as the 14,160 walking occasions drawn from the diaries. For the candidate at 3304 Kingsway, opening the full day gives 82 modeled visits, including 35 from the added shopping outings. Opening at 11:15 gives 68 visits. Both replays preserve the same candidate location, travel windows and store catalogue. These counts cover modeled grocery occasions on foot. [Try the Kingsway opening](http://127.0.0.1:8187/cityday.html?marketRun=00fac08be88c569abe28768669b09712ec29ab07236fde413ba1c9a09802672f&shop=1387&hours=full&shopPlay=1&minute=675#market)

The combined replay adds the census workplace assignments, incoming workers, the 20,584 shopping outings and 9,944 reconstructed walks. At the revised addresses, 64,597 journeys match direct transit, before applying the separate capacity and transfer model. The legacy workplace mode reassignment reduces adult cycling by 56,886 trips and adds 62,105 driver trips relative to the fitted diaries. Estimated pedestrian passings fall from 2,403 to 2,100 across the measured sites. The combined replay exposes this tension between workplace and diary calibration. [Compare the combined weekday](http://127.0.0.1:8187/cityday.html?jointRun=5bd010875b22fbc5c446&jointSite=2&minute=480#joint-weekday)

The diary-mode workplace variant starts from the fitted diaries and retains each recorded travel mode, stop time and travel window. Census workplace tracts supply the job targets. The allocator checks candidate workplaces against every timed leg with one workplace endpoint. Walking and cycling legs must fit their published street graphs at 75 and 220 metres per minute, including address access and the direction of bicycle edges. It also looks for feasible addresses within a worker’s current tract when an active route misses its window. The census targets apply at tract scale. The individual businesses and the sites for motorized modes use approximate trip-distance constraints during assignment. A separate timetable pass checks scheduled transit at the resulting places and can book space and add connections on the bus network.

The fitted population has 247,499 workers with eligible located jobs. The variant changes 107,532 workplace tracts and finds a different site within the same tract for another 18,003 workers. Unfilled tract targets fall from 123,237 to 15,705. Among 79,592 eligible workers with applicable walking or cycling legs, the count whose active legs all fit the existing travel windows increases from 44,104 to 68,476. Every worker whose active legs previously fit retains a feasible set of routes. The 11,116 remaining cases still lack a complete active route within the fixed travel windows at their assigned sites. An independent check in the browser’s A* router verifies the 82,809 relocated active legs with distinct endpoints. [Follow a cycling commuter](http://127.0.0.1:8187/cityday.html?marketRun=220721db8b996ccab2b449284d30f37c74c16ab7708d094e6a2382393b961913&commute=tracts&da=59150307&person=37&minute=532.5&follow=1)

The grocery catalogue also uses the revised workplaces. The Kingsway opening preserves the workplace release and commute rule when saved and reopened in Datahike. [Open the Kingsway scenario](http://127.0.0.1:8187/cityday.html?marketRun=220721db8b996ccab2b449284d30f37c74c16ab7708d094e6a2382393b961913&commute=tracts&shop=1387&hours=full#market)

At the revised addresses, the timetable finds 71,919 direct journeys. Booking seats within the modeled bus limits keeps 63,102 journeys on their original matched service, reroutes 7,162 within the original window and leaves 1,655 without space. The resulting 70,264 direct journeys fit the bus capacity estimates on every occupied segment with a published limit. The count covers scheduled journeys made by simulated city residents.

On the combined replay with these workplace sites and the direct bookings, the modeled pedestrian count rises from 2,403 to 2,416 across the six measured intersections, compared with 11,002 observed. At Ontario Street and 1st Avenue it rises from 622 to 659, compared with 4,363 observed. The six Downtown SkyTrain stations receive 1,417 matched city-resident alightings between 07:00 and 09:00. TransLink reports 25,677 alightings from all riders across the same stations and hours. The comparison limits the model column to city residents and includes only complete scheduled itineraries. [Open the combined weekday](http://127.0.0.1:8187/cityday.html?jointRun=ac20ad40f5c86d824e13&jointSite=2&minute=480#joint-weekday) · [TransLink station counts](https://www.translink.ca/tspr)

The driving audit uses 183,433 single-mode work-linked drives with both addresses in the city, after excluding 35,413 with workplaces outside Vancouver, 4,608 with an unresolved address and 750 mixed-mode legs. The same directed free-flow road graph fits 161,728 legs at the diary addresses and 164,830 at the revised workplaces. This is a gain of 3,941 fits and a loss of 839 previously feasible drives. Among departures from 07:00–09:00, the number that fits rises from 36,879 to 37,310 out of 39,042. Adding the three measured corridor profiles at the revised addresses leaves 164,821 feasible legs across the full day. The profiles use the departure hour and cover three reaches of Granville and Georgia. The rest of the network uses free-flow timing. These are feasibility estimates for the same synthetic diaries. [See the road comparison and follow a driver](http://127.0.0.1:8187/cityday.html?marketRun=220721db8b996ccab2b449284d30f37c74c16ab7708d094e6a2382393b961913&commute=tracts#workplace-driving)

An independent check agrees with the browser’s A* times on 1,100 sampled legs, including 99 on paths affected by the corridor profile. The linked replay follows the estimated time along each driving edge. Any extra time in the diary travel window is spent at the destination before the next activity begins.

The repair phase considers the 847 legs that fit at the original addresses and fail at the revised ones with corridor times. It searches up to 24 neighbouring licensed workplaces within the assigned tract. A replacement must fit every supported work-linked driving, walking and cycling leg at its recorded time. The compiled repair moves 661 workers and recovers 833 of those legs. A separate A* pass verifies every recovered drive. Workplace counts by tract retain the same census targets and assignments. To reuse scheduled transit bookings, the combined weekday builder independently extracts transit for both layouts and requires the same window, trip identity, endpoints and exclusion counts on every leg.

Rechecking the full roster finds 165,655 driving legs that fit the repaired workplaces with measured corridor speeds. The 14 remaining regressions are all present in the earlier comparison. [Compare the repaired weekday](http://127.0.0.1:8187/cityday.html?marketRun=2f2a68bdf7d9b2d9bc61e513d74b4a40e57000513c4d168ce22acf8ecaea6c84&commute=tracts#workplace-driving) · [Follow a repaired drive](http://127.0.0.1:8187/cityday.html?marketRun=2f2a68bdf7d9b2d9bc61e513d74b4a40e57000513c4d168ce22acf8ecaea6c84&commute=tracts&roadTraffic=bcc29ece6795ac643929&roadClock=street&da=59150307&person=308&minute=690.5&follow=1)

The fitted diary page opens the combined weekday with the road repairs and scheduled transfers. A single scheduled transfer adds 32,242 journeys and keeps all 70,264 direct bookings. The total is 102,506 of 287,947 transit-assigned bouts. Of the added journeys, 834 recover trips that had lost a direct seat. The transfer search checks the published minimum connection time, boarding with a three-minute margin, a maximum 250 m walk between stops and available space on every bus segment with a capacity estimate. Total modeled passings at the six pedestrian sites rise from 2,416 to 2,504. The city observed 11,002 passings there. [Follow a resident changing vehicles](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&minute=480#joint-weekday)

At six Downtown SkyTrain stations from 07:00 to 09:00, scheduled city-resident alightings rise from 1,417 to 3,423. TransLink observed 25,677 alightings from all riders across these stations and hours. Between 16:00 and 18:00, resident boardings rise from 684 to 1,664, compared with 29,796 observed boardings from all riders. [Compare Downtown rush hour](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&downtown=am&minute=480#downtown) · [TransLink station counts](https://www.translink.ca/tspr)

#### Lunch walks and pedestrian route choice

The lunch replay adds 120 walks from a workplace to a named restaurant and back. The fit uses five observed restaurant tours that leave and return to paid work on foot, pooling the British Columbia and other urban weekday Time Use Survey diaries. It finds 53,969 eligible meal breaks and 459 existing modeled tours with the necessary addresses. Every added tour keeps the recorded meal window, routes both legs on mapped pedestrian links and preserves the paid-work episodes. The added tours pass none of the six count sites in their recorded hours. [Play a lunch walk](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&lunch=walk#workplace-lunch) · [2022 Time Use Survey public-use data](https://www150.statcan.gc.ca/n1/en/catalogue/452500012025001)

The pedestrian route comparison holds trip addresses, travel windows and timetable walks fixed. For each other mapped walk it sums the shortest network distances from both endpoints to the count circle. Those shortest approaches may reach different points in the circle, so the sum gives a lower bound on the distance via the site. This provides an upper bound on the walks that can pass within each measured hour under two detour limits. At Ontario and 5th at noon, the simulation produces 7 passings, the 10% and 25% limits allow up to 249 and 469, and the City observes 565. At Ontario and 1st at 15:00, the 25% limit is 163 against 378 observed. Six hours across three sites have observed counts above the 25% upper bound. The City counts include pedestrians outside the simulated resident roster. [Inspect the Ontario and 5th comparison](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&jointSite=1#joint-counts)

```sh
python -m scripts.vancouver_zone_diary_fit ../Simulations/city 1e4e72301329a70fb075 target/vancouver-timeuse-income-diaries.json
clojure -M -m city.run-catalog vancouver-diary-fit 309376fc6e41dadaa98a
python -m scripts.vancouver_capacity_riders ../Simulations/city 5a9289c6bc981c54b70d
python -m scripts.vancouver_diary_transfers ../Simulations/city 5a9289c6bc981c54b70d --booked-direct
python -m scripts.vancouver_diary_weekday ../Simulations/city 5a9289c6bc981c54b70d
python -m scripts.vancouver_market ../Simulations/city --fitted-atlas 5a9289c6bc981c54b70d
python -m scripts.vancouver_shopping_market ../Simulations/city --fitted-atlas 5a9289c6bc981c54b70d
python -m scripts.vancouver_diary_weekday ../Simulations/city 5a9289c6bc981c54b70d --preserve-modes --capacity
python -m scripts.vancouver_diary_weekday ../Simulations/city 5a9289c6bc981c54b70d --preserve-modes --capacity --transfers
python -m scripts.vancouver_market ../Simulations/city --fitted-atlas 5a9289c6bc981c54b70d --preserve-modes --workplaces-only
python -m scripts.vancouver_workplace_drives 265f5aaf1c3003f60de9
python -m scripts.vancouver_workplace_drive_repairs ../Simulations/city 265f5aaf1c3003f60de9
python -m scripts.vancouver_workplace_drive_repairs ../Simulations/city 265f5aaf1c3003f60de9 --apply
python -m scripts.vancouver_diary_weekday ../Simulations/city 5a9289c6bc981c54b70d --preserve-modes --capacity --tract-release 12abe0a44946315de998 --reuse-riders-from ac20ad40f5c86d824e13
python -m scripts.vancouver_diary_weekday ../Simulations/city 5a9289c6bc981c54b70d --preserve-modes --capacity --transfers --tract-release 12abe0a44946315de998 --reuse-riders-from bd42387cb0e4438bbb7b
clojure -M -m city.vancouver.atlas-diaries ../Simulations/city --shopping-comparison > target/vancouver-lunch-diaries.json
python -m scripts.vancouver_lunch_walks ../Simulations/city 5ab7efac0ffa7e618e13 target/vancouver-lunch-diaries.json
python -m scripts.vancouver_walk_reach 5ab7efac0ffa7e618e13 --network
```

#### Household vehicle access

Assign the vehicle availability of a whole household at once. Within each income bracket, a seeded draw of intact households stops at the closest count of adult residents implied by Figure 25 of the 2022 travel survey. The reported coverage goes from 52% of adults in the lowest bracket to 91% in the highest. Households without a complete income keep their original travel assumptions. The draw treats households within the same income range as exchangeable and represents a model assignment, including for the household members outside the age-18 survey cohort. Figure 54's mode percentages remain a separate check. [2022 Transportation Survey, Figures 25 and 54](https://vancouver.ca/files/cov/2022-transportation-panel-survey.pdf)

The comparison attempts to replace complete home-to-home driver tours in households assigned no vehicle. Every leg must use a known pair of endpoints. The tour retains the same stops, activity times and travel windows. It first tests walking at 80 m/min for the entire tour, then cycling at up to 220 m/min on the directed graph for residents with survey-based bicycle access. It also tests walks and scheduled transit within the same tour, with up to one transfer per transit leg. A failed tour retains all of its original trips. This leaves other journeys in households assigned no vehicle visible as demand the comparison has yet to accommodate.

The transit branch carries the combined weekday's riders forward. Some modeled bus segments are already over the proxy capacity. New riders can board on segments with remaining space, and a whole tour must fit before it uses any of that space. The added transit legs receive the same 800 m stop-access limit as the earlier replay, a three-minute initial boarding allowance and, on transfers, the published minimum connection time and a walk of up to 250 m. [Bus load data](https://www.translink.ca/tspr)

Of 40,419 candidate driver tours, 10,569 switch every leg. The resulting 21,321 changes include 7,721 walking trips, 12,194 bicycle trips and 1,406 transit journeys. The 62 already overloaded bus runs remain the same. Another 118,129 trips remain assigned to driving in households drawn without a vehicle. Across the lowest income bracket, the driving share falls from 58.2% to 54.0% and transit rises from 6.3% to 6.5%. The survey reports 22% driving and 44% transit. The comparison keeps trip locations and times fixed and prioritizes active modes before transit. [Replay household vehicle access](http://127.0.0.1:8187/cityday.html?jointRun=414d1c1c2b95a51d126d&vehicleRun=cb59e5b0455c18645ee0&incomeBand=0#income-trip-modes)

Of the unswitched driving trips, 68,971 are in eligible tours that fail to switch all legs. The other 49,158 fall outside eligible tours. In the lowest income bracket, 13,024 trips fall in unswitched eligible tours and 7,076 fall outside eligible tours. Even if all 23,730 original driver trips in this bracket's households drawn without a vehicle became transit and each counted as a full adult trip, transit would account for at most 34.2% of the 85,059.4 weighted adult trips. Closing the gap to the survey's 44% therefore requires changes beyond these households' driving trips.

The same 5,316 changes across the Downtown boundary appear in its hourly mode counts, which preserve total arrivals and departures. During 07:00–09:00, resident driver arrivals fall from 12,245 to 11,283. Matched city-resident alightings at six Downtown SkyTrain stations rise from 1,649 to 1,723 during those hours, against 25,677 observed alightings from all riders in 2025. [Compare Downtown rush hour](http://127.0.0.1:8187/cityday.html?jointRun=414d1c1c2b95a51d126d&vehicleRun=cb59e5b0455c18645ee0&downtown=am#downtown) · [TransLink station counts](https://www.translink.ca/tspr)

Rebuild with `python -m scripts.vancouver_vehicle_access ../Simulations/city 414d1c1c2b95a51d126d` after publishing the combined weekday with transit transfers and the municipal bicycle-access assignment.

#### Allowing a scheduled transfer

The paired replay keeps the 30,780 direct rides and tries one change of vehicles for the 55,787 unmatched bouts with accessible stops at both ends. The endpoints, diary windows and September 15, 2026 service stay fixed. The search uses shared platforms and directed GTFS transfer pairs connected by up to 250 metres of walking. It requires three minutes for boarding the initial vehicle. A connection must fit its walk plus the same margin and the minimum time published in GTFS. The replay preserves the street path, both vehicle trips and their scheduled times. [GTFS transfer rules](https://gtfs.org/documentation/schedule/reference/#transferstxt)

The transfer replay matches 42,722 of 118,807 resident transit bouts, including 11,942 with a change of vehicle. The rail comparison counts station entries and exits. A change within the same paid area at one station contributes zero gate crossings. A change between the Canada Line and Expo Line at Waterfront contributes an exit and an entry. [TransLink rail ridership definitions](https://www.translink.ca/-/media/translink/documents/plans-and-projects/managing-the-transit-network/tspr/tspr_2019_rail_definitions.pdf)

| Downtown SkyTrain counts | Direct rides | With transfers | Observed weekday, 2025 |
|---|---:|---:|---:|
| Morning alightings, 07:00–09:00 | 999 | 1,649 | 25,677 |
| Morning boardings, 07:00–09:00 | 346 | 562 | 7,557 |
| Afternoon alightings, 16:00–18:00 | 236 | 575 | 16,579 |
| Afternoon boardings, 16:00–18:00 | 508 | 957 | 29,796 |

Across the six pedestrian sites, matched access and egress plus the new interchange walks bring the simulated total from 783 to 836 over the 44 observed hours. Two passages come from the interchange paths themselves. The City counted 11,002. Independent shortest-path trees reproduce the hourly counts, and the occupancy array matches the direct-ride weekday at every minute. [Follow a change of vehicle](http://127.0.0.1:8187/cityday.html?jointRun=414d1c1c2b95a51d126d&downtown=am&jointSite=4#joint-weekday)

The six-station observations cover commuters, residents and visitors. The simulated station counts cover municipal residents with a feasible scheduled itinerary. The separate incoming-work cohort contains 3,609 attending workers assigned to Downtown jobs whose usual mode is transit. Of these, 1,803 have an outward trip window overlapping 07:00–09:00, before filtering for walk access, timetable fit or a Downtown rail station. This tally measures the size of the incoming commute cohort available to fit, alongside the remaining gap in resident rail journeys. [TransLink observed station counts](https://www.translink.ca/tspr) · [Incoming cohort method](#incoming-workers-and-downtowns-workday)

Rebuild the paired weekday with `python -m scripts.vancouver_joint_weekday ../Simulations/city --transfers`.

#### Incoming workers on the combined Vancouver weekday

The city weekday routes its incoming-worker cohort on the full September 15, 2026 TransLink timetable. The cohort uses synthetic home points from 2021 census dissemination areas outside the city, the published workplace assignments, and the original travel windows. The router checks an 800 m street walk to and from service and up to 250 m walking at each transfer. Resident journeys keep their vehicles and reservations. Translating their run indexes by service signatures reserves all 134,748 resident vehicle legs before matching incoming journeys. The six-station comparison includes both cohorts and can filter the incoming part by home municipality. [Open Downtown rush hour](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&downtown=am&commuters=combined#downtown)

With at most one transfer, 2,265 of 20,226 incoming work trips fit. There are 692 direct trips and 1,573 with a transfer. In this cohort, 2,800 trips lack stop access, 15,142 fail the timetable window and 19 fail the modeled bus capacity check. From 07:00 to 09:00, the incoming cohort adds 266 alightings across the six Downtown stations, giving 3,689 combined, compared with 25,677 observed across all riders. Between 16:00 and 18:00 it adds 270 boardings, giving 1,934 combined, compared with 29,796 observed across all riders. The modeled counts include scheduled city-resident trips and commutes from outside Vancouver. [Replay the one-transfer comparison](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&incomingTransit=f472aef67fc350d797b8&downtown=am&commuters=combined#downtown) · [TransLink station and bus tables](https://www.translink.ca/tspr)

The published weekday with two transfers retains all 2,265 earlier bookings and adds 604 within the original windows. It fits 2,869 of 20,226 trips. Its incoming cohort accounts for 323 of the combined 3,746 Downtown morning alightings and 317 of the combined 1,981 afternoon boardings. The worker inspector can follow individual transit bookings through all vehicles and their street walks. [Open the two-transfer weekday](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&incomingTransit=0e1492c6c8598b233eb2&downtown=am&commuters=combined#downtown)

The commute timing comparison gives an unmatched trip up to 15 extra minutes, then offers up to 30 minutes total to trips still unmatched. The trip to work can start earlier and the trip home can finish later. Work times, home and workplace coordinates, accepted bookings, bus capacities and the one-transfer limit are fixed. A recovered trip uses only the additional minutes required by the selected itinerary. The 15-minute allowance adds 2,043 bookings. The 30-minute allowance adds another 2,177, bringing the total to 6,485. Workers with a booked trip in both directions increase from 919 to 2,756. Raster checks the added 72,949 travel person-minutes against the per-worker clock and reproduces the paid-work counts at every minute. These time allowances are sensitivity settings. [Replay the commute timing comparison](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&incomingTransit=99a655b06036ea463183&downtown=am&commuters=combined#downtown)

The timing comparison brings the Downtown morning rail total to 4,179 alightings across the two cohorts. Its incoming-worker access, interchange and egress walks add 26 passages across the six pedestrian sites during the City’s recorded hours, compared with 12 incoming passages using the original commute windows. This gives 2,530 combined passages across all six sites, compared with 11,002 observed from all pedestrians. [Compare the Ontario and 5th walking count](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&incomingTransit=99a655b06036ea463183&jointSite=1#joint-counts)

To compare the timing settings with measured travel, standardize the published 2021 transit duration distributions to the synthetic cohort’s mix of home municipalities and straight-line trip distances. The Census counts cover usual workplaces at all destinations. The source has complete cells for 10,050 of 10,113 simulated transit workers. Mean assigned outbound duration is 54.4 minutes, compared with 53.3 after standardizing the Census mix. Among the 2,143 comparable outbound trips that the timing comparison extended, average planned duration moves from 46.1 to 61.9 minutes, compared with a Census benchmark of 49.3. Mean absolute error across the five duration shares rises from 2.6 to 10.5 percentage points for this subset. The timing comparison remains a sensitivity run. [Statistics Canada commute duration table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101)

Open **City of Vancouver · Combined weekday** in the shared run library to reopen the pinned census, street, resident and incoming releases. The library stores the published run in its browser Datahike database. [City simulation library](http://127.0.0.1:8187/runs.html?city=vancouver)

The incoming home fit compares the Census transit share across dissemination areas within each home municipality. It shrinks the area's public-transit share toward the municipal share using 40 equivalent published count units and adjusts the odds to respect the municipality's original synthetic transit stock. A deterministic nearest-home search exchanges a transit worker’s address with a worker of the same age band, gender and attendance status within the municipality. Both workers retain their workplace, commute distance band, mode and complete shift schedule. Each census area retains its synthetic worker count. The published commute counts cover all destinations and workplace types in the Census Profile universe. [2021 Census Profile](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E)

Of 91,675 synthetic incoming workers, 5,702 receive a different home area. The median move covers 1.65 km. Summed absolute error against the fitted home-area transit counts falls from 7,282 to 1,580. With one transfer allowed, 2,524 trips fit the timetable, up from 2,265 at the original homes. There are 302 gained and 43 lost bookings. Trips without street access to stops fall from 2,800 to 2,506, and the original commute-duration benchmarks by origin and distance still use the same workers and duration bands. Morning alightings at the six Downtown stations rise from 3,689 to 3,715 for the combined cohorts. [Compare fitted home locations with one transfer](http://127.0.0.1:8187/cityday.html?jointRun=5ab7efac0ffa7e618e13&incomingTransit=1621ce0c4c5ff3fa0130&downtown=am&commuters=combined#downtown)

With two transfers allowed on both sides, the fitted homes give 3,121 bookings, up from 2,869. There are 306 gained and 54 lost itineraries. The scheduler reuses 12,385 results for identical address pairs and travel windows, then checks bus capacity against the bookings in each replay. Morning alightings for the combined cohorts reach 3,771 across the six Downtown stations, compared with 3,746 at the original homes and 25,677 observed from all riders. Scheduled walks by incoming workers account for 17 passages during the six measured sidewalk windows. The current combined run in the city library pins the fitted homes. [Replay the fitted homes with two transfers](http://127.0.0.1:8187/cityday.html?dayRun=058dd1e2b3098a19fd2372ce8fca49e711d1bbdc566f6907c094323b33c0670e&downtown=am&commuters=combined#downtown)

The same home exchanges change 3,308 of 89,096 incoming driver trips. The directed metro road graph has 114,417 mapped sections, with posted driving speeds where available and class-based speeds elsewhere. At free flow, 61,215 trips fit the original window from the original homes and 61,086 fit from the calibrated homes. There are 84 gained and 213 lost feasible drives. The driver trace uses the computed road speeds and waits at the workplace if it reaches the job before the shift begins. The aggregate travel rows report assigned commute windows. [Inspect incoming drivers](http://127.0.0.1:8187/cityday.html?dayRun=058dd1e2b3098a19fd2372ce8fca49e711d1bbdc566f6907c094323b33c0670e&downtown=am&commuters=combined#incoming)

**Road counts across Vancouver** times those feasible drives at the legal city boundary and at twelve observed road locations. It uses elapsed free-flow time from the driver’s departure, including access from the home or workplace. At the legal boundary each route contributes the entry or exit closest to its workplace end. Each of the feasible drives crosses the boundary in both home assignments. The six eastern road locations use city-side approaches nearby. The city-limit total includes all incoming work municipalities. [Replay the morning city-limit crossings](http://127.0.0.1:8187/cityday.html?dayRun=058dd1e2b3098a19fd2372ce8fca49e711d1bbdc566f6907c094323b33c0670e&downtown=am&commuters=combined&roadGate=city&roadDirection=0#incoming-road-crossings)

| Location and travel direction | Hours | Original homes | Census-calibrated homes | March 2025 weekday, all vehicles |
|---|---|---:|---:|---:|
| City limit, into Vancouver | 07:00–09:00 | 14,578 | 14,556 | — |
| City limit, out of Vancouver | 16:00–18:00 | 14,278 | 14,251 | — |
| Lions Gate, toward Vancouver | 07:00–09:00 | 984 | 975 | 5,425 |
| Ironworkers, toward Vancouver | 07:00–09:00 | 812 | 813 | 8,483 |
| Oak Street Bridge, northbound | 07:00–09:00 | 1,134 | 1,150 | 6,071 |
| Kingsway near Boundary, westbound | 07:00–09:00 | 1,460 | 1,398 | 1,920 |

At the twelve stations the vehicle selector also shows resident drives to or from paid work, other resident drives and scheduled buses. Resident counts use the same combined weekday and its ClojureScript workplace resolver. The 713,583 candidate trips have a diary bout made entirely by car as driver. Trips with distinct mapped endpoints enter the route comparison. The solver excludes a route if it exceeds the available diary time. It counts paths by their elapsed travel time, including address connectors. The road graph and observed locations are shared with the incoming-worker comparison. The bus counts use mapped GTFS shapes and interpolate the crossing between scheduled departure and arrival times. Select an hourly result to follow a synthetic driver at the crossing. [Permanent count stations](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations) · [Ironworkers March 2025 counts](https://tradas.th.gov.bc.ca/reports/AllYears/2025/03/MV03/MV03P_Second%20Narrows%20P-15-2EW%20-%20NY3-2025.csv)

| 07:00–09:00 toward Downtown or Vancouver | Incoming work | Resident work | Other resident | Scheduled bus | Combined | Observed |
|---|---:|---:|---:|---:|---:|---:|
| Burrard Bridge, northbound | 60 | 1,618 | 720 | 28 | 2,426 | 2,988 |
| Granville Bridge, northbound | 513 | 1,372 | 359 | 66 | 2,310 | 3,726 |
| Cambie Bridge, northbound | 873 | 1,940 | 582 | 8 | 3,403 | 4,015 |
| Lions Gate, toward Vancouver | 975 | 0 | 0 | 65 | 1,040 | 5,425 |
| Ironworkers, toward Vancouver | 813 | 2 | 4 | 52 | 871 | 8,483 |
| Oak Street Bridge, northbound | 1,150 | 0 | 3 | 0 | 1,153 | 6,071 |
| Kingsway near Boundary, westbound | 1,398 | 389 | 726 | 11 | 2,524 | 1,920 |

The combined southbound count on Granville from 16:00 to 18:00 reaches 3,710 against 3,548 observed. The morning Kingsway approach also exceeds the count. The comparisons give different errors by time and location. The City’s March 2025 archive identifies each eastern station by street and direction. The released geometries omit the road segments, so those six modeled paths use nearby cuts on each named street. [Replay Granville Bridge](http://127.0.0.1:8187/cityday.html?dayRun=058dd1e2b3098a19fd2372ce8fca49e711d1bbdc566f6907c094323b33c0670e&downtown=am&commuters=combined&roadGate=GranvilleStBridge&roadDirection=1&roadVehicles=all#incoming-road-crossings)

The counters measure all vehicles. Of 223,454 recorded resident drives linked to paid work, 35,413 have an external job without a street address. Richmond accounts for 9,975 of those drives and Burnaby for 9,175. Nonwork visitors, freight, taxis and ride-hailing also fall outside the road comparison. Simulated drivers use free-flow routes without congestion feedback. Bus schedules come from a September 2026 weekday. The counters report weekday averages for the month recorded for each direction.

```sh
python -m scripts.vancouver_incoming_commutes ../Simulations/city 5ab7efac0ffa7e618e13
python -m scripts.vancouver_incoming_commutes ../Simulations/city 5ab7efac0ffa7e618e13 --two-transfers --processes 4 --checkpoint target/vancouver-incoming-transfer-checkpoint.json
python -m scripts.vancouver_incoming_commutes ../Simulations/city 5ab7efac0ffa7e618e13 --timing-from f472aef67fc350d797b8 --processes 3 --checkpoint target/vancouver-incoming-timing-checkpoint.json
python -m scripts.vancouver_incoming_duration_check 99a655b06036ea463183
python -m scripts.vancouver_incoming_home_fit ../Simulations/city 5ab7efac0ffa7e618e13 f472aef67fc350d797b8
python -m scripts.vancouver_incoming_commutes ../Simulations/city 5ab7efac0ffa7e618e13 --home-fit 8b9df5874a68abe758bb --processes 4 --checkpoint target/vancouver-incoming-home-routes-checkpoint.json
python -m scripts.vancouver_incoming_commutes ../Simulations/city 5ab7efac0ffa7e618e13 --home-fit 8b9df5874a68abe758bb --two-transfers --processes 4 --checkpoint target/vancouver-incoming-home-two-checkpoint.json --reuse-checkpoint target/vancouver-incoming-transfer-checkpoint.json
python -m scripts.vancouver_incoming_drives 5ab7efac0ffa7e618e13 8b9df5874a68abe758bb
python -m scripts.vancouver_incoming_road_crossings ../Simulations/city 5ab7efac0ffa7e618e13 8b9df5874a68abe758bb
python -m scripts.vancouver_resident_road_crossings ../Simulations/city 5ab7efac0ffa7e618e13 8b9df5874a68abe758bb
clojure -M -m city.run-catalog vancouver-combined-weekday 5ab7efac0ffa7e618e13 public/data 03738fec2bffa002bc2a
npx shadow-cljs release experiments
```

#### Resident road commutes to external workplaces

The current **Combined weekday** in the city library includes the mapped outbound workplaces. Open **Residents working outside Vancouver** to compare it with the municipality-only replay. The model gives a mapped workplace to a resident only when every recorded leg touching their paid-work stops can reach that same site in its diary window. Whole driving and car-passenger legs can use the directed metro road graph. A worker needs at least one recorded drive to qualify. Missing endpoints, unsupported modes and unrecorded changes of place can keep a workplace at municipality resolution. The replay retains each worker’s original Census municipality, mode, time window and paid-work intervals. At the destination, the clock uses the original diary’s start of paid work.

The inventory uses OpenStreetMap job locations, including shops, offices, industrial premises, schools and airport terminals within 14 Census subdivisions. The model finds all address candidates that fit the diary before applying the Census tract employment prior. Within a tract it favours drives close to the diary duration. It fits the feasible workers with the fewest available tracts first, using the remaining employment-weighted tract targets where feasible. Tract employment totals cover people with usual workplaces across all home origins and serve as a geographic prior. The individual addresses are synthetic assignments conditional on the municipality, mapped opportunities and diary. [Census place-of-work income table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801) · [Census commuting flows by subdivision](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

The road panel adds **Residents’ work drives outside Vancouver** at the legal city limit and twelve traffic locations. Selecting an hour follows a driver at the modeled crossing time. The companion report independently checks the assigned municipality and daily activities against the original roster. Raster executes the same paid-work clock for 8,919 individual residents and 1,051 weighted groups and compares both with per-minute enumeration. The mapped and municipality-only counts sum to the baseline external workplace count every minute. At noon, 7,623 residents are at mapped external jobs and 33,450 are at a job known only by municipality. [Follow a morning driver at the city limit](http://127.0.0.1:8187/cityday.html?dayRun=a5e1ed1a9e952923ec8be7827b369b0e660cbe7462e91bfb68c19d32dfa63740&downtown=am&commuters=combined&roadGate=city&roadDirection=1&roadVehicles=outboundWork#incoming-road-crossings)

The fitted release maps 8,919 residents to 4,736 workplaces. It recovers 17,893 of 35,413 recorded resident work drives with an external job. Among the 16,095 residents with at least one such drive, 4,529 fall outside the address inventory or have an unsupported travel mode, missing leg, or missing endpoint. Another 2,647 have no site that fits all their legs. The assigned drives average 16.5 minutes by free-flow roads and 35.7 minutes in the original diary. A driver who reaches the destination early stays there until the original activity begins. Parking and congestion remain outside this timing model.

The mapped share of residents with an external work drive varies by home neighbourhood. It ranges from 38.7% in West Point Grey (67 of 173 residents) to 62.3% in South Cambie (104 of 167). In Renfrew-Collingwood, which contributes the most mapped residents, it is 58.1% (1,131 of 1,948). These are route and diary coverage rates within the synthetic cohort.

| Municipality | Workers placed | Driving legs placed | Recorded driving legs |
|---|---:|---:|---:|
| Richmond | 2,953 | 5,938 | 9,975 |
| Burnaby | 2,810 | 5,646 | 9,175 |
| Metro Vancouver A | 618 | 1,235 | 2,660 |
| City of North Vancouver | 462 | 924 | 1,793 |
| District of North Vancouver | 440 | 880 | 1,674 |
| All external municipalities | 8,919 | 17,893 | 35,413 |

The mapped outbound cohort adds 4,112 drives out of Vancouver from 07:00 to 09:00 and 3,789 drives into Vancouver from 16:00 to 18:00. Two drives have both anchors on the same side of the legal city line and contribute only to named road counts where applicable. In the morning, the combined eastbound count near Kingsway rises from 1,131 to 1,453 against 1,923 observed. The combined northbound count over Ironworkers rises from 47 to 377 against 9,096 observed. The added trips improve specific directions and leave substantial traffic unexplained. [Vancouver permanent count stations](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations) · [Ironworkers March 2025 counts](https://tradas.th.gov.bc.ca/reports/AllYears/2025/03/MV03/MV03P_Second%20Narrows%20P-15-2EW%20-%20NY3-2025.csv)

```sh
python -m scripts.vancouver_outbound_road_jobs ../Simulations/city 5ab7efac0ffa7e618e13 8b9df5874a68abe758bb
python -m scripts.vancouver_commuter_basemap ../Simulations/city 36ff43d53013e09dd6be
python -m scripts.vancouver_outbound_road_counts ../Simulations/city f5eaa497b25db2fb1d92
clojure -M -m city.run-catalog vancouver-combined-weekday 5ab7efac0ffa7e618e13 public/data 03738fec2bffa002bc2a f5eaa497b25db2fb1d92
clojure -M:ui -m shadow.cljs.devtools.cli release experiments
```

#### Resident transit commutes to external workplaces

The municipal weekday also tests outbound work diaries whose paid-work trips use transit, with walking permitted in a transit bout. A resident needs a recorded outward and return trip, located anchors and an address in the assigned Census municipality. The candidate job points use the same Census tract weights and mapped workplace inventory as the outbound road fit. The worker keeps their mode, municipality, work intervals and original travel windows.

The reachability screen scans the dated connections forward from the recorded departure or backward from the deadline. It checks every mapped workplace in the municipality for a full set of feasible trips. Access uses connected pedestrian paths of up to 800 metres. The timetable allows two transfers per journey using published permitted transfer pairs, a three-minute boarding margin and connected transfer walks of up to 250 metres. After the screen, the booking step tries up to eight addresses. It prioritizes the workers with the fewest feasible tracts and uses the remaining tract targets to choose among addresses. A successful worker keeps one job address and all of their recorded transit windows. [TransLink GTFS](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data) · [Census commuting flows by subdivision](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901)

Bus capacity is shared with the already-booked city residents and incoming workers. The builder holds those reservations in place and adds an outbound worker’s reservations only when all their legs can be booked. Capacity uses the published proxy by bus route. The audit rereads the timetable and verifies all boarding rules, transfer margins and door-to-door deadlines. It also reruns the mapped workplace clock using Raster’s weighted and individual executions and checks that the road and transit workplace assignments contain different residents. [TransLink service performance review](https://www.translink.ca/tspr)

The release books 7,370 journeys for 3,685 residents across 12 destination municipalities, including 1,716 in Burnaby and 1,237 in Richmond. There are 1,671 direct journeys, 4,294 with one transfer and 1,405 with two. The starting cohort contains 14,181 residents with a work-linked transit bout. Of the 10,331 who qualify for the timetable screen, 648 lack stop access at an existing anchor, 5,659 have no single site feasible for all their windows, and 339 remain unbooked after the bounded address and capacity search. The capacity comparison starts with 140,766 earlier vehicle-leg reservations. At noon both outbound layers together have 11,053 residents at mapped external jobs, with 30,020 more at jobs known only by municipality. [Follow outbound transit on the combined weekday](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&downtown=am#outbound-transit-work)

The duration check uses booked home-to-work trips. It standardizes the Census usual-workplace transit durations to the published replay’s straight-line distance mix and compares them with the original diaries and scheduled travel including walking and waiting from the recorded departure. The Census margin includes Vancouver residents travelling to workplaces inside and outside their home municipality. [Census commuting duration table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101)

The original home-to-work window averages 60.1 minutes across the screened cohort and 73.3 minutes among those booked. The booked journeys take 67.9 minutes on the timetable, compared with 40.3 minutes in the distance-standardized Census reference. Longer diaries are overrepresented in the booked cohort. The fitted timetable is a feasibility check, and the duration gap remains a calibration target.

**Time departures for the booked vehicles** compares the same 7,370 passenger journeys with a clock that keeps each worker at the origin until the latest whole minute that leaves enough time for the walk and a three-minute platform margin. Each passenger takes the original vehicles, walks the original paths, and starts paid work at the same minute. After the final walk, the passenger is at the destination until the diary activity begins. This alternative uses a known timetable and assumes workers can use spare time at either endpoint. [Try the timing comparison](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&outboundClock=8dccb2c9f12af0e98820&downtown=am#outbound-transit-work)

| Stage in 3,685 booked home-to-work journeys | Recorded departure | Timetable-timed departure |
|---|---:|---:|
| Walking, including transfers | 10.6 min | 10.6 min |
| Waiting at the first stop | 24.9 min | 3.5 min |
| Waiting at transfer stops | 7.4 min | 7.4 min |
| Aboard vehicles | 25.1 min | 25.1 min |
| Door-to-door journey | 67.9 min | 46.5 min |

The timed replay reallocates 21.4 minutes of the average recorded-departure journey to time at the origin. It narrows the mean gap to the 40.3-minute Census reference. Departure hours still differ substantially. Around 51% of the booked workers depart between 09:00 and noon in either replay, compared with 20% in the distance-matched Census reference. The mean absolute error across the six departure shares stays at 12.2 percentage points. The published combined weekday defaults to the recorded departure times and offers the timed replay as a sensitivity comparison. [Census departure and duration table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101)

Raster checks the timetable clock for 3,683 residents whose minute-level activity locations change. Both individual and grouped executions agree with direct interval accounting. The timed replay has 1,491 fewer residents travelling at 09:00. Paid-work occupancy and booked vehicles stay fixed, and each minute accounts for all 662,248 residents. The city clock counts mapped external workplaces as places and keeps municipality-only locations in the unresolved total. The Downtown rail benchmark now includes outbound bookings. These add 54 morning alightings and 86 boardings in the six Downtown stations. [TransLink service performance review](https://www.translink.ca/tspr)

```sh
python -m scripts.vancouver_outbound_transit ../Simulations/city 5ab7efac0ffa7e618e13 03738fec2bffa002bc2a
python -m scripts.vancouver_outbound_transit_audit 01a4505c4a27a12673f3 --road f5eaa497b25db2fb1d92
python -m scripts.vancouver_outbound_transit_clock ../Simulations/city 01a4505c4a27a12673f3 --road f5eaa497b25db2fb1d92
clojure -M -m city.run-catalog vancouver-combined-weekday 5ab7efac0ffa7e618e13 public/data 03738fec2bffa002bc2a f5eaa497b25db2fb1d92 01a4505c4a27a12673f3
clojure -M:ui -m shadow.cljs.devtools.cli release experiments
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver
```

#### Published Downtown rush-hour benchmark

The **Rush-hour benchmark** in the Downtown inspector uses the combined municipal weekday with mapped outbound workplaces and fitted incoming worker homes. It compares vehicle crossings on the three False Creek bridges and passenger events at Burrard, Granville, Stadium-Chinatown, Vancouver City Centre, Waterfront and Yaletown-Roundhouse. Totals cover 07:00–09:00 and 16:00–18:00. The busiest hour in each direction is found over the broader 06:00–11:00 and 15:00–20:00 bands, keeping ties. The downloadable report includes all 24 hours and the contribution of each modeled cohort. [Open the benchmark](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&minute=480#downtown-audit)

| Comparable count and window | Observed | Modeled | Busiest hour starts, observed → modeled |
|---|---:|---:|---|
| Burrard northbound, 07:00–09:00 | 2,988 | 2,478 | 08:00 → 07:00 |
| Burrard southbound, 07:00–09:00 | 2,758 | 808 | 08:00 → 09:00 |
| Burrard northbound, 16:00–18:00 | 3,485 | 1,847 | 16:00 → 17:00 |
| Burrard southbound, 16:00–18:00 | 4,219 | 2,175 | 17:00 → 16:00 |
| SkyTrain alightings, 07:00–09:00 | 25,677 | 3,825 | 08:00 → 08:00 |
| SkyTrain boardings, 07:00–09:00 | 7,557 | 805 | 08:00 → 09:00 |
| SkyTrain alightings, 16:00–18:00 | 16,579 | 921 | 16:00 → 18:00 |
| SkyTrain boardings, 16:00–18:00 | 29,796 | 2,054 | 17:00 → 17:00 |

Northbound trips account for 52% of observed morning vehicles on Burrard and 75% of modeled vehicles. The afternoon southbound shares are 55% observed and 54% modeled. Burrard's two counter series both represent March 2025. Granville's southbound and northbound series represent December 2020 and July 2022 respectively. Cambie's represent March 2025 and November 2024 respectively. Each series has its own comparison in the report. [City of Vancouver permanent count stations](https://vancouver.ca/streets-transportation/traffic-count-data.aspx#permanent-count-stations)

The simulated road counts include work and other car-driver trips with usable routes, fitted incoming drivers and scheduled buses. The published road graph uses free-flow times. The SkyTrain counts include bookings for residents and incoming workers. Incoming work trips account for 348 of 3,825 modeled morning alightings and 344 of 2,054 modeled afternoon boardings. The observed rail series includes all riders on a 2025 average weekday. The replay pairs synthetic diaries, worker assignments and a September 2026 timetable. Gaps can reflect cohort coverage, route feasibility and demand timing. These comparisons cover selected crossings and station events, which use different units from the Downtown endpoint and mode tables. [TransLink service performance review](https://www.translink.ca/tspr)

Across the entire municipal incoming transit cohort, the router books 3,121 of 20,226 attempted work legs. Another 2,506 lack usable stop access and 14,599 remain unmatched after the stop-access check. Those totals cover all Vancouver workplaces in the incoming cohort. They identify a routing gap to investigate alongside trips missing from the synthetic demand.

##### Downtown transit demand and bookings

Under **Rush-hour benchmark**, select **Six Downtown SkyTrain stations** and open **Transit demand and bookings**. The comparison counts simulated trips crossing the Downtown local-area boundary. The morning window uses the trip's planned arrival and the afternoon window uses its planned departure. The resident column traces the located walk-and-transit bouts used by the combined ride publisher. The incoming column traces attending transit commuters who work Downtown. Residents with mapped external jobs are counted in the station benchmark and have their own route assignment outside this comparison. The downloaded series covers all 24 hours and splits residents by home neighbourhood and incoming workers by home municipality. [Inspect demand and bookings](http://127.0.0.1:8187/cityday.html?dayRun=9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f&minute=480#downtown-transit-audit)

| Modeled Downtown transit trips | Resident arrivals 07:00–09:00 | Incoming worker arrivals 07:00–09:00 | Resident departures 16:00–18:00 | Incoming worker departures 16:00–18:00 |
|---|---:|---:|---:|---:|
| Trip windows | 7,359 | 1,478 | 8,129 | 1,656 |
| Missing usable stop access | 196 | 224 | 803 | 239 |
| Accessible and unbooked | 538 | 929 | 2,502 | 1,061 |
| Booked | 6,625 | 325 | 4,824 | 356 |
| Of those booked, use SkyTrain somewhere | 2,238 | 271 | 1,406 | 309 |

The incoming search checkpoints identify 929 morning and 1,057 afternoon trips for which neither production search found an itinerary. Four other outgoing trips had an itinerary and remained unbooked at the seat check. An independent connection scan includes the walk from the last stop in the deadline. All the production search misses remain infeasible at their original windows. The earlier diagnostic used final vehicle arrival to determine whether the query returned a connection and counted trips whose final walk arrived late. With the corrected check, allowing up to 30 more minutes on the home side makes 655 morning and 677 afternoon search misses feasible before considering bus reservations.

The resident route input loses mixed-mode and unresolved bouts citywide before the endpoint comparison. The incoming demand includes commutes and leaves out other external purposes such as shopping and leisure. The station counters measure events across all riders, including trips without an endpoint in the Downtown neighbourhood. To measure how much demand is missing before routing, the relevant comparison is observed transit trips by matched origin, Downtown destination, purpose and time. The public 2023 Trip Diary dashboard covers municipality-level flows. The finer origin–destination tables identified in [DATA.md](../DATA.md) would support that comparison. [TransLink Trip Diary](https://www.translink.ca/plans-and-projects/data-and-information/research-and-insights/trip-diary-survey)

Rebuild the same comparison from the published inputs by pinning the outbound booking clock alongside the weekday.

```sh
clojure -M -m city.vancouver.downtown-audit public/data \
  9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f 8dccb2c9f12af0e98820
python -m scripts.vancouver_downtown_transit_audit \
  9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f --processes 4
```

The transit audit writes checked search checkpoints under `target/downtown-transit-audit`. To reuse the matching build's existing checkpoints, copy its fitted-home one-transfer checkpoint to `one.json` and its two-transfer checkpoint to `two.json` there. The audit checks the pinned inputs and the hash of the ordered search windows before using either checkpoint.

##### Booking with fixed work shifts

Open **Test the commute window** in the transit demand panel. The experiment reconstructs itineraries from the independent timetable scan and verifies that their walks and transfers fit. It protects the published resident, incoming and outbound work bookings and uses the same bus segment capacity proxies. Each stage keeps accepted bookings from earlier stages and tries the smallest whole-minute extension available for each pending trip, with a capacity-aware retry within the stage's allowance if necessary. All cases keep the same endpoints and work shifts. Extensions move the home departure earlier or the home arrival later.

| Incoming work windows | Added trips across the day | 07:00–09:00 SkyTrain alightings | 16:00–18:00 SkyTrain boardings | Census duration error |
|---|---:|---:|---:|---:|
| Published weekday | 0 | 3,825 | 2,054 | 2.33 pp |
| Independent search, original windows | 0 | 3,825 | 2,054 | 2.33 pp |
| Up to 15 extra minutes | 1,363 | 4,075 | 2,337 | 2.59 pp |
| Up to 30 extra minutes | 2,739 | 4,333 | 2,613 | 4.60 pp |
| Observed station counts | — | 25,677 | 29,796 | — |

The duration comparison uses the same 3,592 supported home-to-work trips in every row. It compares planned door-to-door window length with the five Census duration bands standardized to the modeled trips' home municipality and straight-line distance. With 30 extra minutes allowed, the mean window grows from 55.9 to 61.7 minutes versus 53.8 in the Census reference. Counts are for all station users in the reference and modeled riders in the replay. The capacity-checked comparison leaves a large station-volume gap even at 30 minutes. Both extensions are sensitivity settings. [Census commuting duration](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101&request_locale=en) · [SkyTrain station counts](https://www.translink.ca/tspr)

```sh
python -m scripts.vancouver_downtown_transit_booking \
  9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f ../Simulations/city
```

Load the experiment once in the Clojure REPL. Each target includes its source, period, geography, population and unit. The residuals keep duration shares and passenger event counts in their own units.

```clojure
(require '[city.vancouver.booking-scorecard :as booking])
(def experiment
  (booking/load-experiment "public/data"
    "9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f"))
(booking/scorecard experiment)
```

##### Separating North Shore workplace assignment and timing

In **Test the commute window**, choose **North Shore workplaces and timing**. The comparison starts from the same municipal weekday and uses North Shore transit workers who attend a mapped job in Vancouver. The workplace fit transfers the three 2023 survey shares for CBD and West End jobs conditional on working in Vancouver or UEL. These are all-mode usual-workplace shares used as proxies for the modeled transit cohort. The model uses Downtown and the West End for the CBD and West End group. Its municipal cohort has Vancouver jobs. [2023 North Shore Transportation Survey, Table 20](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

The fit exchanges job addresses between an incoming North Shore transit worker and an incoming transit worker from elsewhere. Only workers with neither leg booked can exchange. The partners share a gender and age stratum, retain their own homes and shifts, and both keep their original Census commute distance band. The exchange preserves the number of assigned jobs at each address. Job selection uses the survey targets and ranks exchanges by the total change in the partners' straight-line commute distances. Timetable feasibility and station counts are evaluated after assignment.

The fit makes 272 exchanges. The North Shore cohort's Downtown and West End share rises from 40.5% to 60.6%. The independently rounded 2025 survey cells give about 59.6% among North Shore commuters to Vancouver or UEL, across all modes. The fit has 13 fewer Downtown or West End workers than the 2023 proxy quota for the City of North Vancouver. District of North Vancouver and West Vancouver reach their quotas. [2025 North Shore Transportation Survey, Table 54](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

| Case | Added bookings in the paired cohort | Booked North Shore legs | Downtown morning SkyTrain alightings | Downtown afternoon SkyTrain boardings | Duration error |
|---|---:|---:|---:|---:|---:|
| Original jobs and windows | 0 | 261 | 3,825 | 2,054 | 1.00 pp |
| Original jobs, up to 15 extra minutes | 470 | 607 | 3,846 | 2,092 | 1.14 pp |
| Fitted jobs, original windows | 43 | 299 | 3,825 | 2,055 | 1.00 pp |
| Fitted jobs, up to 15 extra minutes | 485 | 694 | 3,829 | 2,061 | 1.24 pp |

All four cases route the same 1,626 workers, including 272 exchange partners from outside the North Shore. The comparison protects all existing bookings and uses the same bus segment limits in both workplace assignments. The duration comparison standardizes the Census bands to the same 1,617 supported home-to-work trips. Station events cover the combined weekday. The workplace fit improves the approximate destination share and has little effect on SkyTrain volumes. Combining the workplace fit with longer windows adds more bookings for the North Shore cohort and yields fewer additional SkyTrain events than longer windows alone. The two metrics count different parts of the transit system. [Census durations](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810046101&request_locale=en) · [TransLink station counts](https://www.translink.ca/tspr)

Run the paired comparison and load it with `city.vancouver.booking-scorecard/load-workplace-timing`. The same `scorecard` function includes the 2025 workplace share as a held-out comparison and scores duration distributions and passenger events in their own units.

```sh
python -m scripts.vancouver_commute_sensitivity \
  9a347b6c66b391a5ee139050c5ba5540ba11f9e2733ca706ff121bc3cb13966f ../Simulations/city
```

#### Incoming workers on the regional timetable

The regional workplace replay adds scheduled trips for the attending external workers assigned to transit. Their homes are represented by census dissemination-area points outside the regional resident roster. The workplace address, travel time window and shift remain fixed. The matcher permits one change of vehicle and books bus space after loading the resident work, personal, attendance and outing reservations from the same published day. This order gives the resident itineraries priority when a bus segment fills. The capacity proxy covers the buses in the TransLink tables. [Follow an incoming commuter](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&incomingTransit=6ab0417f6bd7bb2aa7c2#regional-incoming-transit)

The regional matcher assigns 1,109 of 19,766 incoming journeys. There are 450 direct trips and 659 with a transfer. Of the remaining trips, 11,924 lack a stop within an 800 metre walk, 6,730 have accessible stops and fail the timetable window, and three run out of bus space. The access failures occur at the home only on 11,008 trips, at the workplace only on 386, and at both ends on 530. The booked cohort adds 87 alightings and zero boardings from 07:00 to 09:00 at the six Downtown SkyTrain stations. From 16:00 to 18:00 it adds 16 alightings and 116 boardings. These counts describe the external cohort of the regional release. Point placement and the coverage of the street and transit networks affect the access result. [TransLink station and bus tables](https://www.translink.ca/tspr)

Counting each worker once, 5,769 fail the walk-to-stop check at home. Of these, 4,748 home points are outside the mapped street frame and 4,799 have no scheduled stop within 800 metres in a straight line in the published timetable subset. Only 249 have no stop point within that radius in the complete archived GTFS feed. The full feed comparison includes every passenger stop in the archive across calendar days. An 800 metre straight-line distance establishes proximity alone. Walkable routes and service on the modeled date still need to be checked. [Timetable and street sources](../DATA.md)

Rebuild the incoming comparison with `python -m scripts.vancouver_regional_inbound_transit ../Simulations/city` after publishing the regional incoming workers and resident transit layers.

#### Walking and transit coverage at commuter origins

The paired coverage run uses all trips with stop times from the same TransLink GTFS archive on the modeled weekday. The street extractor takes walkable OpenStreetMap ways within the envelope of the commuter endpoints and timetable stops, with an extra 802 metres on each side. It retains connections only between consecutive nodes on the original way. The maximum access walk stays 800 metres and the maximum interchange walk stays 250 metres. The 3D buildings and resident roster still cover the regional study area described above. [OpenStreetMap archive and network inputs](../DATA.md)

The wider timetable can reorder route runs. Resident bus reservations are translated by stop IDs, permissions, geometry, departure time and every stop time. Matching also preserves the order and count of runs with identical signatures. The expanded run keeps the same worker homes, workplace assignments, work attendance, commute windows and resident reservations. It publishes the exact access and egress walking paths used in the new journeys.

The timetable grows from 88 routes and 12,303 runs to 236 routes and 25,726 runs. The walking graph contains 280,372 mapped sections. Stop-access failures fall from 11,924 to 3,022 trips. The replay matches 1,614 of 19,766 incoming work trips, including every one of the original 1,109 journeys and 505 additional journeys. The number of direct trips remains 450. With one transfer, the number rises from 659 to 1,164. An additional 15,126 trips have pedestrian access at both ends and fail to find an itinerary within their existing time and one-transfer limit. Four run out of bus space. [Follow a commuter on the wider network](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&incomingTransit=4f87677c97727a62b999#regional-incoming-transit)

| Six Downtown SkyTrain stations | Earlier incoming cohort | Expanded incoming cohort | Observed, all riders |
|---|---:|---:|---:|
| 07:00–09:00 alightings | 87 | 159 | 25,677 |
| 07:00–09:00 boardings | 0 | 0 | 7,557 |
| 16:00–18:00 alightings | 16 | 41 | 16,579 |
| 16:00–18:00 boardings | 116 | 169 | 29,796 |

Rebuild with `python -m scripts.vancouver_regional_inbound_transit ../Simulations/city --expanded` after publishing the earlier coverage comparison and obtaining `data/region/vancouver.osm.pbf`.

The next comparison allows a second transfer and adds 746 journeys, for 2,360 of 19,766 incoming transit trips. The 1,614 earlier itineraries keep their routes and times. Each added trip keeps the same home, workplace and travel window, and the matcher reserves every occupied bus segment. The two transfer walks each follow the street graph and are limited to 250 metres. Among the remaining unmatched trips, 3,022 lack stop access and 14,384 lack a feasible match within their timetable window and the capacity check. The six Downtown stations now receive 216 modeled morning alightings and 211 afternoon boardings from this cohort, up from 159 and 169. [Follow a commuter across three vehicles](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&incomingTransit=5322edc1367cbecf2bac#regional-incoming-transit)

Rebuild the second-transfer comparison with `python -m scripts.vancouver_regional_inbound_transit ../Simulations/city --two-transfers`.

### North Shore resident travel demand

Open **Compare North Shore travel with surveys** to compare trips per 1,000 residents by home municipality, mode, destination purpose, departure hour and southbound destination. You can follow an example with two located and distinct endpoints. The comparison includes all 158,899 private-household residents with a known age of at least 15, including those who stayed home. The 2023 survey population is 168,310 at ages 15 and older. Its municipal groups also include First Nations areas listed in Table 1. The simulated weekday uses the three modeled municipalities. The per-capita comparison accommodates population size and still reflects differences in geographic coverage and survey year. [Open the North Shore comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&northDemand=North+Shore&northBreakdown=purposes) · [2023 North Shore Transportation Survey, Tables 1, 3, 4, 7 and 8](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

The downtown-fit weekday records 309,312 trips, or 1.95 per resident, compared with 3.12 per resident in the survey. The driver share is about 68% in both. The two observed peak hours and daily rates by purpose show where trip demand is low.

| Measure | Model, trips per 1,000 residents | Survey, trips per 1,000 residents |
|---|---:|---:|
| Auto driver, full day | 1,324.1 | 2,124.5 |
| Cycling, full day | 19.1 | 73.1 |
| Paid work, full day | 389.7 | 458.9 |
| Shopping and personal errands, full day | 228.7 | 589.5 |
| Recreation, full day | 99.2 | 276.9 |
| Trips starting 08:00–09:00 | 152.5 | 300.6 |
| Trips starting 16:00–17:00 | 167.2 | 304.2 |

Consecutive travel episodes form a single trip. Primary mode follows the survey’s ordering, including taxi, motorcycle and ride-hailing in Other. Trip purpose uses the immediate destination activity and location. The comparison pools shopping, household maintenance and personal business, combines usual and work-related travel, and groups passenger escorting with other or unclear purposes. It estimates purpose counts from rounded published shares. The survey counts recreational loops without intervening destinations. The weekday can record a trip in the same assigned place or with a missing endpoint and has limited information on escort and recreational loops. The departure comparison shows the two peak-hour totals stated in section 3.1.2. [Survey definitions and peak hours](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

There are 68,230 changes between assigned places without a recorded trip. Of these, 3,752 have a walk that fits both bordering activities and takes at most ten minutes at 80 metres per minute on the directed pedestrian graph. **Replay reconstructed short walks** permits these inferred trips and displays their routes when following residents. These walks raise the North Shore estimate from 1.95 to 1.97 trips per resident. The evidence table continues to show the recorded diary counts. The reconstruction accounts for departures, arrivals and occupancy for the full 867,776-resident roster on each minute.

The downtown job exchanges raise assigned southbound trips to Downtown or the West End from 5,697 to 11,780. Across Downtown, the rest of Vancouver and UBC, the combined assigned count stays at 31,029, against 36,030 of the survey’s southbound trips. Another 18,550 of the survey trips cross southbound to destinations beyond Vancouver and UBC, including Burnaby and New Westminster. These comparisons use all modes from North Shore resident diaries and use assigned endpoints for the model. They provide separate evidence from the traffic counters. [Survey, Table 11](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

The held-out 2025 survey estimates 698,400 trips for 174,600 residents aged 15 and over, or 4.00 trips per person. It reports 97,000 recreation trips and 156,400 walking trips. Fieldwork began about a month earlier than for the 2023 survey. The report discusses earlier daylight and weather as possible contributors to the increase in recreation. Municipality-level purpose counts are estimates from whole percentages. The regional columns show published counts where available. [2025 North Shore Transportation Survey, section 5](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The eastern replay assigns 4,031 outward trips to Burnaby and New Westminster. The 2023 and 2025 surveys estimate 11,540 and 12,100 trips in those directions across all purposes. The 2025 survey separately estimates roughly 5,600 people who commuted to Burnaby that day, summed across eight home zones. The difference in outward trips includes commute demand as well as other activities. The survey's crossing table does not divide those trips by purpose. [Open the southbound comparison](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=c1b31a9daf40041dcb73&northDemand=North+Shore&northBreakdown=outbound) · [2025 North Shore Transportation Survey, Tables 35 and 54](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The panel is published for the original regional weekday, the municipal workplace fit, the downtown fit and the eastern workplace fit. To rebuild the reference views and the routed gaps for the downtown fit, run these commands with the survey PDFs in the archive paths listed in `DATA.md`.

```sh
python -m scripts.vancouver_short_walks --region --day 14dfd26a0355cc5695ea
python -m scripts.vancouver_north_shore_demand --day 803724fb5af012e0a0c7 --day 7bc1b970083653ba45cd --day 14dfd26a0355cc5695ea --day 533a1bf0a60bb5bab477
clojure -M:ui -m shadow.cljs.devtools.cli release experiments
```

### Additional North Shore shopping and recreation outings

Open **Add shopping and recreation outings** on the downtown-fit weekday. The comparison shows the recorded and augmented weekday for driving and walking. Enabling the replay adds the journeys, destination stays and returns to the live clock. Choose **Follow** and use the three steps to inspect one outing. The household atlas shows the original diary.

A resident can add one home-based outing during an uninterrupted block of at-home media or leisure. The allocator reserves time for work, school, care, sleep and previously reconstructed short walks. An added drive requires a resident aged 20 or older with a driving episode in the original diary. The model draws a whole, single-mode, home–destination–home tour from the original diary templates. It uses the full recorded dwell and treats the two recorded travel times as separate ceilings. It draws the new start within a feasible break in the schedule, favouring the donor departure. The assigned road or walking path determines the actual leg time.

Candidate addresses are named North Shore shops, parks and recreation sites from the existing mapped inventory. Walking uses the pedestrian graph at 80 metres per minute. Driving uses directed free-flow street times. The search includes the eight nearest addresses of each type and, for drivers, nearby candidates in eight directions around the home at two, four and six kilometres. Among reachable driving destinations, it favours the one whose travel times most closely match the donor’s. Visits must fit assumed hours of 08:00–20:00 for shopping and 07:00–21:00 for recreation. Access, parking, opening hours and capacity are generalized assumptions at individual sites.

Table 7 and Figure 14 provide purpose and mode targets. The allocator uses each municipality's reported per-resident trip rates and the North Shore purpose-specific shares for drivers and walkers. It adds trips up to the gaps in those cells. This uses marginals for all destinations to constrain a local daytime replay. The destinations, timings and other modes remain evaluation gaps. [2023 North Shore survey, Table 7 and Figure 14](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

The fitted weekday adds 59,868 outings at 844 named destinations. There are 39,385 shopping and errand outings and 20,483 recreation outings. Driving accounts for 39,603 and walking for 20,265. Two legs per outing bring the North Shore total from 309,312 to 429,048, or from 1.95 to 2.70 trips per resident. The survey reports 3.12. Added driving legs average 9.2 minutes, compared with 2.7 minutes when the search used only nearby venues. Added walking legs average 10.6 minutes. The survey's averages across all origins, destinations and purposes are 12.7 minutes for drivers and 12.6 minutes for walkers. [Replay the added outings](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&outingsRun=a639dda90b0f9f2ebb91) · [North Shore survey, Table 13](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

| Measure | Recorded trips per 1,000 residents | With added outings | Survey estimate |
|---|---:|---:|---:|
| Shopping and personal errands, full day | 228.7 | 476.6 | 589.5 |
| Recreation, full day | 99.2 | 228.1 | 276.9 |
| Trips starting 08:00–09:00 | 152.5 | 168.7 | 300.6 |
| Trips starting 16:00–17:00 | 167.2 | 222.1 | 304.2 |

Raster checks the scenario as resident itineraries and as weighted groups of identical area and time intervals. Both executions must match an independent minute-by-minute enumeration. The build uses the same Raster interval phase as the work-from-home comparison.

```sh
python -m scripts.vancouver_north_shore_demand --day 14dfd26a0355cc5695ea
python -m scripts.vancouver_discretionary_outings
```

#### Bicycle and scheduled transit outings

The expanded replay fits bicycle and transit outings around the same paid work, care, sleep and short-walk commitments. Both modes use an observed dwell and departure preference from a shopping or recreation diary. The planner borrows the two travel allowances together from complete single-stop diaries for the selected mode, capped at 60 minutes per leg. This combines evidence across activity types because the atlas contains few complete discretionary transit diaries and no single-stop bicycle shopping or recreation diaries. The assignment uses each municipality's all-destination purpose rates and Figure 14 mode shares as ceilings. [North Shore survey, Table 7 and Figure 14](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

The seeded bicycle access assignment includes everyone with a bicycle episode and fills the remaining municipal targets among private-household residents aged 15 or older. The rates are 54% in the City of North Vancouver, 58% in the District of North Vancouver and 47% in West Vancouver. Both legs use the directed bicycle network at 220 metres per minute, including connectors. [North Shore survey, Table 36](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

Each transit leg uses a direct September 15, 2026 scheduled ride and street access to stops within 800 metres. The rider has at least three minutes of boarding margin. The return cannot start until the full dwell is over, and the rider must reach home within their available time. Each route's greatest reported fall 2025 weekday average peak passenger load, rounded up across periods and directions, reserves space for background riders. Added riders share the remaining passenger-space proxy on every segment they use. The model allows added bus riders on routes with published background loads and positive remaining space. This transfers a route-level 2025 estimate to a 2026 timetable. It treats each run conservatively and gives no stop-level prediction of regular boardings. [TransLink 2025 Transit Service Performance Review data](https://www.translink.ca/plans-and-projects/strategies-plans-and-guidelines/managing-the-transit-network)

In playback, the transit buttons jump to the corresponding bus ride. Scrubbing earlier shows walking and waiting at the stop. A highlighted vehicle accompanies the selected resident while on board. The live count includes the full itinerary, including access and egress.

The expanded weekday adds 1,949 bicycle outings and 3,835 transit outings, for 65,652 added outings across all four modes. The North Shore trip rate rises from 2.70 to 2.77 per resident, against 3.12 in the survey. All municipality, purpose and mode targets for the two additional modes are reached. In a sensitivity that granted the new outings all of the vehicle's passenger space, assignments on 183 runs would have exceeded the stricter limit. With the observed background reserve, the planner reaches the same targets with zero such exceedances. Raster and an independent minute-by-minute check agree on the regional head count. [Replay bicycle and transit outings](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=3c70c4228343c1492290&outingsRun=78d6fe9df0b082599d8f)

```sh
python -m scripts.vancouver_multimodal_outings
```

#### Outings to Burnaby and New Westminster

**Add errands in Burnaby and New Westminster** extends the 2025 workplace-fit weekday with round trips from North Shore homes. Residents with a recorded driving episode can add one trip in an at-home leisure or media window. Existing local outings, inferred walks, flexible transit, school escorts, recreational walks, on-site work and assigned caregiving hours reserve their time. Paid work, sleep and other diary commitments stay fixed. Both directed road journeys and the full visit must fit. Named stores, parks and recreation venues come from OpenStreetMap and are matched to the eastern municipal boundaries. Routes use the free-flow road profile, including access from each address to the graph.

The 2023 survey reports 11,540 southbound trips to the two cities. Adjusting that total to the size of the synthetic North Shore adult population gives a ceiling of 10,895. The allocator starts with 4,330 assigned trips and 10 added on-site commutes, and uses the residual as a ceiling. It also respects the separate 2023 driving targets by home municipality and purpose after local outings. The survey combines modes and purposes for the eastern destinations, so this is an upper-bound driving scenario. It uses no bridge counter totals in allocation. The 2025 survey's estimate of 12,100 serves as a separate comparison. [2023 survey, Table 11](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF) · [2025 survey, Table 35](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The scenario assigns 6,555 round trips, with 5,773 to Burnaby and 782 to New Westminster. It adds 4,398 shopping and 2,157 recreation visits across 352 mapped venues. The median drive takes 16 minutes each way and the median visit lasts 30 minutes. The assignment draws from 63 shopping and 26 recreation diary tours with at least ten minutes recorded on each leg. The most reused source diary supplies 1,219 outings. Raster reproduced the minute-by-minute occupancy change using all 6,555 individual itineraries and as 5,331 weighted groups. The UI supports following the outward drive, the visit and the drive home.

All 13,110 road legs cross Ironworkers in the replay. Only 270 new southbound crossings fall in the 07:00–09:00 window, bringing the full replay from 4,444 to 4,714 against 8,483 counted. The northbound 16:00–18:00 count rises from 7,912 to 8,684 against 9,508. About 63% of the new southbound crossings occur from 18:00 onwards. The available survey tables give no hour-by-purpose distribution for these destinations. [Replay the eastern outings and morning counts](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=flex&outings=fit&walks=fit&recreation=on&schools=on&attendance=on&easternOutingRun=1890ea2cbe8d554d4003&bridge=Ironworkers&bridgeDirection=0&bridgeWindow=am&bridgeMetric=highway1&bridgePlayback=1)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_eastern_outings
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_bridge_layers
```

### Recreational walks from home

**Recreational walks from home** follows people who leave and return to the same home without a recorded stop. The regional weekday contains 1,274 such walking bouts among North Shore residents aged 15 or older. The replay locates 1,254 on the pedestrian graph. The other 20 remain in the recorded trip count. Recorded home-to-home walks are a proxy for recreational loops.

The 2025 North Shore survey estimates that 4% of all trips start and end at home for recreation. Figure 31 assigns 49% of all recreation trips to walking. Applying that share to home-based loops at the published overall rate gives a scenario target of 12,458 walks for the 158,899 modeled adults. The survey publishes the two margins separately. The target applies the same rate to adults in each municipality. [2025 North Shore Transportation Survey, section 5.3 and Figure 31](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

The model places 11,184 additional walks in time the diary allocated to media or leisure at home. It preserves existing destinations and activities, reserves the published shopping and recreation visits, reconstructed short walks and extra time used by flexible transit, and adds at most one walk per resident. It draws start times and durations from survey-weighted outdoor or neighbourhood exercise episodes reported by 91 urban BC weekday respondents, shifting starts by up to one hour to fit the recipient's diary. The median added walk is 40 minutes and 3.19 km. [Statistics Canada Time Use Survey, 2022 PUMF](https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm)

Each path uses walkable streets or trails and connects to the assigned home at both ends. The router looks for a circuit within the 60–80 m/min pace range. Where it finds no such circuit, it tries a walk out and back. Raster verified the 11,184 added schedules individually and as 2,069 weighted itineraries. With the compatible activity layers enabled, the modeled rate is 2.87 daily trips per North Shore adult versus 4.00 in the 2025 survey. [Replay recreational walks](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=flex&outings=fit&walks=fit&recreation=on)

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_recreation_loops ../Simulations/city
```

### School drop-off and pickup

In **School drop-off and pickup**, choose a walking or family-car example. The household adult and students travel together on the same route and clock. At the school, the adult stays for two minutes. For a morning drop-off the adult then returns alone. For an afternoon pickup the adult arrives alone and leaves with the students. [Replay school escorts](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=flex&outings=fit&walks=fit&recreation=on&schools=on)

The eligible roster includes 8,911 residents younger than 15 whose synthetic weekday already assigns them to one of 25 public elementary schools in North Vancouver School District 44. Same-household students at the same school share an escort. The student keeps their school and the base 09:00–15:00 class time. The adult needs enough eligible time at home for the complete round trip. Paid work, sleep, existing trips and the other published schedule additions reserve their time. Time for meals, personal care, domestic work, leisure and childcare at home can be reassigned. When a younger child has a home-care day, a second adult must be awake and available at home during the escort. A driver must have previously driven in their own diary, and households share at most one active school vehicle.

Walking uses mapped pedestrian links at 70 metres per minute and is limited to 2 km each way. Cars use directed free-flow road times with road-specific speeds. Both legs must fit the original student diary’s 30-minute travel allowance per leg. The replay models round trips from home. Household schedules with no feasible adult or no feasible route keep the original child trip.

The 2021 school survey’s City of North Vancouver respondents reported 43% family-car travel to school and 28% from school. Walking and mobility aids accounted for 40% to school and 45% from school. Those values serve as ceilings for both North Vancouver municipalities. The walking ceiling includes students travelling without an adult. The survey sampled families, and the scenario uses the reported shares at student level. [City of North Vancouver school travel survey, Appendix B, Figures 4–5](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Safe-and-Active-Schools/Safe-and-Active-School-Travel-Program-Refresh-Appendices.pdf)

| Student legs with a household escort | Walking | Family car | Total |
| --- | ---: | ---: | ---: |
| To school | 1,606 | 905 | 2,511 (28%) |
| From school | 1,604 | 641 | 2,245 (25%) |

The 3,506 completed escorts add 7,012 adult trips. There are 1,859 new departures in each of the 08:00 and 09:00 hours and 1,647 in each of the 14:00 and 15:00 hours. The survey counts 48,800 passenger pickups or drop-offs of all kinds in 2025, so school escorts cover one part of that category. With the compatible layers active, the model produces **2.91 daily trips per North Shore resident aged 15+**, compared with **4.00** in the survey. The school model still needs measured school bell times and journeys that combine drop-off or pickup with a commute or errand. [2025 North Shore Transportation Survey, Table 26](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

Counting the added outings, reconstructed short walks and recreational walks gives 507 shopping and errand trips, 321 recreation trips and 390 work trips per 1,000 residents aged 15+. The 2025 survey has 739, 556 and 603 respectively. At 08:00–09:00 the model reaches 185 departures per 1,000, and at 16:00–17:00 it reaches 230. The 2023 survey gives 301 and 304 for those hours. The 2025 report shows the hourly pattern in a figure without a table of exact counts. [2025 North Shore Transportation Survey, Figure 26 and Table 26](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf) · [2023 North Shore Transportation Survey, section 3.1.2](https://docs.dnv.org/documents/FINAL_2023-North-Shore-Transportation-Survey.PDF)

Raster checked the occupancy adjustments individually and as 271 weighted schedules. A separate reconstruction checked the household and supervision assignments, times, road and path permissions, and the total of 867,776 residents at each minute.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_school_escorts ../Simulations/city
```

### Moving a home-working shift on-site

**Work at a usual workplace** follows a resident from home to a mapped workplace and back. The paid-work episodes retain their starting times and number of minutes. Short meal and rest breaks in the same at-home shift move with it. Both trips need time in adjacent home activities. Existing school escorts, shopping or recreation outings, short walks and work transit reserve their time. When a household has a child on the home-care schedule, another adult must be awake and at home throughout the absence. [Replay on-site work](http://127.0.0.1:8187/cityday.html?coverage=region&workplaceRun=06c504c638de40f775a7&workTransit=flex&outings=fit&walks=fit&recreation=on&schools=on&attendance=on)

The census household match supplies workplace status, commute mode, departure band and duration band from the same donor. Candidates have a usual fixed workplace inside their municipality or elsewhere in the region. Candidate addresses come from the replay's occupied workplace inventory. The 2025 origin–destination estimates prioritize zones that have fewer workers in the replay. The car routes use directed free-flow travel times. Walking and cycling use their corresponding street networks. Transit uses the September 15, 2026 timetable, walking access, at most one transfer and the bus space left by the published work and outing trips. [Statistics Canada commuting definitions and table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810047901) · [TransLink GTFS data](https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data)

The original weekday has **51,285** North Shore residents aged 15+ with a recorded trip to paid work, including trips that begin away from home. The survey estimates **65,200** residents with a trip to work or for work-related reasons. Among residents aged 15+, the synthetic roster is 58.8% employed and the survey estimates 63.6%. Among those employed, 54.9% record a trip to paid work in the model and 58.7% report a trip in the survey's work-related category. The assignment uses the rounded mode counts in Tables 50–52 scaled to the model's municipal adult populations as ceilings. The differences in purpose definition and reference dates carry into that comparison. Passengers travelling by car require a shared-ride assignment and are outside this change. [2025 North Shore Transportation Survey, Tables 40 and 49–54](https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/Transportation-Plan/2025-North-Shore-Transportation-Survey-Report.pdf)

Of 2,223 candidates with an eligible home shift and a matched commute profile, **250** receive paired commutes, including 196 drivers, 34 transit riders, 14 walkers and six cyclists. For 1,704 candidates the 2021 departure band, duration band and fixed shift time leave no feasible departure minute. The result shows how strongly a usual commute from one source constrains a work shift from another. The scenario adds 500 trips and keeps every assigned shift's paid-work minutes. Raster verified the occupancy change for individual residents and grouped schedules, and the combined assignments stay within the published bus capacity proxy.

```sh
OPENBLAS_NUM_THREADS=1 python -m scripts.vancouver_weekday_attendance ../Simulations/city
```

### Complete discretionary cycling outings

On the municipal weekday, open **Bicycle counts on city streets** and then **Could residents cycle a whole outing?** The citywide control switches drivers between their original car journeys and two bicycle access scenarios. Choose a home zone and first-stop purpose to inspect individual outings. Each leg button follows the same resident at that leg’s midpoint. Changed riders also appear on the directed network in the city overview and among nearby cyclists in street mode. [Follow a shopping outing in Kitsilano](http://127.0.0.1:8187/cityday.html?cycleTours=access&tourZone=360&tourPurpose=Shopping)

The cohort consists of private-household residents whose census age band is entirely 20 or older. Each candidate leaves home, visits one or more stops and returns home. Every travel episode must be recorded as a car driver, every change of place must have a recorded leg, and each away destination must classify as shopping, dining, socializing or recreation. Paid work, education and caring or helping commitments within the outing exclude it. All stops retain their assigned address, purpose, dwell time and travel window. A changed outing must fit **in every direction**, including connections from the address to the nearest network node. Several short legs cannot compensate for a leg that takes too long. Bicycle speeds can reach 220 metres per minute. Road access, direction and route choice use the same graph as street playback.

The access scenario draws one binary bicycle-access assignment per known adult aged 20+ in each survey zone. Anyone with a bicycle episode in their original diary retains access. A seeded draw without replacement among other residents brings each zone to the closest whole-person count implied by Table 8. The survey covers residents aged 18+ and includes e-bikes. We assume its zonal access rates apply to ages 20+ and that the remaining residents in a zone are exchangeable for this draw. Unmapped homes use the citywide rate. The release records the seed and a byte per roster position, with separate values for outside the cohort, no assigned access and assigned access. Across 551,336 known adults, 359,446 receive access, including 6,105 who already cycled. Both scenarios assume full uptake of eligible outings among residents with access. Passenger needs, cargo capacity, slope, weather and willingness to cycle could reduce uptake. [City of Vancouver 2023 Transportation Survey, Tables 8 and 16](https://vancouver.ca/files/cov/2023-transportation-survey-report.PDF)

Of 75,832 candidate outings, 314 have missing or coincident endpoints, 52,200 exceed a leg’s time budget even in a straight line and 7,584 more lack a fitting directed street route. The remaining 15,734 outings contain 31,733 travel legs. Applying the survey access assignment leaves 10,211 outings with 20,589 legs for 9,993 residents. First stops are shopping for 3,444, dining for 1,054, recreation for 5,291 and social visits for 422. These counts describe travel occasions. Purchasing at a particular shop requires a destination-choice model.

The live clock uses the existing Raster weekday occupancy phase. For each minute it counts drivers currently riding by home zone under each scenario. Running 15,388 drivers individually or as 1,931 weighted schedules produced identical counts over 1,440 minutes on the JVM backend. A direct enumeration of every travel minute independently checks the result. At 08:00, 288 drivers would be riding with survey-based access, including 25 from Kitsilano. The largest simulated peak is 3,237 at 20:05. One recreation diary supplies 2,373 of those riders, so that peak is particularly sensitive to diary reuse.

| Share of recorded trips by bicycle | Original | Survey-based access | Universal access | 2023 City survey |
| --- | ---: | ---: | ---: | ---: |
| Whole city | 1.03% | 2.88% | 3.89% | 7.9% |
| Kitsilano | 1.07% | 3.04% | 3.96% | 12% |
| False Creek | 1.00% | 2.28% | 3.36% | 3% |

The survey shares above are independent of the access assignment. The mode-share denominator uses the same estimated adult weekday population as the trip demand panel, including the age-weighted 18–19 group. The citywide mobility comparison can additionally include inferred short walks. Each intersection score uses individual travellers and the City’s observed hours. The scorer runs both the original and changed bicycle legs through the playback route function. A separate implementation reconstructs the hours and approach directions on the directed graph.

| City count site | City count | Original, shortest | Survey access, shortest | Original, prefer bikeways | Survey access, prefer bikeways |
| --- | ---: | ---: | ---: | ---: | ---: |
| Arbutus and West 10th | 309 | 67 | 76 | 127 | 170 |
| 700 block of Powell | 18 | 55 | 164 | 4 | 17 |
| Ontario and 5th | 3,021 | 30 | 44 | 261 | 458 |
| Prince Edward and Broadway | 287 | 20 | 23 | 8 | 9 |

On Powell the direction of the error depends on the routing assumption. Ontario remains far below the observed count under every combination, including the 543 passages under universal access with bikeway preference. With survey-based access, at most 2,504 distinct legs could pass Ontario during the survey hours even if individually routed through that junction. This leaves at least 517 of its 3,021 observed passages unexplained under that scenario. The four observations cover different sites, dates and hours. The scenario calibrates bicycle availability against a separate survey and uses these counts to check the consequences on the street. [City traffic count data](https://vancouver.ca/streets-transportation/traffic-count-data.aspx)

```sh
python -m scripts.vancouver_cycle_tours
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver
python -m scripts.vancouver_cycle_counts ../Simulations/city --cycle-tours --verify
python -m scripts.vancouver_cycle_counts ../Simulations/city --cycle-tours --bikeways --verify
```

### Combining commutes and discretionary bicycle outings

The municipal replay can apply census workplace and commute assignments and switch whole discretionary outings to cycling on the same weekday. In the bicycle count panel, select a site to compare the original day, workplace and commute assignments alone, bicycle outings alone, and both together. Each row uses the same survey hours and route preference. Select an hourly passage count or an outing leg to follow a resident. The count builder checks that the two models change disjoint resident legs. Both keep the diary clock fixed. The count uses original shopping locations. The shop-opening scenario on the census workplace day uses its walking catalogue. [Compare Ontario and 5th](http://127.0.0.1:8187/cityday.html?workplaces=census&commute=tracts&cycleTours=access&cycleCheck=ontario5)

At Ontario Street and 5th Avenue, shortest-distance routes give 26 passages in the original weekday, 42 with the workplace and commute assignment, 40 with survey-based bicycle outings, and 56 with both changes. Preferring City bikeways gives 553 with both changes. The City counted 3,021 over the same hours. On Powell, applying both changes gives 217 shortest-route passages or 25 when preferring bikeways, against 18 observed. These counts include only simulated city residents. The site observations include riders from every origin.

The two models use different observations. The commute fit uses census mode shares and workplace totals. The discretionary scenario uses survey-based bicycle access and assumes that drivers with access switch whenever their full outing fits. The exercise therefore measures how far the paired assumptions go toward explaining the independent street counts. Commute bicycle access and vehicle availability across trips remain unresolved.

```sh
python -m scripts.vancouver_cycle_counts ../Simulations/city --cycle-tours --combine-workplaces --verify
python -m scripts.vancouver_cycle_counts ../Simulations/city --cycle-tours --combine-workplaces --bikeways --verify
```

### Grocery arrivals on foot and by bicycle

At 2693 E Hastings Street, a proposed grocer open from 08:00 to 20:00 receives 36 walking visits and six bicycle visits on the original municipal weekday. Under survey-based bicycle access and full uptake of eligible driver outings, another 80 visits arrive by bicycle. Of the resulting 122 visits, 75 move from an existing grocer and 47 become feasible for the first time. Universal bicycle access raises the total to 167. Follow a shopper to see the route to the store, the stop and the onward trip. Saving the opening in Datahike retains each visit’s travel mode and the releases used for replay. [Try the Hastings-Sunrise opening](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access)

The same 40% grocery-purchase assumption applies to in-person goods stops with two walking legs, two recorded bicycle legs or two driving legs switched to cycling on an eligible outing. Citywide, 514 goods stops have two recorded bicycle legs. The repeatable purchase draw selects 205, all from a single source diary assigned to multiple residents. Switching drivers adds 1,175 selected occasions under survey-based bicycle access and another 653 under universal access. These assumptions and diary reuse limit what customer counts can establish about actual store demand.

Each occasion compares 73 incumbent grocers with one of 964 possible storefront openings. Bicycle choice minimizes total distance from the previous stop to the retailer and on to the next stop. Both rides must respect street direction and fit their own diary windows at 220 metres per minute. Their combined time must fit 45 minutes. A visit must also fit entirely within opening hours. An equal-cost candidate leaves the incumbent choice in place. Count-site validation uses the original destinations. The opening changes the shop visits, live travel and neighbourhood totals for the municipal weekday.

After publishing the walking market and cycling outings, build the combined catalogue and browser modules with these commands.

```sh
python -m scripts.vancouver_cycle_market
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver experiments
```

### Survey-based grocery demand and shop hours

On the municipal weekday, open a storefront and change the grocery purchase assumption. The original draw assigns 40% of eligible goods stops to groceries. The historical alternative estimates this proportion separately for active travellers and drivers from the 2010 General Social Survey. Both scenarios use the same residents, random draws, streets, stores and travel-time budgets. A driver switching to cycling keeps the original outing's purpose and clock. [Compare the scenarios at 2693 E Hastings Street](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&grocery=bc2010&shopCheck=1)

The 2010 comparison uses weekdays in large urban centres and requires an in-person retail stop between two legs of the same mode with identifiable non-store endpoints. A grocery purchase is food or alcohol purchased at a grocery store. The percentage is the survey-weighted share of eligible retail stops. Approximate 95% intervals use the 500 episode bootstrap weights and the survey's mean-bootstrap variance adjustment. They quantify sampling uncertainty within each survey geography. Transfer to present-day Vancouver adds uncertainty. [Statistics Canada Cycle 24 data and user guide](https://www150.statcan.gc.ca/n1/en/catalogue/12M0024X)

| 2010 diary sample | Grocery stops / eligible stops | Weighted grocery share | Approx. 95% interval |
| --- | ---: | ---: | ---: |
| Urban BC, on foot or by bicycle | 38 / 47 | 78.2% | 63.8–92.6% |
| Urban BC, driving | 135 / 224 | 59.1% | 51.1–67.1% |
| Other urban provinces, on foot or by bicycle | 99 / 166 | 56.5% | 46.6–66.4% |
| Other urban provinces, driving | 639 / 1,127 | 55.8% | 52.1–59.5% |

Only two BC cycling stops qualified in 2010. This is why the scenario pools cycling with walking. The 2022 Time Use Survey provides a separate timing check for goods shopping. There was one qualifying cycling stop in the BC training diaries, zero in the BC holdout and one in 5,900 weekday diaries from other urban provinces. **Check shopping travel and opening hours** shows how many respondents contributed by mode, and how often their whole stop fits the chosen opening hours when the sample supports a comparison. Repeated assignment of one diary to synthetic residents adds no observations to the survey. [Statistics Canada public use microdata](https://www150.statcan.gc.ca/n1/pub/45-25-0001/index-eng.htm)

The City's transportation surveys also provide an external check on the mix of trips reaching shops. The following municipal model percentages include 778 inferred short walks and use 112,746.6 adult-equivalent shopping arrivals as the denominator. The bicycle scenarios transfer eligible outings from driving to cycling. The surveys cover shopping of all kinds. The storefront visit count covers a narrower subset of grocery stops accessible on foot or by bicycle.

| Travel to shopping | Original weekday | Survey-based bicycle access and full uptake | City 2019 | City 2024 |
| --- | ---: | ---: | ---: | ---: |
| Walking | 14.1% | 14.1% | 39% | 43% |
| Cycling | 0.4% | 3.5% | 10% | |
| Driving | 66.5% | 63.4% | 38% | |
| Auto passenger | 12.0% | 12.0% | 4% | |
| Transit | 4.4% | 4.4% | 9% | |

The model assigns too few shopping trips to walking even after short walks are included. Changing the probability of buying groceries leaves this citywide mode imbalance in place. [City of Vancouver 2019 Transportation Panel Survey, Figure 4-7](https://vancouver.ca/files/cov/2019-transportation-panel-survey.pdf) · [City of Vancouver 2024 Transportation Snapshot, Walking and Rolling](https://vancouver.ca/files/cov/2024-transportation-snapshot.pdf)

At 2693 E Hastings Street, with survey-based bicycle access and full uptake, an 08:00–20:00 opening receives 122 simulated visits under the fixed share and 207 under the historical shares. Of the latter, 121 shift from another grocer and 86 newly fit the travel and time constraints. With eight hours of staffing, 09:00–17:00 admits 98 and 160 visits respectively. The comparison evaluates all 96 quarter-hour start times and reports ties. Applying the shift updates the map and individual visits. Saving the experiment in browser Datahike records the purchase assumption, market release and hours for replay. These counts omit customers arriving by car or transit.

After building the walking market and bicycle outings, reproduce both catalogues and the comparison with these commands.

```sh
curl -fL https://www150.statcan.gc.ca/n1/pub/45-25-0001/cat7/c24_2010.zip -o data/mobility/c24_2010.zip
python -m scripts.vancouver_cycle_market
python -m scripts.vancouver_cycle_market --grocery-survey data/mobility/c24_2010.zip
python -m scripts.vancouver_shopping_evidence ../Simulations/city
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver experiments
```

### Walk to a local grocer

In **Open a grocery shop**, enable **Walk to a local grocer when the driving diary allows**. This changes destinations and both travel legs for eligible residents. Open **Neighbourhood grocery access** to check the local inventory and follow a driver on their new walking route. The weekday clock, moving shoppers, walking and driving counts at the Downtown boundary, individual diaries’ trip overlays and saved experiments all reflect the choice. [Play the East Hastings opening](http://127.0.0.1:8187/cityday.html?shop=3738&cycleTours=access&grocery=bc2010&localWalk=1&accessCheck=1)

The original weekday contains 27,475 home–store–home goods outings by private-household residents aged 20 or older with driving on both sides of the purchase. The 2010 driver-specific grocery share selects 16,256 of them. Each driver can switch the whole outing to walking if both street routes fit the original travel times, the store is open for the entire dwell, and each walk takes at most 15 minutes at 3.87 km/h. The speed and time limit come from Vancouver’s healthy food retail study. Our graph uses pedestrian-permitted streets and paths with endpoint connectors. Signal delays, slopes, the weight of a grocery basket, mobility limitations and personal preferences can further restrict uptake. [City of Vancouver food access study, Appendix C](https://vancouver.ca/files/cov/equitable-access-to-healthy-food-retail-report.pdf)

The closest eligible incumbent retains ties. Each potential new store competes against those incumbents independently at its selected hours. If the walking option fails, the resident keeps driving to the original destination. A driver who has already switched this outing to cycling keeps the bicycle trip. Existing grocers admit 6,897 of the selected driving outings on foot before the bicycle scenario or 6,105 after assigning survey-based bicycle access and full bicycle uptake. The model assumes everyone still eligible takes the local walk.

At 2693 E Hastings Street, an 08:00–20:00 opening with the historical purchase shares and survey-based bicycle access receives 207 visits before the local walking option and 306 after. The additional 99 shoppers have 34 distinct source diaries. All 99 could still drive in the reference day. Their extra visits count journeys that became feasible on foot. Including the inferred short walks, the share of shopping trips arriving on foot rises from 14.1% to 19.6% under full uptake. The City reported 43% in its 2024 survey. [City transportation snapshot](https://vancouver.ca/files/cov/2024-transportation-snapshot.pdf)

**External check on destinations.** The Can-FED 2024 public release gives separate density classes for independent grocery stores and chain grocery stores within 1 and 3 km network buffers around each census representative point. We compare presence of either class with an exact shortest-path search from the same point to the 73 licensed grocers in the model. We use zero versus positive density because the published categories are ordinal. Can-FED uses its own network buffers, business definitions and geocoding, and can include businesses beyond the City boundary. [Statistics Canada data](https://www150.statcan.gc.ca/n1/pub/13-20-0001/132000012025001-eng.htm) · [Method and variable definitions](https://www150.statcan.gc.ca/n1/pub/13-20-0001/132000012025002-eng.htm)

| Within 1 km | Municipal census areas | Can-FED finds access | Model finds access |
| --- | ---: | ---: | ---: |
| City of Vancouver | 1,016 | 969 | 626 |
| Hastings-Sunrise | 57 | 53 | 19 |
| Sunset | 63 | 63 | 14 |
| Victoria-Fraserview | 53 | 47 | 0 |
| West End | 68 | 68 | 68 |

There are 345 city areas with observed 1 km access missing from the model, and two with access only in the model. Within 3 km the respective totals with access are 1,016 and 1,008. The hypothetical East Hastings opening gives 15 census points a first modelled grocer within 1 km. Can-FED already records access at every one of them. These discrepancies limit estimates of newly served customers.

**Population footprint in the archived experiment.** The food-access benchmark uses all 1,016 areas in Vancouver census subdivision 5915022. The 1,017-area replay used for this experiment included three Musqueam 2 areas with 1,646 residents and omitted Vancouver areas 59150891 and 59153586. The current weekday reconciles to the benchmark footprint. [Archived boundary audit](http://127.0.0.1:8187/population.html?boundary=1&dayRun=18b619163185acd3e6d336aa88fb61abd9a13987d17bd5ba8a69d9204e935a0a) · [Statistics Canada Geographic Attribute File](https://www150.statcan.gc.ca/n1/en/catalogue/92-151-X)

After publishing both purchase rules in the previous section, run the following commands. The first build verifies each market archive and publishes new versioned catalogues, including the source hashes. The census comparison alone can be published with `python -m scripts.vancouver_census_geography`.

```sh
curl -fL https://www150.statcan.gc.ca/n1/pub/13-20-0001/2025001/zip/canfed_2024.zip -o data/mobility/canfed_2024.zip
curl -fL https://data.source.coop/dataforcanada/d4c-datapkg-statistical/archive/statcan/geographic_attribute_file/2021_92-151_X.zip -o data/mobility/2021_92-151_X.zip
python -m scripts.vancouver_local_groceries
clojure -M:ui -m shadow.cljs.devtools.cli release vancouver experiments
```
