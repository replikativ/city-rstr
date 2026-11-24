(ns city.vancouver.street-walks-test
  (:require [city.vancouver.street-walks :refer [indexed-parts]]
            [clojure.test :refer [deftest is]]))

(deftest complete-hour-coverage-with-mixed-bouts-reserved-for-mode-changes
  (let [t {"slots" ["home" "job"]
           "parts" [[270 10 "stop" 0 0] [280 20 "walk" 0 1] [300 45 "stop" 1 1]
                    [345 25 "walk" 1 0] [370 20 "stop" 0 0]]}
        d {"episodes" [[270 10 "sleep" "home"] [280 15 "travel" "walk"] [295 5 "travel" "transit"]
                       [300 45 "paid-work" "job"] [345 25 "travel" "walk"] [370 20 "meal" "home"]]}]
    (is (= [[:walk 3 1 0 [5 6]]] (indexed-parts t d false)))
    (is (= [[:commute 1 0 1 [4]] [:walk 3 1 0 [5 6]]] (indexed-parts t d true)))))

(deftest bike-and-rail-commute-stays-separate-from-a-pure-bicycle-trip
  (let [template {"slots" ["home" "job"]
                  "parts" [[465 10 "stop" 0 0] [475 15 "bike" 0 1] [490 30 "stop" 1 1]
                           [520 20 "bike" 1 0] [540 10 "stop" 0 0]]}
        diary {"episodes" [[465 10 "meal" "home"] [475 15 "travel" "bike"] [490 30 "paid-work" "job"]
                           [520 5 "travel" "bike"] [525 15 "travel" "transit"] [540 10 "meal" "home"]]}]
    (is (= [[:bike 1 0 1 [7 8]]] (indexed-parts template diary false)))
    (is (= [[:bike 1 0 1 [7 8]] [:commute 3 1 0 [8]]] (indexed-parts template diary true)))))

(deftest driver-index-preserves-census-replacements
  (let [template {"slots" ["home" "job"]
                  "parts" [[470 10 "stop" 0 0] [480 15 "car-driver" 0 1] [495 520 "stop" 1 1]
                           [1015 10 "car-passenger" 1 0] [1025 25 "stop" 0 0]]}
        diary {"episodes" [[470 10 "meal" "home"] [480 15 "travel" "car-driver"]
                           [495 520 "paid-work" "work-or-school"] [1015 10 "travel" "car-passenger"]
                           [1025 25 "meal" "home"]]}]
    (is (= [[:car 1 0 1 [8]]] (indexed-parts template diary false)))
    (is (= [[:car 1 0 1 [8]] [:commute 1 0 1 [8]] [:commute 3 1 0 [16 17]]]
           (indexed-parts template diary true)))))
