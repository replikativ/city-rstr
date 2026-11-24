(ns city.vancouver.trip-demand
  "Count weekday diary bouts by the resident's home zone, primary mode and destination purpose."
  (:require [city.vancouver.roster :as roster]
            [city.vancouver.departures :refer [read-json]]
            [city.vancouver.survey-zones :refer [adult-fifths]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def visit-residents! roster/visit-private!)

(defn -main [atlas-dir day-dir input output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        {:strs [trips zone zones]} (read-json input)
        codes (mapv #(get % "code") zones)
        adults (volatile! {}) counts (java.util.HashMap.) examples (java.util.HashMap.) donors (java.util.HashMap.)]
    (visit-residents!
     atlas-dir day-dir atlas (day "das")
     (fn [da i person home plan]
       (let [w (adult-fifths (first person))]
         (when (pos? w)
           (let [z (get codes (get zone home -1) "unmapped")]
             (vswap! adults update z (fnil + 0) w)
             (doseq [[mode purpose minute a b visible?] (trips (peek person))]
               (let [k [z mode purpose]]
                 (.put counts k (+ w (or (.get counts k) 0)))
                 (when-not (.containsKey donors k) (.put donors k (java.util.BitSet.)))
                 (.set ^java.util.BitSet (.get donors k) (int (peek person)))
                 (when (and visible? (not (.containsKey examples k))
                            (<= 0 (get plan a -1)) (<= 0 (get plan b -1))
                            (not= (plan a) (plan b)))
                   (.put examples k [da i minute])))))))))
    (with-open [w (io/writer output)]
      (json/write {:adults @adults
                   :cells (mapv (fn [[k n]]
                                  (conj k n (.get examples k)
                                        (vec (.toArray (.stream ^java.util.BitSet (.get donors k)))))) (sort-by key counts))}
                  w))))
