(ns city.vancouver.outbound-test
  (:require [city.vancouver.outbound :as outbound]
            [clojure.test :refer [deftest is testing]]))

(deftest capacity-constrained-local-margins
  (is (= [2 6 2] (outbound/bounded-counts [20 3 1] [2 8 8] 10)))
  (is (= [1 1 1] (outbound/bounded-counts [1 0 0] [1 2 1] 3)))
  (is (= [0 0] (outbound/bounded-counts [0 0] [0 0] 0)))
  (is (thrown? clojure.lang.ExceptionInfo (outbound/bounded-counts [1 1] [1 1] 3))))

(deftest municipal-controls-preserve-resident-identity
  (let [input {"seed" 3 "candidates" [[[0 1 5] [1 1 4] [3 2 6]] [[3 2 5] [8 1 5]]]
               "local" [[5 1] [nil 0]]
               "destinations" [{"total" 2 "women" 1 "men" 1} {"total" 1 "women" 1 "men" 0}]}
        {:keys [eligible assignments stock women]} (outbound/assign input)]
    (is (= [2 1] stock))
    (is (= [1 1] women))
    (is (= 5 eligible))
    (is (= [0 1 3] (mapv first (first assignments))))
    (is (empty? (second assignments)))))

(deftest paired-geography-of-work-stops
  (let [template {"slots" ["home" "job" "job" "school" "job"]
                  "parts" [[240 20 "stop" 0 0] [260 30 "walk" 0 1]
                           [290 200 "stop" 1 1] [490 10 "walk" 1 2]
                           [500 920 "stop" 2 2] [1420 30 "transit" 2 3]
                           [1450 30 "stop" 3 3] [1480 10 "walk" 3 4] [1490 190 "stop" 4 4]]}
        diary {"episodes" [[300 50 "paid-work"] [560 60 "paid-work"] [1460 20 "paid-work"] [1500 60 "eating"]]}
        slots (outbound/paid-slots template diary)
        result (outbound/events template slots [0 1 -1 1 0] [0 1] 1 2 {"walk" 6 "transit" 5 "other" 7})]
    (is (= #{1 2} slots))
    (is (= 6 (:commute result)))
    (testing "only bounded Downtown crossings change, using the endpoint-specific clock"
      (is (= [[4 0 6 -1] [0 0 5 1]] (:flows result))))
    (testing "external paid work has an overnight diary clock and retains the break"
      (is (= [[50 250 1] [260 1180 2]] (:intervals result))))))

(deftest direct-workplace-modes
  (let [template {"slots" ["home" "job" "school" "job"]
                  "parts" [[400 30 "walk" 0 1] [430 45 "stop" 1 1] [475 10 "walk" 1 2]
                           [485 15 "transit" 2 3] [500 20 "bike" 3 0] [520 15 "walk" -1 1]
                           [535 5 "walk" 1 3]]}
        result (outbound/events template #{1 3} [0 1 2 1] [1 1 0] 1 2
                                {"walk" 6 "transit" 5 "bike" 4 "other" 7})]
    (is (= [[400 30 6 1] [500 20 4 0]] (:direct result)))
    (is (= 6 (:commute result)))
    (is (= [[6 1 6 -1] [6 1 5 1]] (outbound/usual-flow-changes (first (:direct result)) 5)))
    (is (= [[0 0 4 -1] [0 0 5 1]] (outbound/usual-flow-changes [1435 20 4 0] 5)))
    (is (nil? (outbound/usual-flow-changes [500 20 4 nil] 5)))
    (is (nil? (outbound/usual-flow-changes [500 20 4 0] -1)))
    (is (nil? (outbound/usual-flow-changes [500 20 4 0] 4)))))
