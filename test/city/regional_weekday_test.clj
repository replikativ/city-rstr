(ns city.regional-weekday-test
  (:require [city.vancouver.weekday-presence :as presence]
            [city.vancouver.roster :as roster]
            [city.vancouver.diary-clock :as clock]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.test :refer [deftest is]]))

(defn- read-json [dir filename]
  (with-open [in (io/reader (io/file dir filename))]
    (json/read in :key-fn keyword)))

(deftest roster-scope-and-identity
  (let [tmp (.toFile (java.nio.file.Files/createTempDirectory
                      "city-roster-" (make-array java.nio.file.attribute.FileAttribute 0)))
        atlas-dir (io/file tmp "atlas")
        day-dir (io/file tmp "day")
        atlas {"das" {"z" {"population" 2 "private" 1} "a" {"population" 1 "private" 0}}}
        das ["z" "a"]
        seen (atom [])]
    (try
      (.mkdir atlas-dir)
      (.mkdir day-dir)
      (doseq [[da names] [["z" ["private" "collective"]] ["a" ["collective"]]]]
        (spit (io/file atlas-dir (str da ".json")) (json/write-str {:people names}))
        (spit (io/file day-dir (str da ".json"))
              (json/write-str {:home (vec (range (count names))) :plans (mapv vector names)})))
      (is (= [0 2] (roster/area-offsets das #(get-in atlas ["das" % "population"]))))
      (is (= [[0 "private" 0 ["private"]] [1 "collective" 1 ["collective"]]]
             (roster/residents atlas-dir day-dir "z" {:population 2})))
      (roster/visit-private! atlas-dir day-dir atlas das
                             (fn [da i person _ _] (swap! seen conj [da i person])))
      (is (= [["z" 0 "private"]] @seen))
      ;; A missing institutional row must not silently shift later area IDs.
      (spit (io/file atlas-dir "z.json") (json/write-str {:people ["private"]}))
      (is (thrown? clojure.lang.ExceptionInfo
                   (roster/residents atlas-dir day-dir "z" {:population 2})))
      ;; Older presence-only shards have plans but no home positions.
      (spit (io/file day-dir "a.json") (json/write-str {:plans [[5]]}))
      (is (= [[0 "collective" nil [5]]] (roster/residents atlas-dir day-dir "a" {})))
      (is (thrown? clojure.lang.ExceptionInfo
                   (roster/residents atlas-dir day-dir "a" {:require-homes? true})))
      (finally (doseq [f (reverse (file-seq tmp))] (.delete f))))))

(deftest weekday-uses-resolved-producer-inputs
  (let [tmp (.toFile (java.nio.file.Files/createTempDirectory
                      "city-pinned-roster-" (make-array java.nio.file.attribute.FileAttribute 0)))
        inputs (into {} (for [k [:day :roster :incoming-workers :incoming-transit :commuters :home-fit]]
                          [k (io/file tmp (name k))]))
        write! (fn [k id value]
                 (let [file (io/file (k inputs) (str id ".json"))]
                   (io/make-parents file)
                   (spit file (json/write-str value))))
        positions (atom [])
        spec {:root (io/file tmp "unused") :atlas "atlas-id" :day "day-id" :inbound 1
              :producer-inputs inputs :position-fn #(swap! positions conj %)}
        worker [0 0 0 0 0 480 30 480 1 0]]
    (try
      (write! :day "day" {:areas ["A"] :templates [{:parts [[240 1440 "stop" 0]]}] :population 1 :das ["da"]})
      (write! :day "places" [[0 0 0]])
      (write! :day "da" {:plans [[0]] :home [0]})
      (write! :roster "atlas" {:das {"da" {:population 1}}})
      (write! :roster "da" {:people [[0 0 0 0 0 0 0 0]]})
      (write! :incoming-workers "commuters" {:atlas "atlas-id" :groups {:g 1} :workSpans [[[0 480]]]})
      (write! :incoming-workers "g" {:homes ["outside"] :homePoints [[1000 1000]] :people [worker]})
      (let [weights (atom [])]
        ((:batches! (presence/prepare (assoc spec :regionalWorkers "workers-id"))) #(swap! weights into (vals %)))
        (is (= [1 1] @weights))
        (is (= 2 (count @positions))))
      (reset! positions [])
      (write! :incoming-transit "report" {:joint "joint-id" :workerRelease "workers-id" :homeFit {:version "fit-id"}})
      (write! :incoming-transit "homes" [[1000 1000 nil "area original"] [2000 2000 nil "area updated"]])
      (write! :commuters "commuters" {:groups {:g 1}})
      (write! :commuters "g" {:homes ["original" "updated"] :people [worker]})
      (write! :home-fit "g" [[0 0 1]])
      ((:batches! (presence/prepare (assoc spec :jointRun "joint-id" :incomingTransit "transit-id"))) identity)
      (is (= 2 (count @positions)))
      (is (= [0 (- (/ 2000 72600.0) 123.1) (- 49.26 (/ 2000 111195.0))] (first (last @positions))))
      (finally (doseq [f (reverse (file-seq tmp))] (.delete f))))))

(deftest diary-clock-resolution
  (let [phases (map clock/phase (range clock/period))]
    ;; Published floats are observable in content-addressed trajectory and grocery files.
    (is (= 1.4569801139202556 (clock/phase 0) (clock/phase clock/period)))
    (is (= -1.6728290196862197 (clock/phase 3)))
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
