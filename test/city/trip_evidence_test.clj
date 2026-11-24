(ns city.trip-evidence-test
  (:require [city.experiment :as experiment]
            [city.trip-evidence :as evidence]
            [clojure.test :refer [deftest is]]
            [datahike.api :as d]))

(deftest release-cells-share-resident-identities-and-keep-donor-support
  (let [config {:store {:backend :memory :id (random-uuid)} :value-caps :default
                :initial-tx experiment/schema :schema-flexibility :write}
        cells [["360" "Cycling" "Shopping" 37 ["DA1" 7 505] [1 5]]
               ["360" "Transit" "Recreation" 12 nil [9]]]
        source {"city" "vancouver" "atlas" "a" "day" "d" "source" "survey" "cells" cells}
        id (evidence/release-id "vancouver" "a" "d" "v")
        other (evidence/release-id "stuttgart" "a" "d" "v")
        _ (d/create-database config) conn (d/connect config)]
    (try
      (is (false? (evidence/present? @conn id)))
      (doseq [[key report] [[id source] [id source] [other (assoc source "city" "stuttgart" "cells" [(second cells)])]]]
        (d/transact conn (evidence/transaction key report)))
      (is (evidence/present? @conn id))
      (is (= cells (evidence/cells @conn id)))
      (is (= [(second cells)] (evidence/cells @conn other)))
      (is (empty? (experiment/openings @conn "vancouver")))
      (finally (d/release conn) (d/delete-database config)))))
