(ns city.vancouver.downtown-audit-test
  (:require [city.vancouver.downtown-audit :as audit]
            [clojure.test :refer [deftest is]]))

(deftest peak-volume-and-timing-use-distinct-windows
  (let [empty-day (vec (repeat 24 0))
        observed (assoc empty-day 7 40 8 60 9 60 18 50)
        residents (assoc empty-day 7 10 8 20 18 5)
        incoming (assoc empty-day 6 30 7 12 8 4)
        [am pm] (:windows (audit/comparison observed {:resident residents :incoming incoming}))]
    (is (= {:observed 100 :modeled 46 :modeledToObserved 0.46
            :cohorts {:resident 30 :incoming 16}
            :observedPeakStarts [8 9] :modeledPeakStarts [6]}
           am))
    (is (= {:observed 0 :modeled 0 :modeledToObserved nil
            :cohorts {:resident 0 :incoming 0}
            :observedPeakStarts [18] :modeledPeakStarts [18]}
           pm))
    (is (= [] (get-in (audit/comparison empty-day {:resident empty-day}) [:windows 0 :observedPeakStarts])))
    (is (thrown-with-msg? clojure.lang.ExceptionInfo #"24 nonnegative hourly counts"
                          (audit/comparison observed {:resident (assoc residents 12 -1)})))))
