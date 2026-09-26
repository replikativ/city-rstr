(ns city.infer
  "Bayesian inference of the destination kernel's parameters, through spindel.

   The model is a spindel program. `segmented-model` samples, per demand class
   s, α_s ~ U(0, 1.5), β_s ~ U(1, 3.5) and log d₀_s ~ U(log 200, log 2000)
   (`default-priors`), calls a host simulator θ → predicted turnover per
   (district, class), and observes each published turnover under a log-normal
   model: 69 observations on Stuttgart. `turnover-model` is the single-class
   version, one observe per district. Every site carries an explicit id, so it
   has the same address in every particle and every replay.

   Two drivers, `run` and `run-segmented`, share `infer-with`:
   - `:kernel :prior` is importance sampling with a resampling barrier at every
     observe. There is no move step, so the posterior is supported on the N
     prior draws; read `:distinct-theta`, not ESS.
   - `:kernel :random-walk-mh` runs N chains of single-site Gaussian
     random-walk moves. With `:chains :independent` they share no barrier and
     their final states are weighted uniformly (`uniform-chains`). The
     published posterior is 48 such chains of 30 moves
     (`city.demo.stuttgart/fit-posterior`).

   The simulator the demo passes is the exact expected allocation
   (`city.sim.candidates/reduce-dense`), so the likelihood carries no Monte
   Carlo noise. Host evaluations are serialised (`serialised`), which also
   counts them: a simulator may reuse one buffer across calls, and spindel's
   default executor runs particles on two threads.

   ## Reproducibility

   Given the same world, tables and observations, the only randomness is
   spindel's sampling, and every `sample*` in spindel draws from
   `anglican.runtime/RNG` — one process-global commons-math generator.
   `:seed` calls `setSeed` on it before inference. That alone is not enough:
   spindel's default executor runs particles on two threads, and concurrent
   particles consume the one seeded stream in a racy interleaving — the same
   numbers reappear run to run, attached to different particles and different
   parameters. So a seeded run also uses a single-threaded executor, which
   costs nothing here because the host evaluation is serialised on its buffer
   anyway. Even that is not enough: each particle context runs its program
   body on its own drain thread, so the first draws of N particles still race
   for the one stream, and two seeded 24-particle runs agreed in most fresh
   JVMs and disagreed in about one of three. What a seed guarantees today is
   that every draw comes from the seeded generator — spindel's resampling,
   site choice and acceptance included, since 2026-09-15 — and that a
   single-particle run is bit-reproducible. The proper fix is a per-particle,
   counter-addressed RNG in spindel, the way the city's own day kernel draws.
   Being process-global, the seed also affects anything else sampling from
   anglican in the same JVM, which a test suite must not do concurrently. The
   result records the seed with N, σ, the priors and the wall time."
  (:require [org.replikativ.spindel.inference.inference :as infer]
            [org.replikativ.spindel.inference.kernel :as k]
            [org.replikativ.spindel.inference.measure :as measure]
            [org.replikativ.spindel.inference.effects :refer [sample observe]]
            [org.replikativ.spindel.spin.cps :refer [spin]]
            [org.replikativ.spindel.effects.await :as aw]
            [org.replikativ.spindel.engine.core :as rtc]
            [org.replikativ.spindel.engine.context :as ctx]
            [org.replikativ.spindel.engine.protocols :as rtp]
            [org.replikativ.spindel.engine.executor :as sched]
            [anglican.runtime :as ar]))

(def default-priors
  "Uniform on α and β, log-uniform on d₀ — the centres and ranges of
   `city.sim.run/defaults`' :prior entries."
  {:alpha [0.0 1.5] :beta [1.0 3.5] :log-d0 [(Math/log 200.0) (Math/log 2000.0)]})

(defn turnover-model
  "The probabilistic program. `simulate` is θ → {district → prediction}, or
   θ → {:turnover {district → prediction} :shop-km x} when the simulator also
   reports the population's expected straight-line shopping distance;
   `observations` is {district → observed}; both keyed identically. Districts
   are walked with loop/recur, which the CPS transformer handles, so the
   observation set is data rather than something unrolled at macroexpansion.

   `distance`, when given as [km sigma-km], adds one more `observe`: the
   simulator's :shop-km against km under a normal observation model. That
   turns the trip-distance check from a holdout into a fitted quantity, so a
   run that uses it must not also report it as a holdout. The MiD figure is a
   reported door-to-door distance; converting it to the straight-line quantity
   the simulator computes needs a detour factor, and that conversion belongs
   to the caller, stated, not to this function."
  [simulate observations sigma priors & [distance]]
  (let [districts (vec (sort (keys observations)))
        [a0 a1] (:alpha priors) [b0 b1] (:beta priors) [l0 l1] (:log-d0 priors)
        [dist-km dist-sigma] distance]
    (spin
      ;; Every site carries an explicit :id. spindel's hash-chain address is a
      ;; function of execution history, so it only lines up across particles
      ;; whose histories are identical; a keyed site has the same address in
      ;; every particle and every replay whatever path reached it. That is
      ;; the join key a batched checkpoint needs, and it is what the DOM
      ;; layer already does for keyed children.
      (let [alpha (sample (ar/uniform-continuous a0 a1) :id :alpha)
            beta  (sample (ar/uniform-continuous b0 b1) :id :beta)
            ld0   (sample (ar/uniform-continuous l0 l1) :id :log-d0)
            theta {:alpha alpha :beta beta :d0-m (Math/exp ld0)}
            y     (simulate theta)
            yhat  (if (contains? y :turnover) (:turnover y) y)]
        (loop [ds districts]
          (when (seq ds)
            (let [d (first ds)]
              (observe (ar/normal (Math/log (double (yhat d))) sigma)
                       (Math/log (double (observations d)))
                       :id (keyword "obs" (str d)))
              (recur (rest ds)))))
        (when dist-km
          (when-not (contains? y :shop-km)
            (throw (ex-info "distance observe needs a simulator that returns :shop-km"
                            {:keys (when (map? y) (keys y))})))
          (observe (ar/normal (double (:shop-km y)) (double dist-sigma)) (double dist-km)
                   :id :obs/shop-km))
        theta))))

(def segments [:short :medium :long])

(defn segmented-model
  "The three-class program: one kernel per demand
   class, nine latent numbers, and one observe per (district, class) — 69 on
   Stuttgart. θ is returned FLAT, `{:short/alpha … :long/d0-m}`, so
   `summarise` needs nothing new; `run-segmented` regroups it per class
   before calling the simulator, which must return
   `{:turnover {[district class] eur} …}` keyed like `observations`.
   Sites are keyed `:short/alpha`, `:obs/Mitte|medium`, and so on.

   `:distance {:km x :sigma s :weights {class w}}` adds one observe: the
   trip-share-weighted mean of the simulator's expected straight-line shopping
   distance per class (`:km`, in km) against `x`. As at `turnover-model`,
   converting a surveyed door-to-door distance to that quantity is the
   caller's, stated."
  [simulate observations sigma priors & [{:keys [levels distance]}]]
  (let [keys* (vec (sort (keys observations)))
        [a0 a1] (:alpha priors) [b0 b1] (:beta priors) [l0 l1] (:log-d0 priors)
        level-sd (when levels (double levels))]
    (spin
      (let [;; nine samples, three per class, in a fixed order — twelve with
            ;; a free level per class
            th (loop [ss segments acc {}]
                 (if (empty? ss) acc
                     (let [s (first ss)
                           alpha (sample (ar/uniform-continuous a0 a1) :id (keyword (name s) "alpha"))
                           beta  (sample (ar/uniform-continuous b0 b1) :id (keyword (name s) "beta"))
                           ld0   (sample (ar/uniform-continuous l0 l1) :id (keyword (name s) "log-d0"))
                           ;; The class's level, log scale, centred on the
                           ;; resident money split. Its posterior is the
                           ;; measured non-resident flow of that class — inflow
                           ;; above 0, leakage below — which is what the
                           ;; non-resident layer must then explain. Without
                           ;; it the likelihood asks the kernel to absorb a
                           ;; −0.57 level on clothing by distorting its shape.
                           lvl   (if level-sd (sample (ar/normal 0.0 level-sd) :id (keyword (name s) "log-level")) 0.0)]
                       (recur (rest ss) (cond-> (assoc acc (keyword (name s) "alpha") alpha
                                                       (keyword (name s) "beta") beta
                                                       (keyword (name s) "d0-m") (Math/exp ld0))
                                          level-sd (assoc (keyword (name s) "log-level") lvl))))))
            y (simulate th)
            yhat (:turnover y)]
        (loop [ks keys*]
          (when (seq ks)
            (let [[d s :as k] (first ks)
                  lvl (double (get th (keyword (name s) "log-level") 0.0))]
              (observe (ar/normal (+ lvl (Math/log (double (yhat k)))) sigma)
                       (Math/log (double (observations k)))
                       :id (keyword "obs" (str d "|" (name s))))
              (recur (rest ks)))))
        (when distance
          (let [km-hat (reduce + (map (fn [[s w]] (* (double w) (double (get-in y [:km s])))) (:weights distance)))]
            (observe (ar/normal km-hat (double (:sigma distance))) (double (:km distance)) :id :obs/shop-km)))
        th))))

(defn by-segment
  "`{:short/alpha a …}` → `{:short {:alpha a :beta b :d0-m d} …}`."
  [flat]
  (into {} (for [s segments]
             [s {:alpha (get flat (keyword (name s) "alpha"))
                 :beta (get flat (keyword (name s) "beta"))
                 :d0-m (get flat (keyword (name s) "d0-m"))}])))

(defn serialised
  "Wrap a simulator so concurrent particles cannot race on a shared buffer.
   Also counts evaluations, which is the honest unit of cost."
  [simulate]
  (let [lock (Object.) n (atom 0)]
    {:simulate (fn [theta] (locking lock (swap! n inc) (simulate theta)))
     :evaluations n}))

(defn summarise
  "A portable summary of an EmpiricalMeasure: values, normalised weights, ESS,
   weighted means and the best particle, in a canonical particle order.
   Nothing here holds a live context."
  [m]
  (let [;; Particle order is the executor's completion order and varies run to
        ;; run even with a seed and one thread; nothing downstream may depend
        ;; on it, so sort canonically (log-weight, then the sampled value).
        ps (vec (sort-by (fn [[c w]] [(double w) (str (measure/get-value c))])
                         (measure/get-particles m)))
        lw (mapv second ps)
        w (measure/normalize-log-weights lw)
        vals (mapv (fn [[c _]] (measure/get-value c)) ps)
        keys* (keys (first vals))
        wmean (fn [k] (reduce + (map (fn [v wi] (* (double wi) (double (get v k)))) vals w)))
        bi (first (apply max-key second (map-indexed vector lw)))
        ;; MH diagnostics, when the kernel left any: acceptance per chain from
        ;; RandomWalkMHKernel's own state. Zero acceptance with iterations > 0
        ;; means every proposal was rejected — usually a step size larger than
        ;; the prior's support — and distinct-theta then stays at n.
        mh (keep (fn [[c _]] (rtp/get-state c [:inference :rw-mcmc])) ps)
        accepted (reduce + 0 (map #(or (:acceptance-count %) 0) mh))
        iterated (reduce + 0 (map #(or (:completed-iterations %) 0) mh))]
    {:n (count ps)
     ;; how many trace entries each particle ended with: under a correct
     ;; replay this is exactly the program's site count, however many moves
     ;; were made — the number that was growing without bound before the
     ;; 2026-09-15 spindel fix
     :trace-sizes (mapv (fn [[c _]] (count (rtp/get-state c [:inference :trace]))) ps)
     :distinct-theta (count (distinct vals))
     :ess (measure/compute-ess w)
     :mh (when (seq mh) {:chains (count mh) :iterations iterated :accepted accepted
                         :acceptance-rate (when (pos? iterated) (/ (double accepted) iterated))})
     :log-weights lw :weights (vec w) :values vals
     :posterior-mean (into {} (for [k keys*] [k (wmean k)]))
     :best {:theta (nth vals bi) :log-weight (nth lw bi) :weight (nth w bi)}}))

(defn uniform-chains
  "Under an MCMC kernel every chain's final state is one posterior draw and
   its log-weight is the log-likelihood it ended at, already paid for by the
   accept step. Normalising those log-weights would count the likelihood
   twice, so the chains are weighted uniformly and the reported log-weights
   stay as what they are: the final log-likelihood per chain, useful for
   ranking, not for weighting."
  [summary]
  (let [n (count (:values summary)) w (/ 1.0 n)
        ks (keys (first (:values summary)))]
    (assoc summary
           :weights (vec (repeat n w)) :ess (double n) :weighting :uniform-chains
           :posterior-mean (into {} (for [k ks] [k (/ (reduce + (map #(double (get % k)) (:values summary))) n)])))))

(defn- infer-with
  "The driver `run` and `run-segmented` share: serialise the simulator, seed,
   build the program inside the context binding, run the chosen kernel, and
   summarise. `build-model` is (fn [serialised-simulate] spin-task)."
  [build-model simulate {:keys [n sigma priors resample-threshold kernel iterations step-size seed chains]
                         :or {n 64 sigma 0.15 priors default-priors resample-threshold 0.5
                              kernel :prior iterations 20 step-size 0.15 chains :independent}}
   extra]
  (when seed (.setSeed ^org.apache.commons.math3.random.RandomGenerator ar/RNG (long seed)))
  (let [{sim :simulate evals :evaluations} (serialised simulate)
        t0 (System/nanoTime)
        root (ctx/create-execution-context)
        ;; one thread when seeded: see the namespace doc on why the seed alone
        ;; does not make particles reproducible
        executor (when seed (sched/thread-pool-executor {:threads 1}))
        opts (cond-> {:resample-threshold resample-threshold}
               executor (assoc :executor executor)
               ;; `:chains :independent` — N chains that never share a
               ;; resampling barrier. `:resample-move` keeps kernel-infer's
               ;; default: resample at every observe, replays included, then
               ;; move. The population collapses onto its best particles and a
               ;; final resample copies them, so its N is not N draws — on the
               ;; city, eight ended bit-identical — but it reaches the mode in
               ;; far fewer evaluations than chains started from the prior:
               ;; −4 against −61 to −345 after the same 168 evaluations on
               ;; the nine-parameter program. Say which one was run.
               (and (= kernel :random-walk-mh) (= chains :independent)) (assoc :barrier-policy :none))]
    (try
      (binding [rtc/*execution-context* root]
        ;; the model must be built here: `spin` registers its task with the
        ;; execution context that is bound when the form is evaluated
        (let [model (build-model sim)
              m @(spin (aw/await
                        (case kernel
                          :prior (infer/smc-infer model n opts)
                          :random-walk-mh (infer/kernel-infer model (k/random-walk-mh-kernel iterations {:step-size step-size})
                                                              n opts))))]
          (merge (cond-> (summarise m) (= kernel :random-walk-mh) uniform-chains)
                 {:kernel kernel :iterations (when (= kernel :random-walk-mh) iterations) :seed seed
                  :chains (when (= kernel :random-walk-mh) chains)
                  :evaluations @evals :seconds (/ (- (System/nanoTime) t0) 1e9)
                  :sigma sigma :priors priors}
                 extra)))
      ;; spindel's executor exposes no shutdown; kernel-infer does not shut its
      ;; own default down either. One idle thread per seeded run is the cost.
      (finally (ctx/stop-context! root)))))

(defn run
  "Run inference for `n` particles and return `summarise`'s map plus run
   metadata. The execution context is created here and stopped in `finally`,
   so a run never leaks a drain thread.

   `:kernel`
   - `:prior` (default) — spindel's prior kernel with a resampling barrier at
     every observe: SMC without moves, i.e. importance sampling with
     sequential resampling. Cheap (N evaluations) and degenerate: on the city,
     48 particles collapsed onto 5 ancestors across 23 barriers. Read
     `:distinct-theta`, not `:ess`.
   - `:random-walk-mh` — spindel's `RandomWalkMHKernel`: after each particle's
     first pass it perturbs one continuous sample by a Gaussian step and
     replays the program from that site with every other site held at its
     trace value, accepting on the ratio of joints, `:iterations` times.
     This needs spindel 0.1.48 or later, whose replay keeps site addresses
     stable; before it, proposals landed on dead sites and were accepted as
     no-ops, which is why an acceptance rate near 1.0 is a warning sign.
     N independent chains from prior draws, N × (1 + iterations) evaluations.
     `:chains :independent` (default) runs them with no resampling barrier;
     `:chains :resample-move` keeps spindel's resample-at-every-observe and
     is a population sampler whose final set is partly copies — read
     `:distinct-theta`, and expect it to reach the mode much sooner.
     That is rejuvenation the memory model already supports; what it lacks is
     batching, so every step is one serialised host evaluation.

   Read the right diagnostic for each. Under `:prior`, `:distinct-theta`
   below `n` measures collapse onto ancestors. Under `:random-walk-mh` it is
   always `n` — one final θ per chain — and `:mh :acceptance-rate` is what
   says whether chains moved. A rate near 1.0 on a sharp likelihood is a
   symptom, not good mixing: it is what the pre-fix kernel reported while
   accepting no-op proposals.

   `:distance [km sigma-km]` adds the shopping-distance observe described at
   `turnover-model`; the simulator must then return :shop-km alongside
   :turnover, and the run's result records the pair under :distance so a
   reader can see the distance was fitted, not held out."
  [simulate observations & {:as opts}]
  (let [{:keys [sigma priors distance] :or {sigma 0.15 priors default-priors}} opts]
    (infer-with (fn [sim] (turnover-model sim observations sigma priors distance))
                simulate opts
                {:districts (count observations) :distance distance})))

(defn run-segmented
  "`run` for `segmented-model`. `simulate` takes `{:short {:alpha …} …}`
   and returns `{:turnover {[district class] eur} …}`; `observations` is
   keyed the same way. The result's θ are flat, `by-segment` regroups them.
   `:levels sd` adds a free log-level per class with a N(0, sd) prior; see
   `segmented-model` for what its posterior means."
  [simulate observations & {:as opts}]
  (let [{:keys [sigma priors levels] :or {sigma 0.25 priors default-priors}} opts]
    (infer-with (fn [sim] (segmented-model (fn [flat] (sim (by-segment flat))) observations sigma priors
                                           {:levels levels :distance (:distance opts)}))
                simulate (assoc opts :sigma sigma :priors priors)
                {:observations (count observations) :segmented true :levels levels :distance (:distance opts)})))

(defn synthetic-observations
  "What the simulator says at a known θ*, for recovery tests: fit to this and
   the posterior must cover θ*."
  [simulate theta*]
  (simulate theta*))
