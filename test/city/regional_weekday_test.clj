(ns city.regional-weekday-test
  (:require [city.vancouver.diary-clock :as clock]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.test :refer [deftest is]]))

(defn- read-json [dir filename]
  (with-open [in (io/reader (io/file dir filename))]
    (json/read in :key-fn keyword)))

(deftest diary-clock-resolution
  (let [phases (map clock/phase (range 10007))]
    (is (= 10007 (count (distinct phases))))
    (is (every? #(< -2.5 % 2.5) phases))
    (is (= 0 (clock/day-boundary 0 2)))
    (is (= 1440 (clock/day-boundary 1440 -2)))
    (is (= 600 (- (clock/day-boundary 690 -2) (clock/day-boundary 90 -2))))))

(deftest ^:data regional-weekday-balance
  (let [data (io/file "public/data")
        region (io/file data "vancouver/region")
        run (first (filter :regionalWorkers (read-json data "runs/current.json")))
        overview (io/file data "overview")
        pointer (read-json overview (str (:release run) ".json"))
        scene (read-json overview (str (:scene pointer) ".json"))
        day (read-json (io/file region "cityday" (:day run)) "day.json")
        workers (io/file region "incoming-workers" (:regionalWorkers run))
        reference (:counts (read-json workers "presence.json"))
        downtown (.indexOf (:areas scene) "Downtown")
        travelling (.indexOf (:areas scene) "travelling")
        places (read-json (io/file region "cityday" (:day run)) "places.json")
        ;; A uniform shift preserves the integrated time in every internal
        ;; interval. Pinning the first and last resident boundaries changes
        ;; just those intervals by +shift and -shift respectively.
        ordinal (volatile! -1)
        adjustments
        (reduce
         (fn [totals da]
           (let [people (:people (read-json (io/file region "atlas" (:atlas run)) (str da ".json")))
                 plans (:plans (read-json (io/file region "cityday" (:day run)) (str da ".json")))]
             (reduce (fn [totals [person plan]]
                       (let [shift (clock/minute-offset (vswap! ordinal inc))
                             parts (:parts (nth (:templates day) (nth person 7)))
                             area (fn [[_ _ kind slot]]
                                    (if (= kind "stop")
                                      (let [place (nth plan slot)]
                                        (if (neg? place) (inc travelling) (nth (nth places place) 2)))
                                      travelling))]
                         (-> totals (update (area (first parts)) (fnil + 0) shift)
                             (update (area (last parts)) (fnil - 0) shift))))
                     totals (map vector people plans))))
         {} (:das day))]
    (is (= 1440 (count (:presence scene)) (count reference)))
    (is (= (:population scene) (+ (:population run) (:inbound run))))
    (is (every? #(= (:population scene) (reduce + %)) (:presence scene)))
    (doseq [area [downtown travelling]]
      (let [residents (reduce + (map #(nth % area) (:occupancy day)))
            external (reduce + (for [cohort reference pair cohort]
                                 (if (= area downtown) (get-in pair [1 1])
                                     (reduce + (for [[out _ back] pair] (+ out back))))))]
        (is (= (+ residents external (get adjustments area 0))
               (reduce + (map #(nth % area) (:presence scene)))))))))
