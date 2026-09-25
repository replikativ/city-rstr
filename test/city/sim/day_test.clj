(ns city.sim.day-test
  "The untraced and the traced weekday on a small hand-built world: the same
   draws must give the same visits, and the diary pick must be the inverse cdf
   of the type's diary weights."
  (:require [clojure.test :refer [deftest is testing]]
            [city.econ.day :as eday]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]
            [city.sim.kernel :as kn]))

(def ^:private by-type
  {[:worker :a25-34 :women]
   [{:weight 1.0 :chain [{:act :home :loc :home :start 0 :dur 420}
                         {:act :travel :loc :walk :start 420 :dur 20}
                         {:act :work :loc :work-or-school :start 440 :dur 480}
                         {:act :shop :loc :store :start 930 :dur 30}
                         {:act :eat :loc :restaurant :start 1000 :dur 60}
                         {:act :home :loc :home :start 1080 :dur 360}]}
    {:weight 2.0 :chain [{:act :home :loc :home :start 0 :dur 600}
                         {:act :shop :loc :store :start 600 :dur 40}
                         {:act :home :loc :home :start 660 :dur 780}]}]
   [:retired :a65-74 :men]
   [{:weight 1.0 :chain [{:act :home :loc :home :start 0 :dur 540}
                         {:act :travel :loc :transit :start 540 :dur 25}
                         {:act :shop :loc :store :start 565 :dur 60}
                         {:act :eat :loc :restaurant :start 700 :dur 50}
                         {:act :home :loc :home :start 780 :dur 660}]}]})

(defn- tiny-day [np nf seed]
  (let [rng (java.util.Random. seed)
        flon (double-array nf) flat (double-array nf) attract (double-array nf)
        _ (dotimes [j nf]
            (aset flon j (+ 9.17 (* 0.03 (.nextDouble rng))))
            (aset flat j (+ 48.77 (* 0.02 (.nextDouble rng))))
            (aset attract j (* 100.0 (Math/exp (* 2.0 (.nextDouble rng))))))
        firms {:n nf :lon flon :lat flat :alive (int-array nf 1)
               :retail (int-array nf 1) :food (int-array (map #(if (even? %) 1 0) (range nf)))}
        worker? (fn [i] (even? i))
        persons {:n np
                 :home-lon (double-array (map (fn [_] (+ 9.17 (* 0.03 (.nextDouble rng)))) (range np)))
                 :home-lat (double-array (map (fn [_] (+ 48.77 (* 0.02 (.nextDouble rng)))) (range np)))
                 :labour (int-array (map #(if (worker? %) 1 0) (range np)))
                 :attsch (int-array np)
                 :age (int-array (map #(if (worker? %) 5 12) (range np)))
                 :sex (int-array (map #(if (worker? %) 1 2) (range np)))
                 :work (int-array (map #(if (worker? %) (mod % nf) -1) (range np)))}
        world {:persons persons :firms firms}
        grid (d2/grid-spec world)
        dt (d2/diary-tables by-type)
        dense (cand/build-dense grid firms (:retail firms))
        cell (fn [lon lat] (int (d2/cell-of grid lon lat)))]
    {:world world
     :tables {:grid grid
              :retail (cand/table-dense dense attract {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0})
              :food (d2/gravity-table grid firms (:food firms) :kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0 :k 8
                                      :attract attract)
              :diaries dt
              :ptype (d2/person-types persons dt)
              :home-cell (int-array (map #(cell (aget ^doubles (:home-lon persons) %) (aget ^doubles (:home-lat persons) %)) (range np)))
              :work-cell (int-array (map #(cell (aget flon %) (aget flat %)) (range nf)))
              :cls-table (object-array d2/n-loc) :cls-lon (object-array d2/n-loc) :cls-lat (object-array d2/n-loc)
              :modes nil}}))

(deftest the-traced-day-makes-the-same-visits
  (let [{:keys [world tables]} (tiny-day 200 25 3)
        plain (d2/step-day world tables 7)
        traced (d2/step-day-traces world tables 7 :stride 5)]
    (is (every? #(>= % 0) (:ptype tables)) "every person has a diary type")
    (is (= (vec (:visits plain)) (vec (:visits traced))))
    (doseq [k [:diaries :work-episodes :store-visits :restaurant-visits]]
      (is (= (get-in plain [:counts k]) (get-in traced [:counts k])) (name k)))
    (is (pos? (get-in plain [:counts :store-visits])))
    (testing "every fifth person is traced, and a traced leg ends where a visit was counted"
      (is (= 40 (count (:traces traced))))
      (is (every? #(seq (:legs %)) (:traces traced))))))

(defn- store-choices
  "The store decisions for a tiny day under three differently shaped classes,
   with leakage in two of them, and the money day they add up to."
  [{:keys [world tables]} seed]
  (let [{:keys [grid diaries]} tables
        firms (:firms world) persons (:persons world) np (:n persons)
        dense (cand/build-dense grid firms (:retail firms)) ^ints cand (:cand dense) nc (:nc dense) n (:n grid)
        cl (double-array (map #(first (d2/cell-center grid %)) (range n))) ca (double-array (map #(second (d2/cell-center grid %)) (range n)))
        ql (double-array (map #(aget ^doubles (:lon firms) (aget cand %)) (range nc))) qa (double-array (map #(aget ^doubles (:lat firms) (aget cand %)) (range nc)))
        att3 (double-array (for [s (range 3) q (range nc)] (if (zero? (mod (+ q s) 5)) 0.0 (+ 10.0 (* 7.0 (mod (* q (inc s)) 11))))))
        params3 (double-array [0.8 2.4 300.0  1.1 1.4 900.0  1.0 2.0 600.0])
        totals3 (double-array (* 3 n))
        _ (dotimes [s 3] (let [att (double-array nc) p (double-array 3) tot (double-array n)]
                           (System/arraycopy att3 (* s nc) att 0 nc) (System/arraycopy params3 (* s 3) p 0 3)
                           (kn/cell-totals! cl ca ql qa att p tot n nc) (System/arraycopy tot 0 totals3 (* s n) n)))
        max-s (eday/max-store-episodes diaries)
        diary (int-array np -1) choice (int-array (* np max-s) -9)]
    (kn/store-choices! (:ptype tables) (:home-cell tables) (:work persons) (:work-cell tables)
                       (:type-offsets diaries) (:type-cdf diaries) (:diary-offsets diaries) (:ep-loc diaries)
                       (double-array (interleave cl ca)) (double-array (interleave ql qa)) att3 totals3 params3
                       (double-array [0.5 0.8 1.0 0.2 0.0 0.4]) (eday/store-ranks diaries) diary choice (long-array [np nc seed n max-s]))
    (let [sc {:diary diary :choice choice :max-s max-s :cand cand}]
      {:store-choices sc :cand cand :nc nc
       :money (eday/money-from-choices sc diaries (int-array (* 3 np) 100) np nc)})))

(deftest one-store-decision-for-trip-visit-and-money
  ;; the money day, the untraced day and the traced day read the same store
  ;; decisions: the same store visits at the same venue and hour, leaked
  ;; purchases nowhere, and the other visits untouched
  (let [{:keys [world tables] :as day} (tiny-day 300 25 3)
        {:keys [store-choices money cand nc]} (store-choices day 7)
        tables' (assoc tables :store-choices store-choices)
        plain (d2/step-day world tables' 7)
        traced (d2/step-day-traces world tables' 7 :stride 3)
        before (d2/step-day world tables 7)
        nf (:n (:firms world))
        ^ints vis3 (:visits3 money)
        store-visits (int-array (* nf 24))
        _ (dotimes [s 3] (dotimes [q nc] (dotimes [h 24]
                                          (let [j (aget cand q) k (+ (* j 24) h)]
                                            (aset store-visits k (+ (aget store-visits k) (aget vis3 (+ (* (+ (* s nc) q) 24) h))))))))]
    (is (pos? (nth (:counts money) 1)) "some purchases are placed")
    (is (pos? (+ (nth (:counts money) 5) (nth (:counts money) 7))) "some purchases leak")
    (is (= (nth (:counts money) 1) (get-in plain [:counts :store-visits])) "the day counts the money day's visits")
    (is (= (vec (:visits plain)) (vec (:visits traced))) "traced and untraced agree")
    (testing "store visits are the money day's, venue by venue and hour by hour"
      ;; a day whose every store decision is \"no venue\" keeps only the work and
      ;; restaurant visits; the real day minus the money day's store visits is that day
      (let [none (d2/step-day world (assoc tables :store-choices
                                           (assoc store-choices :choice (int-array (alength ^ints (:choice store-choices)) -4)))
                              7)]
        (is (zero? (get-in none [:counts :store-visits])))
        (is (= (get-in before [:counts :restaurant-visits]) (get-in plain [:counts :restaurant-visits]) (get-in none [:counts :restaurant-visits])))
        (is (= (vec (:visits none))
               (vec (map - (:visits plain) store-visits))))))))

(deftest the-diary-pick-is-the-inverse-cdf
  (let [dt (d2/diary-tables by-type)
        ^ints off (:type-offsets dt) ^doubles cdf (:type-cdf dt)
        pick #'d2/pick-diary
        scan (fn [t u] (let [a (aget off t) b (aget off (inc t))]
                         (or (first (filter #(< u (aget cdf %)) (range a b))) (dec b))))
        rng (java.util.Random. 11)]
    (doseq [t (range (:n-types dt)) _ (range 500)]
      (let [u (.nextDouble rng)]
        (is (= (scan t u) (pick off cdf t u)))))))
