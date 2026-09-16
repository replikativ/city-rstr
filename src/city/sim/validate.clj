(ns city.sim.validate
  "Scores of a simulated day against counted Stuttgart targets: retail demand
   share, centrality and turnover by district (`retail-demand-share`,
   `retail-centrality`, `retail-revenue`), trip generation (`trip-rate`), and
   street counts of bicycles and pedestrians passing counted sites
   (`bicycle-counts`, `koenigstrasse-pedestrians`, both over
   `simulated-passings`). The street counts need a routed day and are run from
   the REPL; they are not part of the published run."
  (:require [city.sim.day :as d2]
            [city.sim.network :as net]
            [city.intake.stuttgart-counts :as stu-counts]))

;; ---- counted sites: legs passing a point ------------------------------------------------------

(defn- seg-approach
  "Closest approach of the segment a→b to the point p, in metres, together with
   the position t ∈ [0,1] along the segment where it happens. Metric is a local
   equirectangular projection, which is exact enough over a block."
  ;; no primitive hints: Clojure only allows them on fns of ≤4 args
  [px py ax ay bx by]
  (let [px (double px) py (double py) ax (double ax) ay (double ay) bx (double bx) by (double by)
        k (Math/cos (Math/toRadians py))
        ax' (* 111320.0 k ax) bx' (* 111320.0 k bx) px' (* 111320.0 k px)
        ay' (* 111320.0 ay) by' (* 111320.0 by) py' (* 111320.0 py)
        dx (- bx' ax') dy (- by' ay')
        len2 (+ (* dx dx) (* dy dy))
        t (if (zero? len2) 0.0 (max 0.0 (min 1.0 (/ (+ (* (- px' ax') dx) (* (- py' ay') dy)) len2))))
        qx (+ ax' (* t dx)) qy (+ ay' (* t dy))]
    [(Math/sqrt (+ (* (- px' qx) (- px' qx)) (* (- py' qy) (- py' qy)))) t]))

(defn leg-pass-minute
  "Minute at which a leg's polyline comes closest to [lon lat], or nil when it
   never comes within `radius-m`. The *segments* are tested, not the vertices:
   the polyline is simplified to ≤40 points, so a straight block is two
   vertices hundreds of metres apart and a vertex test would miss the
   intersection in between. The minute is interpolated along the segment from
   the leg's own timestamps."
  [path timestamps lon lat radius-m]
  (let [lon (double lon) lat (double lat) radius-m (double radius-m)
        pts (vec path) ts (vec timestamps) n (count pts)]
    (when (>= n 2)
      (loop [i 1 bd Double/MAX_VALUE bm nil]
        (if (>= i n)
          (when (<= bd radius-m) bm)
          (let [a (pts (dec i)) b (pts i)
                [d t] (seg-approach lon lat (double (a 0)) (double (a 1)) (double (b 0)) (double (b 1)))]
            (if (< (double d) bd)
              (let [t0 (double (nth ts (dec i) 0)) t1 (double (nth ts i t0))]
                (recur (inc i) (double d) (+ t0 (* (double t) (- t1 t0)))))
              (recur (inc i) bd bm))))))))

(defn simulated-passings
  "Simulated legs of one **mode** passing each counted site, per hour.

   Runs one traced weekday (`stride` 1 = the whole population) and counts, for
   every leg of the requested `:mode` (walk by default), the sites its polyline
   passes within `radius-m`. Every other mode is excluded, because the counters
   count one mode too: a pedestrian counter counts pedestrians and an
   Eco-Counter counts bicycles across a cordon.

   For a walk count, a transit leg's *access and egress walk* is included: it is
   emitted by `city.sim.day/step-day-traces` as a leg of its own (mode
   `walk`, purpose `access`, flagged `:access`), so the walking to and from the
   stop is counted on the sidewalk it happens on while the in-vehicle run is
   not. `:count-access?` false drops those again. Bike legs have no such stubs.
   With `stride` > 1 the counts are scaled by the stride.

   The legs are **reduced as they are produced** (`:trace-fn`), never
   collected: a city-wide day at stride 1 is a million routed polylines, which
   is a gigabyte if it is held and nothing if it is counted and dropped. Pass
   `:traces` to score a day that is already in hand instead of running one.

   Three knobs exist so the moves that produce the count can be *separated*
   (each one is an ablation of this target, not a tuning parameter):
   `:p-keep` and `:route-variants` are handed to
   `city.sim.day/step-day-traces`, and `:count-access?` (default true) drops
   the transit access/egress walk stubs from the count again. `:route` passes a
   router in — which a second city must do, because the shared network is one
   graph and the default router builds whichever pull was last loaded."
  [world tables sites & {:keys [seed stride radius-m traces p-keep route-variants count-access? mode route]
                         :or {seed 1 stride 1 radius-m 30.0 count-access? true mode "walk"}}]
  (let [route (or route (net/route-fn))
        _ (net/reset-stats!)
        t0 (System/currentTimeMillis)
        sites (vec sites)
        counts (into {} (for [s sites] [(:key s) (long-array 24)]))
        n-legs (volatile! 0)
        n-access (volatile! 0)
        score! (fn [{:keys [legs]}]
                 (doseq [{m :mode :keys [path timestamps access]} legs
                         :when (and (= mode m) (or count-access? (not access)))]
                   (vswap! n-legs inc)
                   (when access (vswap! n-access inc))
                   (doseq [s sites]
                     (when-let [m (leg-pass-minute path timestamps (double (:lon s)) (double (:lat s)) (double radius-m))]
                       (let [h (min 23 (max 0 (long (quot (long m) 60))))
                             ^longs a (counts (:key s))]
                         (aset a h (inc (aget a h))))))))
        day (if traces
              (do (run! score! traces) {:counts nil :leg-stats nil})
              (apply d2/step-day-traces world tables seed
                     (concat [:stride stride :route route :trace-fn score!]
                             (when p-keep [:p-keep p-keep])
                             (when route-variants [:route-variants route-variants]))))
        ms (- (System/currentTimeMillis) t0)]
    {:by-site (into {} (for [[k ^longs a] counts]
                         [k (vec (map #(* (long stride) (aget a %)) (range 24)))]))
     :walk-legs @n-legs :access-walk-legs @n-access
     :legs @n-legs :mode mode
     :episode-counts (:counts day)
     :stride stride :seed seed :radius-m radius-m
     :p-keep p-keep :route-variants route-variants :count-access? count-access?
     :ms ms :leg-stats (:leg-stats day)}))

(defn retail-demand-share
  "{district → share of the city's retail choice probability}, read off the
   gravity table. Factored out of `retail-centrality` so that the centrality
   score and the revenue score cannot drift apart: both are this one number
   divided by two different denominators."
  [world tables & {:keys [table district-of] :or {district-of identity}}]
  (let [grid (:grid tables)
        {:keys [^ints offsets ^ints venues ^doubles cdf]} (or table (:retail tables))
        ps (:persons world) n (:n ps)
        fs (:firms world) ^objects fla (:la fs)
        ^ints hc (:home-cell tables)
        cellpop (let [a (long-array (:n grid))]
                  (dotimes [i n] (when (>= (aget hc i) 0) (aset a (aget hc i) (inc (aget a (aget hc i))))))
                  a)
        demand (java.util.HashMap.)]
    (dotimes [c (:n grid)]
      (let [p (aget cellpop c)]
        (when (pos? p)
          (let [a (aget offsets c) b (aget offsets (inc c))]
            (loop [k a prev 0.0]
              (when (< k b)
                (let [cur (aget cdf k) m (- cur prev)
                      d (district-of (aget fla (aget venues k)))]
                  (.put demand d (+ (double (or (.get demand d) 0.0)) (* p m)))
                  (recur (inc k) cur))))))))
    (let [tot (reduce + (vals demand))]
      (when (pos? (double tot))
        (into {} (for [[d v] demand] [d (/ (double v) (double tot))]))))))

(defn retail-centrality
  "Simulated retail centrality per district, against the measured one.

   **Centrality** is a retail study's ratio of a district's turnover to its
   residents' purchasing power. Above one the district imports spending; below
   one it exports it. Stuttgart's 2021 establishment census publishes it for all
   23 Stadtbezirke (`data/derived/stuttgart_retail_districts.json`), and Mitte
   is **10.54** — the centre sells ten and a half times what its own residents
   can buy.

   This is a far better target for destination choice than the pedestrian
   sensor it replaces: 22 usable observations rather than one, at district
   geography, from a full establishment census rather than a camera whose
   location is unpublished, and it measures *draw* rather than passing footfall.

   The simulated side needs no traced day. It is read straight off the gravity
   table: for every grid cell, the probability mass its retail choice set puts
   on each venue, weighted by how many people anchor in that cell, summed by the
   destination's district. So a destination-model change can be scored in
   seconds where a routed day costs ninety minutes and then yields nineteen legs
   of signal at the one sensor.

   `district-of` maps a firm's area name to the district the target is
   published for (Stadtteil → Stadtbezirk in Stuttgart).

   **The denominator.** Without `:kaufkraft`, purchasing power is proxied by
   resident count, while the study's own Kaufkraft varies across districts by
   about ±35 % per resident. Measured, the difference is small: passing
   `:kaufkraft` from `city.synth.retail/targets` moves log-correlation from
   **0.825 to 0.832** and the mean absolute log ratio from **0.431 to 0.429**;
   Mitte is 8.25 against 8.21. So resident count is a fine proxy here: Kaufkraft
   per head varies, but not enough to disturb a ranking that population
   dominates. Pass `:kaufkraft` anyway when you have it, since it makes the
   comparison like-for-like at no cost — just do not expect it to buy anything."
  [world tables observed & {:keys [table district-of kaufkraft]
                            :or {district-of identity}}]
  (let [ps (:persons world) n (:n ps) ^objects pla (:la ps) ^ints ext (or (:external ps) (int-array n))
        ;; the denominator: measured purchasing power where we have it, resident
        ;; count otherwise. `kaufkraft` removes an error term rather than adding
        ;; a feature — see the note below.
        pop (or kaufkraft
                (reduce (fn [m i] (if (or (= 1 (aget ext i)) (nil? (aget pla i))) m
                                      (update m (district-of (aget pla i)) (fnil inc 0))))
                        {} (range n)))
        share (retail-demand-share world tables :table table :district-of district-of)
        tot-pop (double (reduce + (map double (vals pop))))
        r2 (fn [^double x] (/ (Math/round (* 100.0 x)) 100.0))
        rows (vec (for [[d obs] (sort-by key observed)
                        :let [pd (double (get pop d 0))
                              sim (when (and (pos? pd) share)
                                    (/ (double (get share d 0.0)) (/ pd tot-pop)))]]
                    {:district d :observed obs :simulated (when sim (r2 sim))
                     :denominator pd :ratio (when (and sim (pos? (double obs))) (r2 (/ sim (double obs))))}))
        paired (filterv :simulated rows)
        corr (let [xs (mapv (comp double :observed) paired) ys (mapv (comp double :simulated) paired)
                   n* (count xs) mx (/ (reduce + xs) n*) my (/ (reduce + ys) n*)
                   sxy (reduce + (map (fn [a b] (* (- a mx) (- b my))) xs ys))
                   sxx (reduce + (map #(let [d (- % mx)] (* d d)) xs))
                   syy (reduce + (map #(let [d (- % my)] (* d d)) ys))]
               (when (and (pos? sxx) (pos? syy)) (/ sxy (Math/sqrt (* sxx syy)))))
        logcorr (let [ok (filterv #(and (pos? (double (:observed %))) (pos? (double (:simulated %)))) paired)
                      xs (mapv #(Math/log (double (:observed %))) ok) ys (mapv #(Math/log (double (:simulated %))) ok)
                      n* (count xs)]
                  (when (> n* 2)
                    (let [mx (/ (reduce + xs) n*) my (/ (reduce + ys) n*)
                          sxy (reduce + (map (fn [a b] (* (- a mx) (- b my))) xs ys))
                          sxx (reduce + (map #(let [d (- % mx)] (* d d)) xs))
                          syy (reduce + (map #(let [d (- % my)] (* d d)) ys))]
                      (when (and (pos? sxx) (pos? syy)) (/ sxy (Math/sqrt (* sxx syy)))))))]
    {:rows rows
     :n (count paired)
     :corr (some-> corr (* 1000.0) Math/round (/ 1000.0))
     :log-corr (some-> logcorr (* 1000.0) Math/round (/ 1000.0))
     :centre (first (filter #(= "Mitte" (:district %)) rows))
     ;; mean |log ratio|: a factor-of-two miss in either direction scores 0.69
     :mean-abs-log-ratio (let [ok (filterv #(and (:ratio %) (pos? (double (:ratio %)))) paired)]
                           (when (seq ok)
                             (/ (Math/round (* 1000.0 (/ (reduce + (map #(Math/abs (Math/log (double (:ratio %)))) ok)) (count ok)))) 1000.0)))}))

(defn retail-revenue
  "Simulated retail **turnover in euros** per district, against the measured one.

   This is the score the whole economic model is aimed at, and it is a stronger
   claim than `retail-centrality`. Centrality is a ratio, so a destination model
   can reproduce it while being wrong about scale everywhere by the same factor.
   Turnover is a level: 4,484.4 M € across the 23 Stadtbezirke, of which Mitte
   is 1,905.8 M € (`city.synth.retail/targets`, from the 2024 Einzelhandels- und
   Zentrenkonzept, survey year 2021).

   The model has no prices and no baskets, so it cannot *derive* a euro. What it
   can do is distribute the city's known retail spend by its own choice
   probabilities and ask whether the resulting map matches. That is a real test
   — it is exactly the step where a gravity model is usually let off — but be
   clear about what it is not: the citywide total is taken from the census, not
   predicted. Only the **distribution** is the model's own claim.

   Costs no traced day. Like `retail-centrality` it reads the gravity table, so
   a destination-model change is scored in seconds.

   Returns per-district rows plus `:mean-abs-log-ratio` (a district missed by a
   factor of two scores 0.69) and `:share-of-revenue-misplaced`, which is half
   the total variation distance between the simulated and measured revenue
   distributions — the fraction of the city's retail euro that the model puts in
   the wrong district. That last one is the number to quote, because it is in
   units anyone can argue with."
  [world tables targets & {:keys [table district-of] :or {district-of identity}}]
  (let [share (retail-demand-share world tables :table table :district-of district-of)
        total (reduce + (keep :umsatz-eur (vals targets)))
        r2 (fn [^double x] (/ (Math/round (* 100.0 x)) 100.0))
        rows (vec (for [[d t] (sort-by key targets)
                        :let [obs (:umsatz-eur t)
                              sim (some-> (get share d) (* (double total)))]]
                    {:district d
                     :observed-mio (some-> obs (/ 1.0e6) r2)
                     :simulated-mio (some-> sim (/ 1.0e6) r2)
                     :ratio (when (and sim obs (pos? (double obs))) (r2 (/ (double sim) (double obs))))}))
        paired (filterv :ratio rows)
        tvd (when (pos? (double total))
              (* 0.5 (reduce + (for [[d t] targets
                                     :let [o (/ (double (or (:umsatz-eur t) 0.0)) (double total))
                                           s (double (or (get share d) 0.0))]]
                                 (Math/abs (- s o))))))]
    {:rows rows
     :n (count paired)
     :total-mio (r2 (/ (double total) 1.0e6))
     :centre (first (filter #(= "Mitte" (:district %)) rows))
     :mean-abs-log-ratio (when (seq paired)
                           (/ (Math/round (* 1000.0 (/ (reduce + (map #(Math/abs (Math/log (double (:ratio %)))) paired))
                                                       (count paired))))
                              1000.0))
     :share-of-revenue-misplaced (some-> tvd (* 1000.0) Math/round (/ 1000.0))}))

(defn trip-rate
  "The model's trip generation, counted the way a travel survey counts it, so
   that it can be compared with a published rate at all.

   **Definition, because this is where the comparison is usually lost.** A
   *trip* here is one movement between two activities: the unit the German
   `Weg` and the Toronto linked trip use. A transit trip's access and egress
   walk are emitted by `step-day-traces` as flagged sub-legs of the same
   journey and are **not** separate trips; counting them would inflate the
   rate by about a sixth. Published rates across North America
   run from 2.1 to 4.2 and most of that spread is this decision, not
   behaviour: Calgary's panel counts every leg, Toronto's survey drops stops
   under 15 minutes, and Seattle reports 4.1 where the US national survey
   reports 3.4.

   The denominator is everyone the simulator could have moved — a diary type
   and either a home or a workplace — not everyone in the world, since
   children under 15 carry no diary.

   Returns the three numbers that decompose any shortfall: `:trips-per-person`
   is the product of `:mobile-share` and `:trips-per-mobile-person`, and it
   matters a great deal which of the two is wrong.

   **And it is reported per group, because the aggregate hides where the
   shortfall is.** Measured 2026-09-12 on a stride-200 traced day: city-wide
   mobile share **0.789** and 2.675 trips per person against a 2.861 target, but
   split, in-commuters sit at **0.873** — essentially on target, since they have
   a commute by construction — and residents at **0.737**, against a measured
   0.834 in the tilted diary pool and 0.87 in MiD 2017 for Stuttgart. So the
   residual is a *resident* one and a fix aimed at the aggregate would be aimed
   at the wrong population."
  [world tables traces & {:keys [stride] :or {stride 10}}]
  (let [ps (:persons world) n (:n ps)
        ^ints ptype (:ptype tables) ^ints hc (:home-cell tables) ^ints work (:work ps)
        ^ints ext (or (:external ps) (int-array n))
        eligible (count (filter #(and (>= (aget ptype %) 0)
                                      (or (>= (aget hc %) 0) (>= (aget work %) 0)))
                                (range n)))
        traced (/ (double eligible) stride)
        legs (remove :access (mapcat :legs traces))
        movers (count (distinct (map :person (filter #(seq (remove :access (:legs %))) traces))))
        r3 (fn [^double x] (/ (Math/round (* 1000.0 x)) 1000.0))
        ;; eligibility has to be applied *inside* the split, or a group's mobile
        ;; share is divided by its whole population instead of the part the
        ;; simulator could have moved — which understates residents, who carry
        ;; most of the ineligible children.
        elig? (fn [i] (and (>= (aget ptype i) 0) (or (>= (aget hc i) 0) (>= (aget work i) 0))))
        split (fn [pred]
                (let [ts (filter #(pred (:person %)) traces)
                      ls (remove :access (mapcat :legs ts))
                      mv (count (distinct (map :person (filter #(seq (remove :access (:legs %))) ts))))
                      e (count (filter #(and (elig? %) (pred %)) (range n)))
                      d (/ (double e) stride)]
                  (when (pos? d)
                    {:n (count (filter #(pred %) (range n)))
                     :eligible e
                     :trips-per-person (r3 (/ (count ls) d))
                     :mobile-share (r3 (/ mv d))})))]
    {:eligible eligible :traced (long traced)
     :trips (count legs) :movers movers
     :mobile-share (r3 (/ movers traced))
     :trips-per-person (r3 (/ (count legs) traced))
     :trips-per-mobile-person (r3 (/ (count legs) (max 1 movers)))
     :access-legs (count (filter :access (mapcat :legs traces)))
     :by-purpose (into (sorted-map) (frequencies (map :purpose legs)))
     :residents (split #(zero? (aget ext %)))
     :in-commuters (split #(= 1 (aget ext %)))}))

(defn- pearson [xs ys]
  (let [n (count xs)]
    (when (>= n 3)
      (let [mx (/ (reduce + xs) n) my (/ (reduce + ys) n)
            dx (map #(- % mx) xs) dy (map #(- % my) ys)
            sxy (reduce + (map * dx dy))
            sxx (reduce + (map * dx dx)) syy (reduce + (map * dy dy))]
        (when (and (pos? sxx) (pos? syy))
          (/ sxy (Math/sqrt (* sxx syy))))))))

;; ---- Stuttgart: Eco-Counter hourly bicycle counts ---------------------------------------------

(defn bicycle-counts
  "Compare simulated **bike** legs against the Mobidata BW Eco-Counter hourly
   bicycle counts for the Stuttgart sites
   (`city.intake.stuttgart-counts/bike-counts`).

   The same rule as the pedestrian target with two terms changed: the mode is
   `bike` rather than `walk`, and the observed value is a **mean weekday hour**
   over a whole month rather than one day's study. That second change is an
   improvement in the target and a complication in the comparison — the model
   day carries a single seed's sampling noise against an observation that has
   already averaged twenty weekdays.

   Returns the same shape as `pedestrian-counts`: `:table` one row per site ×
   hour, `:by-site`, `:overall` Σsim/Σobs, `:corr` (Pearson across sites at 08
   and 17, plus the hourly-profile correlation) and `:profile`.

   What is compared is a *cordon crossing* on both sides: an Eco-Counter counts
   every bicycle past its loop in either direction, and a simulated bike leg is
   counted when its polyline comes within `radius-m` of the counter. Unlike the
   pedestrian target there is no crossing-vs-passing factor to argue about; the
   error that replaces it is that a counter sits on **one** cycle path and the
   router puts a bike on the street graph's shortest line, which near a
   riverside path is often the parallel road."
  [world tables & {:keys [counts seed stride radius-m traces route p-keep]
                   :or {seed 1 stride 1 radius-m 30.0}}]
  (let [data (or counts (stu-counts/bike-counts))
        sites (vec (for [c (:sites data)]
                     {:key (:key c) :site-id (:site-id c) :lon (:lon c) :lat (:lat c)
                      :days (:days c)
                      :hours (into {} (for [[h v] (:hours c)] [(long h) (double v)]))}))
        sim (simulated-passings world tables sites :seed seed :stride stride :radius-m radius-m
                                :traces traces :route route :p-keep p-keep :mode "bike")
        rows (vec (for [s sites
                        [h obs] (sort-by key (:hours s))]
                    {:site (:key s) :hour h :observed obs
                     :simulated (nth (get-in sim [:by-site (:key s)]) h 0)}))
        tot-obs (reduce + (map :observed rows))
        tot-sim (reduce + (map :simulated rows))
        at (fn [h] (let [rs (filter #(= h (:hour %)) rows)]
                     {:n (count rs)
                      :r (pearson (mapv #(double (:observed %)) rs) (mapv #(double (:simulated %)) rs))
                      :observed (reduce + (map :observed rs))
                      :simulated (reduce + (map :simulated rs))}))
        profile (vec (for [h (range 24)
                           :let [rs (filter #(= h (:hour %)) rows)]
                           :when (>= (count rs) 3)]
                       {:hour h :n (count rs)
                        :observed (reduce + (map :observed rs))
                        :simulated (reduce + (map :simulated rs))}))]
    {:table rows
     :by-site (into (sorted-map)
                    (for [s sites
                          :let [rs (filter #(= (:key s) (:site %)) rows)
                                o (reduce + (map :observed rs)) m (reduce + (map :simulated rs))]]
                      [(:key s) {:site-id (:site-id s) :days (:days s) :hours (count rs)
                                 :lon (:lon s) :lat (:lat s)
                                 :observed o :simulated m
                                 :ratio (when (pos? o) (/ (double m) o))}]))
     :overall {:observed tot-obs :simulated tot-sim
               :ratio (when (pos? tot-obs) (/ (double tot-sim) tot-obs))
               :cells (count rows) :sites (count sites)}
     :corr {:hour-8 (at 8) :hour-17 (at 17)
            :sites (pearson (mapv (fn [s] (double (reduce + (vals (:hours s))))) sites)
                            (mapv (fn [s] (double (reduce + (get-in sim [:by-site (:key s)])))) sites))
            :profile {:n (count profile)
                      :r (pearson (mapv #(double (:observed %)) profile)
                                  (mapv #(double (:simulated %)) profile))}}
     :profile profile
     :month (:month data)
     :weekdays (count (:weekday-dates data))
     :run (dissoc sim :by-site)}))

(defn koenigstrasse-pedestrians
  "The one pedestrian number Stuttgart publishes for free: hystreet's *monthly*
   totals for its six measured Stuttgart locations, three of them on
   Königstraße (`city.intake.stuttgart-counts/hystreet-stuttgart`).

   A month is not a day, so the observed total is divided by the month's
   weekday count to give a per-weekday figure — which assumes a weekend day
   counts like a weekday and is therefore an **upper** bound on the weekday
   value on a shopping street (Saturday is Königstraße's busiest day). The
   simulated side is every walk leg of the traced day passing within
   `radius-m`, scaled by the stride, exactly as in `pedestrian-counts`.

   The comparison this supports is one ratio per location and nothing else: no
   hours, no shape, no correlation. It is reported because it is the only
   pedestrian measurement of this city that exists in the open, not because it
   is a strong test."
  [world tables & {:keys [seed stride radius-m traces route weekdays-in-month]
                   :or {seed 1 stride 1 radius-m 30.0 weekdays-in-month 21}}]
  (let [data (stu-counts/hystreet-stuttgart)
        sites (vec (filter :lon (:locations data)))
        sim (simulated-passings world tables sites :seed seed :stride stride :radius-m radius-m
                                :traces traces :route route :mode "walk")]
    {:month (str (:year data) "-" (:month data))
     :weekdays-in-month weekdays-in-month
     :sites (vec (for [s sites
                       :let [m (reduce + (get-in sim [:by-site (:key s)]))
                             obs-day (/ (double (:pedestrians-month s)) weekdays-in-month)]]
                   {:key (:key s) :pedestrians-month (:pedestrians-month s)
                    :observed-per-weekday (Math/round obs-day)
                    :simulated m
                    :ratio (when (pos? obs-day) (/ (double m) obs-day))}))
     :run (dissoc sim :by-site)}))
