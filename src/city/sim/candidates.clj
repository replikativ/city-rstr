(ns city.sim.candidates
  "The exact retail choice kernel over every candidate, with no top-K
   truncation.

   `build-dense` computes the distance from every grid cell to every retail
   candidate once, as float32 (about 0.5 GB on Stuttgart). Only the kernel
   weights `A_j^α (1 + d/d₀)^−β` depend on θ = (α, β, d₀), so a new θ is a
   reweight of those stored distances, not a rebuild. Two consumers read them:

   - `table-dense` writes the full choice table in `day/gravity-table`'s CSR
     layout, so `day/step-day` and `day/step-day-traces` can sample shops from
     it;
   - `reduce-dense` computes the expected allocation of money to buckets
     (districts, or single candidates) without materialising the table, which
     is what the likelihood (`city.demo.stuttgart/segmented-simulator`) and the
     scenarios (`city.sim.scenario`) need.

   Why no truncation: measured on Stuttgart, the top 64 venues by weight hold
   30 % of the power kernel's mass and the top 256 about 50 %, so a top-K table
   renormalises a minority of the distribution and K silently becomes a
   behavioural parameter."
  (:require [city.sim.day :as d2]
            [city.sim.world :as w]))

(def ^:private store-kernel
  "What a spec leaves out: the store kernel of `day/default-venue-kernels`."
  (:retail d2/default-venue-kernels))

;; ---- the exact kernel: no truncation at all ------------------------------------------

(defn build-dense
  "Every candidate for every cell, distances precomputed: `{:cand int[nc]
   :dist float[n*nc] :n n :nc nc}`. Row c holds the distance from cell c to
   candidate q at `(+ (* c nc) q)`.

   34,650 cells × 3,637 retail candidates is 126 M float32 distances, about
   0.5 GB, built once; any θ, including a reach bound `:max-m` (a mask on the
   stored distances), is then an exact reweight in seconds.

   Distances are float32: about 1e-5 m at city scale, about 1e-8 relative on a
   probability. Measured against the untruncated double-precision rows on the
   Stuttgart world, total variation 1.5e-8. That is the only sense in which
   exact is qualified.

   `flag` selects the candidates (with the firms' `:alive`), in firm order."
  [grid firms ^ints flag]
  (let [nf (:n firms) ^doubles flon (:lon firms) ^doubles flat (:lat firms) ^ints alive (:alive firms)
        cand (int-array (filter #(and (= 1 (aget flag %)) (= 1 (aget alive %))) (range nf)))
        nc (alength cand) n (:n grid)
        dist (float-array (* n nc))]
    (dotimes [c n]
      (let [[lon lat] (d2/cell-center grid c) lon (double lon) lat (double lat) base (* c nc)]
        (dotimes [q nc]
          (let [j (aget cand q)]
            (aset dist (+ base q) (float (w/haversine-m lon lat (aget flon j) (aget flat j))))))))
    {:cand cand :dist dist :n n :nc nc}))

(defn table-dense
  "The exact choice table for θ from a dense build, in `gravity-table`'s CSR
   layout so `step-day` and every scorer consume it unchanged: every cell's row
   is all `nc` candidates in candidate order, cdf normalised to 1.

   `spec` is a kernel spec as in `day/default-venue-kernels`,
   `{:kernel :power|:exp :alpha :beta :d0-m :lambda-m :max-m}`, with missing
   keys taken from the store kernel there; `:k` is ignored, there is no
   truncation. `:max-m`
   zeroes every candidate beyond the reach; `pick-from-cdf`'s strict `<` never
   selects a zero-width interval, so masked venues are never chosen. A cell with
   nothing in reach falls back to uniform over its row, as `gravity-table` does
   when its weights sum to zero.

   Pass `:into` a previous result to reuse its arrays: the venues array is
   identical for every θ and the cdf is overwritten in place, which avoids
   allocating about 1.5 GB per θ on Stuttgart."
  [{:keys [^ints cand ^floats dist n nc]} attract spec & {:keys [into]}]
  (let [{:keys [alpha beta d0-m kernel lambda-m max-m]} (merge store-kernel spec)
        n (long n) nc (long nc)
        alpha (double alpha) power? (= :power kernel)
        inv-d0 (/ 1.0 (double d0-m)) beta (double beta)
        bmode (long (cond (= 1.0 beta) 1 (= 2.0 beta) 2 (= 3.0 beta) 3 :else 0)) nbeta (- beta)
        neg-inv-lambda (/ -1.0 (double lambda-m))
        bounded? (boolean (and max-m (pos? (double max-m)))) mx (double (or max-m 0.0))
        ;; attract^α once per candidate
        ^doubles aw (let [a (double-array nc)]
                      (dotimes [q nc]
                        (aset a q (let [x (if attract (aget ^doubles attract (aget cand q)) 1.0)]
                                    (cond (zero? alpha) 1.0 (= 1.0 alpha) (max 0.0 x) :else (Math/pow (max 0.0 x) alpha)))))
                      a)
        ^ints venues (or (:venues into)
                         (let [v (int-array (* n nc))]
                           (dotimes [c n] (System/arraycopy cand 0 v (* c nc) nc))
                           v))
        ^doubles cdf (or (:cdf into) (double-array (* n nc)))
        ^ints offsets (or (:offsets into)
                          (let [o (int-array (inc n))] (dotimes [c n] (aset o (inc c) (* (inc c) nc))) o))
        row (double-array nc)]
    (dotimes [c n]
      (let [base (* c nc)]
        (loop [q 0 total 0.0]
          (if (< q nc)
            (let [d (double (aget dist (+ base q)))
                  wgt (if (and bounded? (> d mx))
                        0.0
                        (* (aget aw q)
                           (if power?
                             (let [x (+ 1.0 (* d inv-d0))]
                               (case bmode 1 (/ 1.0 x) 2 (/ 1.0 (* x x)) 3 (/ 1.0 (* x x x)) (Math/pow x nbeta)))
                             (Math/exp (* d neg-inv-lambda)))))]
              (aset row q wgt)
              (recur (inc q) (+ total wgt)))
            (loop [q 0 acc 0.0]
              (when (< q nc)
                (let [acc (+ acc (if (pos? total) (/ (aget row q) total) (/ 1.0 nc)))]
                  (aset cdf (+ base q) acc)
                  (recur (inc q) acc))))))))
    {:offsets offsets :venues venues :cdf cdf :k nc :dense true}))

;; ---- the fused reduction: an expected allocation without a CSR --------------------------

(defn candidate-weights
  "A_q^α for every candidate `q` (firm `cand[q]`), zero for a candidate whose
   attractiveness is not positive: it is not in the choice set. Shared by
   `reduce-dense` and its device version (`city.sim.device`), so both start
   from the same numbers."
  ^doubles [^ints cand ^doubles attract alpha]
  (let [alpha (double alpha) nc (alength cand) a (double-array nc)]
    (dotimes [q nc]
      (let [x (double (aget attract (aget cand q)))]
        (aset a q (if (pos? x)
                    (cond (zero? alpha) 1.0 (= 1.0 alpha) x :else (Math/pow x alpha))
                    0.0))))
    a))

(defn reduce-dense
  "The exact kernel's expected allocation, accumulated straight into buckets,
   with no choice table materialised.

   `table-dense` writes a cdf of `n × nc` doubles — 1.0 GB on Stuttgart — which
   `step-day` needs because it samples, and which a *likelihood* does not,
   because it only ever reduces over it. Three segments would have cost 3 GB of
   cdf to compute three numbers per district. This computes the same
   expectation in one pass with an `nc` scratch row, so the segmented model
   costs the same memory as the unsegmented one and one reweight per segment.

   `spec` is the kernel as for `table-dense`. `opts`:
   - `:cell-value` double[n]  — what each cell has to allocate (euros)
   - `:bucket` int[nc]        — the bucket each *candidate* belongs to
   - `:n-buckets`             — how many
   - `:cell-pop` long[n]      — weights for the expected-distance figure

   **A candidate whose attractiveness is not positive is not in the choice
   set.** `table-dense` treats α = 0 as \"every candidate weighs 1\", which is
   right for a size-free kernel and wrong for a segmented one, where a zero is
   how a namespace says this shop sells no clothing. Here the exclusion is
   explicit and independent of α.

   Returns `{:bucket double[n-buckets] :allocated total :expected-distance-m d
             :cells-served k}`."
  [{:keys [^ints cand ^floats dist n nc]} ^doubles attract spec
   {:keys [^doubles cell-value ^ints bucket n-buckets ^longs cell-pop]}]
  (let [{:keys [alpha beta d0-m kernel lambda-m max-m]} (merge store-kernel spec)
        n (long n) nc (long nc) nb (long n-buckets)
        alpha (double alpha) power? (= :power kernel)
        inv-d0 (/ 1.0 (double d0-m)) beta (double beta)
        bmode (long (cond (= 1.0 beta) 1 (= 2.0 beta) 2 (= 3.0 beta) 3 :else 0)) nbeta (- beta)
        neg-inv-lambda (/ -1.0 (double lambda-m))
        bounded? (boolean (and max-m (pos? (double max-m)))) mx (double (or max-m 0.0))
        ^doubles aw (candidate-weights cand attract alpha)
        out (double-array nb)
        row (double-array nc)
        acc (double-array 3)]                     ; allocated, dist-num, dist-den
    (dotimes [c n]
      (let [base (* c nc)
            v (double (aget cell-value c))
            p (double (aget cell-pop c))]
        (when (or (pos? v) (pos? p))
          (let [total (loop [q 0 t 0.0]
                        (if (= q nc) t
                            (let [a (aget aw q)]
                              (if (zero? a)
                                (do (aset row q 0.0) (recur (inc q) t))
                                (let [d (double (aget dist (+ base q)))
                                      w (if (and bounded? (> d mx))
                                          0.0
                                          (* a (if power?
                                                 (let [x (+ 1.0 (* d inv-d0))]
                                                   (case bmode 1 (/ 1.0 x) 2 (/ 1.0 (* x x)) 3 (/ 1.0 (* x x x)) (Math/pow x nbeta)))
                                                 (Math/exp (* d neg-inv-lambda)))))]
                                  (aset row q w)
                                  (recur (inc q) (+ t w)))))))]
            (when (pos? total)
              (let [inv (/ 1.0 total)
                    ds (loop [q 0 s 0.0]
                         (if (= q nc) s
                             (let [w (aget row q)]
                               (if (zero? w) (recur (inc q) s)
                                   (let [m (* w inv) b (aget bucket q)]
                                     (aset out b (+ (aget out b) (* v m)))
                                     (recur (inc q) (+ s (* m (double (aget dist (+ base q)))))))))))]
                (aset acc 0 (+ (aget acc 0) v))
                (when (pos? p)
                  (aset acc 1 (+ (aget acc 1) (* p ds)))
                  (aset acc 2 (+ (aget acc 2) p)))))))))
    {:bucket out
     :allocated (aget acc 0)
     :expected-distance-m (when (pos? (aget acc 2)) (/ (aget acc 1) (aget acc 2)))
     :cells-served (count (filter #(pos? (double (aget cell-value %))) (range n)))}))
