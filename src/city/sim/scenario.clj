(ns city.sim.scenario
  "A policy question on the three-class economy, answered under a posterior.

   An intervention changes the venue set and nothing else: `close-set` zeroes
   the attractiveness of a set of firms in every demand class (a building's
   clothing floor leaves the medium class, its supermarket the short one),
   `open-site` appends one candidate with its own distance column and floor
   per class. The population, its money and θ are held fixed, so this is
   do(venues := V').

   The evaluation runs under a *set* of θ, the posterior particles of
   `city.infer/run-segmented`:
   - `outcome3` is the expected allocation of every class's money at one θ,
     computed exactly by `candidates/reduce-dense` (no random number);
   - `across3` evaluates baseline and scenario under every particle and keeps
     the paired difference `delta3`, so the reported spread is the posterior
     over the effect, not two independent uncertainties added;
   - `report` summarises the rows for the explorer: weighted means and
     5/50/95 % quantiles per district and venue, the posterior predictive
     beside the observed turnover, and the expected shopping distance.

   The paired economic day under the same seed, which the explorer shows as
   visit changes, is run by `city.demo.stuttgart/scenarios` with
   `city.sim.kernel/store-choices!`.

   Units: euros per year, km, weights summing to one."
  (:require [city.sim.candidates :as cand]
            [city.sim.day :as d2]
            [city.sim.world :as w]
            [city.synth.segments :as seg]))

;; ---- venue sets -------------------------------------------------------------------------

(defn footprint
  "The candidates within `r` metres of (lon, lat), with their per-class
   attractiveness: a shopping centre in the registry is not one firm but the
   shops inside it, so an intervention on the centre is an intervention on
   this set. `firms` needs :lon :lat :name; `atts` is `{:short double[] …}`
   by firm index."
  [dense firms atts lon lat r]
  (let [^ints c (:cand dense) nc (long (:nc dense))
        ^doubles flon (:lon firms) ^doubles flat (:lat firms) names (:name firms)
        lon (double lon) lat (double lat) r (double r)]
    (vec (for [q (range nc)
               :let [j (aget c q) d (w/haversine-m (aget flon j) (aget flat j) lon lat)]
               :when (< d r)]
           {:q q :firm j :name (get names j) :lon (aget flon j) :lat (aget flat j)
            :distance-m d
            :att (mapv #(aget ^doubles (get atts %) j) seg/segments)}))))

(defn close-set
  "Every class's attractiveness with the firms in `firms` at zero: the venues
   are out of every class's choice set, which is what closing a building
   means. Firms that are not candidates are ignored — they were never in it."
  [atts firms]
  (into {} (for [s seg/segments]
             [s (let [a (aclone ^doubles (get atts s))]
                  (doseq [j firms] (aset a (long j) 0.0))
                  a)])))

(defn- extend-dense
  "The dense build with one more candidate at (lon, lat): its firm index is
   `firm`, its distance column is computed from every cell centre. Costs one
   copy of the distance matrix plus n haversines."
  [grid dense firm lon lat]
  (let [{:keys [^ints cand ^floats dist n nc]} dense
        n (long n) nc (long nc) nc' (inc nc)
        cand' (int-array nc') _ (System/arraycopy cand 0 cand' 0 nc) _ (aset cand' nc (int firm))
        dist' (float-array (* n nc'))
        lon (double lon) lat (double lat)]
    (dotimes [c n]
      (System/arraycopy dist (* c nc) dist' (* c nc') nc)
      (let [[clon clat] (d2/cell-center grid c)]
        (aset dist' (+ (* c nc') nc) (float (w/haversine-m (double clon) (double clat) lon lat)))))
    {:cand cand' :dist dist' :n n :nc nc'}))

(defn open-site
  "One venue at (lon, lat) with per-class floor `sizes` (`{:short m² …}`,
   missing classes at zero): the dense build is extended once, every class
   vector once. Returns `{:dense :atts :firm}`; the new firm's index is one
   past the last existing firm, in every class alike, so a `district-of`
   must be told its district."
  [grid dense atts lon lat sizes]
  (let [j (alength ^doubles (get atts (first seg/segments)))
        extend (fn [^doubles a size]
                 (let [b (double-array (inc (alength a)))]
                   (System/arraycopy a 0 b 0 (alength a))
                   (aset b (alength a) (double size))
                   b))]
    {:dense (extend-dense grid dense j lon lat) :firm j
     :atts (into {} (for [s seg/segments]
                      [s (extend (get atts s) (get sizes s 0.0))]))}))

;; ---- outcomes ---------------------------------------------------------------------------

(defn outcome3
  "Expected euros at every candidate, per class, under `thetas` =
   `{:short {:alpha β d0-m} …}`. `cell-eur` is `{:short double[n] …}`, the
   class's money by home cell. Returns `{:short {:venue-eur double[nc]
   :input :expected-km} …}`, `:input` the class money put in."
  [dense atts spec thetas {:keys [cell-eur ^longs cell-pop]}]
  (let [nc (long (:nc dense)) ident (int-array (range nc))]
    (into {} (for [s seg/segments]
               (let [r (cand/reduce-dense dense (get atts s) (merge spec (get thetas s))
                                          {:cell-value (get cell-eur s) :bucket ident
                                           :n-buckets nc :cell-pop cell-pop})]
                 [s {:venue-eur (:bucket r)
                     ;; the class's money as put in, cell by cell, whether or
                     ;; not any venue could take it
                     :input (areduce ^doubles (get cell-eur s) c acc 0.0 (+ acc (aget ^doubles (get cell-eur s) c)))
                     :expected-km (some-> (:expected-distance-m r) (/ 1000.0))}])))))

(defn by-district
  "Euros per district from a candidate-order vector; a candidate whose
   district is unknown counts as \"outside\"."
  [dense district-of ^doubles venue-eur]
  (let [^ints c (:cand dense) m (java.util.HashMap.)]
    (dotimes [q (alength venue-eur)]
      (let [v (aget venue-eur q)]
        (when (not= 0.0 v)
          (let [d (or (district-of (aget c q)) "outside")]
            (.put m d (+ (double (or (.get m d) 0.0)) v))))))
    (into {} m)))

(defn- by-firm [dense ^doubles ve]
  (let [^ints c (:cand dense)]
    (into {} (map (fn [q] [(aget c q) (aget ve q)]) (range (alength ve))))))

(defn delta3
  "Scenario minus baseline, per class: venue deltas keyed by firm index (a
   closed venue's delta is minus its baseline, an opened one's its whole
   scenario turnover), district deltas, expected-km delta, and whether every
   euro is still accounted for."
  [dense-b base dense-s scen district-of]
  (into {} (for [s seg/segments]
             (let [b (get base s) sc (get scen s)
                   vb (by-firm dense-b (:venue-eur b)) vs (by-firm dense-s (:venue-eur sc))
                   db (by-district dense-b district-of (:venue-eur b))
                   ds (by-district dense-s district-of (:venue-eur sc))]
               [s {:venue-eur (into {} (for [j (into (set (keys vb)) (keys vs))]
                                         [j (- (double (get vs j 0.0)) (double (get vb j 0.0)))]))
                   :district-eur (into {} (for [d (into (set (keys db)) (keys ds))]
                                            [d (- (double (get ds d 0.0)) (double (get db d 0.0)))]))
                   :baseline-district db
                   :expected-km (when (and (:expected-km sc) (:expected-km b)) (- (:expected-km sc) (:expected-km b)))
                   ;; every euro put in lands at a venue, before and after: a
                   ;; closure that strands a cell's money shows up here
                   :conserved? (let [tol (* 1e-9 (max 1.0 (:input b)))
                                     landed (fn [o] (areduce ^doubles (:venue-eur o) q acc 0.0 (+ acc (aget ^doubles (:venue-eur o) q))))]
                                 (and (< (Math/abs (- (landed b) (:input b))) tol)
                                      (< (Math/abs (- (landed sc) (:input sc))) tol)))}]))))

;; ---- under a posterior ------------------------------------------------------------------

(defn weighted-stats
  "Mean and weighted quantiles of `xs` under `ws` (summing to one). The
   quantile is the smallest x whose cumulative weight reaches p — the
   posterior's own credible bounds, not a normal approximation."
  [xs ws]
  (let [pairs (sort-by first (map vector (map double xs) (map double ws)))
        total (reduce + (map second pairs))
        q (fn [p] (loop [ps pairs acc 0.0]
                    (let [[x wi] (first ps) acc' (+ acc wi)]
                      (if (or (>= acc' (* p total)) (empty? (rest ps))) x (recur (rest ps) acc')))))]
    {:mean (/ (reduce + (map (fn [[x wi]] (* x wi)) pairs)) total)
     :q05 (q 0.05) :q50 (q 0.5) :q95 (q 0.95)
     :min (ffirst pairs) :max (first (last pairs))}))

(defn across3
  "Evaluate baseline and scenario under every particle, in parallel, and
   keep the paired deltas. `particles` is `[{:theta {:short {…} …} :weight w}
   …]` — `city.infer/by-segment` over a run's :values, zipped with its
   :weights. `baseline` and `scenario` are `{:dense :atts}`. Returns the
   per-particle rows; `report` summarises them."
  [particles baseline scenario spec opts district-of]
  (vec (pmap (fn [{:keys [theta weight]}]
               (let [ob (outcome3 (:dense baseline) (:atts baseline) spec theta opts)
                     os (outcome3 (:dense scenario) (:atts scenario) spec theta opts)]
                 {:theta theta :weight weight
                  :baseline (into {} (for [s seg/segments] [s (select-keys (get ob s) [:input :expected-km])]))
                  :delta (delta3 (:dense baseline) ob (:dense scenario) os district-of)}))
             particles)))

(defn- stat-over [rows f]
  (weighted-stats (map f rows) (map :weight rows)))

(defn report
  "The scenario for the explorer, from `across3` rows.

   `observations` is `{[district class] eur}` as `city.infer/run-segmented`
   saw it, so the calibration panel can put the posterior predictive next to
   what was measured. `venues` is a lookup firm → {:name :lon :lat} for the
   venues worth listing: the closed set, the opened one, and the `top`
   largest movers by mean total delta. `closed`/`opened` describe the
   intervention for the reader, `priors` the ranges the posterior was drawn
   against; nothing here recomputes."
  [rows {:keys [observations venues closed opened top priors] :or {top 300}}]
  (let [classes seg/segments
        closed-set (set (map :firm closed))
        role (fn [j] (cond (closed-set j) :closed (= j (:firm opened)) :opened :else :other))
        districts (sort (distinct (mapcat #(keys (get-in % [:delta (first classes) :district-eur])) rows)))
        firms (distinct (mapcat #(keys (get-in % [:delta (first classes) :venue-eur])) rows))
        total-delta (fn [j] (fn [r] (reduce + (map #(get-in r [:delta % :venue-eur j] 0.0) classes))))
        venue-mean (into {} (for [j firms] [j (:mean (stat-over rows (total-delta j)))]))
        listed (concat (map :firm closed) (when opened [(:firm opened)])
                       (take top (sort-by #(- (Math/abs (double (venue-mean %)))) firms)))]
    {:particles (mapv (fn [r] {:theta (:theta r) :weight (:weight r)}) rows)
     :priors priors
     :classes classes
     :closed closed :opened opened
     :calibration (vec (for [d districts s classes
                             :let [obs (get observations [d s])]
                             :when obs]
                         {:district d :class s :observed obs
                          :predicted (stat-over rows #(get-in % [:delta s :baseline-district d] 0.0))}))
     :districts (vec (for [d districts]
                       {:district d
                        :baseline (mapv (fn [s] (:mean (stat-over rows #(get-in % [:delta s :baseline-district d] 0.0)))) classes)
                        :delta (mapv (fn [s] (stat-over rows #(get-in % [:delta s :district-eur d] 0.0))) classes)
                        :delta-total (stat-over rows (fn [r] (reduce + (map #(get-in r [:delta % :district-eur d] 0.0) classes))))}))
     :venues (vec (for [j (distinct listed) :let [v (get venues j)]]
                    {:firm j :name (:name v) :lon (:lon v) :lat (:lat v) :role (role j)
                     :delta (mapv (fn [s] (:mean (stat-over rows #(get-in % [:delta s :venue-eur j] 0.0)))) classes)
                     :delta-total (stat-over rows (total-delta j))}))
     :expected-km (vec (for [s classes]
                         {:class s
                          :baseline (:mean (stat-over rows #(get-in % [:baseline s :expected-km] 0.0)))
                          :delta (stat-over rows #(get-in % [:delta s :expected-km] 0.0))}))
     :conserved? (every? (fn [r] (every? #(get-in r [:delta % :conserved?]) classes)) rows)}))
