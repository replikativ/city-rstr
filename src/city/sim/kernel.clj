(ns city.sim.kernel
  "The day's store decisions and the likelihood as raster kernels: every
   inhabitant, no choice table.

   A choice table for the store kernel is 1 GB per demand class on Stuttgart
   and seconds to rebuild per θ. Without one, a store episode in cell `c`
   walks the 3,637 retail candidates, computes each one's weight from
   coordinates on the spot, and stops where the running sum passes `u · Z_c`.
   The inputs are ~38,000 coordinate pairs and one number per candidate, under
   a megabyte.

   `raster.par/map-void!` over an index with inner loops, the shape raster
   compiles for a GPU. Run uncompiled they are plain JVM loops, which is how
   the tests and the demo run them; `dev/checks/kernel_device.clj` and
   `likelihood_device.clj` compare a device run with the JVM.

   - `cell-totals!`: Z_c = Σ_j A_j^α (1 + d_cj/d₀)^−β for every cell.
   - `store-choices!`: every store episode's demand class, leakage and venue,
     which the money day, the traced day and the untraced day all read, so a
     person's trip, visit and spending come from one decision. Same
     counter-addressed draws as `day/uniform`.
   - `dense-cell-totals!`, `dense-cell-distance!`, `dense-candidate-mass!`:
     the likelihood's expected allocation (`city.sim.device`).

   Parameters travel in small arrays: `params` = [α β d₀] because `invoke!`
   scalars are int, float or long, and `dims` = [n nc seed ...] because a Clojure
   fn takes at most twenty positional arguments. The compiler hoists the
   `let` that reads them into kernel scalars, so on the device they arrive as
   scalar arguments in the ABI's order.

   Draws are `day/uniform`: splitmix(stream key + k), the stream key
   splitmix(seed·1000003 + i) computed once per person. The splitmix draw is
   written out inside the kernel body: raster's C
   emitter lowers 64-bit arithmetic there, but a helper `deftm` with integer
   parameters reaches the emitter un-devirtualised and its `unchecked-*`
   operators come out as bare symbols (raster `c_emit.clj`, the infix branch's
   `op-map`). Every helper in the namespace is emitted into the kernel source,
   so a broken helper breaks the whole kernel even if nothing calls it."
  ;; No `and`/`or` in the kernel bodies: they expand to boolean bindings the C
  ;; emitter does not type; conditions are counted instead.
  (:refer-clojure :exclude [aget aset alength aclone])
  (:require [raster.core :refer [deftm]]
            [raster.arrays :refer [aget aset alength]]
            [raster.par :as par]))


;; Literals are written out inside the kernels: a var reference, even a
;; ^:const one, reaches the C emitter as a bare symbol (`earth_m`).
(deftm haversine-m
  "Great-circle metres between two lon/lat points in degrees; the atan2 form,
   which every backend has, equal to `world/haversine-m`'s asin form."
  [lon1 :- Double, lat1 :- Double, lon2 :- Double, lat2 :- Double] :- Double
  (let [rlat1 (* lat1 0.017453292519943295) rlat2 (* lat2 0.017453292519943295)
        dlat (- rlat2 rlat1) dlon (* (- lon2 lon1) 0.017453292519943295)
        sdlat (Math/sin (* 0.5 dlat)) sdlon (Math/sin (* 0.5 dlon))
        a (+ (* sdlat sdlat) (* (Math/cos rlat1) (Math/cos rlat2) sdlon sdlon))]
    (* 12742000.0 (Math/atan2 (Math/sqrt a) (Math/sqrt (- 1.0 a))))))

(deftm weight
  "A_j^α (1 + d/d₀)^−β, the power kernel. A candidate with non-positive A is
   not in the choice set at any α — zero is how a class vector says a venue
   sells nothing of the class, or is closed — which is `reduce-dense`'s
   convention; α = 0 removes the size term of every candidate that is."
  [att :- Double, d :- Double, alpha :- Double, beta :- Double, d0 :- Double] :- Double
  (let [a (if (<= att 0.0) 0.0 (if (== alpha 0.0) 1.0 (if (== alpha 1.0) att (Math/pow att alpha))))
        x (+ 1.0 (/ d d0))]
    (* a (Math/pow x (- 0.0 beta)))))

(deftm cell-totals!
  "Z_c for every cell: the normaliser of the choice distribution."
  [cell-lon :- (Array double), cell-lat :- (Array double),
   cand-lon :- (Array double), cand-lat :- (Array double), cand-att :- (Array double),
   params :- (Array double), totals :- (Array double),
   n-cells :- Long, nc :- Long] :- Void
  (let [alpha (aget params 0) beta (aget params 1) d0 (aget params 2)]
    (par/map-void! c n-cells
      (let [lon (aget cell-lon c) lat (aget cell-lat c)]
        (loop [q (int 0) z 0.0]
          (if (< q nc)
            (recur (unchecked-add-int q 1)
                   (+ z (weight (aget cand-att q) (haversine-m lon lat (aget cand-lon q) (aget cand-lat q)) alpha beta d0)))
            (aset totals c z)))))))

;; ---- the store decision ------------------------------------------------------------------

(deftm store-choices!
  "Every store episode's decision, for every person `i`: the demand class, the
   leakage, and the venue, the one choice that the money day, the traced day
   and the untraced day all read (`city.econ.day/money-from-choices`,
   `city.sim.day/step-day`, `step-day-traces`).

   A store episode first draws its class `s` from `shares` (cumulative trip
   shares, draw index 100000 + k), then whether the purchase leaves the city
   (index 200000 + k, residents with a home cell only), then its venue from
   that class's kernel (index k + 1, as `step-day` draws its other venues):
   `att3`, `totals3` and `params3` hold the three classes stacked,
   class-major.

   `shares` = [π₀ π₀+π₁ 1 | ℓ_short ℓ_medium ℓ_long]: the cumulative class
   shares of shopping trips, then the leakage share per class. In-commuters
   have a home cell too, at their entry point on the boundary
   (`city.sim.cityworld/place-externals!`), so they take the leakage draw as
   well; that changes nothing as long as no class has both an inflow and a
   leakage share, which `city.econ.day/class-balances` guarantees.

   `store-rank[e]` is episode `e`'s place among its diary's store episodes
   (`city.econ.day/store-ranks`); a loop carry counting them would do the same,
   but raster 0.2.951 does not lower an effectful loop with that third carry.

   Out: `diary[i]`, which the caller fills with −1 (a person with no day),
   the diary drawn, and
   `choice[i·max-s + r]`, which the caller fills with −9 (no such episode),
   for the person's r-th store episode: `q·3 + s` for a
   visit to candidate `q`, `−1 − s` for a leaked purchase and `−4 − s` for an
   anchor cell that reaches no venue of the class. `dims` = [n nc seed ncell
   max-s]; coordinates are interleaved, `cell-xy[2c]` = lon,
   `cell-xy[2c+1]` = lat."
  [ptype :- (Array int), home-cell :- (Array int), work :- (Array int), work-cell :- (Array int),
   type-offsets :- (Array int), type-cdf :- (Array double),
   diary-offsets :- (Array int), ep-loc :- (Array int),
   cell-xy :- (Array double), cand-xy :- (Array double),
   att3 :- (Array double), totals3 :- (Array double), params3 :- (Array double), shares :- (Array double),
   store-rank :- (Array int), diary :- (Array int), choice :- (Array int),
   dims :- (Array long)] :- Void
  (let [n (aget dims 0) nc (aget dims 1) seed (aget dims 2) ncell (aget dims 3) max-s (aget dims 4)]
    (par/map-void! i n
      (let [t (aget ptype i) wj (aget work i) hc (aget home-cell i)]
        (when (>= (int (+ (if (>= t (int 0)) 1 0) (if (>= hc (int 0)) 1 (if (>= wj (int 0)) 1 0)))) (int 2))
          (let [a (int (aget type-offsets t)) b (int (aget type-offsets (unchecked-add-int t 1)))
                ;; stream key splitmix(seed·1000003 + i), then the diary draw splitmix(key + 0)
                xs (long (unchecked-add (unchecked-multiply (long seed) 1000003) (long i)))
                zs (long (unchecked-add xs -7046029254386353131))
                zs (long (unchecked-multiply (bit-xor zs (unsigned-bit-shift-right zs 30)) -4658895280553007687))
                zs (long (unchecked-multiply (bit-xor zs (unsigned-bit-shift-right zs 27)) -7723592293110705685))
                key (long (bit-xor zs (unsigned-bit-shift-right zs 31)))
                z0 (long (unchecked-add key -7046029254386353131))
                z0 (long (unchecked-multiply (bit-xor z0 (unsigned-bit-shift-right z0 30)) -4658895280553007687))
                z0 (long (unchecked-multiply (bit-xor z0 (unsigned-bit-shift-right z0 27)) -7723592293110705685))
                z0 (long (bit-xor z0 (unsigned-bit-shift-right z0 31)))
                u0 (/ (double (unsigned-bit-shift-right z0 11)) 9007199254740992.0)
                d (int (loop [lo (int a) hi (int (unchecked-add-int b -1))]
                         (if (>= lo hi) lo
                             (let [m (int (quot (unchecked-add-int lo hi) 2))]
                               (if (< u0 (aget type-cdf m)) (recur lo m) (recur (int (unchecked-add-int m 1)) hi))))))
                e0 (int (aget diary-offsets d)) e1 (int (aget diary-offsets (unchecked-add-int d 1)))
                start (int (if (>= hc (int 0)) hc (aget work-cell wj)))]
            ;; d + 1 onto the caller's −1, atomically: raster 0.2.951 on a
            ;; device drops the episode loop, effects and all, unless the body
            ;; around it holds an atomic
            (par/atomic-add! diary i (int (unchecked-add-int d 1)))
            (loop [e (int e0) anchor (int start)]
              (when (< e e1)
                (let [loc (int (aget ep-loc e))
                      k (int (unchecked-add-int e (- 0 e0)))]
                  ;; one back edge per iteration (raster lowers an effectful loop
                  ;; with a single recur): the store episode is an effect-only
                  ;; branch, then the anchor update
                  (do (when (== loc (int 2))
                        (let [;; class draw, index 100000 + k
                              xc (long (unchecked-add key (long (unchecked-add-int k 100000))))
                              zc (long (unchecked-add xc -7046029254386353131))
                              zc (long (unchecked-multiply (bit-xor zc (unsigned-bit-shift-right zc 30)) -4658895280553007687))
                              zc (long (unchecked-multiply (bit-xor zc (unsigned-bit-shift-right zc 27)) -7723592293110705685))
                              zc (long (bit-xor zc (unsigned-bit-shift-right zc 31)))
                              uc (/ (double (unsigned-bit-shift-right zc 11)) 9007199254740992.0)
                              s (int (if (< uc (aget shares 0)) 0 (if (< uc (aget shares 1)) 1 2)))
                              ;; leakage draw, index 200000 + k; residents only
                              xl (long (unchecked-add key (long (unchecked-add-int k 200000))))
                              zl (long (unchecked-add xl -7046029254386353131))
                              zl (long (unchecked-multiply (bit-xor zl (unsigned-bit-shift-right zl 30)) -4658895280553007687))
                              zl (long (unchecked-multiply (bit-xor zl (unsigned-bit-shift-right zl 27)) -7723592293110705685))
                              zl (long (bit-xor zl (unsigned-bit-shift-right zl 31)))
                              ul (/ (double (unsigned-bit-shift-right zl 11)) 9007199254740992.0)
                              leaked (int (if (>= hc (int 0)) (if (< ul (aget shares (unchecked-add-int 3 s))) 1 0) 0))
                              alpha (aget params3 (unchecked-add-int (* s 3) 0))
                              beta (aget params3 (unchecked-add-int (* s 3) 1))
                              d0 (aget params3 (unchecked-add-int (* s 3) 2))
                              ;; venue draw, index k + 1, as step-day
                              x1 (long (unchecked-add key (long (unchecked-add-int k 1))))
                              z1 (long (unchecked-add x1 -7046029254386353131))
                              z1 (long (unchecked-multiply (bit-xor z1 (unsigned-bit-shift-right z1 30)) -4658895280553007687))
                              z1 (long (unchecked-multiply (bit-xor z1 (unsigned-bit-shift-right z1 27)) -7723592293110705685))
                              z1 (long (bit-xor z1 (unsigned-bit-shift-right z1 31)))
                              u (/ (double (unsigned-bit-shift-right z1 11)) 9007199254740992.0)
                              z (aget totals3 (unchecked-add-int (* s ncell) anchor))
                              lon (aget cell-xy (* anchor 2)) lat (aget cell-xy (unchecked-add-int (* anchor 2) 1))
                              target (* u z)
                              abase (int (* s nc))
                              ;; the first candidate whose cumulative weight passes u·Z; if
                              ;; rounding leaves the target past the last increment, the last
                              ;; candidate with weight; −1 when the cell reaches none.
                              ;; One exit: the hit rides in a carry and ends the loop at the next test
                              j (int (loop [q (int 0) acc 0.0 last (int -1) hit (int -1)]
                                       (if (>= (int (+ (if (>= q (int nc)) 1 0) (if (>= hit (int 0)) 1 0))) (int 1))
                                         (if (>= hit (int 0)) hit last)
                                         (let [wq (weight (aget att3 (unchecked-add-int abase q))
                                                          (haversine-m lon lat (aget cand-xy (* q 2)) (aget cand-xy (unchecked-add-int (* q 2) 1)))
                                                          alpha beta d0)
                                               acc2 (+ acc wq)]
                                           (recur (int (unchecked-add-int q 1)) acc2 (int (if (> wq 0.0) q last))
                                                  (int (if (> wq 0.0) (if (< target acc2) q -1) -1)))))))]
                          ;; an atomic add of code + 9 onto the −9 the caller fills
                          ;; in: each slot is written once, so this is a store.
                          ;; raster 0.2.951 drops a plain aset in this branch
                          ;; on a device, silently
                          (par/atomic-add! choice (+ (* i max-s) (aget store-rank e))
                                           (int (+ 9 (if (== leaked (int 1)) (- -1 s)
                                                          (if (>= j (int 0)) (unchecked-add-int (* j 3) s) (- -4 s))))))))
                      (recur (int (unchecked-add-int e 1))
                             ;; home after a home episode, the workplace after a work
                             ;; episode, otherwise the anchor stays
                             (int (if (== loc (int 0)) (if (>= hc (int 0)) hc anchor)
                                      (if (== (int (+ (if (== loc (int 1)) 1 0) (if (>= wj (int 0)) 1 0))) (int 2))
                                        (aget work-cell wj)
                                        anchor))))))))))))))

;; ---- the likelihood on a device -----------------------------------------------------------
;;
;; `candidates/reduce-dense` as three passes with no atomics, so the result does
;; not depend on scheduling: per cell the normaliser, per cell the weighted
;; distance, then per candidate the money it receives from every cell. All
;; read the stored float32 distances, candidate-major here (`dist-t[q·n + c]`,
;; the transpose of `build-dense`'s rows) so that neighbouring threads read
;; neighbouring distances in every pass, and A_q^α computed on the host, as
;; `reduce-dense` does. `params` = [1/d₀ −β βmode] with βmode 1, 2 or 3 for
;; β = 1, 2, 3 (exact reciprocals, as `reduce-dense`) and 0 for `Math/pow`.
;; The normaliser and the distance are separate kernels because raster 0.2.951
;; does not lower a loop that ends in two stores.

(deftm dense-weight
  "The power kernel's distance factor (1 + d/d₀)^−β, as `reduce-dense` computes it."
  [d :- Double, inv-d0 :- Double, nbeta :- Double, bmode :- Double] :- Double
  (let [x (+ 1.0 (* d inv-d0))]
    (if (== bmode 1.0) (/ 1.0 x)
        (if (== bmode 2.0) (/ 1.0 (* x x))
            (if (== bmode 3.0) (/ 1.0 (* x x x)) (Math/pow x nbeta))))))

(deftm dense-cell-totals!
  "Z_c = Σ_q w_cq for every cell `c`, over the candidates with positive `aw`."
  [dist-t :- (Array float), aw :- (Array double), params :- (Array double),
   z :- (Array double), n :- Long, nc :- Long] :- Void
  (let [inv-d0 (aget params 0) nbeta (aget params 1) bmode (aget params 2)]
    (par/map-void! c n
      (loop [q (int 0) t 0.0]
        (if (< q nc)
          (let [a (aget aw q)
                w (if (> a 0.0) (* a (dense-weight (double (aget dist-t (+ (* q n) c))) inv-d0 nbeta bmode)) 0.0)]
            (recur (unchecked-add-int q 1) (+ t w)))
          (aset z c t))))))

(deftm dense-cell-distance!
  "D_c = Σ_q w_cq·d_cq for every cell `c`: with Z_c, the cell's expected
   distance to the shop it chooses."
  [dist-t :- (Array float), aw :- (Array double), params :- (Array double),
   dz :- (Array double), n :- Long, nc :- Long] :- Void
  (let [inv-d0 (aget params 0) nbeta (aget params 1) bmode (aget params 2)]
    (par/map-void! c n
      (loop [q (int 0) s 0.0]
        (if (< q nc)
          (let [a (aget aw q)
                d (double (aget dist-t (+ (* q n) c)))
                w (if (> a 0.0) (* a (dense-weight d inv-d0 nbeta bmode)) 0.0)]
            (recur (unchecked-add-int q 1) (+ s (* w d))))
          (aset dz c s))))))

(deftm dense-candidate-mass!
  "The money candidate `q` receives from the cells b, b+B, b+2B, … (B =
   `blocks`), Σ_c v_c·w_cq/Z_c over those with a positive normaliser, into
   `mass[q·B + b]`; the host adds the blocks in order. Blocks keep the work per
   thread short (one thread per candidate would walk all 34,650 cells), and
   the stride keeps neighbouring threads on neighbouring cells. Zero outside
   the choice set."
  [dist-t :- (Array float), aw :- (Array double), params :- (Array double),
   cell-value :- (Array double), z :- (Array double), mass :- (Array double),
   n :- Long, nc :- Long, blocks :- Long] :- Void
  (let [inv-d0 (aget params 0) nbeta (aget params 1) bmode (aget params 2)]
    (par/map-void! t (* nc blocks)
      (let [q (quot t blocks) b (rem t blocks) a (aget aw q)
            steps (quot (+ n (- blocks 1)) blocks)]
        ;; a unit-step counter: raster does not lower a loop that starts at b
        ;; and steps by `blocks`
        (loop [k 0 m 0.0]
          (if (< k steps)
            (let [c (+ b (* k blocks))
                  zc (if (< c n) (aget z c) 0.0)
                  ;; v·(w·(1/Z)), the order `reduce-dense` multiplies in
                  add (if (> zc 0.0)
                        (if (> a 0.0)
                          (* (aget cell-value c) (* (* a (dense-weight (double (aget dist-t (+ (* q n) c))) inv-d0 nbeta bmode)) (/ 1.0 zc)))
                          0.0)
                        0.0)]
              (recur (+ k 1) (+ m add)))
            (aset mass t m)))))))
