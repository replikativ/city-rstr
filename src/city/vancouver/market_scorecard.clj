(ns city.vancouver.market-scorecard
  "Inspect paired openings and a local grocery access reference at the REPL."
  (:require [city.calibration :as calibration]
            [city.vancouver.departures :refer [read-json]]
            [clojure.java.io :as io]))

(defn load-experiment [data-root release site]
  (let [report (read-json (io/file data-root "vancouver" "market" "sensitivity"
                                  (str site "-" release ".json")))]
    (when-not (and (= 1 (get report "schema")) (= release (get report "release"))
                   (= site (get-in report ["site" "id"])))
      (throw (ex-info "Storefront evidence belongs to a different weekday or site"
                      {:release release :site site})))
    report))

(defn scorecard [{:strs [access cases]}]
  (let [{:strs [observedAccess modeledAccess neighbourhood source comparable]} access]
    {:access (calibration/score
              {:id :nearby-grocer :role :held-out :unit :census-areas
               :population "Census representative points with comparable presence data"
               :geography neighbourhood :period "Can-FED 2024"
               :source source :compared comparable :reference [observedAccess]
               :cells ["At least one grocer within 1 km"]}
              [modeledAccess])
     :openings (mapv (fn [{:strs [minute recorded augmented]}]
                       {:activation minute :recorded (get recorded "visits")
                        :with-fitted (get augmented "visits") :diverted (get augmented "diverted")
                        :newly-feasible (get augmented "newlyFeasible")
                        :most-used-diary (get augmented "largestDiary")})
                     cases)}))
