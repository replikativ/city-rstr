(ns city.weekday-test
  (:require [city.experiment :as experiment]
            [city.sim.weekday :as engine]
            [city.sim.schedule-pack :as pack]
            [city.weekday :as weekday]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.test :refer [deftest is]]
            [datahike.api :as d]))

(deftest prepared-releases-survive-storage-shutdown
  (let [cfg {:store {:backend :memory :id (random-uuid)} :value-caps :default
             :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database cfg)
        conn (d/connect cfg)
        day {:city "fixture" :release "one" :coverage "city" :label "Tiny city"
             :model-notes (apply str (repeat 5000 "x"))
             :areas ["home" "work"] :population 3 :day-start 0
             :schedules {[[480 0] [1020 1] [1440 0]] 2 [[1440 0]] 1}}
        other (assoc day :release "two" :schedules {[[1440 1]] 3})
        [a b] (try
                ;; A release indexed by an older browser has no manifest yet.
                (d/transact conn [{:entity/ext-id "weekday/fixture/one" :run/city "fixture"}])
                (d/transact conn (experiment/register-runs @conn [day other]))
                (is (empty? (experiment/register-runs @conn [day other])))
                (is (thrown? Exception (experiment/register-runs @conn [(assoc day :population 4)])))
                (mapv #(weekday/prepare (experiment/release-manifest @conn "fixture" %)) ["one" "two"])
                (finally (d/release conn) (d/delete-database cfg)))
        result (:presence (weekday/execute a :jvm))]
    (is (= [[3 0] [1 2] [1 2] [3 0]] (mapv result [479 480 1019 1020])))
    (is (= result (:presence (weekday/execute a :jvm))))
    (is (= (repeat 1440 [0 3]) (:presence (weekday/execute b :jvm))))))

(deftest weighted-trip-ends-share-the-presence-clock
  (let [result (weekday/run {:city :fixture :population 2 :areas ["home" "work" :travelling]
                             :day-start 240 :products #{:presence :trip-ends}
                             :schedules {[[55 0] [65 2] [70 1] [1440 1]] 2}})
        {:keys [arrivals departures]} (:trip-ends result)]
    (is (= [2 0 0] (departures 0)))
    (is (= [0 2 0] (arrivals 1)))
    (is (= 2 (reduce + (mapcat identity arrivals)) (reduce + (mapcat identity departures))))
    (is (= [0 0 2] (get-in result [:presence 55])))
    (is (= [0 2 0] (get-in result [:presence 65])))))


(deftest shared-schedules-cross-census-shards
  (let [path [[480 0] [1440 1]]
        source {:areas ["home" "work"] :population 9 :connection (Object.)
                :batches! (fn [submit!] (submit! {path 4}) (submit! {path 5}))}
        prepared (engine/prepare-batches source)]
    (is (not-any? #(contains? prepared %) [:connection :batches!]))
    (is (= [[9]] (mapv (comp vec :weights) (:batches prepared))))
    (is (= [0 9] (get-in (engine/execute prepared :jvm) [:presence 480])))
    (is (thrown? Exception
                 (engine/prepare-batches
                  (assoc source :batches! (fn [submit!] (submit! {path -1}) (submit! {path 10}))))))))

(deftest portable-day-retains-weighted-origin-destination-pairs
  (let [day (weekday/prepare {:city :fixture :areas ["home" "work" :travelling]
                              :population 7 :day-start 240
                              :schedules {[[55 0] [58 2] [65 2] [1440 1]] 6
                                          [[10 2] [1430 1] [1440 2]] 1}})
        file (java.io.File/createTempFile "weekday-test-" ".gz")]
    (try
      (pack/write-pack! file day)
      (let [products #{:presence :trip-ends :od-flows}
            out (weekday/run {:schedule-pack file :products products})]
        (is (= (weekday/execute day :jvm products) out))
        (is (= [[0 1 0 1 6]] (:od-flows out))))
      (finally (.delete file)))))

(deftest packed-release-is-checked-before-execution
  (let [root (.toFile (java.nio.file.Files/createTempDirectory "city-release-" (make-array java.nio.file.attribute.FileAttribute 0)))
        dir (io/file root "overview")
        release (apply str (repeat 64 "a"))
        pointer (io/file dir (str release ".json"))
        file (io/file dir "day.gz")
        prepared (weekday/prepare {:city :fixture :release release :population 1
                                   :areas ["home"] :day-start 0 :schedules {[[1440 0]] 1}})]
    (try
      (.mkdir dir)
      (pack/write-pack! file prepared)
      (let [bytes (java.nio.file.Files/readAllBytes (.toPath file))
            hash (.formatHex (java.util.HexFormat/of) (.digest (java.security.MessageDigest/getInstance "SHA-256") bytes))
            other (apply str (repeat 64 "b"))]
        (doseq [digest [hash other]]
          (io/copy file (io/file dir (str digest ".gz")))
          (spit pointer (json/write-str {:release release :schedules digest}))
          (if (= hash digest)
            (is (= 1 (:population (weekday/prepare-release root release))))
            (is (thrown-with-msg? Exception #"checksum" (weekday/prepare-release root release))))))
      (finally (doseq [f (reverse (file-seq root))] (.delete f))))))
