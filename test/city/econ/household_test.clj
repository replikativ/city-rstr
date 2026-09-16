(ns city.econ.household-test
  "Purchasing power within a district: the assumed ratios apply by census age
   group, and the district total is reproduced exactly."
  (:require [clojure.test :refer [deftest is testing]]
            [city.econ.household :as hh]))

(deftest ratios-read-census-age-groups-not-years
  (testing "AGEGRP 1–2 is under 15, 3 is 15–19, 12–13 is 65 and over"
    (is (= 0.25 (hh/relative-weight 1 false)))
    (is (= 0.25 (hh/relative-weight 2 true)) "a child's weight does not depend on the employment flag")
    (is (= 0.45 (hh/relative-weight 3 false)))
    (is (= 1.30 (hh/relative-weight 6 true)))
    (is (= 0.70 (hh/relative-weight 6 false)))
    (is (= 0.85 (hh/relative-weight 12 false)))
    (is (= 1.30 (hh/relative-weight 12 true)) "a working 67-year-old counts as working")))

(deftest a-district-total-is-shared-by-those-ratios
  ;; five residents of one district and an in-commuter: a child, a teenager,
  ;; a worker, a retiree, an adult not in work
  (let [world {:persons {:n 6 :la (object-array (repeat 6 "West"))
                         :age (int-array [1 3 6 12 7 6])
                         :employed (int-array [0 0 1 0 0 1])
                         :external (int-array [0 0 0 0 0 1])}}
        out (hh/assign-purchasing-power! world :kk {"West" {:total-eur 3550.0}})
        ^doubles pp (get-in out [:persons :pp])
        weights [0.25 0.45 1.30 0.85 0.70]]
    (is (< (Math/abs (- 3550.0 (reduce + (seq pp)))) 1e-9) "the district total is exact")
    (is (zero? (aget pp 5)) "an in-commuter carries no resident purchasing power")
    (is (every? true? (map (fn [i w] (< (Math/abs (- (aget pp i) (* 1000.0 w))) 1e-9)) (range 5) weights))
        "each resident holds their ratio's share: total 3550 over weight 3.55")))
