(ns city.sim.candidates-test
  "The dense choice table must be the untruncated `gravity-table`, and the
   fused reduction must equal the expectation over that table."
  (:require [clojure.test :refer [deftest is testing]]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]))

(defn- tiny-world
  "A 600 m × 600 m patch with `nf` venues on a seeded grid-ish scatter, so the
   grid is a few dozen cells and every venue is in reach."
  [nf seed]
  (let [rng (java.util.Random. seed)
        lon (double-array nf) lat (double-array nf)
        _ (dotimes [j nf]
            (aset lon j (+ 9.17 (* 0.008 (.nextDouble rng))))
            (aset lat j (+ 48.77 (* 0.0055 (.nextDouble rng)))))
        attract (double-array nf)
        _ (dotimes [j nf] (aset attract j (Math/exp (* 3.0 (.nextDouble rng)))))
        firms {:n nf :lon lon :lat lat :alive (int-array nf 1)}
        persons {:n 2 :home-lon (double-array [9.17 9.178]) :home-lat (double-array [48.77 48.7755])}]
    {:firms firms :persons persons :attract attract
     :flag (int-array nf 1)
     :grid (d2/grid-spec {:firms firms :persons persons})}))

(defn- row-dist [{:keys [^ints offsets ^ints venues ^doubles cdf]} c]
  (let [a (aget offsets c) b (aget offsets (inc c))]
    (loop [p a prev 0.0 m {}]
      (if (= p b) m
          (let [cur (aget cdf p)] (recur (inc p) cur (assoc m (aget venues p) (- cur prev))))))))

(defn- same-distribution?
  "Same choice distribution per cell, comparing only venues with positive
   probability on either side: gravity-table pads unfilled top-K slots with
   venue -1 at zero weight, and a reach bound masks venues to zero. Tolerance
   is 1e-6, not 1e-12 — build-dense stores float32 distances, so probabilities
   agree to about 1e-8 relative and no tighter."
  [a b n]
  (every? (fn [c] (let [pos (fn [m] (into {} (filter #(pos? (double (val %))) m)))
                        p (pos (row-dist a c)) q (pos (row-dist b c))]
                    (and (= (set (keys p)) (set (keys q)))
                         (every? #(< (Math/abs (- (double (p %)) (double (q %)))) 1e-6) (keys p)))))
          (range n)))

(deftest dense-table-is-the-untruncated-kernel
  ;; gravity-table with K = every candidate keeps them all, i.e. it IS the exact
  ;; kernel; the dense table must be that same distribution, cell for cell.
  (let [{:keys [grid firms flag attract]} (tiny-world 40 5)
        dense (cand/build-dense grid firms flag)]
    (doseq [spec [{:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0 :k 40}
                  {:kernel :power :alpha 1.3 :beta 2.0 :d0-m 300.0 :k 40}
                  {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0 :k 40 :max-m 250.0}   ; reach bound
                  {:kernel :exp :lambda-m 400.0 :alpha 1.0 :k 40}]]
      (testing (pr-str spec)
        (let [ref (apply d2/gravity-table grid firms flag (apply concat (assoc spec :attract attract)))
              dns (cand/table-dense dense attract spec)]
          (is (same-distribution? ref dns (:n grid))))))))

(deftest dense-table-reuses-buffers-across-theta
  (let [{:keys [grid firms flag attract]} (tiny-world 30 9)
        dense (cand/build-dense grid firms flag)
        t1 (cand/table-dense dense attract {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0})
        c1 (vec (:cdf t1))
        t2 (cand/table-dense dense attract {:kernel :power :alpha 1.0 :beta 3.0 :d0-m 500.0} :into t1)]
    (is (identical? (:venues t1) (:venues t2)))
    (is (identical? (:cdf t1) (:cdf t2)))
    (is (not= c1 (vec (:cdf t2))) "the cdf was rewritten in place for the new θ")
    (is (same-distribution? (d2/gravity-table grid firms flag :kernel :power :alpha 1.0 :beta 3.0 :d0-m 500.0 :k 30 :attract attract)
                            t2 (:n grid)))))

;; ---- the fused reduction ------------------------------------------------------------------

(defn- reduce-via-table
  "The same expectation computed the slow way: build the CSR, walk it. This is
   the reference `reduce-dense` has to reproduce."
  [dense attract spec {:keys [^doubles cell-value ^ints bucket n-buckets ^longs cell-pop]}]
  (let [{:keys [^ints offsets ^ints venues ^doubles cdf]} (cand/table-dense dense attract spec)
        {:keys [^ints cand ^floats dist nc n]} dense
        q-of (into {} (map-indexed (fn [q j] [j q]) (seq cand)))
        out (double-array n-buckets)]
    (loop [c 0 num 0.0 den 0.0 alloc 0.0]
      (if (= c n)
        {:bucket out :allocated alloc :expected-distance-m (when (pos? den) (/ num den))}
        (let [a (aget offsets c) b (aget offsets (inc c))
              v (aget cell-value c) p (double (aget cell-pop c))]
          (if (and (zero? v) (zero? p))
            (recur (inc c) num den alloc)
            (let [[ds] (loop [k a prev 0.0 s 0.0]
                         (if (= k b) [s]
                             (let [cur (aget cdf k) m (- cur prev)
                                   j (aget venues k) q (q-of j)]
                               (when (pos? m)
                                 (aset out (aget bucket q) (+ (aget out (aget bucket q)) (* v m))))
                               (recur (inc k) cur (+ s (* m (double (aget dist (+ (* c nc) q)))))))))]
              (recur (inc c) (+ num (* p ds)) (+ den p) (+ alloc v)))))))))

(defn- close? [a b tol] (< (Math/abs (- (double a) (double b))) tol))

(deftest the-fused-reduction-equals-the-table-it-does-not-build
  (let [w (tiny-world 40 17)
        dense (cand/build-dense (:grid w) (:firms w) (:flag w))
        n (:n (:grid w)) nc (:nc dense)
        rng (java.util.Random. 5)
        cell-value (double-array n) cell-pop (long-array n)
        _ (dotimes [c n] (when (zero? (mod c 3))
                           (let [p (inc (.nextInt rng 30))]
                             (aset cell-pop c p) (aset cell-value c (* 1000.0 p)))))
        bucket (int-array (map #(mod (long %) 4) (seq (:cand dense))))
        opts {:cell-value cell-value :bucket bucket :n-buckets 4 :cell-pop cell-pop}]
    (doseq [spec [{:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0}
                  {:kernel :power :alpha 1.3 :beta 2.4 :d0-m 900.0}
                  {:kernel :exp :alpha 1.0 :lambda-m 400.0}]]
      (let [fast (cand/reduce-dense dense (:attract w) spec opts)
            slow (reduce-via-table dense (:attract w) spec opts)
            total (reduce + (seq cell-value))]
        (testing (str spec)
          (is (every? true? (map #(close? %1 %2 1e-6) (:bucket fast) (:bucket slow)))
              (str (vec (:bucket fast)) " vs " (vec (:bucket slow))))
          (is (close? (:expected-distance-m fast) (:expected-distance-m slow) 1e-9))
          (is (close? (:allocated fast) total 1e-9))
          (testing "and every euro lands in some bucket"
            (is (close? (reduce + (:bucket fast)) total 1e-6))))))
    (is (= nc (alength ^ints (:cand dense))))))

(deftest a-candidate-with-no-attractiveness-is-not-in-the-choice-set
  (let [w (tiny-world 24 9)
        dense (cand/build-dense (:grid w) (:firms w) (:flag w))
        n (:n (:grid w)) nc (:nc dense)
        cell-value (double-array n 100.0) cell-pop (long-array n 1)
        ;; bucket 1 holds exactly one candidate; zero its attractiveness
        target (aget ^ints (:cand dense) 0)
        bucket (int-array (map #(if (= (long %) (long target)) 1 0) (seq (:cand dense))))
        zeroed (let [a (aclone ^doubles (:attract w))] (aset a target 0.0) a)
        opts {:cell-value cell-value :bucket bucket :n-buckets 2 :cell-pop cell-pop}
        with (cand/reduce-dense dense (:attract w) {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0} opts)
        without (cand/reduce-dense dense zeroed {:kernel :power :alpha 1.0 :beta 1.6 :d0-m 500.0} opts)]
    (is (pos? (aget ^doubles (:bucket with) 1)) "it earns when it has floor area")
    (is (zero? (aget ^doubles (:bucket without) 1)) "and nothing when it has none")
    (testing "the money is conserved either way"
      (is (close? (reduce + (:bucket without)) (* 100.0 n) 1e-6)))
    (testing "alpha 0 does not resurrect it, which is why the segmented model uses this"
      (let [a0 (cand/reduce-dense dense zeroed {:kernel :power :alpha 0.0 :beta 1.6 :d0-m 500.0} opts)]
        (is (zero? (aget ^doubles (:bucket a0) 1)))))
    (is (pos? nc))))
