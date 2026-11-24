(ns city.vancouver.hired-rides
  "Extract passenger trips on the published weekday for a paired hired-ride replay."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.survey-zones :refer [adult-fifths]]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util ArrayList]))

(def hired-modes #{"taxi" "ridehail"})

(defn candidates [atlas-dir day-dir das trips]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        indexes (zipmap (day "das") (range))
        rows (ArrayList.)
        main (volatile! {:residents 0 :trips 0 :taxi 0 :ridehail 0})]
    (when-not (and (every? indexes das)
                   (= (count trips) (count (day "templates")) (count (atlas "templates"))))
      (throw (ex-info "Hired-ride inputs and weekday differ" {})))
    (visit-residents!
     atlas-dir day-dir atlas das
     (fn [da i [age :as person] _ plan]
       (let [weight (adult-fifths age)
             legs (trips (peek person))]
         (when (pos? weight)
           (vswap! main update :residents + weight)
           (vswap! main update :trips + (* weight (count legs)))
           (doseq [[start duration primary display from-slot to-slot pure?] legs]
             (when (hired-modes primary)
               (vswap! main update (keyword primary) + weight))
             (when (and pure? (= primary display)
                        (or (hired-modes primary) (and (= weight 5) (= primary "car-passenger"))))
               (let [a (get plan from-slot -1) b (get plan to-slot -1)]
                 (when (and (<= 0 a) (<= 0 b) (not= a b))
                   (.add rows [(indexes da) i start duration a b primary])))))))))
    {:fifths @main :candidates (vec rows)}))

(defn -main [atlas-dir day-dir input output]
  (let [{:strs [das trips]} (read-json input)]
    (with-open [w (io/writer output)]
      (json/write (candidates atlas-dir day-dir das trips) w))))
