(ns city.build-inputs-test
  (:require [city.artifact :as artifact]
            [city.build-inputs :as inputs]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.test :refer [deftest is testing]])
  (:import [java.nio.file Files]
           [java.nio.file.attribute FileAttribute]))

(deftest pinned-build-and-source-audit
  (let [root (.toFile (Files/createTempDirectory "city-build-fixture-" (make-array FileAttribute 0)))
        release (apply str (repeat 64 "b"))
        run {:release release :city "vancouver" :coverage "region"}
        file! (fn [path body]
                (let [f (io/file root path)]
                  (io/make-parents f)
                  (spit f body)
                  [path (artifact/sha256-file f)]))]
    (try
      (let [[_ run-sha] (file! (str "runs/" release ".json") (json/write-str run))
            market (file! "vancouver/market/reviewed.json" "{\"variant\":\"reviewed\"}")
            evidence (file! "vancouver/counts.json" (json/write-str {:release release}))
            recipe {:city "vancouver" :coverage "region" :run-sha256 run-sha :sources ["commuters"] :files {:market market}
                    :evidence {:roads evidence}}
            check #(inputs/resolve-inputs root root run)
            fixtures {:source-register-sha256 (artifact/sha256-file "public/sources/weekday.json")
                      :builds {release recipe}}]
        (with-redefs-fn {#'inputs/recipes (delay fixtures)}
          (fn []
            (testing "the chosen artifact and run identity are stable"
              (file! "vancouver/market/current.json" "{\"variant\":\"changed\"}")
              (is (= (io/file root (first market)) (:market (check))))
              (is (= (io/file root (first evidence)) (get-in (check) [:evidence :roads])))
              (is (= (:market (check)) (:market (inputs/scenario-inputs root run))))
              (is (thrown-with-msg? clojure.lang.ExceptionInfo #"metadata differs"
                                    (inputs/resolve-inputs root root (assoc run :coverage "city")))))
            (testing "an explicit source audit requires the cited source bytes"
              (is (false? (:source-bytes-verified? (check))))
              (is (seq (get-in (check) [:sources "commuters" :archive-files])))
              (is (thrown-with-msg? clojure.lang.ExceptionInfo #"Missing weekday build input"
                                    (inputs/resolve-inputs root root run {:verify-sources? true}))))
            (testing "changes to the selected content fail before simulation"
              (spit (io/file root (first market)) "{}")
              (is (thrown-with-msg? clojure.lang.ExceptionInfo #"checksum differs" (check)))))))
      (finally (doseq [f (reverse (file-seq root))] (.delete f))))))
