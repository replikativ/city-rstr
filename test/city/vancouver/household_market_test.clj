(ns city.vancouver.household-market-test
  (:require [city.vancouver.household-market :as market]
            [clojure.test :refer [deftest is]]))

(deftest catchment-boundaries-and-incumbent-ties
  (let [ids (int-array (range 5))
        counts (int-array 18)]
    ;; Equal incumbent distance, closer incumbent, strictly closer candidate,
    ;; a newly reachable household on the boundary, and one outside it.
    (market/reach! ids (int-array [2 3 4 5 6]) (int-array [0 0 0 1 1])
                   (int-array [200 200 200 400 401])
                   (int-array [200 199 400 401 402])
                   (int-array [400]) counts 5)
    (is (= [9 5 0 0 0 0, 4 0 0 0 0 0, 0 5 0 0 0 0] (vec counts)))))
