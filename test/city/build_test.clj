(ns city.build-test
  (:require [city.artifact :as artifact]
            [city.build :as build]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.test :refer [deftest is]])
  (:import [java.nio.file Files]
           [java.nio.file.attribute FileAttribute]))

(deftest publishing-checks-all-shards-before-replacing-an-index
  (let [stage (.toFile (Files/createTempDirectory "weekday-build" (make-array FileAttribute 0)))
        out (io/file stage "overview")
        dest (io/file stage "installed")
        release (apply str (repeat 64 "a"))
        hash (artifact/sha256 (.getBytes "sample" "UTF-8"))
        ptr (str release ".json")
        index (fn [name fields]
                (spit (io/file out name) (json/write-str (assoc fields :release release))))]
    (try
      (.mkdirs out)
      (.mkdirs dest)
      (index ptr {:scene hash :agents hash :schedules hash})
      (index (str release "-cases.json") {:cases hash})
      (index (str release "-traces.json") {:hours (vec (repeat 24 hash)) :roads hash})
      (spit (io/file out (str hash ".gz")) "sample")
      (spit (io/file out (str hash ".json")) "corrupt")
      (spit (io/file dest ptr) "previous")
      (is (thrown-with-msg? clojure.lang.ExceptionInfo #"Corrupt weekday shard"
                            (#'build/install! stage dest release nil)))
      (is (= "previous" (slurp (io/file dest ptr))))
      (spit (io/file out (str hash ".json")) "sample")
      (is (= {:files 5 :release release} (#'build/install! stage dest release nil)))
      (is (= hash (:scene (json/read-str (slurp (io/file dest ptr)) :key-fn keyword))))
      (finally (doseq [file (reverse (file-seq stage))] (.delete file))))))

(deftest build-uses-selected-run-and-its-resolved-inputs
  (let [root (.toFile (Files/createTempDirectory "weekday-entry" (make-array FileAttribute 0)))
        release (apply str (repeat 64 "b"))
        run {:release release :city "vancouver" :coverage "region"}
        inputs {:route-cache "fixture"}
        written (atom [])
        emit (fn [stage selected resolved]
               (is (= run selected))
               (is (= inputs resolved))
               (swap! written conj stage))]
    (try
      (let [catalog (io/file root "runs/current.json")]
        (io/make-parents catalog)
        (.mkdir (io/file root "vancouver"))
        (spit catalog (json/write-str [run]))
        (spit (io/file root "runs" (str release ".json")) (json/write-str run))
        (with-redefs-fn {(requiring-resolve 'city.build-inputs/resolve-inputs) (fn [_ _ _ _] inputs)
                         (requiring-resolve 'city.overview/publish-day!) emit
                         (requiring-resolve 'city.trajectory/publish!) emit
                         #'build/install! (fn [stage _ id _]
                                            (is (= [stage stage] @written))
                                            {:release id})}
          #(is (= [{:release release}] (build/build! {:data root :city :vancouver})))))
      (finally (doseq [file (reverse (file-seq root))] (.delete file))))))
