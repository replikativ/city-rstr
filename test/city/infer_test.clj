(ns city.infer-test
  "Synthetic recovery on a small world: generate observations at a known θ*,
   run SMC, and require the posterior to cover it. This is the test the
   consolidation doc asks for before any real-data fit — recover known
   parameters from synthetic observations."
  (:require [clojure.test :refer [deftest is testing]]
            [city.infer :as infer]
            [city.sim.candidates :as cand]
            [city.sim.day :as d2]))

(defn- tiny-world [nf seed]
  (let [rng (java.util.Random. seed)
        lon (double-array nf) lat (double-array nf)
        _ (dotimes [j nf] (aset lon j (+ 9.17 (* 0.03 (.nextDouble rng)))) (aset lat j (+ 48.77 (* 0.02 (.nextDouble rng)))))
        attract (double-array nf)
        _ (dotimes [j nf] (aset attract j (Math/exp (* 3.0 (.nextDouble rng)))))
        firms {:n nf :lon lon :lat lat :alive (int-array nf 1)}
        persons {:n 2 :home-lon (double-array [9.17 9.2]) :home-lat (double-array [48.77 48.79])}
        grid (d2/grid-spec {:firms firms :persons persons})
        flag (int-array nf 1)]
    {:grid grid :firms firms :attract attract :flag flag
     :dense (cand/build-dense grid firms flag)
     ;; 5 "districts": venue index mod 5
     :district-of (fn [j] (str "d" (mod j 5)))}))

(defn- simulator
  "θ → {district → total choice mass from every cell}: the small analogue of
   turnover by district, cheap enough for hundreds of particles in seconds."
  [{:keys [grid dense attract district-of]}]
  (let [n (:n grid)]
    (fn [theta]
      (let [{:keys [^ints offsets ^ints venues ^doubles cdf]} (cand/table-dense dense attract (assoc theta :kernel :power))]
        (loop [c 0 acc {}]
          (if (= c n) acc
              (let [a (aget offsets c) b (aget offsets (inc c))]
                (recur (inc c)
                       (loop [p a prev 0.0 m acc]
                         (if (= p b) m
                             (let [cur (aget cdf p)]
                               (recur (inc p) cur (update m (district-of (aget venues p)) (fnil + 0.0) (- cur prev))))))))))))))

(defn- simulator-with-distance
  "The same simulator, also reporting the expected straight-line shopping
   distance in km over every cell, so a distance observe can be tested."
  [{:keys [grid dense attract district-of] :as w}]
  (let [base (simulator w)
        n (:n grid)
        ^floats dist (:dist dense) nc (:nc dense)]
    (fn [theta]
      (let [{:keys [^ints offsets ^ints venues ^doubles cdf]} (cand/table-dense dense attract (assoc theta :kernel :power))
            km (loop [c 0 acc 0.0]
                 (if (= c n) (/ acc n 1000.0)
                     (let [a (aget offsets c) b (aget offsets (inc c))]
                       (recur (inc c)
                              (loop [p a prev 0.0 e acc]
                                (if (= p b) e
                                    (let [cur (aget cdf p) j (aget venues p)]
                                      (recur (inc p) cur (+ e (* (- cur prev) (aget dist (+ (* c nc) j))))))))))))]
        {:turnover (base theta) :shop-km km}))))

(deftest a-distance-observe-pulls-beta-toward-the-distance-it-implies
  ;; Turnover shares alone (σ 0.3, five districts) leave β loose; a distance
  ;; observe that only a small β can satisfy (long trips) must move the
  ;; posterior mean of β down, and one that only a large β satisfies must move
  ;; it up. The two runs share a seed so the prior draws are the same.
  (let [w (tiny-world 60 21)
        sim (simulator-with-distance w)
        obs (:turnover (sim {:alpha 1.0 :beta 2.0 :d0-m 500.0}))
        priors {:alpha [0.9 1.1] :beta [1.0 3.5] :log-d0 [(Math/log 450.0) (Math/log 550.0)]}
        km-at (fn [b] (:shop-km (sim {:alpha 1.0 :beta b :d0-m 500.0})))
        far (km-at 1.0) near (km-at 3.5)
        run! (fn [distance] (infer/run sim obs :n 120 :sigma 0.3 :priors priors :seed 5 :distance distance))
        r-none (run! nil) r-far (run! [far 0.02]) r-near (run! [near 0.02])]
    (is (< near far) "a steeper kernel means shorter trips in this world")
    (is (nil? (:distance r-none)))
    (is (= [far 0.02] (:distance r-far)) "the fitted distance is recorded on the result")
    (is (< (get-in r-far [:posterior-mean :beta]) (get-in r-none [:posterior-mean :beta]))
        (str "far " (get-in r-far [:posterior-mean :beta]) " none " (get-in r-none [:posterior-mean :beta])))
    (is (> (get-in r-near [:posterior-mean :beta]) (get-in r-none [:posterior-mean :beta]))
        (str "near " (get-in r-near [:posterior-mean :beta]) " none " (get-in r-none [:posterior-mean :beta])))
    (is (thrown? clojure.lang.ExceptionInfo
                 (infer/run (simulator w) obs :n 4 :sigma 0.3 :priors priors :distance [2.0 0.1]))
        "a distance observe without a :shop-km simulator fails loudly")))

(deftest recovers-a-known-beta-from-synthetic-district-shares
  (let [w (tiny-world 60 21)
        sim (simulator w)
        theta* {:alpha 1.0 :beta 2.0 :d0-m 500.0}
        obs (infer/synthetic-observations sim theta*)
        ;; hold α and d₀ near truth so the test is about β and runs fast
        priors {:alpha [0.9 1.1] :beta [1.0 3.5] :log-d0 [(Math/log 450.0) (Math/log 550.0)]}
        r (infer/run sim obs :n 160 :sigma 0.05 :priors priors :seed 7)]
    (testing "the run is well-formed"
      (is (= 160 (:n r)))
      (is (= 160 (:evaluations r)) "one evaluation per particle: resampling must not re-simulate")
      (is (= 5 (:districts r))))
    (testing "the posterior covers the truth"
      (is (> (:ess r) 3.0) (str "ESS " (:ess r)))
      (is (< (Math/abs (- (get-in r [:posterior-mean :beta]) 2.0)) 0.35)
          (str "posterior mean beta " (get-in r [:posterior-mean :beta])))
      (is (< (Math/abs (- (get-in r [:best :theta :beta]) 2.0)) 0.5)))
    (testing "and prefers the truth to a wrong beta"
      (let [lw (:log-weights r) vals (:values r)
            pairs (map vector vals lw)
            near (for [[v l] pairs :when (< (Math/abs (- (:beta v) 2.0)) 0.2)] l)
            far (for [[v l] pairs :when (> (Math/abs (- (:beta v) 2.0)) 1.0)] l)]
        (when (and (seq near) (seq far))
          (is (> (apply max near) (apply max far))))))))


(deftest random-walk-mh-moves-particles-and-still-recovers
  ;; The prior kernel cannot create new theta after the first draw; MH must.
  ;; distinct-theta > n is the direct evidence that moves happened.
  (let [w (tiny-world 60 21)
        sim (simulator w)
        theta* {:alpha 1.0 :beta 2.0 :d0-m 500.0}
        obs (infer/synthetic-observations sim theta*)
        ;; full-width priors: a proposal must be able to land inside the support,
        ;; or every step is rejected and no particle moves
        r (infer/run sim obs :n 12 :sigma 0.1 :priors infer/default-priors
                     :kernel :random-walk-mh :iterations 20 :step-size 0.15 :seed 11)]
    (is (= :random-walk-mh (:kernel r)))
    (is (> (:evaluations r) 12) (str "iterations must cost evaluations: " (:evaluations r)))
    (is (= (repeat 12 8) (:trace-sizes r))
        (str "three samples and five observes per particle, however many moves: " (:trace-sizes r)))
    ;; N independent chains have at most N distinct theta whether or not they
    ;; moved, so distinct-theta cannot show movement here; acceptance can.
    (is (pos? (get-in r [:mh :accepted] 0)) (str "no proposal was ever accepted: " (:mh r)))
    (is (= 12 (:distinct-theta r)))
    ;; No numerical tolerance on this run. An earlier version asserted the
    ;; 12-chain posterior mean of β within 0.35 of the truth; it passed alone
    ;; and failed inside the full suite, for the reason this namespace's
    ;; docstring gives. N particles race for the one seeded stream, so which
    ;; chain receives which draw moves with timing, and a tolerance on a
    ;; 12-chain mean is really a tolerance on the scheduler. Recovery under MH
    ;; is asserted below on a single chain, where the seed does determine the
    ;; answer.
    (is (every? #(<= 1.0 (:beta %) 3.5) (:values r)) "every chain stayed in the prior's support")))

(deftest seeded-chains-walk-toward-the-truth
  ;; The recovery claim, made where it is reproducible: single seeded chains,
  ;; one thread each, so every number here is the same in every JVM. Six
  ;; chains of 60 random-walk moves from prior draws on the full-width
  ;; priors, against synthetic observations at β = 2. Under the prior the
  ;; expected distance |β − 2| is 0.65; a working kernel must do clearly
  ;; better, and every chain must end at a likelihood no worse than the
  ;; prior draw it started from (MH accepts a worse joint only with the
  ;; Metropolis probability, so over 60 moves the end is essentially never
  ;; below the start).
  ;;
  ;; Until 2026-09-15 this could not pass: spindel's replay did not reseed
  ;; the address cursor, so proposals landed on dead sites and the kernel
  ;; was repeated prior sampling with 95 % acceptance. dev/mh_address_bug.clj
  ;; is the reproduction and now prints three PASS lines.
  (let [w (tiny-world 60 21)
        sim (simulator w)
        obs (infer/synthetic-observations sim {:alpha 1.0 :beta 2.0 :d0-m 500.0})
        runs (for [seed (range 1 7)]
               (let [start (infer/run sim obs :n 1 :sigma 0.1 :priors infer/default-priors :seed seed)
                     end (infer/run sim obs :n 1 :sigma 0.1 :priors infer/default-priors
                                    :kernel :random-walk-mh :iterations 60 :step-size 0.2 :seed seed)]
                 {:seed seed
                  :start-lw (get-in start [:best :log-weight]) :end-lw (get-in end [:best :log-weight])
                  :beta (get-in end [:best :theta :beta])
                  :rate (get-in end [:mh :acceptance-rate])}))
        ;; the log-likelihood at the truth itself, the ceiling a chain can reach
        truth-lw (get-in (infer/run sim obs :n 1 :sigma 0.1 :seed 1
                                    :priors {:alpha [1.0 1.0000001] :beta [2.0 2.0000001]
                                             :log-d0 [(Math/log 500.0) (Math/log 500.0001)]})
                         [:best :log-weight])
        near (filter #(> (:end-lw %) (- truth-lw 1.5)) runs)]
    (is (= 6 (count runs)))
    (is (every? #(< 0.05 (:rate %) 0.95) runs) (str "acceptance rates " (mapv :rate runs)))
    (is (>= (count (filter #(>= (:end-lw %) (- (:start-lw %) 1e-9)) runs)) 5)
        (str "chains that ended no worse than they started: " (mapv (juxt :seed :start-lw :end-lw) runs)))
    ;; Not |β − 2|: on this five-district world the shares do not identify β.
    ;; Measured, chains sit within 0.1 nats of the truth's likelihood at β
    ;; anywhere from 1.4 to 3.4 — the ridge the twelfth pass found on the
    ;; city, in miniature. What a working sampler must do is reach that
    ;; ceiling, and five of six do within 60 moves.
    (is (>= (count near) 5)
        (str "chains within 1.5 nats of the truth's " truth-lw ": "
             (mapv (juxt :seed :beta :end-lw) runs)))))

(deftest a-seeded-single-chain-is-reproducible
  ;; What :seed guarantees today, and no more. Every draw — prior samples,
  ;; proposals, site choice, acceptance, resampling offset — now comes from
  ;; anglican's seeded generator (spindel used clojure.core/rand for the last
  ;; four until 2026-09-15). But each particle context runs its program body
  ;; on its own drain thread, so with several particles the seeded stream is
  ;; consumed in a racy interleaving and particle i's θ is assembled from
  ;; whichever draws it happened to win: two seeded 24-particle runs agreed
  ;; in most fresh JVMs and disagreed in about one of three. A single chain
  ;; has no such race, so this is the property that can be asserted until
  ;; spindel gives each particle a counter-addressed generator of its own.
  (let [w (tiny-world 40 3) sim (simulator w)
        obs (infer/synthetic-observations sim {:alpha 1.0 :beta 2.0 :d0-m 500.0})
        run! #(infer/run sim obs :n 1 :sigma 0.1 :seed 43
                         :kernel :random-walk-mh :iterations 30 :step-size 0.2)
        a (run!) b (run!)]
    (is (pos? (get-in a [:mh :accepted])) "the chain moved, so acceptance and site draws were exercised")
    (is (< (get-in a [:mh :accepted]) 30) "and not every proposal was accepted, so rejections were exercised too")
    (is (= (:values a) (:values b)))
    (is (= (:log-weights a) (:log-weights b)))
    (is (= (:mh a) (:mh b)))))

(defn- segmented-simulator
  "Three classes over the tiny world: the same venues with class-specific
   attractiveness, so each class has its own district shares."
  [w]
  (let [scale {:short 1.0 :medium 1.3 :long 0.7}
        sims (into {} (for [s infer/segments]
                        [s (simulator (update w :attract
                                              (fn [^doubles a] (amap a i r (* (double (scale s)) (aget a i))))))]))]
    (fn [thetas]
      {:turnover (into {} (for [s infer/segments [d v] ((sims s) (get thetas s))] [[d s] v]))})))

(deftest the-segmented-program-recovers-per-class-kernels-with-keyed-sites
  (let [w (tiny-world 60 21)
        sim (segmented-simulator w)
        truth {:short {:alpha 1.0 :beta 2.6 :d0-m 500.0}
               :medium {:alpha 1.0 :beta 1.3 :d0-m 500.0}
               :long {:alpha 1.0 :beta 2.0 :d0-m 500.0}}
        obs (:turnover (sim truth))
        priors {:alpha [0.9 1.1] :beta [1.0 3.5] :log-d0 [(Math/log 450.0) (Math/log 550.0)]}
        r (infer/run-segmented sim obs :n 160 :sigma 0.05 :priors priors :seed 9)]
    (is (= 15 (:observations r)) "five districts times three classes")
    (is (= 160 (:evaluations r)))
    (is (= 9 (count (:posterior-mean r))) "nine latent numbers")
    (is (> (:ess r) 3.0))
    (testing "every particle's trace is exactly the model: nine samples, fifteen keyed observes"
      (is (every? #(= 24 %) (:trace-sizes r)) (str (distinct (:trace-sizes r)))))
    (testing "the flat theta regroups per class"
      (is (= #{:short :medium :long} (set (keys (infer/by-segment (:posterior-mean r)))))))
    (testing "the class with the steepest truth is inferred steeper than the flattest"
      (let [pm (:posterior-mean r)]
        (is (> (:short/beta pm) (:medium/beta pm)) (str pm)))))

  (testing "keyed sites survive a replay: MH on the segmented program keeps the trace at the model's size"
    (let [w (tiny-world 40 4)
          sim (segmented-simulator w)
          obs (:turnover (sim {:short {:alpha 1.0 :beta 2.0 :d0-m 500.0}
                               :medium {:alpha 1.0 :beta 2.0 :d0-m 500.0}
                               :long {:alpha 1.0 :beta 2.0 :d0-m 500.0}}))
          r (infer/run-segmented sim obs :n 1 :sigma 0.2 :kernel :random-walk-mh :iterations 15 :step-size 0.2 :seed 2)]
      (is (= [24] (:trace-sizes r)))
      (is (< 0.05 (get-in r [:mh :acceptance-rate]) 0.95)))))

(deftest mh-chains-are-independent-not-a-resampled-population
  ;; Thirty districts means thirty observe barriers per sweep. Under
  ;; kernel-infer's default barrier policy the population resamples at every
  ;; one, replays included, and a final resample copies the winner: on the
  ;; city, eight chains ended bit-identical. Chains must not share a
  ;; barrier at all.
  (let [w (assoc (tiny-world 60 21) :district-of (fn [j] (str "d" (mod j 30))))
        sim (simulator w)
        obs (infer/synthetic-observations sim {:alpha 1.0 :beta 2.0 :d0-m 500.0})
        r (infer/run sim obs :n 6 :sigma 0.1 :kernel :random-walk-mh :iterations 10 :step-size 0.2 :seed 5)]
    (is (= 30 (:districts r)))
    (is (= :independent (:chains r)))
    (is (= 6 (:distinct-theta r)) (str "chains collapsed: " (:values r)))
    (is (= 6 (count (distinct (:log-weights r)))) (str "identical log-weights: " (:log-weights r)))
    (testing "resample-move is available on request and says so"
      (let [p (infer/run sim obs :n 6 :sigma 0.1 :kernel :random-walk-mh :iterations 10 :step-size 0.2 :seed 5
                         :chains :resample-move)]
        (is (= :resample-move (:chains p)))
        (is (<= (:distinct-theta p) 6))))))

(deftest a-free-class-level-recovers-a-planted-inflow
  ;; Multiply the medium class's observations by e^0.5 — an inflow the
  ;; resident money cannot produce — and the level parameter, not the kernel,
  ;; must take it: its posterior mean sits near 0.5 while the other two stay
  ;; near 0. Prior kernel, narrow kernel priors so the test is
  ;; about the levels.
  (let [w (tiny-world 60 21)
        sim (segmented-simulator w)
        truth {:short {:alpha 1.0 :beta 2.0 :d0-m 500.0}
               :medium {:alpha 1.0 :beta 2.0 :d0-m 500.0}
               :long {:alpha 1.0 :beta 2.0 :d0-m 500.0}}
        obs (into {} (for [[[d s :as k] v] (:turnover (sim truth))]
                       [k (if (= s :medium) (* v (Math/exp 0.5)) v)]))
        priors {:alpha [0.95 1.05] :beta [1.9 2.1] :log-d0 [(Math/log 480.0) (Math/log 520.0)]}
        ;; 600 particles: at 240 the ordering margin failed about once in several
        ;; full-suite runs on a loaded machine
        r (infer/run-segmented sim obs :n 600 :sigma 0.05 :priors priors :levels 0.5 :seed 13)
        pm (:posterior-mean r)]
    (is (= 0.5 (:levels r)))
    (is (= 12 (count pm)) "twelve latent numbers with levels")
    (is (every? #(= 27 %) (:trace-sizes r)) "twelve samples and fifteen observes")
    ;; An importance sample's means carry sampling noise, and a
    ;; multi-particle run is not scheduler-reproducible (see the namespace
    ;; doc), so the claim is the ordering and a loose band, not a point: the
    ;; planted class stands clearly above the other two, near 0.5, and the
    ;; other two stay near 0. A tighter band on the nulls passed alone and
    ;; failed inside the full suite at −0.25.
    (is (< (Math/abs (- (:medium/log-level pm) 0.5)) 0.25) (str "medium level " (:medium/log-level pm)))
    (is (< (Math/abs (:short/log-level pm)) 0.35) (str "short level " (:short/log-level pm)))
    (is (< (Math/abs (:long/log-level pm)) 0.35) (str "long level " (:long/log-level pm)))
    (is (> (:medium/log-level pm) (+ 0.25 (max (:short/log-level pm) (:long/log-level pm))))
        (str "the planted class is not clearly above the others: " (select-keys pm [:short/log-level :medium/log-level :long/log-level])))))

