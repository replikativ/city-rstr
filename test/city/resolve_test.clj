(ns city.resolve-test
  (:require [clojure.test :refer [deftest is]]
            [city.resolve :as r]))

(deftest name-similarity
  (is (= 1.0 (r/name-sim "Robert Bosch" "robert  bosch")))
  (is (= 1.0 (r/name-sim "Bosch Ltd." "Bosch")) "legal-form stop words are dropped")
  (is (>= (r/name-sim "Heart Breaker" "Heartbreaker") 0.85) "space-free forms are compared")
  (is (< (r/name-sim "Mercedes-Benz Werk" "Porsche Museum") 0.5))
  (is (= 0.0 (r/name-sim "" "Bosch"))))
