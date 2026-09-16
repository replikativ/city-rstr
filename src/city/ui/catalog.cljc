(ns city.ui.catalog
  "The requests the explorer makes, as data: `requests` describes each one
   for a context (city, level, area, run key, scenario), and `static-path`
   maps it to the file a static export holds instead. Pure, so it is tested on
   the JVM.")

(def ^:private whole-city-run
  {:vancouver "city"
   :stuttgart "stuttgart"})

(def ^:private year-kinds #{:storefront :licence})

(defn- value-string [x]
  (cond
    (keyword? x) (name x)
    (some? x) (str x)))

(defn- numeric-id? [x]
  (or (integer? x)
      (and (string? x) (boolean (re-matches #"[0-9]+" x)))))

(defn- request [base path params]
  {:base base :path path :params params})

(defn- with-bbox [params bbox]
  (cond-> params
    (and (string? bbox) (not (empty? bbox))) (assoc :bbox bbox)))

(defn- point-request [area year kind]
  (assoc (request :store "/api/points"
                  (cond-> {:kind (name kind) :area (value-string area)}
                    (and year (year-kinds kind)) (assoc :year year)))
         :kind kind))

(defn requests
  "Return request descriptions available for `context`.

  `:points` is a vector because the store endpoint accepts one kind per call.
  Simulation requests use `:run-key` when the caller resolved one from
  `/sim/layers`; otherwise they address the city's whole-city run."
  [{:keys [city level area year bbox kinds stride entity run-key scenario]}]
  (let [area? (numeric-id? area)
        entity? (numeric-id? entity)
        run (or (value-string run-key) (whole-city-run city))
        sim-params (when run {:area run})
        viewport-params (when run (with-bbox sim-params bbox))]
    (cond->
      {:runs (request :sim "/sim/layers" {})}
      (and city (seq level))
      (assoc :areas (request :store "/api/areas"
                             {:city (name city) :level level}))

      (= city :stuttgart)
      (assoc :cells (request :store "/api/cells" {:city "stuttgart"})
             ;; the 23 Stadtbezirke: the level the turnovers, the posterior and
             ;; the scenario deltas are reported at
             :districts (request :store "/api/areas" {:city "stuttgart" :level "stadtbezirk"}))

      area?
      (assoc :points (mapv #(point-request area year %)
                           (sort-by name (filter keyword? kinds)))
             :summary (request :store "/api/summary"
                               {:area (value-string area)})
             :resolved (request :store "/api/firms"
                                (cond-> {:area (value-string area)}
                                  year (assoc :year year))))

      entity?
      (assoc :entity (request :store
                              (str "/api/entity/" (value-string entity)) {}))

      run
      (assoc :meta (request :sim "/sim/meta" sim-params)
             :visits (request :sim "/sim/visits" viewport-params)
             :revenue (request :sim "/sim/revenue" viewport-params)
             :trips (request :sim "/sim/trips"
                             (cond-> viewport-params
                               (and (integer? stride) (pos? stride))
                               (assoc :stride stride)))
             :stops (request :sim "/sim/stops" viewport-params)
             :aggregates (request :sim "/sim/areas" sim-params)
             :econ (request :sim "/sim/econ" sim-params)
             :scenarios (request :sim "/sim/scenarios" sim-params))

      (and run scenario)
      (assoc :scenario (request :sim "/sim/scenario" (assoc sim-params :scenario (value-string scenario)))))))

(def ^:private static-files
  "The published export: one file per simulation response, whole city, no
   viewport filter. A request without an entry here is not part of the export."
  {"/sim/layers" "layers.json" "/sim/meta" "meta.json" "/sim/scenarios" "scenarios.json"
   "/sim/econ" "econ.json" "/sim/areas" "aggregates.json"
   "/sim/revenue" "revenue.json" "/sim/visits" "visits.json"
   "/sim/stops" "stops.json" "/sim/trips" "trips.json" "/api/cells" "cells.json"})

(defn static-path
  "The file of a static export that answers `request`, relative to the export's
   data directory, or nil when the export does not carry it (observed records,
   receipts, previews). Parameters that only filter the viewport are ignored:
   the export holds the whole city."
  [{:keys [path params]}]
  (cond
    (= path "/api/areas") (when-let [level (:level params)] (str "areas-" level ".json"))
    (= path "/sim/scenario") (when-let [k (:scenario params)] (str "scenario-" k ".json"))
    :else (get static-files path)))
