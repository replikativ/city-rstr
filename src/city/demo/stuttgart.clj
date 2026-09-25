(ns city.demo.stuttgart
  "The Stuttgart demo end to end, as functions over one context map.

   Each step takes the context the previous steps built and returns it with
   its own keys added, so the chain can be run whole (`up!`), resumed from a
   REPL, or stopped after any step:

     (build-world)          people, firms, diaries, choice tables       ~8 min
     (segment-inputs ctx)   three demand classes: floor, money, targets
     (fit-posterior ctx)    nine kernel numbers from 69 turnovers       ~80 min
     (money-day ctx θ)      the economic day for every inhabitant       ~50 s
     (publish! ctx)         a traced weekday, areas, scores, money      ~5 min
     (scenarios ctx)        interventions under the posterior           ~2 min
     (export-static! ctx)   the explorer and its data as files

   Memory: the world and its tables take about 5 GB of heap; start the JVM
   with -Xmx6g or more. The traced day's routing adds about 1 GB.

   Data is not in the repository. Every input is read from `data/derived/`
   and `data/raw/`; see DATA.md for sources, licences and how to obtain them.
   The evidence store (`city.store`) must be connected for the area polygons,
   `(city.store/connect!)`."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]
            [city.econ.day :as eday]
            [city.econ.household :as hh]
            [city.econ.report :as econ-report]
            [city.econ.spending :as spending]
            [city.infer :as infer]
            [city.sim.candidates :as cand]
            [city.sim.device :as dev]
            [city.sim.cityworld :as cw]
            [city.sim.day :as d2]
            [city.sim.kernel :as kn]
            [city.sim.network :as net]
            [city.sim.publish :as pub]
            [city.sim.run :as run]
            [city.sim.scenario :as sc]
            [city.sim.serve :as serve]
            [city.synth.retail :as retail]
            [city.synth.segments :as seg]
            [city.web :as web]))

;; ---- logging -------------------------------------------------------------------------------

(defn heap-gb []
  (let [r (Runtime/getRuntime)]
    (/ (Math/round (/ (- (.totalMemory r) (.freeMemory r)) 1.0e7)) 100.0)))

(defn- step [label f]
  (let [t0 (System/nanoTime) v (f)]
    (println (format "  %-30s %8.1f s   heap %.2f GB" label (/ (- (System/nanoTime) t0) 1e9) (heap-gb)))
    (flush)
    v))

;; ---- the world -----------------------------------------------------------------------------

(defn- cell-population
  "Residents per grid cell (in-commuters have no home cell)."
  ^longs [grid persons ^ints home-cell]
  (let [a (long-array (:n grid)) ^ints ext (:external persons)]
    (dotimes [i (:n persons)]
      (when (and (zero? (aget ext i)) (>= (aget home-cell i) 0))
        (aset a (aget home-cell i) (inc (aget a (aget home-cell i))))))
    a))

(defn build-world
  "Synthesise Stuttgart and prepare everything the day and the likelihood read.

   Returns a context with
   `:world` the persons and firms, with purchasing power;
   `:tables` the day's tables (`d2/prepare`) with the exact dense retail table;
   `:grid`, `:dense` (candidate distances), `:attract` (raked retail floor),
   `:spec` (the retail kernel), `:district-of` (Stadtteil → Stadtbezirk),
   `:spend` (retail potential per person), `:cell-pop`, and
   `:reference-day` (one untraced weekday, `d2/step-day`)."
  [& {:keys [sample seed] :or {sample 1.0 seed 1}}]
  (println "building Stuttgart" (java.util.Date.))
  (step "street graph" #(net/load! :ds net/stuttgart-dataset))
  (let [districts (retail/district-of)
        district-of (fn [a] (get districts a a))
        world (step "persons and firms" #(cw/build-stuttgart :sample sample))
        world (step "out-commuters" #(cw/place-out-commuters! world cw/stuttgart-out-destinations))
        world (step "purchasing power" #(hh/assign-purchasing-power! world :by-district district-of))
        diaries (step "diaries" #(pub/diaries-for world :stuttgart))
        attract (step "attractiveness" #(:attract (retail/attract (:firms world))))
        kernels (d2/venue-kernels (run/config {}))
        spec (:retail kernels)
        grid (d2/grid-spec world)
        firms (:firms world)
        dense (step "candidate distances" #(cand/build-dense grid firms (or (:retail firms) (:storefront firms))))
        retail-table (step "dense retail table" #(cand/table-dense dense attract spec))
        tables (step "day tables" #(d2/prepare world diaries :net-ds net/stuttgart-dataset :attract attract
                                               :mode-shares cw/mid-2017-stuttgart-modes :kernels kernels
                                               :retail retail-table))
        ctx {:world world :tables tables :grid grid :dense dense :attract attract :spec spec
             :district-of district-of
             :spend (step "retail potential" #(spending/retail-potential world))
             :cell-pop (cell-population grid (:persons world) (:home-cell tables))
             :seed seed}]
    (assoc ctx :reference-day (step "reference weekday" #(d2/step-day world tables seed)))))

;; ---- three demand classes ------------------------------------------------------------------

(defn segment-inputs
  "Per demand class: raked floor area (`:atts`, by firm index), resident money
   by home cell (`:cell-eur`), the published turnovers the likelihood compares
   with (`:observations`, keyed [district class]), and the district bucket of
   every candidate (`:bucket`, the observed districts then one \"outside\")."
  [{:keys [world tables grid dense district-of spend] :as ctx}]
  (let [targets (seg/targets)
        shares (seg/potential-shares targets)
        atts (step "floor by class" #(seg/attract-by-segment (:firms world) :tg targets :shares shares))
        observed (into (sorted-map) (for [[d t] (retail/targets) :when (:umsatz-eur t)] [d (:umsatz-eur t)]))
        districts (vec (keys observed))
        index (into {} (map-indexed (fn [i d] [d i]) districts))
        persons (:persons world)
        cell-eur (let [^objects la (:la persons) ^ints ext (:external persons)
                       ^ints hc (:home-cell tables) ^doubles sp spend
                       out (into {} (for [s seg/segments] [s (double-array (:n grid))]))]
                   (dotimes [i (:n persons)]
                     (when (and (zero? (aget ext i)) (>= (aget hc i) 0))
                       (when-let [k (get shares (district-of (aget la i)))]
                         (doseq [s seg/segments]
                           (let [^doubles a (get out s) c (aget hc i)]
                             (aset a c (+ (aget a c) (* (aget sp i) (double (get k s 0.0))))))))))
                   out)
        bucket (let [^ints c (:cand dense) ^objects la (:la (:firms world)) outside (count districts)]
                 (int-array (map (fn [j] (get index (district-of (aget la j)) outside)) (seq c))))]
    (assoc ctx :segment-targets targets :shares shares :atts atts :cell-eur cell-eur :bucket bucket
           :districts districts
           :observations (into (sorted-map)
                               (for [[d rows] targets s seg/segments
                                     :let [u (get-in rows [s :umsatz-eur])] :when (and u (pos? u))]
                                 [[d s] u])))))

(defn segmented-simulator
  "θ per class → `{:turnover {[district class] eur}}`: the exact expected
   allocation of every class's resident money, the simulator the likelihood
   evaluates. With a `:device` handle (`city.sim.device/open-dense`) in the
   context the allocation runs on the GPU, equal to the CPU's to about 1e-15
   relative."
  [{:keys [dense atts spec cell-eur bucket cell-pop districts device]}]
  (let [nb (inc (count districts))
        reduce-dense (if device (partial dev/reduce-dense device) cand/reduce-dense)]
    (fn [thetas]
      (reduce (fn [acc s]
                (let [r (reduce-dense dense (get atts s) (merge spec (get thetas s))
                                      {:cell-value (get cell-eur s) :bucket bucket :n-buckets nb :cell-pop cell-pop})]
                  (-> acc
                      (assoc-in [:km s] (/ (:expected-distance-m r) 1000.0))
                      (update :turnover into (for [[i d] (map-indexed vector districts)] [[d s] (aget ^doubles (:bucket r) i)])))))
              {:turnover {}} seg/segments))))

;; ---- the posterior -------------------------------------------------------------------------

(def posterior-file "data/derived/stuttgart-seg-posterior-n48.edn")

(defn fit-posterior
  "Nine kernel numbers, three per class, from the published turnovers:
   `n` independent random-walk Metropolis–Hastings chains of `iterations`
   single-site moves each, started from prior draws, final states weighted
   uniformly (`city.infer/run-segmented`). An approximate posterior: the
   chains are short, and the acceptance rate is the only diagnostic recorded.
   `:backend :gpu` evaluates the likelihood on the GPU (`city.sim.device`)."
  [{:keys [observations dense] :as ctx} & {:keys [n iterations sigma step-size seed backend]
                                           :or {n 48 iterations 30 sigma 0.25 step-size 0.15 seed 1 backend :cpu}}]
  (let [device (when (= :gpu backend) (dev/open-dense dense))
        p (try
            (step "posterior" #(infer/run-segmented (segmented-simulator (assoc ctx :device device)) observations
                                                    :n n :sigma sigma :chains :independent :kernel :random-walk-mh
                                                    :iterations iterations :step-size step-size :seed seed))
            (finally (when device (dev/close! device))))]
    (assoc (dissoc p :priors)
           :label (keyword (format "segmented-rw-mh-independent-n%d-iter%d-sigma-%s" n iterations sigma))
           :by-segment (mapv infer/by-segment (:values p)))))

(defn save-posterior! [posterior & {:keys [file] :or {file posterior-file}}]
  (io/make-parents file)
  (spit file (pr-str posterior))
  file)

(defn load-posterior [& {:keys [file] :or {file posterior-file}}]
  (when (.exists (io/file file)) (read-string (slurp file))))

(defn particles
  "The posterior as `[{:theta {:short {…} …} :weight w} …]`."
  [posterior]
  (let [vs (:values posterior) ws (or (seq (:weights posterior)) (repeat (/ 1.0 (count vs))))]
    (mapv (fn [v w] {:theta (infer/by-segment v) :weight (double w)}) vs ws)))

(defn posterior-mean [posterior] (infer/by-segment (:posterior-mean posterior)))

;; ---- the economic day ----------------------------------------------------------------------

(defn money-inputs
  "What the money day reads, built once: coordinates, class floor per
   candidate, spend per visit per person and class in cents, trip shares and
   leakage. π, the class shares of shopping trips, is `eday/default-pi`, an
   assumption."
  [{:keys [world tables grid dense atts district-of spend shares segment-targets] :as ctx}]
  (let [persons (:persons world) n (:n persons) diaries (:diaries tables)
        ^ints cand (:cand dense) nc (:nc dense) ncell (:n grid)
        ^doubles flon (:lon (:firms world)) ^doubles flat (:lat (:firms world))
        cell-xy (let [a (double-array (* 2 ncell))]
                  (dotimes [c ncell] (let [[lon lat] (d2/cell-center grid c)] (aset a (* 2 c) (double lon)) (aset a (inc (* 2 c)) (double lat))))
                  a)
        cand-xy (let [a (double-array (* 2 nc))]
                  (dotimes [q nc] (let [j (aget cand q)] (aset a (* 2 q) (aget flon j)) (aset a (inc (* 2 q)) (aget flat j))))
                  a)
        att3 (let [a (double-array (* 3 nc))]
               (dotimes [s 3] (let [^doubles att (get atts (nth seg/segments s))] (dotimes [q nc] (aset a (+ (* s nc) q) (aget att (aget cand q))))))
               a)
        pi eday/default-pi
        per-day (eday/store-episodes-per-day diaries)
        balances (eday/class-balances segment-targets)
        ^objects la (:la persons)
        spend3 (eday/spend-per-visit n spend (fn [i] (get shares (district-of (aget la i))))
                                     (:ptype tables) (eday/household-ids persons) per-day pi)]
    (eday/add-external-spend! spend3 n (:ptype tables) (:external persons) per-day pi balances)
    (assoc ctx :money {:cell-xy cell-xy :cand-xy cand-xy :att3 att3 :nc nc :pi pi :balances balances
                       :shares-array (eday/shares-array pi balances) :spend3 spend3})))

(defn- params3 [thetas]
  (double-array (mapcat (fn [s] (let [th (get thetas s)] [(:alpha th) (:beta th) (:d0-m th)])) seg/segments)))

(defn- totals3 [grid ^doubles cell-xy ^doubles cand-xy ^doubles att3 nc thetas]
  (let [ncell (:n grid)
        cl (double-array (map #(aget cell-xy (* 2 %)) (range ncell))) ca (double-array (map #(aget cell-xy (inc (* 2 %))) (range ncell)))
        ql (double-array (map #(aget cand-xy (* 2 %)) (range nc))) qa (double-array (map #(aget cand-xy (inc (* 2 %))) (range nc)))
        a (double-array (* 3 ncell))]
    (dotimes [s 3]
      (let [att (double-array nc) _ (System/arraycopy att3 (* s nc) att 0 nc)
            th (get thetas (nth seg/segments s)) tot (double-array ncell)]
        (kn/cell-totals! cl ca ql qa att (double-array [(:alpha th) (:beta th) (:d0-m th)]) tot ncell nc)
        (System/arraycopy tot 0 a (* s ncell) ncell)))
    a))

(defn money-day
  "One economic day for every inhabitant under `thetas`, on the JVM:
   `{:revenue3 :visits3 :counts :nc}`, candidate-indexed with the classes
   stacked, `[(class·nc + candidate)·24 + hour]`, revenue in cents. A venue set
   other than the baseline's is passed as `:att3`, `:cand-xy` and `:nc`."
  [{:keys [world tables grid money seed]} thetas & {:keys [att3 cand-xy nc]}]
  (let [{:keys [cell-xy shares-array spend3]} money
        att3 (or att3 (:att3 money)) cand-xy (or cand-xy (:cand-xy money)) nc (long (or nc (:nc money)))
        persons (:persons world) diaries (:diaries tables)
        rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)]
    (kn/spend-day! (:ptype tables) (:home-cell tables) (:work persons) (:work-cell tables)
                   (:type-offsets diaries) (:type-cdf diaries) (:diary-offsets diaries) (:ep-loc diaries) (:ep-minute diaries)
                   cell-xy cand-xy att3 (totals3 grid cell-xy cand-xy att3 nc thetas) (params3 thetas) shares-array
                   spend3 rev vis cnt (long-array [(:n persons) nc seed (:n grid)]))
    {:revenue3 rev :visits3 vis :counts (vec cnt) :nc nc :theta thetas}))

;; ---- publishing ----------------------------------------------------------------------------

(def run-key "stuttgart")

(defn- area-polygons [level]
  (cw/area-polygons-fc (web/areas {:city "stuttgart" :level level})))

(defn publish!
  "Trace one weekday for every `stride`-th person on the street and transit
   network, reduce it to areas, score the economy against its published
   targets, and register the run with the simulation server together with the
   money day under `thetas`. Starts the server when `:port` is given."
  [{:keys [world tables district-of spend reference-day money seed] :as ctx} thetas & {:keys [stride port] :or {stride 20}}]
  (let [cfg (assoc (select-keys (run/config {}) pub/city-override-keys) :seed seed :days 1 :months 0 :city :stuttgart)
        published (assoc world :daily-tables tables :day (assoc reference-day :days 1) :city :stuttgart)
        route (serve/routing! {:world published})
        acc (java.util.ArrayList.)
        _ (step (str "traced weekday, 1 in " stride)
                #(d2/step-day-traces published tables seed :stride stride :route route
                                     :p-keep (:p-keep-diary-mode cfg) :route-variants (:route-variants cfg)
                                     :trace-fn (fn [{:keys [person legs]}] (doseq [l legs] (.add acc (pub/flat-leg person l))))))
        trips (vec acc)
        areas (step "area aggregates"
                    #(cw/area-aggregates published reference-day (pub/with-access trips) :stride stride
                                         :raster (cw/area-raster (:grid tables) (area-polygons "stadtteil"))))
        econ (step "economic scores" #(econ-report/scores published tables :args {:by-district district-of :spend spend}))
        day (step "money day" #(money-day ctx thetas))]
    (serve/publish! run-key {:world published :areas areas :trips trips :stride stride :econ econ
                             :config (assoc cfg :sample 1.0 :stride stride :resolved-kernels (:kernels tables) :retail-table :dense
                                            :fixed-routing {:profile-walk-max-m net/profile-walk-max-m :route-jitter net/walk-route-jitter})
                             :money {:cand (:cand (:dense ctx)) :nc (:nc money) :revenue3 (:revenue3 day) :visits3 (:visits3 day)
                                     :classes seg/segments :pi (vec (:pi money)) :theta thetas :seed seed
                                     :note "one economic day at the posterior-mean kernel; spend per visit pooled by household; leakage and in-commuter spend from the published class balances"}})
    (when port (serve/start! :port port))
    (assoc ctx :published {:legs (count trips) :stride stride :areas (count (:areas areas))})))

;; ---- scenarios -----------------------------------------------------------------------------

(def milaneo
  "The Milaneo shopping centre at Mailänder Platz: the candidates within 170 m."
  {:lon 9.1829 :lat 48.7912 :radius-m 170.0})

(defn- district-centroid
  "Population-weighted centre of the residents of district `d`."
  [{:keys [world tables grid district-of]} d]
  (let [persons (:persons world) ^objects la (:la persons) ^ints ext (:external persons) ^ints hc (:home-cell tables)
        acc (double-array 3)]
    (dotimes [i (:n persons)]
      (when (and (zero? (aget ext i)) (>= (aget hc i) 0) (= d (district-of (aget la i))))
        (let [[lon lat] (d2/cell-center grid (aget hc i))]
          (aset acc 0 (+ (aget acc 0) (double lon))) (aset acc 1 (+ (aget acc 1) (double lat))) (aset acc 2 (inc (aget acc 2))))))
    [(/ (aget acc 0) (aget acc 2)) (/ (aget acc 1) (aget acc 2))]))

(defn- visits-report
  "Per venue whose day changed: baseline and scenario visits over the day and
   the hourly difference, classes summed; the new venue, if any, last."
  [day0 day1 venues cand new-firm]
  (let [^ints v0 (:visits3 day0) ^ints v1 (:visits3 day1) nc0 (long (:nc day0)) nc1 (long (:nc day1))
        at (fn [^ints v nc s q h] (aget v (+ (* (+ (* s (long nc)) (long q)) 24) (long h))))
        rows (vec (for [q (range nc1)
                        :let [b (fn [h] (if (< q nc0) (reduce + (map #(at v0 nc0 % q h) (range 3))) 0))
                              s (fn [h] (reduce + (map #(at v1 nc1 % q h) (range 3))))
                              bday (reduce + (map b (range 24))) sday (reduce + (map s (range 24)))]
                        :when (not= bday sday)
                        :let [j (if (< q nc0) (aget ^ints cand q) new-firm) v (get venues j)]]
                    {:firm j :name (:name v) :category (:category v) :lon (:lon v) :lat (:lat v)
                     :baseline-day bday :scenario-day sday :delta-hours (mapv #(- (s %) (b %)) (range 24))}))]
    {:venues rows
     :totals {:baseline (reduce + 0 (map :baseline-day rows)) :scenario (reduce + 0 (map :scenario-day rows))}
     :note "one economic day, same seed and diaries as the baseline, posterior-mean kernel; paired by common random numbers, so venues other than the changed ones can also move"}))

(defn scenarios
  "Close the Milaneo; and close it and rebuild its floor at the population
   centre of `target`. Each is evaluated under every posterior particle (the
   exact expectation, `city.sim.scenario`) and as one paired economic day at
   the posterior mean. Installs both on the published run and returns them."
  [{:keys [world dense atts spec cell-eur cell-pop observations district-of grid money] :as ctx} posterior
   & {:keys [target] :or {target "Zuffenhausen"}}]
  (let [firms (:firms world) ^ints cand (:cand dense) nc (:nc dense)
        ps (particles posterior) mean (posterior-mean posterior)
        observed (set (map first (keys observations)))
        district-of-firm (let [^objects la (:la firms) nf (:n firms)]
                           (fn [j] (when (< (long j) nf) (let [d (district-of (aget la j))] (when (observed d) d)))))
        venues (into {} (map (fn [q] (let [j (aget cand q)]
                                       [j {:name (get (:name firms) j) :category (get (:category firms) j)
                                           :lon (aget ^doubles (:lon firms) j) :lat (aget ^doubles (:lat firms) j)}]))
                             (range nc)))
        opts {:cell-eur cell-eur :cell-pop cell-pop}
        base {:dense dense :atts atts}
        footprint (sc/footprint dense firms atts (:lon milaneo) (:lat milaneo) (:radius-m milaneo))
        closed (set (map :firm footprint))
        closed-q (set (map :q footprint))
        sizes (into {} (map (fn [s i] [s (reduce + (map #(nth (:att %) i) footprint))]) seg/segments (range)))
        [tlon tlat] (district-centroid ctx target)
        day0 (step "baseline money day" #(money-day ctx mean))
        ;; close
        att3-closed (let [a (aclone ^doubles (:att3 money))] (doseq [s (range 3) q closed-q] (aset a (+ (* s nc) q) 0.0)) a)
        close-rows (step "close: across particles" #(sc/across3 ps base {:dense dense :atts (sc/close-set atts closed)} spec opts district-of-firm))
        close (assoc (sc/report close-rows {:observations observations :venues venues :closed footprint :priors infer/default-priors})
                     :label "Close the Milaneo shopping centre"
                     :question "What if the Milaneo shopping centre near the main station closed? The same residents and the same money, one hundred shops fewer to choose from."
                     :visits (visits-report day0 (step "close: money day" #(money-day ctx mean :att3 att3-closed)) venues cand nil))
        ;; move
        opened (sc/open-site grid dense atts tlon tlat sizes)
        new-firm (:firm opened)
        new-venue {:name (str "Milaneo, rebuilt in " target) :category "shopping_center" :lon tlon :lat tlat}
        move-rows (step "move: across particles"
                        #(sc/across3 ps base {:dense (:dense opened) :atts (sc/close-set (:atts opened) closed)} spec opts
                                     (fn [j] (if (= (long j) (long new-firm)) target (district-of-firm j)))))
        cand-xy1 (let [a (double-array (* 2 (inc nc)))]
                   (System/arraycopy ^doubles (:cand-xy money) 0 a 0 (* 2 nc)) (aset a (* 2 nc) (double tlon)) (aset a (inc (* 2 nc)) (double tlat)) a)
        att3-moved (let [a (double-array (* 3 (inc nc)))]
                     (dotimes [s 3]
                       (System/arraycopy att3-closed (* s nc) a (* s (inc nc)) nc)
                       (aset a (+ (* s (inc nc)) nc) (double (get sizes (nth seg/segments s)))))
                     a)
        move (assoc (sc/report move-rows {:observations observations :closed footprint :priors infer/default-priors
                                          :opened (assoc new-venue :firm new-firm :district target :att (mapv sizes seg/segments))
                                          :venues (assoc venues new-firm new-venue)})
                    :label (str "Move the Milaneo shopping centre to " target)
                    :question (str "What if the Milaneo shopping centre's floor space stood in " target " instead? Same residents, same money, the centre's floors at the district's population centre.")
                    :target target
                    :visits (visits-report day0 (step "move: money day" #(money-day ctx mean :att3 att3-moved :cand-xy cand-xy1 :nc (inc nc)))
                                           (assoc venues new-firm new-venue) cand new-firm))
        result {"close-milaneo" close "move-milaneo" move}]
    (swap! serve/outputs assoc-in [run-key :scenarios] result)
    result))

;; ---- static export -------------------------------------------------------------------------

(defn- anonymise-venues
  "Venue names out, categories in: the numbers attached to a venue are
   simulated, and a simulated turnover next to a real business's name reads
   as a fact about that business."
  [payload]
  (let [strip (fn [v] (-> v (dissoc :name) (assoc :label (str/replace (str (or (:category v) "venue")) "_" " "))))]
    (cond-> payload
      (:features payload) (update :features (fn [fs] (mapv #(update % :properties strip) fs)))
      (:venues payload) (update :venues #(mapv strip %))
      (:closed payload) (update :closed #(mapv strip %))
      (get-in payload [:visits :venues]) (update-in [:visits :venues] #(mapv strip %)))))

(defn- sim-json [uri query]
  (let [{:keys [status body]} (serve/handler {:uri uri :query-string query})]
    (when-not (= 200 status) (throw (ex-info "export request failed" {:uri uri :query query :status status})))
    (json/read-str body :key-fn keyword)))

(defn export-static!
  "Write the explorer and the published run as a static site under `dir`:
   one JSON file per response the explorer reads, the page and the model
   page with relative paths, and a manifest. Reads the running process's
   published outputs and the connected store; no server needs to listen.
   Venue names are removed (`anonymise-venues`), and the scorecard omits the
   observed purchasing power, which is licensed IFH data."
  [& {:keys [dir] :or {dir "dist/lab"}}]
  (let [data (io/file dir "data" "stuttgart")
        q (str "area=" run-key)
        write! (fn [name payload] (let [f (io/file data name)] (io/make-parents f) (spit f (json/write-str payload)) [name (.length f)]))
        econ (update (sim-json "/sim/econ" q) :rows (fn [rows] (vec (remove #(= "household/purchasing-power" (:quantity %)) rows))))
        scenario-list (sim-json "/sim/scenarios" q)
        written (concat
                 (for [[name uri query] [["layers.json" "/sim/layers" ""] ["meta.json" "/sim/meta" q]
                                         ["scenarios.json" "/sim/scenarios" q] ["aggregates.json" "/sim/areas" q]
                                         ["series.json" "/sim/series" q] ["stops.json" "/sim/stops" q]
                                         ["trips.json" "/sim/trips" (str q "&stride=" (first (keys (get-in @serve/outputs [run-key :trips]))))]]]
                   (write! name (sim-json uri query)))
                 [(write! "econ.json" econ)
                  (write! "revenue.json" (anonymise-venues (sim-json "/sim/revenue" q)))
                  (write! "visits.json" (anonymise-venues (sim-json "/sim/visits" q)))
                  (write! "areas-stadtteil.json" (web/areas {:city "stuttgart" :level "stadtteil"}))
                  (write! "areas-stadtbezirk.json" (web/areas {:city "stuttgart" :level "stadtbezirk"}))
                  (write! "cells.json" (web/cells {:city "stuttgart"}))]
                 (for [{:keys [key]} (:scenarios scenario-list)]
                   (write! (str "scenario-" key ".json")
                           (anonymise-venues (sim-json "/sim/scenario" (str q "&scenario=" key))))))
        copy! (fn [from to] (let [t (io/file dir to)] (io/make-parents t) (io/copy (io/file from) t)))]
    (doseq [f (.listFiles (io/file "public/lab")) :when (.isFile ^java.io.File f)]
      (copy! f (str "lab/" (.getName ^java.io.File f))))
    (copy! "public/js/app/main.js" "js/main.js")
    (spit (io/file dir "index.html")
          (-> (slurp "public/lab.html")
              (str/replace "href=\"/lab/" "href=\"lab/")
              (str/replace "src=\"/js/app/main.js\"" "src=\"js/main.js\"")
              (str/replace "href=\"/model.html" "href=\"model.html")
              (str/replace-first "<meta charset=\"utf-8\">"
                                 (str "<meta charset=\"utf-8\">\n  <meta name=\"city-data\" content=\"data/stuttgart/\">"
                                      ;; every path is relative to the folder, so /lab must become /lab/ first
                                      "\n  <script>if (!/\\/$|\\.html$/.test(location.pathname)) location.replace(location.pathname + \"/\" + location.search + location.hash);</script>"))))
    (spit (io/file dir "model.html")
          (-> (slurp "public/model.html")
              (str/replace "href=\"/lab/lab.css\"" "href=\"lab/lab.css\"")
              (str/replace "href=\"/lab.html?" "href=\"index.html?")))
    (let [manifest {:written (into (sorted-map) written) :exported-at (str (java.time.Instant/now))}]
      (spit (io/file dir "export-manifest.json") (json/write-str manifest))
      manifest)))

;; ---- everything ----------------------------------------------------------------------------

(defn up!
  "Build, load or fit the posterior, publish, evaluate the scenarios and serve
   them on `port`. Returns the context."
  [& {:keys [port fit? stride] :or {port 8092 stride 20}}]
  ((requiring-resolve 'city.store/connect!))
  (let [ctx (-> (build-world) segment-inputs money-inputs)
        posterior (or (when-not fit? (load-posterior))
                      (let [p (fit-posterior ctx)] (save-posterior! p) p))
        ctx (publish! ctx (posterior-mean posterior) :stride stride :port port)]
    (scenarios ctx posterior)
    (println "DEMO-READY" {:port port :heap-gb (heap-gb)})
    (assoc ctx :posterior posterior)))

(defn -main
  "`clojure -M:demo up [port]`     build and serve
   `clojure -M:demo export [dir]`  build, then write the static site"
  [& [cmd arg]]
  (case cmd
    "up" (do (up! :port (if arg (parse-long arg) 8092)) @(promise))
    "export" (do (up! :port nil) (println (export-static! :dir (or arg "dist/lab"))) (shutdown-agents))
    (println (:doc (meta #'-main)))))
