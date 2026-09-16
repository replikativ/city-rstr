(ns city.sim.scenario-test
  "The three-class intervention on a tiny world: closing a footprint takes its
   venues out of every class, money is conserved per class and per particle,
   the paired delta of the closed set is minus its baseline, an opened site
   earns in every class it has floor for, and the report's credible bounds
   bracket its means."
  (:require [clojure.test :refer [deftest is testing]]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]
            [city.sim.scenario :as sc]
            [city.synth.segments :as seg]))

(defn- tiny-world [nf seed]
  (let [rng (java.util.Random. seed)
        lon (double-array nf) lat (double-array nf)
        _ (dotimes [j nf] (aset lon j (+ 9.17 (* 0.03 (.nextDouble rng)))) (aset lat j (+ 48.77 (* 0.02 (.nextDouble rng)))))
        ;; three class vectors; every firm has some floor in at least one class,
        ;; a third of them in only one
        atts (into {} (for [s seg/segments] [s (double-array nf)]))
        _ (dotimes [j nf]
            (doseq [[i s] (map-indexed vector seg/segments)]
              (when (or (zero? (mod j 3)) (= i (mod j 3)))
                (aset ^doubles (get atts s) j (* 100.0 (Math/exp (* 3.0 (.nextDouble rng))))))))
        firms {:n nf :lon lon :lat lat :alive (int-array nf 1) :name (vec (map #(str "shop-" %) (range nf)))}
        persons {:n 2 :home-lon (double-array [9.17 9.2]) :home-lat (double-array [48.77 48.79])}
        grid (d2/grid-spec {:firms firms :persons persons})
        n (:n grid)
        pop (long-array n)
        eur (into {} (for [s seg/segments] [s (double-array n)]))
        _ (dotimes [c n] (when (zero? (mod c 7))
                           (let [p (inc (.nextInt rng 40))]
                             (aset pop c p)
                             (doseq [s seg/segments]
                               (aset ^doubles (get eur s) c (* p (+ 500.0 (* 2000.0 (.nextDouble rng)))))))))]
    {:grid grid :firms firms :atts atts
     :dense (cand/build-dense grid firms (int-array nf 1))
     :opts {:cell-pop pop :cell-eur eur}
     :district-of (fn [j] (when (< (long j) nf) (str "d" (mod (long j) 4))))}))

(def spec {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0})
(def thetas {:short {:beta 2.5 :d0-m 300.0} :medium {:beta 1.3 :d0-m 800.0} :long {:beta 2.0 :d0-m 600.0}})

(defn- total [w s] (reduce + (get-in w [:opts :cell-eur s])))

(deftest closing-a-footprint-removes-it-from-every-class-and-conserves-money
  (let [w (tiny-world 40 5) {:keys [dense atts firms]} w
        fp (sc/footprint dense firms atts (aget ^doubles (:lon firms) 0) (aget ^doubles (:lat firms) 0) 600.0)
        closed (set (map :firm fp))
        atts' (sc/close-set atts closed)
        base (sc/outcome3 dense atts spec thetas (:opts w))
        scen (sc/outcome3 dense atts' spec thetas (:opts w))
        d (sc/delta3 dense base dense scen (:district-of w))]
    (is (pos? (count fp)) "the footprint holds the venue it is centred on")
    (is (every? #(< (:distance-m %) 600.0) fp))
    (doseq [s seg/segments]
      (testing (str (name s) ": every euro lands somewhere, before and after")
        (is (< (Math/abs (- (reduce + (get-in base [s :venue-eur])) (total w s))) 1e-6))
        (is (< (Math/abs (- (reduce + (get-in scen [s :venue-eur])) (total w s))) 1e-6))
        (is (get-in d [s :conserved?])))
      (testing (str (name s) ": a closed venue earns nothing and loses exactly its baseline")
        (doseq [{:keys [q firm]} fp]
          (is (zero? (aget ^doubles (get-in scen [s :venue-eur]) q)))
          (is (< (Math/abs (+ (get-in d [s :venue-eur firm]) (aget ^doubles (get-in base [s :venue-eur]) q))) 1e-6))))
      (testing (str (name s) ": district deltas sum to zero")
        (is (< (Math/abs (reduce + (vals (get-in d [s :district-eur])))) 1e-6))))))

(deftest opening-a-site-earns-in-the-classes-it-has-floor-for
  (let [w (tiny-world 30 9) {:keys [dense atts grid]} w
        c (first (filter #(pos? (aget ^longs (get-in w [:opts :cell-pop]) %)) (range (:n grid))))
        [lon lat] (d2/cell-center grid c)
        {dense' :dense atts' :atts j :firm} (sc/open-site grid dense atts lon lat {:short 3000.0 :medium 8000.0})
        district-of (fn [k] (if (= k j) "new" ((:district-of w) k)))
        base (sc/outcome3 dense atts spec thetas (:opts w))
        scen (sc/outcome3 dense' atts' spec thetas (:opts w))
        d (sc/delta3 dense base dense' scen district-of)]
    (is (= 30 j)) (is (= 31 (:nc dense')))
    (is (every? #(= 31 (alength ^doubles (get atts' %))) seg/segments))
    (is (pos? (get-in d [:short :venue-eur j])))
    (is (pos? (get-in d [:medium :venue-eur j])))
    (is (zero? (get-in d [:long :venue-eur j])) "no long-term floor, no long-term euros")
    (is (pos? (get-in d [:medium :district-eur "new"])))
    (is (every? #(get-in d [% :conserved?]) seg/segments))))

(deftest report-brackets-its-means-and-lists-the-intervention
  (let [w (tiny-world 30 2) {:keys [dense atts firms]} w
        fp (take 3 (sc/footprint dense firms atts (aget ^doubles (:lon firms) 1) (aget ^doubles (:lat firms) 1) 2000.0))
        closed (set (map :firm fp))
        particles [{:theta thetas :weight 0.5}
                   {:theta (assoc-in thetas [:medium :beta] 2.2) :weight 0.3}
                   {:theta (assoc-in thetas [:short :d0-m] 900.0) :weight 0.2}]
        rows (sc/across3 particles {:dense dense :atts atts} {:dense dense :atts (sc/close-set atts closed)}
                         spec (:opts w) (:district-of w))
        venues (into {} (map (fn [j] [j {:name (get (:name firms) j) :lon (aget ^doubles (:lon firms) j) :lat (aget ^doubles (:lat firms) j)}]) (range 30)))
        r (sc/report rows {:venues venues :closed (vec fp) :top 5
                           :observations {["d0" :short] 1.0e5}})]
    (is (= 3 (count rows)))
    (is (:conserved? r))
    (is (= 3 (count (:particles r))))
    (testing "credible bounds bracket the mean, min and max are the extremes"
      (doseq [{:keys [delta-total]} (:districts r)]
        (is (<= (:min delta-total) (:q05 delta-total) (:q50 delta-total) (:q95 delta-total) (:max delta-total)))
        (is (<= (:min delta-total) (:mean delta-total) (:max delta-total)))))
    (testing "the closed venues are listed first and lose money in every particle"
      (is (= (map :firm fp) (map :firm (take 3 (:venues r)))))
      (doseq [v (take 3 (:venues r))] (is (neg? (:max (:delta-total v))))))
    (testing "calibration rows carry the observation beside the posterior predictive"
      (is (= [{:district "d0" :class :short}] (map #(select-keys % [:district :class]) (:calibration r))))
      (is (= 1.0e5 (:observed (first (:calibration r)))))
      (is (pos? (:mean (:predicted (first (:calibration r)))))))))

(deftest weighted-quantiles-follow-the-weights
  (let [s (sc/weighted-stats [1 2 3 4] [0.1 0.1 0.1 0.7])]
    (is (= 4.0 (:q50 s))) (is (= 1.0 (:q05 s))) (is (= 4.0 (:q95 s)))
    (is (< (Math/abs (- 3.4 (:mean s))) 1e-12))))

(deftest conservation-fails-when-money-has-nowhere-to-go
  ;; close every venue: the money put in lands nowhere, and the report says so
  (let [w (tiny-world 20 3) {:keys [dense atts]} w
        all (set (map #(aget ^ints (:cand dense) %) (range (:nc dense))))
        base (sc/outcome3 dense atts spec thetas (:opts w))
        scen (sc/outcome3 dense (sc/close-set atts all) spec thetas (:opts w))
        d (sc/delta3 dense base dense scen (:district-of w))]
    (is (every? #(false? (get-in d [% :conserved?])) seg/segments))))

(deftest opening-a-site-with-no-floor-changes-nothing
  ;; the extended index alone must not move a euro: the new column has zero
  ;; attractiveness in every class, so it is outside every choice set
  (let [w (tiny-world 25 4) {:keys [dense atts grid]} w
        [lon lat] (d2/cell-center grid 0)
        {dense' :dense atts' :atts j :firm} (sc/open-site grid dense atts lon lat {})
        base (sc/outcome3 dense atts spec thetas (:opts w))
        scen (sc/outcome3 dense' atts' spec thetas (:opts w))]
    (is (= 25 j))
    (doseq [s seg/segments]
      (is (zero? (aget ^doubles (get-in scen [s :venue-eur]) j)))
      (is (every? true? (map #(< (Math/abs (- (double %1) (double %2))) 1e-9)
                             (get-in base [s :venue-eur]) (butlast (get-in scen [s :venue-eur])))))
      (is (< (Math/abs (- (get-in base [s :expected-km]) (get-in scen [s :expected-km]))) 1e-12)))))
