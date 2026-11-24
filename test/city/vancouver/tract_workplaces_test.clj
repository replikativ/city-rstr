(ns city.vancouver.tract-workplaces-test
  (:require [clojure.test :refer [deftest is]]
            [city.vancouver.tract-workplaces :as tracts]))

(deftest journeys-on-either-side-of-work
  (let [template {"parts" [[240 120 "stop" 0 0] [360 20 "car-driver" 0 1]
                           [380 240 "stop" 1 1] [620 10 "walk" 1 2]
                           [630 60 "stop" 2 2] [690 20 "transit" 2 0]
                           [710 970 "stop" 0 0]]}
        constraints (tracts/trip-constraints template #{1} #{360})]
    (is (= [[0 20 "car-driver" true] [2 10 "walk" false]] (:trips constraints)))
    (is (= [[0 20 "car-driver" true 360 false] [2 10 "walk" false 620 true]] (:timed-trips constraints)))
    (is (not (:untimed constraints)))))

(deftest workday-with-an-unrecorded-change-of-place
  (let [template {"parts" [[240 100 "stop" 0 0] [340 1340 "stop" 1 1]]}]
    (is (:untimed (tracts/trip-constraints template #{0} #{})))))
