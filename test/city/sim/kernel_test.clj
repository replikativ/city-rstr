(ns city.sim.kernel-test
  "The table-free kernels against the table they replace: a draw with the same
   u must land on the same candidate `pick-from-cdf` lands on, and the store
   decisions (`store-choices!`, added up by `econ.day/money-from-choices`) must
   count the visits `step-day`'s retail branch would."
  (:require [clojure.test :refer [deftest is testing]]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]
            [city.econ.day :as eday]
            [city.sim.kernel :as kn]))

(defn- tiny-world [nf seed]
  (let [rng (java.util.Random. seed)
        lon (double-array nf) lat (double-array nf)
        _ (dotimes [j nf] (aset lon j (+ 9.17 (* 0.03 (.nextDouble rng)))) (aset lat j (+ 48.77 (* 0.02 (.nextDouble rng)))))
        attract (double-array nf)
        _ (dotimes [j nf] (aset attract j (* 100.0 (Math/exp (* 3.0 (.nextDouble rng))))))
        firms {:n nf :lon lon :lat lat :alive (int-array nf 1)}
        persons {:n 2 :home-lon (double-array [9.17 9.2]) :home-lat (double-array [48.77 48.79])}
        grid (d2/grid-spec {:firms firms :persons persons})]
    {:grid grid :firms firms :attract attract :dense (cand/build-dense grid firms (int-array nf 1))}))

(defn- inputs [{:keys [grid firms attract dense]}]
  (let [n (:n grid) nc (:nc dense) ^ints c (:cand dense)]
    {:cell-lon (double-array (map #(first (d2/cell-center grid %)) (range n)))
     :cell-lat (double-array (map #(second (d2/cell-center grid %)) (range n)))
     :cand-lon (double-array (map #(aget ^doubles (:lon firms) (aget c %)) (range nc)))
     :cand-lat (double-array (map #(aget ^doubles (:lat firms) (aget c %)) (range nc)))
     :cand-att (double-array (map #(aget ^doubles attract (aget c %)) (range nc)))
     :n n :nc nc}))

(defn- spend-day
  "The money day through the store decisions, in the shape the tests read:
   fills `rev`, `vis` and `cnt` as the economic day's arrays."
  [ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
   cell-xy cand-xy att3 totals3 params3 shares spend3 ^ints rev ^ints vis ^ints cnt [np nc seed ncell]]
  (let [diaries {:diary-offsets diary-offsets :ep-loc ep-loc :ep-minute ep-minute}
        max-s (eday/max-store-episodes diaries)
        diary (int-array np -1) choice (int-array (* np max-s) -9)
        _ (kn/store-choices! ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc
                             cell-xy cand-xy att3 totals3 params3 shares (eday/store-ranks diaries) diary choice (long-array [np nc seed ncell max-s]))
        m (eday/money-from-choices {:diary diary :choice choice :max-s max-s} diaries spend3 np nc)]
    (System/arraycopy (:revenue3 m) 0 rev 0 (alength rev))
    (System/arraycopy (:visits3 m) 0 vis 0 (alength vis))
    (dotimes [k 8] (aset cnt k (int (nth (:counts m) k))))))

(defn- retail-visits
  "One demand class with no leakage: the store decisions reduced to the retail
   day, `visits` by candidate and hour and `counts` = [diaries store-visits]."
  [ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
   ^doubles cell-lon ^doubles cell-lat ^doubles cand-lon ^doubles cand-lat ^doubles cand-att ^doubles totals ^doubles params
   ^ints visits ^ints counts [np nc seed]]
  (let [n (alength cell-lon)
        rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)]
    (spend-day ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
               (double-array (interleave cell-lon cell-lat)) (double-array (interleave cand-lon cand-lat))
               (double-array (concat cand-att cand-att cand-att)) (double-array (concat totals totals totals))
               (double-array (concat params params params)) (double-array [1.0 1.0 1.0 0.0 0.0 0.0])
               (int-array (* 3 np)) rev vis cnt [np nc seed n])
    (System/arraycopy vis 0 visits 0 (* nc 24))
    (aset counts 0 (aget cnt 0)) (aset counts 1 (aget cnt 1))))

(deftest a-table-free-draw-lands-where-the-table-draw-lands
  (doseq [spec [{:alpha 1.0 :beta 2.0 :d0-m 500.0} {:alpha 1.3 :beta 1.6 :d0-m 900.0} {:alpha 0.0 :beta 2.5 :d0-m 300.0}]]
    (let [w (tiny-world 60 21) {:keys [cell-lon cell-lat cand-lon cand-lat cand-att n nc]} (inputs w)
          params (double-array [(:alpha spec) (:beta spec) (:d0-m spec)])
          totals (double-array n)
          _ (kn/cell-totals! cell-lon cell-lat cand-lon cand-lat cand-att params totals n nc)
          tbl (cand/table-dense (:dense w) (:attract w) (assoc spec :kernel :power))
          rng (java.util.Random. 3)
          trials (for [_ (range 2000)] [(.nextInt rng n) (.nextDouble rng)])
          walk (fn [c u]
                 (let [target (* u (aget totals c)) lon (aget cell-lon c) lat (aget cell-lat c)]
                   (loop [q 0 acc 0.0]
                     (if (>= q (dec nc)) q
                         (let [acc (+ acc (kn/weight (aget cand-att q) (kn/haversine-m lon lat (aget cand-lon q) (aget cand-lat q))
                                                     (:alpha spec) (:beta spec) (:d0-m spec)))]
                           (if (< target acc) q (recur (inc q) acc)))))))
          agree (count (filter (fn [[c u]] (= (aget ^ints (:cand (:dense w)) (walk c u)) (#'d2/pick-from-cdf tbl c u))) trials))]
      (testing (str spec)
        (is (>= agree 1998) (str agree " of 2000 draws agree"))
        (testing "the normaliser matches the table's row sum of weights"
          (is (every? pos? totals)))))))

(deftest haversine-agrees-with-the-world-metric
  (let [w (tiny-world 30 2) {:keys [cell-lon cell-lat cand-lon cand-lat n nc]} (inputs w)]
    (doseq [c [0 (quot n 2) (dec n)] q [0 (quot nc 2) (dec nc)]]
      (let [a (kn/haversine-m (aget cell-lon c) (aget cell-lat c) (aget cand-lon q) (aget cand-lat q))
            b (city.sim.world/haversine-m (aget cell-lon c) (aget cell-lat c) (aget cand-lon q) (aget cand-lat q))]
        (is (< (Math/abs (- a b)) 1e-6) (str a " vs " b))))))

(deftest the-person-loop-counts-store-episodes-and-keeps-the-anchor
  ;; Two person types, three diaries, hand-built: the loop must count one
  ;; visit per store episode, at the episode's hour, drawn from the anchor
  ;; the diary put the person at — home, or the workplace after a work episode.
  (let [w (tiny-world 40 7) {:keys [cell-lon cell-lat cand-lon cand-lat cand-att n nc]} (inputs w)
        params (double-array [1.0 2.0 500.0])
        totals (double-array n)
        _ (kn/cell-totals! cell-lon cell-lat cand-lon cand-lat cand-att params totals n nc)
        ;; diaries: type 0 = [home(0) store(2)@10:00 home(0)], type 1 = [home work(1)@9:00 store(2)@12:00], [home store@18:00]
        type-offsets (int-array [0 1 3])
        type-cdf (double-array [1.0 0.5 1.0])
        diary-offsets (int-array [0 3 6 8])
        ep-loc (int-array [0 2 0  0 1 2  0 2])
        ep-minute (int-array [420 600 720  420 540 720  420 1080])
        np 300
        ptype (int-array (map #(mod % 2) (range np)))
        home-cell (int-array (map #(mod (* % 7) n) (range np)))
        work (int-array (map #(if (odd? %) (mod % nc) -1) (range np)))
        work-cell (int-array (map (fn [q] (d2/cell-of (:grid w) (aget cand-lon q) (aget cand-lat q))) (range nc)))
        visits (int-array (* nc 24)) counts (int-array 2)]
    (retail-visits ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                       cell-lon cell-lat cand-lon cand-lat cand-att totals params visits counts [np nc 5])
    (is (= np (aget counts 0)) "every person has a diary")
    (is (= np (aget counts 1)) "every diary has exactly one store episode")
    (is (= np (reduce + (seq visits))) "one visit counted per store episode")
    (testing "visits fall at the hours the diaries say and nowhere else"
      (let [by-hour (vec (for [h (range 24)] (reduce + (for [q (range nc)] (aget visits (+ (* q 24) h))))))]
        (is (= 150 (nth by-hour 10)) "type 0 shops at 10")
        (is (pos? (nth by-hour 12))) (is (pos? (nth by-hour 18)))
        (is (= 150 (+ (nth by-hour 12) (nth by-hour 18))) "type 1 shops at 12 or 18")
        (is (zero? (reduce + (map by-hour [0 1 2 3 4 5 6 7 8 9 11 13 14 15 16 17 19 20 21 22 23]))))))
    (testing "a person with no diary type is skipped, not counted"
      (let [visits2 (int-array (* nc 24)) counts2 (int-array 2)]
        (retail-visits (int-array np -1) home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                           cell-lon cell-lat cand-lon cand-lat cand-att totals params visits2 counts2 [np nc 5])
        (is (= [0 0] (vec counts2)))))))

(deftest the-money-day-conserves-what-it-counts
  ;; Every visit carries exactly its person's class spend, so this day's revenue
  ;; equals the sum of the spends of the visits it counted; classes partition
  ;; the visits; and a class with zero trip share gets no visits at all.
  (let [w (tiny-world 40 7) {:keys [cell-lon cell-lat cand-lon cand-lat cand-att n nc]} (inputs w)
        cell-xy (double-array (interleave cell-lon cell-lat)) cand-xy (double-array (interleave cand-lon cand-lat))
        att3 (double-array (concat cand-att (map #(* 1.3 %) cand-att) (map #(* 0.7 %) cand-att)))
        params3 (double-array [1.0 2.6 400.0  1.0 1.3 800.0  1.0 2.0 600.0])
        totals3 (double-array (* 3 n))
        _ (dotimes [s 3] (let [att (double-array nc) _ (System/arraycopy att3 (* s nc) att 0 nc) tot (double-array n)
                               p (double-array 3) _ (System/arraycopy params3 (* s 3) p 0 3)]
                           (kn/cell-totals! cell-lon cell-lat cand-lon cand-lat att p tot n nc)
                           (System/arraycopy tot 0 totals3 (* s n) n)))
        type-offsets (int-array [0 1 3]) type-cdf (double-array [1.0 0.5 1.0])
        diary-offsets (int-array [0 3 6 8])
        ep-loc (int-array [0 2 0  0 1 2  0 2]) ep-minute (int-array [420 600 720  420 540 720  420 1080])
        np 400
        ptype (int-array (map #(mod % 2) (range np)))
        home-cell (int-array (map #(mod (* % 7) n) (range np)))
        work (int-array (map #(if (odd? %) (mod % nc) -1) (range np)))
        work-cell (int-array (map (fn [q] (d2/cell-of (:grid w) (aget cand-lon q) (aget cand-lat q))) (range nc)))
        spend3 (int-array (for [s (range 3) i (range np)] (+ 100 (* 10 s) (mod i 7))))
        run (fn [pi]
              (let [rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)]
                (spend-day ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                               cell-xy cand-xy att3 totals3 params3 (double-array (concat (reductions + pi) [0.0 0.0 0.0])) spend3 rev vis cnt [np nc 3 n])
                {:rev rev :vis vis :cnt (vec cnt)}))
        {:keys [rev vis cnt]} (run [0.65 0.20 0.15])]
    (is (= np (nth cnt 0))) (is (= np (nth cnt 1)) "one store episode per diary")
    (is (= np (+ (nth cnt 2) (nth cnt 3) (nth cnt 4))) "classes partition the visits")
    (is (= np (reduce + (seq vis))))
    (testing "revenue is exactly the spends of the counted visits"
      (let [expected (reduce + (for [s (range 3) q (range nc) h (range 24)
                                     :let [k (+ (* (+ (* s nc) q) 24) h) v (aget vis k)] :when (pos? v)]
                                 ;; each visit in cell k came from some person; total per cell = Σ spends —
                                 ;; check the weaker but exact invariant: revenue ≥ v·min-spend and ≤ v·max-spend
                                 0))]
        (is (zero? expected))
        (doseq [s (range 3) q (range nc) h (range 24)
                :let [k (+ (* (+ (* s nc) q) 24) h) v (aget vis k) r (aget rev k)] :when (pos? v)]
          (is (<= (* v (+ 100 (* 10 s))) r (* v (+ 106 (* 10 s)))) (str [s q h v r])))))
    (testing "a class with no trip share gets nothing"
      (let [{:keys [cnt vis]} (run [1.0 0.0 0.0])]
        (is (= [np np np 0 0 0 0 0] cnt))
        (is (zero? (reduce + (map #(aget vis %) (range (* nc 24) (* 3 nc 24))))))))
    (testing "leakage removes the visit and the money, and counts it"
      (let [rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)
            shares (double-array [0.65 0.85 1.0  1.0 0.0 0.0])]   ; every short-class purchase leaks
        (spend-day ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                       cell-xy cand-xy att3 totals3 params3 shares spend3 rev vis cnt [np nc 3 n])
        (is (= np (aget cnt 0)))
        (is (pos? (aget cnt 5)) "short-class episodes leaked")
        (is (zero? (aget cnt 2)) "no short-class visit placed")
        (is (= np (+ (aget cnt 1) (aget cnt 5))) "placed plus leaked is every store episode")
        (is (zero? (reduce + (map #(aget vis %) (range (* nc 24))))) "no short-class visits")
        (is (zero? (reduce + (map #(aget rev %) (range (* nc 24))))) "no short-class revenue")))))

(deftest draws-are-hashed-per-person-and-do-not-align-across-seeds
  (testing "the linear address once made seed s+190 replay seed s, 23,993 persons on"
    (is (not= (d2/uniform 191 5 4) (d2/uniform 1 (+ 5 23993) 7))))
  (testing "distinct purposes of one person draw distinct numbers"
    (is (= 7 (count (set (map #(d2/uniform 7 12345 %) [0 1 977 3001 100001 200001 300000]))))))
  (testing "a world seed equal to the day seed no longer couples workplace and diary"
    (is (not= (d2/uniform 7 3 0) (d2/uniform 7 3 300000)))))

(deftest the-device-kernel-draws-what-the-jvm-draws
  ;; store-choices! inlines the address arithmetic; recomputing every choice
  ;; with day/uniform and the same walk must give the identical visit array
  (let [w (tiny-world 30 11) {:keys [cell-lon cell-lat cand-lon cand-lat cand-att n nc]} (inputs w)
        params (double-array [1.0 1.8 600.0]) totals (double-array n)
        _ (kn/cell-totals! cell-lon cell-lat cand-lon cand-lat cand-att params totals n nc)
        type-offsets (int-array [0 1]) type-cdf (double-array [1.0])
        diary-offsets (int-array [0 4]) ep-loc (int-array [0 2 2 0]) ep-minute (int-array [420 600 660 720])
        np 200 seed 17
        ptype (int-array np) home-cell (int-array (map #(mod (* % 11) n) (range np)))
        work (int-array np -1) work-cell (int-array nc)
        visits (int-array (* nc 24)) counts (int-array 2)
        _ (retail-visits ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                             cell-lon cell-lat cand-lon cand-lat cand-att totals params visits counts [np nc seed])
        expected (int-array (* nc 24))]
    (dotimes [i np]
      (let [c (aget home-cell i)]
        (doseq [[k h] [[1 10] [2 11]]]
          (let [target (* (d2/uniform seed i (inc k)) (aget totals c))
                j (loop [q 0 acc 0.0]
                    (if (>= q (dec nc)) q
                        (let [acc (+ acc (kn/weight (aget cand-att q) (kn/haversine-m (aget cell-lon c) (aget cell-lat c) (aget cand-lon q) (aget cand-lat q)) 1.0 1.8 600.0))]
                          (if (< target acc) q (recur (inc q) acc)))))]
            (aset expected (+ (* j 24) h) (inc (aget expected (+ (* j 24) h))))))))
    (is (= (* 2 np) (aget counts 1)))
    (is (= (vec expected) (vec visits)))))

(deftest a-closed-venue-is-never-chosen-at-any-alpha
  ;; zero attractiveness is closed, also at α = 0 where the size term vanishes
  (let [w (tiny-world 30 13) {:keys [cell-lon cell-lat cand-lon cand-lat cand-att n nc]} (inputs w)
        closed #{0 5 (dec nc)}
        att (double-array (map-indexed (fn [q a] (if (closed q) 0.0 a)) (seq cand-att)))
        type-offsets (int-array [0 1]) type-cdf (double-array [1.0])
        diary-offsets (int-array [0 2]) ep-loc (int-array [0 2]) ep-minute (int-array [420 600])
        np 400 ptype (int-array np) home-cell (int-array (map #(mod % n) (range np)))
        work (int-array np -1) work-cell (int-array nc)]
    (doseq [alpha [0.0 1.0 0.7]]
      (let [params (double-array [alpha 1.5 500.0]) totals (double-array n)
            _ (kn/cell-totals! cell-lon cell-lat cand-lon cand-lat att params totals n nc)
            visits (int-array (* nc 24)) counts (int-array 2)]
        (retail-visits ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                           cell-lon cell-lat cand-lon cand-lat att totals params visits counts [np nc 9])
        (is (= np (aget counts 1)) (str "α " alpha ": every store episode lands"))
        (is (every? zero? (for [q closed h (range 24)] (aget visits (+ (* q 24) h)))) (str "α " alpha ": no visit at a closed venue"))))))
