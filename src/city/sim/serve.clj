(ns city.sim.serve
  "The simulation API (port 8092): published runs held in memory and answered
   as JSON for the explorer. `publish!` registers a run under a key
   (`\"stuttgart\"`); `handler` answers `/sim/*` requests from what the run
   holds, filtering point and leg layers by `bbox` and capping trips at
   `max-legs`. The endpoints are listed in `doc/api.md`.

   `city.demo.stuttgart/export-static!` calls `handler` in process and writes
   each response to a file, so the published explorer needs no server.

   Routing state is shared: `city.sim.network` holds one street graph and one
   transit-stop index, so a request that has to route installs the ones its
   run's city needs first (`city-routing`, `routing!`). A run whose legs are
   already cached never routes at all."
  (:require [org.httpkit.server :as http]
            [clojure.data.json :as json]
            [clojure.string :as str]
            [city.sim.day :as d2]
            [city.sim.network :as net]
            [city.intake.gtfs :as gtfs]))

(defonce server (atom nil))
(defonce outputs (atom {}))  ;; run key → what `publish!` registered

(defonce ^{:doc "city key → the stop rows of that city's feed, read once."}
  stop-tables (atom {}))
(defonce ^{:doc "Which city's stops are currently installed in `city.sim.network`."}
  installed-stops (atom nil))

(def city-routing
  "Per city, the two things a routed leg needs that are not in the world:
   which street pull the shared graph is built from, and which GTFS stop
   table the transit access points come from."
  {:stuttgart {:ds net/stuttgart-dataset :stops gtfs/stops-for-stuttgart}})

(defn stops!
  "Install one city's transit stops as the access points transit legs walk to,
   reading the table once per city. Returns the rows."
  [city]
  (let [rows (or (@stop-tables city)
                 (let [rows (vec ((:stops (city-routing city))))]
                   (swap! stop-tables assoc city rows)
                   rows))]
    (when-not (= city @installed-stops)
      (net/set-stops! rows)
      (reset! installed-stops city))
    rows))

(defn city-of
  "Which city a published run belongs to; a world built by
   `city.sim.cityworld/build-stuttgart` says so itself."
  [out]
  (or (get-in out [:world :city]) :stuttgart))

(defn routing!
  "Make the shared network and the stop index the ones this run's city needs,
   and return a mode router over them. Returns nil when there is no pull to
   build a graph from."
  [out]
  (let [city (city-of out)
        ds (:ds (city-routing city))]
    (stops! city)
    (net/route-fn :ds ds)))

(defn- stops-for
  "The stop rows a `/sim/stops` request draws: the whole table of the run's
   city."
  [area]
  (stops! (if-let [out (get @outputs (str area))] (city-of out) :stuttgart)))

(defn publish!
  "Register a finished run under `area-eid`, the run key. `:world` is the
   world with its day tables and reference day; `:config` is kept so the
   explorer can label the layers with the run's seed and parameters (observed
   and simulated must never be ambiguous).

   `:areas` is the pre-reduced area-level aggregate
   (`city.sim.cityworld/area-aggregates`) — the same run seen at the coarser
   fidelity the zoomed-out view draws, computed once rather than per request.
   `:trips` seeds the leg cache when the run already traced a day, so the
   server never re-routes what the caller has in hand.

   `:econ` is the economic scorecard (`city.econ.report/scores`): every
   registered quantity against its published target, computed once at publish
   because the scorers walk every person."
  [area-eid {:keys [world firm-state config areas trips stride econ preview-trips money]}]
  (swap! outputs assoc (str area-eid)
         (cond-> {:world world :firm-state firm-state :config config :areas areas
                  :published-at (java.util.Date.)}
           trips (assoc :trips {(long (or stride 10)) trips})
           ;; the economic day's candidate-indexed arrays (revenue-layer)
           money (assoc :money money)
           preview-trips (assoc :preview-trips preview-trips)
           ;; economic scores from city.econ.report, already reduced to rows
           ;; the explorer draws; kept whole so /sim/econ is a read
           econ  (assoc :econ econ))))

;; ---- viewport ---------------------------------------------------------------------------------

(defn- parse-bbox
  "`west,south,east,north` → a bbox map, or nil."
  [s]
  (when s
    (let [xs (keep #(try (Double/parseDouble %) (catch Exception _ nil)) (str/split s #","))]
      (when (= 4 (count xs))
        (zipmap [:west :south :east :north] xs)))))

(defn- in-bbox? [bbox ^double lon ^double lat]
  (or (nil? bbox)
      (and (<= (double (:west bbox)) lon (double (:east bbox)))
           (<= (double (:south bbox)) lat (double (:north bbox))))))

(defn- path-in-bbox?
  "A leg is in view when any of its vertices is. Cheap and slightly generous:
   a leg that crosses the viewport without a vertex in it is dropped, which at
   40 vertices per leg is a block-scale error."
  [bbox path]
  (or (nil? bbox) (boolean (some (fn [p] (in-bbox? bbox (double (nth p 0)) (double (nth p 1)))) path))))

(defn- fc [features] {:type "FeatureCollection" :features (vec features)})

(defn- visits-layer [{:keys [world]} bbox]
  (let [fs (:firms world) nf (:n fs) ^ints sf (:storefront fs) vis (get-in world [:day :visits])]
    (fc (for [j (range nf) :when (and (= 1 (aget sf j))
                                      (in-bbox? bbox (aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)))
              :let [v (reduce + (map #(double (aget vis (+ (* j 24) %))) (range 24)))]]
          {:type "Feature" :geometry {:type "Point" :coordinates [(aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)]}
           :properties {:name (aget ^objects (:name fs) j) :type (aget ^objects (:type fs) j)
                        :visits (/ (Math/round (* 10 v)) 10.0)
                        :hours (mapv #(/ (Math/round (* 10 (double (aget vis (+ (* j 24) %))))) 10.0) (range 24))}}))))

(defn- revenue-layer
  "The economic day: per retail venue, this weekday's visits and revenue by
   demand class, annualised. Read off the run's `:money`, which
   `city.sim.kernel/spend-day!` produced: candidate-indexed arrays with the
   three classes stacked, `[(class·nc + candidate)·24 + hour]`.

   Revenue is in euros per year (365 × the day's cents ÷ 100). A venue with
   no visit in any class is omitted. `:classes` names the class order."
  [{:keys [world money]} bbox]
  (if-not money
    (fc [])
    (let [fs (:firms world) ^ints cand (:cand money) nc (long (:nc money))
          ^ints rev (:revenue3 money) ^ints vis (:visits3 money)
          classes (or (:classes money) [:short :medium :long])
          sum (fn [^ints a s q] (let [base (* (+ (* s nc) q) 24)] (loop [h 0 acc 0] (if (= h 24) acc (recur (inc h) (+ acc (aget a (+ base h))))))))]
      (fc (for [q (range nc)
                :let [j (aget cand q)
                      visits (mapv #(sum vis % q) (range (count classes)))]
                :when (and (pos? (reduce + visits))
                           (in-bbox? bbox (aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)))]
            {:type "Feature" :geometry {:type "Point" :coordinates [(aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)]}
             :properties {:name (aget ^objects (:name fs) j) :category (when-let [^objects c (:category fs)] (aget c j))
                          :classes (mapv name classes)
                          :visits visits
                          :revenue-eur-year (mapv #(Math/round (* 365.0 (/ (sum rev % q) 100.0))) (range (count classes)))}})))))

(defn- firms-layer
  "Firm points after the run. A run published without a firm state (the
   Stuttgart run is one day) still answers: the firm's size is then its
   employee count and it is alive, with no age."
  [{:keys [world firm-state]} bbox]
  (let [fs (:firms world) ^ints emp (:employees fs)
        ^ints size (:size firm-state) ^ints founded (:founded firm-state) month (:month firm-state)
        sz (fn [j] (if size (aget size j) (aget emp j)))]
    (fc (for [j (range (:n fs))
              :when (and (or (pos? (long (sz j))) (pos? (aget emp j)))
                         (in-bbox? bbox (aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)))]
          {:type "Feature" :geometry {:type "Point" :coordinates [(aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)]}
           :properties (cond-> {:name (aget ^objects (:name fs) j) :type (aget ^objects (:type fs) j)
                                :size0 (aget emp j) :size (sz j) :alive (if (pos? (long (sz j))) 1 0)}
                         founded (assoc :age-years (quot (- month (aget founded j)) 12)))}))))

(defn- stops-layer
  "GeoJSON of the transit access points, carrying the mean weekday 07:00–19:00
   headway and the routes that call. Observed data, not simulated — but the
   *use* of it (walk to the nearest stop) is the model's, so the UI draws it in
   the simulated style."
  [area bbox]
  (fc (for [{:keys [stop-id code name lon lat routes departures headway-min]} (stops-for area)
            :when (in-bbox? bbox (double lon) (double lat))]
        {:type "Feature" :geometry {:type "Point" :coordinates [lon lat]}
         :properties {:stop-id stop-id :code code :name name
                      :routes (vec routes) :departures departures
                      :headway-min headway-min}})))

(defn- meta-layer
  "What the legend needs to date and identify the run. Falls back to what can be
   read off the outputs when a run was published without its config.

   `:city` is part of a run's identity: the street graph and stop table a leg
   was routed on follow from it (`city-routing`)."
  [{:keys [config firm-state world published-at] :as out}]
  (cond-> {:seed (:seed config)
           :config config
           :days (:days config)
           :city (name (city-of out))
           :months (or (:months config) (count (:series firm-state)))
           :published-at (some-> published-at .toInstant str)}
    (:meta world) (assoc :world (-> (:meta world)
                                    (select-keys [:persons :firms :sample :year :commute :workplaces])))
    true (assoc :persons (:n (:persons world)) :firms (:n (:firms world)))))

(defn- params [{:keys [query-string]}]
  (into {} (for [kv (str/split (or query-string "") #"&") :when (seq kv) :let [[k v] (str/split kv #"=" 2)]] [(keyword k) v])))

(defn- r5 ^double [^double x] (/ (Math/round (* x 100000.0)) 100000.0))

(def max-legs
  "Ceiling on one `/sim/trips` response. A viewport at street zoom holds a few
   thousand legs; a request for the whole city at stride 10 would be a hundred
   thousand, which is a 60 MB payload and a frozen browser. Over the ceiling the
   legs are thinned by a fixed step, so what comes back is a uniform sample of
   what is in view and not its first corner."
  20000)

(defn- thin [xs ^long cap]
  (let [n (count xs)]
    (if (<= n cap) (vec xs)
        (let [step (/ (double n) cap)]
          (vec (map #(nth xs (min (dec n) (long (* % step)))) (range cap)))))))

(defn- trips-cached
  "One record per trip *leg*: a person moves only while travelling, the leg is
   routed on the street network, and its purpose (the destination) is what the
   map colours by. Cached per (area, stride) — routing a whole day is seconds,
   not milliseconds."
  [area stride]
  (or (get-in @outputs [area :preview-trips])
      (get-in @outputs [area :trips stride])
      ;; A published run serves the stride it was traced at, never one it was
      ;; not: tracing a whole-city day inside an http-kit worker takes an
      ;; hour and stalls the server. For a run that carries any cached
      ;; stride, answer with the nearest one; on-demand tracing is only for a
      ;; run published without trips.
      (when-let [cached (seq (get-in @outputs [area :trips]))]
        (let [[k legs] (apply min-key (fn [[k _]] (Math/abs (- (long k) (long stride)))) cached)]
          (println :sim/trips-stride-fallback {:area area :asked stride :served k})
          legs))
      (let [out (get @outputs area)
            {:keys [world]} out
            tables (:daily-tables world)
            route (routing! out)
            _ (net/reset-stats!)
            t0 (System/currentTimeMillis)
            {:keys [traces leg-stats]} (d2/step-day-traces world tables (get-in out [:config :seed] 1)
                                                            :stride stride :route route
                                                            :p-keep (get-in out [:config :p-keep-diary-mode] d2/default-p-keep-diary-mode)
                                                            :route-variants (get-in out [:config :route-variants] net/walk-route-variants))
            ms (- (System/currentTimeMillis) t0)
            trips (vec (for [{:keys [person legs]} traces
                             {:keys [purpose path timestamps mode]} legs]
                         {:pid person :purpose purpose :mode mode
                          :path (mapv (fn [[lon lat]] [(r5 lon) (r5 lat)]) path)
                          :timestamps timestamps}))
            {:keys [routes hits failed]} (net/stats)]
        (println (format "trips area=%s city=%s net=%s stride=%s: %d legs, %d persons, %d ms, routes %s hits %.1f%% failed %s legs %s"
                         area (name (city-of out)) (pr-str @net/net-source)
                         stride (count trips) (count traces) ms routes
                         (if (and routes (pos? routes)) (* 100.0 (/ (double (or hits 0)) routes)) 0.0) failed
                         (pr-str leg-stats)))
        (swap! outputs assoc-in [area :trips stride] trips)
        trips)))

(defn- trips-layer
  "The legs in view. Without a bbox the whole cached day is offered, thinned to
   `max-legs`; with one, only the legs that touch the viewport."
  [area stride bbox]
  (let [all (trips-cached area stride)]
    (thin (if bbox (filterv #(path-in-bbox? bbox (:path %)) all) all) max-legs)))

(defn- areas-layer
  "The run at *area* fidelity: one row per local area with the aggregate
   quantities, plus the origin–destination matrix of resident trips. Reduced
   once at publish time (`city.sim.cityworld/area-aggregates`) — the view never
   re-derives it, and never invents an agent the aggregate does not have."
  [{:keys [areas]}]
  (or areas {:areas [] :od [] :note "this run was published without an area aggregate"}))

(defn handler [{:keys [uri] :as req}]
  (let [{:keys [area stride bbox]} (params req)
        stride (try (max 1 (Long/parseLong (or stride "10"))) (catch Exception _ 10))
        bbox (parse-bbox (some-> bbox (java.net.URLDecoder/decode "UTF-8")))
        out (get @outputs (str area))
        resp (fn [d] {:status 200 :headers {"content-type" "application/json" "access-control-allow-origin" "*"} :body (json/write-str d)})]
    (cond
      (= uri "/sim/layers") (resp {:areas (keys @outputs) :layers ["visits" "firms" "series" "trips" "stops" "areas" "meta" "econ" "revenue" "scenarios"]})
      (= uri "/sim/stops") (resp (stops-layer (str area) bbox))
      (nil? out) {:status 404 :headers {"access-control-allow-origin" "*"} :body "no run for area"}
      (= uri "/sim/visits") (resp (visits-layer out bbox))
      ;; the economic day, when the run carries one (see revenue-layer)
      (= uri "/sim/revenue") (resp (revenue-layer out bbox))
      (= uri "/sim/firms") (resp (firms-layer out bbox))
      (= uri "/sim/series") (resp (or (:series (:firm-state out)) []))
      (= uri "/sim/meta") (resp (meta-layer out))
      (= uri "/sim/areas") (resp (areas-layer out))
      ;; economic scores, computed once at publish time (city.econ.report/scores)
      ;; and stored on the output: every registered quantity, observed against
      ;; predicted, per district
      (= uri "/sim/econ") (resp (or (:econ out) {:rows [] :summary []}))
      (= uri "/sim/trips") (resp (trips-layer (str area) stride bbox))
      ;; policy scenarios evaluated under the posterior at publish time
      ;; (city.sim.scenario/report); the explorer reads them, it never
      ;; re-evaluates one
      (= uri "/sim/scenarios") (resp {:scenarios (vec (for [[k v] (:scenarios out)] (assoc (select-keys v [:label :question]) :key k)))})
      (= uri "/sim/scenario") (if-let [sc (get-in out [:scenarios (:scenario (params req))])]
                                (resp sc)
                                {:status 404 :headers {"access-control-allow-origin" "*"} :body "no such scenario"})
      :else {:status 404 :body "not found"})))

(defn start! [& {:keys [port ip] :or {port 8092 ip "127.0.0.1"}}]
  (when @server (@server))
  (reset! server (http/run-server #'handler {:port port :ip ip}))
  (str "http://localhost:" port))
