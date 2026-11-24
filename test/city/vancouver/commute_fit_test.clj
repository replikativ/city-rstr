(ns city.vancouver.commute-fit-test
  (:require [city.vancouver.commute-fit :as fit]
            [clojure.test :refer [deftest is]])
  (:import [java.util Random]))

(deftest exact-row-and-mode-margins
  (let [seed [[23 7 0 3] [5 17 0 7] [0 0 0 1]]
        target [0 30 12 21]
        fitted (fit/fit-counts seed target)]
    (is (= (mapv #(reduce + %) seed) (mapv #(reduce + %) fitted)))
    (is (= target (apply mapv + fitted)))
    (is (every? nat-int? (mapcat identity fitted)))
    (is (thrown? clojure.lang.ExceptionInfo (fit/fit-counts seed [1 0 0 0])))))

(deftest changes-only-the-required-residents-in-each-group
  (let [people (mapv (fn [i] [0 i (if (< i 8) 0 1) [(if (even? i) "15–24" "65+")]])
                     (range 12))
        run #(fit/fit-area people [2 1 1] (Random. 41))
        result (run)
        outcome (:people result)
        original (into {} (map (juxt second #(nth % 2)) people))]
    (is (= [8 4 0] (:before result)))
    (is (= [6 3 3] (:target result)))
    (is (= {0 6 1 3 2 3} (frequencies (map peek outcome))))
    (is (= (set (range 12)) (set (map second outcome))))
    (is (= 3 (count (remove (fn [[_ i m]] (= (original i) m)) outcome))))
    (is (= result (run)))
    (is (= [] (:people (fit/fit-area [] [0 0 0] (Random. 4)))))))

(deftest joint-calibration-preserves-neighbourhood-capacities
  (is (= [[0 1 0] [0 0 1]]
         (fit/external-targets [[1 0 0] [0 1 0]] [[1 1 0] [0 1 1]] [0 1 1])))
  (is (thrown? clojure.lang.ExceptionInfo
               (fit/external-targets [[1 0 0]] [[1 0 0]] [0 0 1])))
  (is (= [1 2 3 3 1 4] (fit/split-active [1 2 3 4 4] [1 2 3 6 2 4] [5 5 5 8 8 5])))
  (is (= [1 2 3 6 4 4] (fit/split-active [1 2 3 10 4] [1 2 3 6 2 4] [5 5 5 6 8 5]))))

(deftest exchanges-modes-within-a-fixed-diary-cohort
  ;; A three-way exchange can keep both legs of the walk and bike within budget.
  (let [rows [[:a :walk 2 1] [:b :bike 0 0] [:c :bus 1 0] [:d :car 1 1]]
        run #(fit/assign-travel-budgets rows :walk :bike (Random. 7))]
    (is (= {:a :bus :b :walk :c :bike} (run)))
    (is (= {} (fit/assign-travel-budgets [[:e :walk 0 0] [:f :bike 0 0]] :walk :bike (Random. 7)))))
  ;; Compare the lexicographic optimum against all feasible allocations of a small group.
  (let [perms (fn perms [xs]
                (if (empty? xs) [[]]
                    (for [x xs p (perms (disj xs x))] (cons x p))))
        modes [:walk :bike :car :bus] rng (Random. 83)]
    (dotimes [_ 60]
      (let [rows (mapv (fn [i m] [i m (.nextInt rng 4) (.nextInt rng 4)]) (range) modes)
            changes (fit/assign-travel-budgets rows :walk :bike rng)
            actual (mapv #(get changes % (modes %)) (range 4))
            score (fn [choices]
                    [(reduce + (map (fn [m [_ _ w b]] (case m :walk w :bike b 0)) choices rows))
                     (count (remove true? (map = modes choices)))])]
        (is (= (set modes) (set actual)))
        (is (= (score actual) (first (sort (map score (perms (set modes)))))))))))
