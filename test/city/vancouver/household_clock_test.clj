(ns city.vancouver.household-clock-test
  (:require [city.vancouver.household-clock :as clock]
            [clojure.test :refer [deftest is]]))

(deftest household-bands-use-the-microdata-boundaries
  (is (= [6 1 2 3 4 5 5 6 6] (mapv clock/pumf-band [299 300 360 420 480 540 959 960 1679]))))

(deftest compatible-intact-diaries
  (let [day (fn [start minutes mode] {"slots" ["home" "job"]
                                      "parts" [[240 (- start 240) "stop" 0 0] [start minutes mode 0 1]
                                               [(+ start minutes) (- 1680 start minutes) "stop" 1 1]]})
        times [420 480 480 480 480 480 480]
        durations [20 20 10 20 20 20 20]
        templates (mapv day times durations ["walk" "walk" "walk" "bike" "walk" "walk" "walk"])
        diaries (mapv (fn [s d] {"episodes" [[(+ s d) 30 "paid-work" "work-or-school"]]}) times durations)
        sources [["worker" "a25-34" 1] ["worker" "a25-34" 2] ["worker" "a25-34" 3]
                 ["worker" "a25-34" 4] ["student" "a25-34" 5] ["worker" "a55-64" 6]
                 ["worker" "a25-34" 7]]
        tours (assoc (mapv #(hash-map :minute %) times) 6 {:kind :untraced})
        opts (clock/options templates diaries sources tours true)]
    (is (= [1] (mapv :id (get-in opts [0 4]))))
    (is (= [0] (mapv :id (get-in opts [0 3]))))
    (is (nil? (get-in opts [2 3])))
    (is (= [0] (mapv :id (get-in (clock/options templates diaries sources tours false) [2 3]))))
    (is (nil? (opts 4)))))

(deftest balance-stops-at-both-margins
  (is (= {"a" #{0 2}} (clock/balance [0 2 -1 -1 0 0 0]
                                     [["a" 0 1 2] ["b" 0 1 2] ["a" 2 1 3] ["b" 1 3 2]]))))
