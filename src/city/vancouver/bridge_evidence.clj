(ns city.vancouver.bridge-evidence
  "Census workplace flows and diary trip categories for the regional bridge check."
  (:require [city.commute :as commute]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]))

(def ^:private city ["5915022" "Vancouver (CY), B.C."])
(def ^:private vancouver "City of Vancouver")
(def ^:private eastern #{"Burnaby" "New Westminster"})
(def ^:private north
  [["5915051" "North Vancouver (CY), B.C." "City of North Vancouver"]
   ["5915046" "North Vancouver (DM), B.C." "District of North Vancouver"]
   ["5915055" "West Vancouver (DM), B.C." "West Vancouver"]])

(defn- read-json [path]
  (with-open [reader (io/reader path)] (json/read reader)))

(defn- read-flows [path]
  (let [total (with-open [reader (io/reader path)]
                (into {} (map (fn [line]
                                (let [{:strs [DGUID work total]} (json/read-str line)]
                                  [[(subs DGUID 9) work] total])))
                      (line-seq reader)))]
    (mapv (fn [[csd workplace name]]
            (let [[city-csd city-work] city
                  incoming (total [csd city-work])
                  outgoing (total [city-csd workplace])]
              (when-not (and (pos-int? incoming) (pos-int? outgoing))
                (throw (ex-info "Missing census flows in both directions" {:municipality name})))
              {:municipality name :towardVancouver incoming :fromVancouver outgoing}))
          north)))

(defn- direct-legs [{:strs [parts slots] :as template} diary]
  (let [paid (commute/paid-slots template diary)]
    (keep (fn [[_ _ _ i :as part]]
            (when (commute/direct-commute? slots paid part)
              [part (if (= "home" (get slots i)) 1 2)]))
          parts)))

(defn- work-destinations [atlas-dir day-dir das home-areas place-areas outward]
  (reduce (fn [totals da]
            (let [people ((read-json (io/file atlas-dir (str da ".json"))) "people")
                  plans ((read-json (io/file day-dir (str da ".json"))) "plans")
                  home (home-areas da)]
              (when-not (= (count people) (count plans))
                (throw (ex-info "Incomplete regional weekday plans" {:da da})))
              (reduce (fn [counts [[_ _ labour _ _ _ _ template] plan]]
                        (if (= 1 labour)
                          (if-let [[destination mode]
                                   (some (fn [[_ _ mode _ slot]]
                                           (when-let [area (get place-areas (get plan slot))]
                                             [area mode]))
                                         (outward template))]
                            (update counts [home destination mode] (fnil inc 0))
                            counts)
                          counts))
                      totals (map vector people plans))))
          {} das))

(defn- weekday-flows [stock destinations]
  (let [total (reduce-kv (fn [counts [home work _] n]
                           (update counts [home work] (fnil + 0) n))
                         {} destinations)]
    (mapv (fn [{:keys [municipality] :as row}]
            (assoc row
                   :weekdayTowardVancouver (get total [municipality vancouver] 0)
                   :weekdayFromVancouver (get total [vancouver municipality] 0)
                   :weekdayDriversTowardVancouver (get destinations [municipality vancouver "car-driver"] 0)
                   :weekdayDriversFromVancouver (get destinations [vancouver municipality "car-driver"] 0)))
          stock)))

(defn -main [atlas-dir day-dir flows output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        north-names (set (map last north))
        area-name (fn [name] (cond (or (north-names name) (eastern name) (str/starts-with? name "UBC ")) name
                                   :else vancouver))
        home-areas (into {} (mapcat (fn [[name data]]
                                     (map (fn [da] [da (area-name name)]) (get data "das"))))
                         (atlas "areas"))
        group-code (fn [name] (cond (= name vancouver) 0 (north-names name) 1 :else 2))
        homes (mapv home-areas (day "das"))
        templates (day "templates")
        diaries (atlas "templates")]
    (when (or (some nil? homes) (not= (count templates) (count diaries)))
      (throw (ex-info "Bridge evidence and regional weekday releases differ" {})))
    (let [legs (mapv direct-legs templates diaries)
          outward (mapv #(keep (fn [[part purpose]] (when (= 1 purpose) part)) %) legs)
          areas (mapv area-name (day "areas"))
          places (mapv (fn [[_ _ i]] (get areas i)) (read-json (io/file day-dir "places.json")))
          destinations (work-destinations atlas-dir day-dir (day "das") home-areas places outward)]
      (with-open [writer (io/writer output)]
        (json/write {:homeGroups ["Vancouver" "North Shore" "UBC"]
                     :homeCodes (mapv group-code homes)
                     :purposes ["Other travel" "Home to paid work" "Paid work to home"]
                     :templates (mapv #(mapv (fn [[[start] purpose]] [(- start 240) purpose]) %) legs)
                     :workFlows (weekday-flows (read-flows flows) destinations)
                     :widerDestinations (boolean (some eastern areas))}
                    writer)))))
