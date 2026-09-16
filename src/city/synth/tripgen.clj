(ns city.synth.tripgen
  "Trip generation: make the diary pool produce the number of trips a *travel*
   survey counts, without inventing chains.

   **The problem.** Schedules come from a time-use survey (StatCan TUS 2022),
   which records travel only when the respondent reports it as its own episode;
   short and chained legs are absorbed into the activity around them. The pool
   contains 2.00 travel episodes per person-day at a mobile share of 0.70, and
   the simulator delivers 1.83 of those 2.00. Travel surveys, which ask for
   every trip by name, count 2.86 per person-day in Stuttgart. No behavioural
   rule recovers what the questionnaire never asked.

   **The method.** Keep the diaries — a time-use survey measures *when* people
   do things and how long they stay, which is exactly what the day needs — and
   change only how often each diary is drawn. For each person type, tilt the
   sampling weights

       w'(d) ∝ w(d) · exp(λ_t · n_d)

   where `n_d` is the diary's travel-episode count, and solve one λ_t per type
   so the induced mean equals the survey's rate for that type. This is the
   minimum-relative-entropy reweighting subject to one moment constraint: of
   all reweightings that hit the target, it is the one that changes the pool
   least.

   **It is checkable, and it checks out.** Only the *mean* is fitted. The share
   of people who make no trip at all is then a prediction. Tilting the pool to
   Stuttgart's 2.86 yields a mobile share of **0.821** against the published
   0.838, and to 3.00 yields 0.835 — an out-of-sample agreement within two
   points on a statistic no parameter was fitted to.

   **What it cannot do.** It cannot produce a day the pool never recorded: the
   richest diary has 9 travel episodes, so the tail is bounded by the source.
   It also shifts the activity mix, because diaries with more travel are not a
   random subset — they belong to people who shop and socialise more. Both are
   why this is the interim generator and a survey-based chain builder is the
   target; see `doc/sources/trip-generation.md`."
  (:require [city.synth.timeuse :as tu]))

;; ---- published targets --------------------------------------------------------------------

(def stuttgart-level
  "Trips per person per day, Stadt Stuttgart. **MiD 2023 small-area estimate**
   (`MiD23_SAE_..._Gemeindedaten.xlsx`, GKZ 8111000): 2.861, at a
   Mobilitätsquote of 83.79 %.

   Not 3.2 — that is the *2017* Stuttgart figure this repo calibrated against
   until 2026-09-11. The German rate fell across the series: 3.3 (2002),
   3.4 (2008), 3.1 (2017), 2.9 (2023 national)."
  2.861)

(def stuttgart-activity-factors
  "Trips per person per day by Haupttätigkeit relative to the all-person mean,
   **MiD 2017 Stadt Stuttgart Grundauswertung, table P32.1** (Gesamt 3.2):
   Vollzeit 3.4, Teilzeit 3.9, Schüler 2.9, Student 2.3, Rentner 2.8.

   Our five activity classes are coarser than MiD's, so `:worker` takes the
   full-time value (the part-time rate is higher, and we do not carry the
   split), `:student` the mean of Schüler and Student, and `:home` and
   `:other` the population mean, MiD's Hausfrau/-mann row not being in the
   extract."
  {:worker (/ 3.4 3.2) :student (/ 2.6 3.2) :retired (/ 2.8 3.2) :home 1.0 :other 1.0})

(def stuttgart-age-factors
  "The same table by age band, relative to 3.2: 7–17 3.0, 18–29 2.8, 30–39 3.5,
   40–49 3.6, 50–64 3.7, 65–74 3.0, 75+ 2.5. Our bands are decades from 15, so
   25–34 interpolates MiD's 18–29 and 30–39."
  {:a15-24 (/ 2.8 3.2) :a25-34 (/ 3.15 3.2) :a35-44 (/ 3.55 3.2) :a45-54 (/ 3.65 3.2)
   :a55-64 (/ 3.7 3.2) :a65-74 (/ 3.0 3.2) :a75+ (/ 2.5 3.2) :na 1.0})

(def targets
  {:stuttgart {:level stuttgart-level :act stuttgart-activity-factors :age stuttgart-age-factors
               :mobile 0.838
               :source "MiD 2023 SAE (level, mobility) + MiD 2017 Stadt Stuttgart P32.1 (shape)"}})

;; ---- the tilt -----------------------------------------------------------------------------

(defn travel-count
  "Travel episodes in a diary — the model's unit of a *trip*. A transit trip's
   access and egress walk are emitted later as flagged sub-legs and are not
   counted here, so this matches the German `Weg` and the Toronto linked trip
   rather than a leg (see the definition note in doc/sources/trip-generation.md)."
  ^long [d]
  (count (filter #(= :travel (:act %)) (:chain d))))

(defn- weighted-mean ^double [ds ^double lam]
  (let [ws (mapv (fn [d] (* (double (or (:weight d) 1.0)) (Math/exp (* lam (travel-count d))))) ds)
        z (reduce + ws)]
    (if (zero? z) 0.0 (/ (reduce + (map * ws (map travel-count ds))) z))))

(defn solve-lambda
  "λ such that the tilted mean travel-episode count equals `target`. Bisection
   on a monotone function; returns 0.0 when the target is outside what the pool
   can express (an all-immobile or an all-maximal pool)."
  [ds target & {:keys [lo hi iters] :or {lo -4.0 hi 6.0 iters 80}}]
  (let [target (double target)
        f (fn [^double l] (- (weighted-mean ds l) target))]
    (if (or (empty? ds) (pos? (f lo)) (neg? (f hi)))
      0.0
      (loop [lo (double lo) hi (double hi) k 0]
        (if (= k iters) (/ (+ lo hi) 2.0)
            (let [m (/ (+ lo hi) 2.0)]
              (if (neg? (f m)) (recur m hi (inc k)) (recur lo m (inc k)))))))))

(defn target-mean
  "The published trips-per-person-day for one person type `[act age sex]`,
   as level × activity factor × age factor. `scale` renormalizes so that the
   *pool-weighted* population mean is exactly the level (the factors are
   relative to their own survey's mean, not to ours)."
  ^double [[act age _] {:keys [level act-f age-f]} ^double scale]
  (* level scale (double (get act-f act 1.0)) (double (get age-f age 1.0))))

(defn person-type-mix
  "Share of the simulated population in each diary person type, using the same
   mapping `city.sim.day/person-types` uses. Needed because the survey's
   *level* is a population mean, and the population that matters is the city's,
   not the diary pool's: reweighting shifts each type's total pool weight, so
   normalizing against the pool would silently target a different mix of people
   than the one being simulated.

   Persons with no diary type (children under 15) are excluded, as they are in
   the simulation. MiD's 2.861 covers ages 0+, and its own tables put 0–6 at
   2.9 and 7–17 at 3.0 against 3.2 overall, so the adults-only mean it is being
   applied to is about 1 % higher than the published one. That is inside every
   other error here and is not corrected for."
  [persons]
  (let [n (:n persons) ^ints labour (:labour persons) ^ints attsch (:attsch persons)
        ^ints age (:age persons) ^ints sex (:sex persons)
        acc (java.util.HashMap.)]
    (dotimes [i n]
      (when (>= (aget age i) 3)
        (let [l (aget labour i)
              act (cond (<= 1 l 2) :worker (= 1 (aget attsch i)) :student (>= (aget age i) 12) :retired :else :home)
              ag (case (long (aget age i)) (3 4) :a15-24 (5 6) :a25-34 (7 8) :a35-44 (9 10) :a45-54 11 :a55-64 12 :a65-74 13 :a75+ :child)
              sx (case (long (aget sex i)) 1 :women 2 :men :na)
              k [act ag sx]]
          (.put acc k (inc (long (or (.get acc k) 0)))))))
    (let [tot (double (reduce + (vals acc)))]
      (into {} (for [[k v] acc] [k (/ (double v) tot)])))))

(defn calibrate
  "Reweight `by-type` so each person type's mean travel-episode count matches
   the survey. Returns `{:by-type :report}`; the report carries, per type, the
   pool mean before and after, the target, λ, and the diary count, plus the
   population-level before/after and the *predicted* mobile share — which is
   not fitted and is the check.

   `city` selects the published target set (`:stuttgart`);
   `:level` overrides the trips-per-person-day level, which is the one number
   in here worth calibrating."
  [by-type city & {:keys [level type-mix]}]
  (let [{:keys [act age] lvl :level src :source mob :mobile} (get targets city)
        lvl (double (or level lvl))
        spec {:level lvl :act-f act :age-f age}
        all (vec (mapcat val by-type))
        wsum (reduce + (map #(double (or (:weight %) 1.0)) all))
        ;; the factors are relative to their own survey's population; rescale so
        ;; that *our* population, with *our* type mix, averages the level.
        ;; `type-mix` is the simulated population's; without it the pool's own
        ;; weights stand in, which is only right if the two mixes agree.
        mix (or type-mix
                (let [ws (into {} (for [[t ds] by-type]
                                    [t (reduce + (map #(double (or (:weight %) 1.0)) ds))]))
                      z (reduce + (vals ws))]
                  (into {} (for [[t w] ws] [t (/ w z)]))))
        known (filter #(contains? by-type (key %)) mix)
        mz (reduce + (map val known))
        raw (if (pos? mz)
              (/ (reduce + (for [[t p] known] (* p (target-mean t (assoc spec :level 1.0) 1.0)))) mz)
              1.0)
        scale (if (pos? raw) (/ 1.0 raw) 1.0)
        before-pool (/ (reduce + (map (fn [d] (* (double (or (:weight d) 1.0)) (travel-count d))) all)) wsum)
        out (into {} (for [[t ds] by-type
                           :let [tgt (target-mean t spec scale)
                                 lam (solve-lambda ds tgt)]]
                       [t (mapv (fn [d] (update d :weight
                                                #(* (double (or % 1.0)) (Math/exp (* lam (travel-count d))))))
                                ds)]))
        ;; the population statistics are taken over the *simulated* type mix,
        ;; drawing within each type by its tilted weights — exactly what
        ;; `day/diary-tables` then does
        wm (fn [xs f] (let [w (reduce + (map #(double (or (:weight %) 1.0)) xs))]
                        (if (pos? w) (/ (reduce + (map (fn [d] (* (double (or (:weight d) 1.0)) (f d))) xs)) w) 0.0)))
        pop-stat (fn [tbl f] (if (pos? mz)
                               (/ (reduce + (for [[t p] known] (* p (wm (tbl t) f)))) mz)
                               0.0))
        after (pop-stat out travel-count)
        mobile' (pop-stat out #(if (pos? (travel-count %)) 1.0 0.0))
        r2 (fn [^double x] (/ (Math/round (* 1000.0 x)) 1000.0))]
    {:by-type out
     :report {:city city :source src :level lvl :scale (r2 scale)
              :pool-mean-before (r2 before-pool)
              :mean-before (r2 (pop-stat by-type travel-count))
              :mean-after (r2 after)
              :mobile-share-before (r2 (pop-stat by-type #(if (pos? (travel-count %)) 1.0 0.0)))
              :mobile-share-after (r2 mobile')
              :mobile-share-published mob
              :types (count by-type) :diaries (count all)
              :per-type (vec (sort-by (comp - :diaries)
                                      (for [[t ds] by-type
                                            :let [ds' (out t)
                                                  wm (fn [xs] (let [w (reduce + (map #(double (or (:weight %) 1.0)) xs))]
                                                                (if (pos? w) (/ (reduce + (map (fn [d] (* (double (or (:weight d) 1.0)) (travel-count d))) xs)) w) 0.0)))]]
                                        {:type t :diaries (count ds) :target (r2 (target-mean t spec scale))
                                         :before (r2 (wm ds)) :after (r2 (wm ds'))})))}}))

(defn diaries
  "The diary pool for a city: all-province weekday urban diaries, reweighted to
   that city's published trip rate.

   The province filter is gone. It was `#{59}` (British Columbia), which left
   1,117 diaries over 53 person types — about 21 each, and 56 % of simulated
   mobile days came out as a single trip out and back. The trip *rate* is a
   property of the instrument and does not change with the pool; the chain
   variety does. For Stuttgart, where the diaries are already a transfer, there
   was never a reason to restrict them to one Canadian province."
  [city & {:keys [level provinces] :or {provinces nil}}]
  (calibrate (tu/chains-by-type (tu/load-diaries :provinces provinces)) city :level level))
