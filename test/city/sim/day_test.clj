(ns city.sim.day-test
  "The untraced and the traced weekday on a small hand-built world: the same
   draws must give the same visits, and the diary pick must be the inverse cdf
   of the type's diary weights."
  (:require [clojure.test :refer [deftest is testing]]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]))

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
