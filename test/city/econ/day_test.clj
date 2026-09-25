(ns city.econ.day-test
  "Spend per visit must sum back to the money: for every household with a
   shopper, Σ over members and classes of spend × expected visits per year
   equals the household's potential, and a household without a shopper is
   reported as unspent rather than lost silently."
  (:require [clojure.test :refer [deftest is testing]]
            [city.econ.day :as eday]))

(deftest household-spend-sums-back-to-the-potential
  (let [n 12
        ;; households: 0 = two shoppers + a child; 1 = one shopper; 2 = no shopper at all
        hh (int-array [0 0 0  1 1  2 2  0 1 1 2 2])
        ptype (int-array [0 1 -1  0 -1  -1 -1  2 2 0 -1 2])   ; type 2 never shops
        per-day (double-array [0.5 0.2 0.0])
        potential (double-array [3000 2000 500  4000 1000  900 100  0 700 800 50 60])
        shares-of (fn [_] {:short 0.5 :medium 0.2 :long 0.3})
        pi [0.6 0.25 0.15]
        spend (eday/spend-per-visit n potential shares-of ptype hh per-day pi)
        back (fn [h] (reduce + (for [i (range n) :when (= h (aget hh i)) :let [t (aget ptype i)] :when (>= t 0)
                                    s (range 3)]
                                (/ (* (aget spend (+ (* s n) i)) 365.0 (aget per-day t) (nth pi s)) 100.0))))
        pot (fn [h] (reduce + (for [i (range n) :when (= h (aget hh i))] (aget potential i))))]
    (testing "a household with shoppers spends exactly its pooled potential, children's money included"
      (is (< (Math/abs (- (back 0) (pot 0))) 1.0) (str (back 0) " vs " (pot 0)))
      (is (< (Math/abs (- (back 1) (pot 1))) 1.0) (str (back 1) " vs " (pot 1))))
    (testing "a member whose type never shops carries no spend"
      (is (zero? (aget spend 2))) (is (zero? (aget spend 7))) (is (zero? (aget spend 8))))
    (testing "the household with no shopper is the unspent figure, and nothing else is"
      (is (= (double (pot 2)) (eday/unspent-potential n potential ptype hh per-day))))))

(deftest household-ids-combine-cell-and-index
  (let [ps {:n 6 :da (into-array String ["c1" "c1" "c2" "c2" "c1" "x"]) :hh (int-array [0 0 0 1 1 0]) :external (int-array [0 0 0 0 0 1])}
        ids (vec (eday/household-ids ps))]
    (is (= (nth ids 0) (nth ids 1)) "same cell, same index")
    (is (not= (nth ids 0) (nth ids 2)) "same index, different cell")
    (is (not= (nth ids 2) (nth ids 3)))
    (is (not= (nth ids 0) (nth ids 4)))
    (is (= 5 (count (distinct ids))) "an in-commuter is its own household")))

(deftest a-class-has-an-inflow-or-a-leakage-never-both
  ;; store-choices! applies the leakage draw to in-commuters too (they have a
  ;; home cell at the boundary); that is harmless only because a class that
  ;; draws money in leaks none
  (let [tg {"A" {:short {:umsatz-eur 90.0 :kaufkraft-eur 100.0}
                 :medium {:umsatz-eur 180.0 :kaufkraft-eur 100.0}
                 :long {:umsatz-eur 100.0 :kaufkraft-eur 100.0}}
            "B" {:short {:umsatz-eur 50.0 :kaufkraft-eur 70.0}
                 :medium {:umsatz-eur 20.0 :kaufkraft-eur 10.0}
                 :long {:umsatz-eur 10.0 :kaufkraft-eur 30.0}}}
        b (eday/class-balances tg)]
    (is (= {:inflow-eur 0.0 :leak-share (/ 30.0 170.0)} (:short b)))
    (is (= {:inflow-eur 90.0 :leak-share 0.0} (:medium b)))
    (is (= {:inflow-eur 0.0 :leak-share (/ 20.0 130.0)} (:long b)))
    (doseq [[_ {:keys [inflow-eur leak-share]}] b]
      (is (not (and (pos? inflow-eur) (pos? leak-share)))))))
