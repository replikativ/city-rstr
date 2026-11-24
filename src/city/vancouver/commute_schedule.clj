(ns city.vancouver.commute-schedule
  "Count the first direct paid work trips once per eligible resident."
  (:require [city.vancouver.departures :as dep]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]))

(def ^:private modes
  {"car-driver" 1 "car-passenger" 2 "transit" 3 "walk" 4 "bike" 5})

(defn- duration-band [minutes]
  (inc (min 4 (quot minutes 15))))

(defn- home-municipality [north area]
  (cond (nil? area) nil
        (north area) area
        (str/starts-with? area "UBC ") "UBC"
        :else "Vancouver"))

(defn- opposite-shore? [north home work]
  (and work
       (if (north home)
         (#{"Vancouver" "UBC"} work)
         (north work))))

(defn- record-trip [totals home north work {:keys [mode minute duration]}]
  (let [band (inc (dep/profile-band minute))
        length (duration-band duration)
        trip-mode (get modes mode 6)
        cohorts (cond-> [:direct] (opposite-shore? north home work) (conj :across))]
    (reduce (fn [counts group]
              (update counts [home group trip-mode band length] (fnil inc 0)))
            totals cohorts)))

(defn- tally [atlas-dir day-dir atlas day north]
  (let [tours (mapv dep/timed-tour (day "templates") (atlas "templates"))
        municipality (partial home-municipality north)
        das (into {} (for [[area detail] (atlas "areas"), id (detail "das")] [id (municipality area)]))
        places (mapv (fn [[_ _ i]] (municipality (get (day "areas") i)))
                     (dep/read-json (io/file day-dir "places.json")))]
    (reduce (fn [counts da]
              (let [home (das da)]
                (if (= "UBC" home)
                  counts
                  (let [file (str da ".json")
                        people ((dep/read-json (io/file atlas-dir file)) "people")
                        plans ((dep/read-json (io/file day-dir file)) "plans")
                        private (get-in atlas ["das" da "private"])]
                    (when-not (and home (= (count people) (count plans)) (<= private (count people)))
                      (throw (ex-info "Commute schedule and regional roster disagree" {:da da})))
                    (reduce (fn [counts [person plan]]
                              (let [tour (get tours (get person 7))]
                                (if (and (= :direct (:kind tour)) (dep/usual-commuter? person))
                                  (record-trip counts home north (get places (get plan (:to tour))) tour)
                                  counts)))
                            counts (map vector (take private people) plans))))))
            {} (day "das"))))

(defn- marginals [frequencies]
  (reduce-kv
    (fn [cube [home group mode time duration] n]
      (reduce (fn [result cell] (update result cell (fnil + 0) n))
              cube (for [m [0 mode], t [0 time], d [0 duration]] [home group m t d])))
    {} frequencies))

(defn- cube [totals homes group]
  (mapv (fn [m]
          (mapv (fn [t]
                  (mapv (fn [d] (reduce + (map #(get totals [% group m t d] 0) homes)))
                        (range 6)))
                (range 7)))
        (range 7)))

(defn -main [atlas-dir day-dir census-file output]
  (let [atlas (dep/read-json (io/file atlas-dir "atlas.json"))
        day (dep/read-json (io/file day-dir "day.json"))
        reference (dep/read-json census-file)
        areas (keys (reference "census"))
        north (set (remove #{"Vancouver" "North Shore"} areas))]
    (when-not (and (= 3 (count north))
                   (every? (set (day "areas")) north)
                   (= (count (day "templates")) (count (atlas "templates")))
                   (= (set (day "das")) (set (keys (atlas "das")))))
      (throw (ex-info "Census commute reference and regional weekday differ" {})))
    (let [totals (marginals (tally atlas-dir day-dir atlas day north))
          model (into (sorted-map)
                      (for [area areas
                            :let [homes (if (= area "North Shore") north [area])]]
                        [area {:direct (cube totals homes :direct) :across (cube totals homes :across)}]))]
      (with-open [writer (io/writer output)]
        (json/write (assoc reference "atlas" (.getName (io/file atlas-dir))
                           "day" (.getName (io/file day-dir)) "model" model)
                    writer)))))
