(ns city.vancouver.north-shore-demand
  "Count trips and assigned crossings for North Shore residents aged 15+."
  (:require [city.commute :as commute]
            [city.vancouver.departures :refer [read-json]]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util HashMap]))

(defn- add! [^HashMap counts key]
  (.put counts key (inc (long (or (.get counts key) 0)))))

(defn- count-workplace! [^HashMap counts ^HashMap examples
                         {:strs [daZones placeZones placeFlags workplaceGroups]}
                         arrivals da i home plan labour]
  (let [mapped (get placeZones home 0)
        zone (if (pos? mapped) mapped (daZones da))]
    (add! counts ["Zones" "zonePopulation" zone])
    (when (get placeFlags home false)
      (add! counts ["Zones" "zoneBoundary" zone]))
    (when (zero? mapped)
      (add! counts ["Zones" "zoneFallback" zone]))
    (when (= 1 labour)
      (when-let [[start job] (some (fn [[start _ _ _ slot]]
                                    (let [site (get plan slot -1)]
                                      (when (<= 0 site) [start site])))
                                  arrivals)]
        (let [key ["Zones" "zoneWork" [zone (workplaceGroups job)]]]
          (add! counts key)
          (.putIfAbsent examples key [da i start]))))))

(defn -main [atlas-dir day-dir input output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        {:strs [municipalities trips gaps geography zones]} (read-json input)
        arrivals (when zones (mapv (fn [template diary]
                                     (vec (commute/home-work-arrivals template (commute/paid-slots template diary))))
                                   (day "templates") (atlas "templates")))
        home-groups (into {} (for [name municipalities da (get-in atlas ["areas" name "das"])] [da name]))
        counts (HashMap.)
        examples (HashMap.)]
    (visit-residents!
     atlas-dir day-dir atlas (filter #(contains? home-groups %) (day "das"))
     (fn [da i [age _ labour _ _ _ _ template] home-place plan]
       (when (<= 3 age 13)
         (let [home (home-groups da)
               bouts (trips template)]
           (when zones
             (count-workplace! counts examples zones (arrivals template) da i home-place plan labour))
           (add! counts [home "population" "Residents"])
           (when (seq bouts) (add! counts [home "population" "With recorded travel"]))
           (doseq [[a b] (gaps template)
                   :let [a (get plan a -1) b (get plan b -1)]
                   :when (and (<= 0 a) (<= 0 b) (not= a b))]
             (add! counts [home "coverage" "Unrecorded change of place"]))
           (doseq [[mode purpose hour minute a b visible?] bouts]
             (let [a (get plan a -1) b (get plan b -1)
                   origin (get geography a) destination (get geography b)
                   located (and origin destination (not= a b))
                   keys [[home "modes" mode] [home "purposes" purpose] [home "hours" hour]]
                   coverage (cond (not (and origin destination)) "Missing endpoint"
                                  (= a b) "Same assigned place"
                                  :else "Distinct assigned places")]
               (add! counts [home "coverage" coverage])
               (add! counts [home "purposeMode" [purpose mode]])
               (doseq [key keys]
                 (add! counts key)
                 (when (and located visible?) (.putIfAbsent examples key [da i minute])))
               (when (and (= origin "North Shore")
                          (contains? #{"Downtown or West End" "Rest of Vancouver or UBC" "Burnaby and New Westminster"} destination))
                 (let [key [home "outbound" destination]]
                   (add! counts key)
                   (add! counts [home "outboundMode" [destination mode]])
                   (when (and located visible?) (.putIfAbsent examples key [da i minute]))))))))))
    (with-open [w (io/writer output)]
      (json/write (mapv (fn [[key count]] (conj key count (.get examples key))) (sort-by key counts)) w))))
