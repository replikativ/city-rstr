(ns city.sim.occupancy-test
  (:require [city.sim.occupancy :as occupancy]
            [clojure.test :refer [deftest is]]))

(deftest exact-weighted-occupancy
  ;; One two-part itinerary and one single-part itinerary. The second part
  ;; moves to the other zone at 50%, while the single-part group stays put.
  (let [offsets (int-array [0 2 3]), starts (int-array [0 4 1]), ends (int-array [4 8 9])
        ranks (int-array [50 101]), shifts (int-array [0 1 0])
        run (fn [ids weights level]
              (let [out (int-array 10)]
                (dotimes [step 2]
                  (occupancy/interval-changes! (int-array ids) (int-array weights) offsets
                                               starts ends shifts ranks out (int-array [level step]) (count ids)))
                (vec out)))]
    (is (= [6 17 0 0 0 0 0 0 -6 -17] (run [0 1] [6 17] 0)))
    (is (= [6 17 0 0 -6 6 0 0 0 -23]
           (run [0 1] [6 17] 50)
           (run (concat (repeat 6 0) (repeat 17 1)) (repeat 23 1) 50)))))
