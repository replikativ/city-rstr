(ns city.vancouver.incoming-homes-test
  (:require [city.vancouver.incoming-homes :as homes]
            [clojure.test :refer [deftest is]]))

(deftest transit-targets-preserve-cohort-margins
  (let [targets (homes/transit-targets [6 3 0 4] [3 1 0 1] [[100 10] [100 90] [120 20] nil])]
    (is (= 5 (reduce + targets)))
    (is (every? true? (map #(<= 0 %1 %2) targets [6 3 0 4])))
    (is (< (nth targets 0) 3))
    (is (= [3 1] (homes/transit-targets [6 3] [3 1] [nil nil])))))

(deftest home-exchanges-preserve-dates-personal-fields-and-both-distance-bands
  (let [cohort {:people [[0 0 1 6 5 480 40 480 1 0]
                         [1 0 1 6 0 510 30 480 1 0]
                         [1 0 2 6 0 510 30 480 0 0]]
                :points [[0 0] [50 0]] :margins [[100 0] [100 90]]}
        result (homes/fit-group cohort [[500 0]] 5)]
    (is (= [[0 0 1] [1 1 0]] (:changes result)))
    (is (= [2 0] ((juxt :errorBefore :errorAfter) result)))
    (is (empty? (:changes (homes/fit-group (assoc-in cohort [:people 1 8] 0) [[500 0]] 5))))
    (is (empty? (:changes (homes/fit-group (assoc cohort :points [[0 0] [2000 0]]) [[500 0]] 5))))))
