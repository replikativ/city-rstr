(ns city.sim.day
  "The simulated weekday on the CPU: the tables built once per world
   (`prepare`) and the step over persons (`step-day`, `step-day-traces`).

   Every step is a loop over persons or cells on flat arrays, CSR tables and
   counter-addressed draws (`uniform`), the shape of a raster `par/map-void!`
   with `atomic-add!`; `city.sim.kernel` is that port for the retail day and
   the economic day.

   Tables built once per world:
   - grid: 100 m cells over the bbox; per venue class a CSR of candidate venues
     per cell with cumulative choice weights (`gravity-table`). The store table
     is the exact dense one from `city.sim.candidates` when `prepare` is given
     it, as the Stuttgart run does.
   - diaries: per person type a CSR of diaries (cumulative weights), each a CSR
     of venue episodes (location code, minute, departure, arrival) and of
     travel episodes.

   Step: per person → pick a diary (binary search) → for each episode: work →
   the workplace; store or restaurant → binary search in the anchor cell's
   CDF → add to visits[venue*24+hour].

   Every diary location has a destination, not only those four. The TUS
   location codes 3300–3312 all map to a *venue class* (see `loc-codes` and
   `class-of-loc`): schools for a student's work-or-school, clinics, parks,
   gyms, museums and libraries, places of worship from the OSM pull
   (`city.sim.venues`); another resident's home for :other-home; a street-graph
   node near the anchor for :neighbourhood and :elsewhere; an employer firm for
   :business. Each class is one more CSR over the same grid, chosen by the
   same binary search. Only work, store and restaurant count a *visit* against
   a firm; the rest only make a trip leg."
  (:require [city.sim.world :as w]
            [city.sim.network :as net]
            [city.sim.venues :as venues]))

;; ---- hash RNG (GPU-safe, per-agent streams) -------------------------------------------

(defn splitmix ^long [^long x]
  (let [z (unchecked-add x -7046029254386353131)
        z (unchecked-multiply (bit-xor z (unsigned-bit-shift-right z 30)) -4658895280553007687)
        z (unchecked-multiply (bit-xor z (unsigned-bit-shift-right z 27)) -7723592293110705685)]
    (bit-xor z (unsigned-bit-shift-right z 31))))

(defn stream
  "The 64-bit stream key of person (or edge, node) `i` under `seed`. Distinct
   for every (seed, i) with 0 <= i < 1,000,003, and scrambled, so that draw
   indices added to it cannot line up across seeds or persons the way a linear
   combination does (seed s+190 once replayed seed s shifted by 23,993 persons)."
  ^long [^long seed ^long i]
  (splitmix (unchecked-add (unchecked-multiply seed 1000003) i)))

(defn uniform
  "A uniform double in [0, 1): the top 53 bits of splitmix(stream(seed, i) + k).

   Draw indices `k` are reserved by purpose, so one person's draws never meet:
     0              the diary
     1 … 976        the venue of episode k-1 (diaries are far shorter)
     977, 978       diary-mode retention (`p-keep`)
     3001 + leg     route variant of a traced leg
     100000 + k     demand class of store episode k (`kernel/spend-day!`)
     200000 + k     leakage of store episode k
     300000 + t     workplace attempt t (`cityworld/assign-workplaces-grid!`)
   `kernel.clj` inlines the same arithmetic in its device kernels."
  ^double [^long seed ^long i ^long k]
  (/ (double (unsigned-bit-shift-right (splitmix (unchecked-add (stream seed i) k)) 11))
     9007199254740992.0))

;; ---- grid + gravity CDF tables -------------------------------------------------------------

(defn grid-spec [{:keys [firms persons]} & {:keys [cell-m] :or {cell-m 100.0}}]
  (let [lons (concat (remove #(Double/isNaN %) (seq ^doubles (:home-lon persons))) (seq ^doubles (:lon firms)))
        lats (concat (remove #(Double/isNaN %) (seq ^doubles (:home-lat persons))) (seq ^doubles (:lat firms)))
        west (apply min lons) east (apply max lons) south (apply min lats) north (apply max lats)
        dlat (/ cell-m 111320.0) dlon (/ cell-m (* 111320.0 (Math/cos (Math/toRadians (/ (+ south north) 2)))))
        W (inc (long (/ (- east west) dlon))) H (inc (long (/ (- north south) dlat)))]
    {:west west :south south :dlon dlon :dlat dlat :W W :H H :n (* W H)}))

(defn grid-bbox
  "The grid's own bounding box, optionally grown by `pad-m` metres — what the
   venue pulls are selected by."
  [{:keys [west south dlon dlat W H]} & {:keys [pad-m] :or {pad-m 500.0}}]
  (let [dlat' (/ pad-m 111320.0)
        dlon' (/ pad-m (* 111320.0 (Math/cos (Math/toRadians south))))]
    {:west (- west dlon') :south (- south dlat')
     :east (+ west (* W dlon) dlon') :north (+ south (* H dlat) dlat')}))

(defn cell-of ^long [{:keys [west south dlon dlat W H]} ^double lon ^double lat]
  (let [cx (min (dec W) (max 0 (long (/ (- lon west) dlon))))
        cy (min (dec H) (max 0 (long (/ (- lat south) dlat))))]
    (+ cx (* cy W))))

(defn cell-center [{:keys [west south dlon dlat W]} ^long c]
  [(+ west (* (+ 0.5 (mod c W)) dlon)) (+ south (* (+ 0.5 (quot c W)) dlat))])

(defn gravity-table
  "For every cell, the top-K venues with flag=1 by **w = attract^α · f(d)**,
   as CSR {:offsets int[n+1] :venues int[] :cdf double[]} (cdf normalized to 1
   per cell). This is the par/map over cells; a sort-free top-K selection.

   Two decay forms, because a neighbourhood destination and a city-centre one
   are not the same decision:

   - `:kernel :exp` — f(d) = exp(−d/λ), the original kernel. λ is a *length*:
     at 3λ the weight is 5 % and at 6λ it is 0.25 %, so nothing outside a few λ
     can ever be chosen however large it is.
   - `:kernel :power` — f(d) = (1 + d/d₀)^−β, the Huff / universal-visitation
     form (Schläpfer 2021; Deep Gravity). It is flat inside d₀ and scale-free
     outside it, so a destination ten times further away is only ~10^β times
     less attractive and a large enough one still wins. This is the form a
     *city centre* needs: Königstraße's 80,000 daily pedestrians are people who
     travelled to the centre because it is the centre.

   `attract` is a per-venue size (see `venue-attract`); α = 0 removes the size
   term entirely and gives a pure-distance kernel, α = 1 is proportional to
   size (the classic Huff exponent).

   `max-m` bounds the choice set: a candidate further than that gets weight 0
   and is never picked, which is how the classes that are *neighbourhood* by
   definition (another home within 1.5 km, a street node within 500 m) are
   built with the same kernel. A cell with nothing in reach keeps venue −1 and
   the caller makes no trip.

   K is the other half of the choice set: with K = 16 a distant centre can be
   crowded out of a cell's CDF by the sixteen shops on the corner *before* the
   kernel is ever consulted, so the size term only becomes visible at K ≈ 64."
  [grid firms ^ints flag & {:keys [k lambda-m attract max-m alpha kernel d0-m beta]
                            :or {k 16 lambda-m 400.0 alpha 1.0 kernel :exp d0-m 500.0 beta 2.0}}]
  (let [nf (:n firms) ^doubles flon (:lon firms) ^doubles flat (:lat firms) ^ints alive (:alive firms)
        cand (int-array (filter #(and (= 1 (aget flag %)) (= 1 (aget alive %))) (range nf)))
        nc (alength cand) n (:n grid)
        kk (min k nc)
        bounded? (boolean (and max-m (pos? (double max-m))))
        mx (double (or max-m 0.0))
        ;; degree box for the cheap reject when max-m is set
        mlat (if bounded? (/ mx 111320.0) 0.0)
        mlon (if bounded? (/ mx (* 111320.0 (Math/cos (Math/toRadians (double (:south grid)))))) 0.0)
        ;; attract^α once per candidate, not once per (cell, candidate)
        alpha (double alpha)
        ^doubles aw (let [a (double-array nc)]
                      (dotimes [q nc]
                        (aset a q (let [x (if attract (aget ^doubles attract (aget cand q)) 1.0)]
                                    (cond (zero? alpha) 1.0
                                          (= 1.0 alpha) (max 0.0 x)
                                          :else (Math/pow (max 0.0 x) alpha)))))
                      a)
        power? (= :power kernel)
        inv-d0 (/ 1.0 (double d0-m))
        beta (double beta)
        ;; β ∈ {1,2,3} by multiplication; anything else by Math/pow
        bmode (long (cond (= 1.0 beta) 1 (= 2.0 beta) 2 (= 3.0 beta) 3 :else 0))
        nbeta (- beta)
        neg-inv-lambda (/ -1.0 (double lambda-m))
        offsets (int-array (inc n)) venues (int-array (* n kk)) cdf (double-array (* n kk))]
    (dotimes [c n]
      (let [[lon lat] (cell-center grid c)
            lon (double lon) lat (double lat)
            best-i (int-array kk -1) best-w (double-array kk)]
        ;; insertion into a small top-K buffer: O(nc·k) per cell, no allocation
        (dotimes [q nc]
          (let [j (aget cand q)
                vlon (aget flon j) vlat (aget flat j)]
            (when (or (not bounded?)
                      (and (<= (Math/abs (- vlat lat)) (double mlat)) (<= (Math/abs (- vlon lon)) (double mlon))))
              (let [d (w/haversine-m lon lat vlon vlat)]
                (when (or (not bounded?) (<= d mx))
                  (let [decay (if power?
                                (let [x (+ 1.0 (* d inv-d0))]
                                  (case bmode
                                    1 (/ 1.0 x)
                                    2 (/ 1.0 (* x x))
                                    3 (/ 1.0 (* x x x))
                                    (Math/pow x nbeta)))
                                (Math/exp (* d neg-inv-lambda)))
                        wgt (* (aget aw q) decay)]
                    (when (> wgt (aget best-w (dec kk)))
                      (loop [p (dec kk)]
                        (if (and (pos? p) (> wgt (aget best-w (dec p))))
                          (do (aset best-w p (aget best-w (dec p))) (aset best-i p (aget best-i (dec p))) (recur (dec p)))
                          (do (aset best-w p wgt) (aset best-i p j)))))))))))
        (let [base (* c kk) total (reduce + (seq best-w))]
          (aset offsets (inc c) (+ base kk))
          (loop [p 0 acc 0.0]
            (when (< p kk)
              (let [acc (+ acc (if (pos? total) (/ (aget best-w p) total) (/ 1.0 kk)))]
                (aset venues (+ base p) (aget best-i p)) (aset cdf (+ base p) acc) (recur (inc p) acc)))))))
    {:offsets offsets :venues venues :cdf cdf :k kk}))

(defn- pick-from-cdf ^long [{:keys [^ints offsets ^ints venues ^doubles cdf]} ^long cell ^double u]
  (let [lo (aget offsets cell) hi (aget offsets (inc cell))]
    (if (>= lo hi)
      -1
      (loop [a lo b (dec hi)]
        (if (>= a b) (aget venues a)
            (let [m (quot (+ a b) 2)]
              (if (< u (aget cdf m)) (recur a m) (recur (inc m) b))))))))

(defn- pick-diary
  "The diary of person type `t` whose cumulative weight first exceeds `u`: a
   binary search in the type's slice of `type-cdf`."
  ^long [^ints type-offsets ^doubles type-cdf ^long t ^double u]
  (loop [lo (aget type-offsets t) hi (dec (aget type-offsets (inc t)))]
    (if (>= lo hi) lo
        (let [m (quot (+ lo hi) 2)]
          (if (< u (aget type-cdf m)) (recur lo m) (recur (inc m) hi))))))

;; ---- diary tables --------------------------------------------------------------------------

(def loc-codes
  "TUS 2022 location (`city.synth.timeuse/locations`) → episode code. All
   thirteen non-travel locations are here: every one of them is somewhere a
   person goes, and the venue classes below say where."
  {:home 0 :work-or-school 1 :store 2 :restaurant 3
   :other-home 4 :neighbourhood 5 :outdoors 6 :culture 7 :sports-venue 8
   :worship 9 :clinic 10 :elsewhere 11 :business 12})

(def n-loc (count loc-codes))

(def class-of-loc
  "Episode code → venue class. Code 1 (work-or-school) resolves to :school only
   for a person with no workplace — a student; a worker goes to their firm.
   Codes 0/2/3 have their own destinations (home, retail, food firms)."
  {1 :school 4 :other-home 5 :street 6 :outdoors 7 :culture 8 :sports
   9 :worship 10 :clinic 11 :street 12 :business})

(def purpose-of-loc
  "Leg purpose per episode code — the small vocabulary the map colours by
   (work, store, restaurant, home, school, leisure, other)."
  ["home" "work" "store" "restaurant" "other" "other" "leisure" "leisure"
   "leisure" "other" "other" "other" "other"])

(def count-names
  "Day counters: the three that count firm visits, then one leg counter per
   episode code that goes to a venue class."
  [:diaries :work-episodes :store-visits :restaurant-visits
   :other-home-legs :neighbourhood-legs :outdoors-legs :culture-legs
   :sports-legs :worship-legs :clinic-legs :elsewhere-legs :business-legs
   :school-legs :no-venue])

(def n-counts (count count-names))
(def school-count 13)
(def no-venue-count 14)

(def mode-codes
  "Travel-episode locations (TUS 3313–3323) → a small mode code, kept with the
   travel table so a leg can later be routed on the right network."
  {:car-driver 0 :car-passenger 1 :walk 2 :transit 3 :bike 4 :motorcycle 5
   :taxi 6 :ridehail 7 :ferry 8 :air 9 :travel-other 10 :travel-ns 10 :unknown 10})

(def census-mode-codes
  "Census commute-mode columns → the same mode codes. `:other` stays 10, which
   the router resolves by distance."
  {:car 0 :transit 3 :walk 2 :bike 4 :other 10})

(def default-travel-min
  "Assumed departure lead when a venue episode is *not* directly preceded by a
   travel episode (the diary just jumps location)."
  15)

(defn- split-chain
  "One diary chain → {:venues [[loc start depart arrive mode] ...]
                      :travels [[start dur mode] ...]}.

   Movement happens during travel episodes only: a venue episode takes its
   departure and arrival from the travel episode that *directly* precedes it,
   and otherwise the person is assumed to leave `default-travel-min` minutes
   before the episode starts. Episodes at locations without a code are dropped
   (they generate no venue visits) but still break the 'directly precedes'
   chain, which is what we want — an untracked stop is not a trip leg.

   Consecutive episodes at the *same* location with no travel between them are
   one stay, not two: the TUS splits an episode when the activity changes, so
   eating and then socializing at the same restaurant is two episodes and one
   place. Without this rule every such pair would draw a second venue and
   invent a trip between them."
  [chain]
  (loop [es (seq chain) prev nil last-loc nil venues [] travels []]
    (if-let [e (first es)]
      (let [start (long (or (:start e) 0)) dur (long (or (:dur e) 0))]
        (if (= :travel (:act e))
          (recur (next es) e nil venues (conj travels [start dur (mode-codes (:loc e) 10)]))
          (if-let [c (loc-codes (:loc e))]
            (if (= last-loc c)
              (recur (next es) e last-loc venues travels)   ; same place, still there
              (let [pt (when (and prev (= :travel (:act prev))) prev)
                    arrive (if pt (min start (+ (long (:start pt)) (long (:dur pt)))) start)
                    depart (if pt (long (:start pt)) (- start default-travel-min))
                    depart (max 0 (min depart (max 0 (dec arrive))))]
                (recur (next es) e c
                       (conj venues [c start depart arrive (if pt (mode-codes (:loc pt) 10) -1)])
                       travels)))
            (recur (next es) e nil venues travels))))
      {:venues venues :travels travels})))

(defn diary-tables
  "by-type {[act age sex] [{:weight :chain [{:act :loc :start :dur}]}]} → flat
   tables. type-index: map type → t; per type CSR over diaries with cumulative
   weight; per diary CSR over venue episodes (location code, start minute, and
   the departure/arrival minutes of the movement that brought the person there)
   plus a CSR over the diary's travel episodes (start, duration, mode)."
  [by-type]
  (let [types (vec (keys by-type)) tix (zipmap types (range))
        diaries (vec (mapcat (fn [t] (map #(assoc % :t (tix t)) (by-type t))) types))
        ;; type → diary CSR
        by-t (group-by :t diaries)
        t-off (int-array (inc (count types)))
        _ (dotimes [t (count types)] (aset t-off (inc t) (+ (aget t-off t) (count (by-t t)))))
        ordered (vec (mapcat #(by-t %) (range (count types))))
        t-cdf (double-array (count ordered))
        _ (dotimes [t (count types)]
            (let [a (aget t-off t) b (aget t-off (inc t)) tot (reduce + (map #(double (or (:weight %) 1.0)) (subvec ordered a b)))]
              (loop [i a acc 0.0] (when (< i b) (let [acc (+ acc (/ (double (or (:weight (ordered i)) 1.0)) tot))] (aset t-cdf i acc) (recur (inc i) acc))))))
        split (mapv #(split-chain (:chain %)) ordered)
        eps (mapv :venues split)
        trs (mapv :travels split)
        d-off (int-array (inc (count ordered)))
        _ (dotimes [i (count ordered)] (aset d-off (inc i) (+ (aget d-off i) (count (eps i)))))
        tr-off (int-array (inc (count ordered)))
        _ (dotimes [i (count ordered)] (aset tr-off (inc i) (+ (aget tr-off i) (count (trs i)))))
        ne (aget d-off (count ordered))
        nt (aget tr-off (count ordered))
        ep-loc (int-array ne) ep-minute (int-array ne)
        ep-depart (int-array ne) ep-arrive (int-array ne) ep-mode (int-array ne -1)
        tr-start (int-array nt) tr-dur (int-array nt) tr-mode (int-array nt)
        diary-start (int-array (count ordered) 240)
        diary-end (int-array (count ordered) 1440)
        clamp (fn ^long [^long m] (min 1440 (max 0 m)))]
    (dotimes [i (count ordered)]
      (let [base (aget d-off i)
            tbase (aget tr-off i)
            chain (:chain (ordered i))]
        (when (seq chain)
          (aset diary-start i (int (clamp (long (:start (first chain))))))
          (aset diary-end i (int (clamp (reduce max (map #(+ (long (:start %)) (long (:dur %))) chain))))))
        (doseq [[q [c minute depart arrive mode]] (map-indexed vector (eps i))]
          (aset ep-loc (+ base q) c)
          (aset ep-minute (+ base q) (int (clamp minute)))
          (aset ep-depart (+ base q) (int (clamp depart)))
          (aset ep-arrive (+ base q) (int (clamp arrive)))
          (aset ep-mode (+ base q) (int mode)))
        (doseq [[q [start dur mode]] (map-indexed vector (trs i))]
          (aset tr-start (+ tbase q) (int (clamp start)))
          (aset tr-dur (+ tbase q) (int dur))
          (aset tr-mode (+ tbase q) (int mode)))))
    {:types tix :n-types (count types) :type-offsets t-off :type-cdf t-cdf
     :diary-offsets d-off :diary-start diary-start :diary-end diary-end
     :ep-loc ep-loc :ep-minute ep-minute
     :ep-depart ep-depart :ep-arrive ep-arrive :ep-mode ep-mode
     :travel-offsets tr-off :tr-start tr-start :tr-dur tr-dur :tr-mode tr-mode}))

(defn person-types
  "int[] type index per person (−1 = no diary: children, or missing type → fall
   back to any type with the same activity status)."
  [persons {:keys [types]}]
  (let [n (:n persons) ^ints labour (:labour persons) ^ints attsch (:attsch persons) ^ints age (:age persons) ^ints sex (:sex persons)
        by-act (group-by first (keys types))
        out (int-array n -1)]
    (dotimes [i n]
      (when (>= (aget age i) 3)
        (let [l (aget labour i)
              act (cond (<= 1 l 2) :worker (= 1 (aget attsch i)) :student (>= (aget age i) 12) :retired :else :home)
              ag (case (long (aget age i)) (3 4) :a15-24 (5 6) :a25-34 (7 8) :a35-44 (9 10) :a45-54 11 :a55-64 12 :a65-74 13 :a75+ :child)
              sx (case (long (aget sex i)) 1 :women 2 :men :na)
              t (or (types [act ag sx]) (some types (by-act act)))]
          (when t (aset out i (int t))))))
    out))

;; ---- the mode table (census commute modes per DA) --------------------------------------------

(def mode-order [:car :transit :walk :bike :other])

(defn- mode-table* [persons shares]
  (when (seq shares)
    (let [n (:n persons) ^objects da (:da persons)
          present (vec (distinct (filter shares (remove nil? (seq da)))))]
      (when (seq present)
        (let [pooled (apply merge-with + (map shares present))
              rows (into [pooled] (map shares present))
              ix (zipmap present (map inc (range)))
              row (int-array n)
              _ (dotimes [i n] (aset row i (int (get ix (aget da i) 0))))
              nr (count rows)
              cdf (double-array (* nr (count mode-order)))]
          (dotimes [r nr]
            (let [m (rows r) tot (double (reduce + (map #(get m % 0) mode-order)))]
              (loop [q 0 acc 0.0]
                (when (< q (count mode-order))
                  (let [acc (+ acc (if (pos? tot) (/ (double (get m (mode-order q) 0)) tot) (/ 1.0 (count mode-order))))]
                    (aset cdf (+ (* r (count mode-order)) q) acc)
                    (recur (inc q) acc))))))
          {:row row :cdf cdf :rows nr
           :codes (int-array (map census-mode-codes mode-order))
           :pooled (let [tot (double (reduce + (map #(get pooled % 0) mode-order)))]
                     (into {} (for [m mode-order] [m (/ (Math/round (* 1000.0 (/ (double (get pooled m 0)) tot))) 1000.0)])))})))))

(defn city-wide?
  "Is `shares` one mode profile for the whole city rather than a map of
   per-zone profiles? A city-wide profile is `{:car n :transit n …}`, so its
   values are numbers; a per-zone map's values are maps."
  [shares]
  (and (map? shares) (seq shares) (every? number? (vals shares))))

(defn mode-table
  "The commute-mode CDF as a flat table
   {:row int[n-persons] :cdf double[rows*5] :codes int[5] :rows n :pooled}.

   `shares` is either **one** profile `{:car n :transit n :walk n :bike n
   :other n}` for the whole city, or a map zone → profile. Stuttgart uses one
   profile (`city.sim.cityworld/mid-2017-stuttgart-modes`): MiD publishes the
   Stadt and nothing smaller, so every person draws from the same row and the
   table has exactly one, rather than 152 identical Stadtteil splits.

   With per-zone profiles, row 0 is the pooled split over the zones the world
   contains and is used for anyone whose zone is unknown. With no `shares` at
   all there is no table, and legs fall back to the distance rule."
  [persons shares]
  (if (city-wide? shares)
    (let [n (:n persons) ord mode-order
          tot (double (reduce + (map #(get shares % 0) ord)))
          cdf (double-array (count ord))]
      (loop [q 0 acc 0.0]
        (when (< q (count ord))
          (let [acc (+ acc (if (pos? tot) (/ (double (get shares (ord q) 0)) tot) (/ 1.0 (count ord))))]
            (aset cdf q acc) (recur (inc q) acc))))
      {:row (int-array n) :cdf cdf :rows 1
       :codes (int-array (map census-mode-codes ord))
       :city-wide? true
       :pooled (into {} (for [m ord] [m (/ (Math/round (* 1000.0 (/ (double (get shares m 0)) tot))) 1000.0)]))})
    (mode-table* persons shares)))

(def default-p-keep-diary-mode
  "Probability that a leg *whose diary timed it* keeps the diary's own travel
   mode instead of the person's census draw. TUS 2022 measures urban Canada
   (78 % car); the census measures this person's own dissemination area. Half
   and half is the deliberate middle: neither source is right for a specific
   person on a specific day, and the parameter is the only honest place to say
   so. Drawn once per person-day, so a person is a diary person or a census
   person for the whole day and their legs stay consistent."
  0.5)

(defn- census-day?
  "Is this person-day's mode taken from the census rather than from the diary?
   One draw per person-day (`p-keep` is the probability of keeping the diary)."
  [^long i ^long seed ^double p-keep]
  (>= (uniform seed i 978) p-keep))

(defn- profile-mode
  "The person's census mode applied to one leg. A census commute mode is a
   *profile*, not a promise: a walk person walks up to
   `net/profile-walk-max-m` and rides transit beyond it, a bike person likewise
   above `net/profile-bike-max-m`; car is car, transit is transit (the router
   degrades a too-short ride to a walk), and census `other` falls back to the
   distance rule."
  [^long code ^double crow-m]
  (let [m (net/mode-of-code code :unknown)]
    (cond
      (and (= :walk m) (> crow-m (double net/profile-walk-max-m))) :transit
      (and (= :bike m) (> crow-m (double net/profile-bike-max-m))) :transit
      :else m)))

(defn- sample-mode
  "The person's default mode for the day: one draw from their DA's commute-mode
   split. −1 when there is no table (the distance rule then applies)."
  ^long [mode-table ^long i ^long seed]
  (if (nil? mode-table)
    -1
    (let [^ints row (:row mode-table) ^doubles cdf (:cdf mode-table) ^ints codes (:codes mode-table)
          base (* (aget row i) 5)
          u (uniform seed i 977)]
      (loop [q 0]
        (if (or (= q 4) (< u (aget cdf (+ base q))))
          (aget codes q)
          (recur (inc q)))))))

;; ---- venue attractiveness and the per-class kernel table ------------------------------------

(defn customer-flag
  "1 for every firm a diary can *visit* — retail, food or an observed
   storefront. This is the population the street-density proxy counts, not the
   candidate set of any one table: a restaurant makes the block it is on a
   destination for a shopper too."
  ^ints [firms]
  (let [n (:n firms) a (int-array n)
        ^ints rt (or (:retail firms) (int-array n)) ^ints fo (or (:food firms) (int-array n))
        ^ints sf (or (:storefront firms) (int-array n))]
    (dotimes [j n] (when (or (= 1 (aget rt j)) (= 1 (aget fo j)) (= 1 (aget sf j))) (aset a j 1)))
    a))

(defn colocation-counts
  "For every firm, how many flagged venues (itself included) lie within
   `radius-m` — a spatial hash at exactly that radius, so the cost is the
   venues in the nine neighbouring buckets and not the 8·10⁹ pairs a city's
   90k firms would otherwise be."
  ^doubles [firms ^ints flag ^double radius-m]
  (let [n (:n firms) ^doubles flon (:lon firms) ^doubles flat (:lat firms)
        idx (filterv #(= 1 (aget flag %)) (range n))
        lat0 (if (seq idx) (aget flat (first idx)) 0.0)
        dlat (/ radius-m 111320.0)
        dlon (/ radius-m (* 111320.0 (Math/cos (Math/toRadians lat0))))
        cx (fn ^long [^long j] (long (Math/floor (/ (aget flon j) dlon))))
        cy (fn ^long [^long j] (long (Math/floor (/ (aget flat j) dlat))))
        key (fn ^long [^long x ^long y] (+ (* y 100000000) x))
        buckets (persistent!
                 (reduce (fn [m j] (let [k (key (cx j) (cy j))]
                                     (assoc! m k (conj (get m k []) j))))
                         (transient {}) idx))
        out (double-array n)]
    (dotimes [j n]
      (let [x (cx j) y (cy j) plon (aget flon j) plat (aget flat j)]
        (aset out j
              (double (reduce + (for [dx [-1 0 1] dy [-1 0 1]
                                      q (get buckets (key (+ x dx) (+ y dy)) [])
                                      :when (<= (w/haversine-m plon plat (aget flon (long q)) (aget flat (long q))) radius-m)]
                                  1))))))
    out))

(def default-attract-radius-m
  "Radius of the street-density proxy: 100 m is one block face, which is the
   scale at which 'this is a shopping street' is true or false."
  100.0)

(defn venue-attract
  "Fallback attractiveness per firm, used when `prepare` is given no
   `:attract` (the Stuttgart run passes the raked floor area of
   `city.synth.retail/attract`). In the order the data supports it:

   1. an **observed** employee count (`:emp-observed` 1, for example a matched
      anchor employer), because a statement is a measurement;
   2. else the number of **co-located customer-facing venues within
      `radius-m`**, the street-density proxy that makes a shopping street
      larger than a corner shop;
   3. else 1.

   A synthesized headcount is not a measurement and does not win here.
   Stuttgart's employee counts are an allocation of sector totals across
   Overture places, and that allocation once put 2,889 employees on a
   convenience store and 1 on the median shop of Königstraße.

   It is one number per venue and it mixes two units: a 40-employee
   supermarket and a shop on a block with 40 other shops score the same."
  ^doubles [firms & {:keys [radius-m] :or {radius-m default-attract-radius-m}}]
  (let [n (:n firms) ^ints emp (:employees firms)
        ^ints obs (or (:emp-observed firms) (int-array n 1))
        ^doubles co (colocation-counts firms (customer-flag firms) (double radius-m))
        a (double-array n)]
    (dotimes [j n]
      (aset a j (max 1.0 (if (and (= 1 (aget obs j)) (pos? (aget emp j)))
                           (double (aget emp j))
                           (aget co j)))))
    a))

(def default-venue-kernels
  "Per venue class, the destination-choice kernel `gravity-table` builds:
   `{:kernel :exp|:power :alpha α :lambda-m λ :d0-m d₀ :beta β :k K :max-m}`.
   `city.sim.run/defaults` reads the store and restaurant numbers from here.

   **Store and restaurant** (`:retail`, `:food`) use the competing-destinations
   form, size^α with a power decay, because they are the only classes for
   which a city centre is the right answer. β = 1.6 was calibrated by hand
   against the district turnover of the 2024 retail concept (see the `:venue-beta`
   entry of `city.sim.run/defaults`). The store kernel of the traced day uses
   these numbers through the exact dense table (`city.sim.candidates`, K is
   ignored there); the economic day and the likelihood use one inferred kernel
   per demand class instead. The restaurant table keeps the top K = 64 venues
   per cell: K truncates the choice set and is an approximation, not a
   behavioural parameter.

   Every other class keeps a pure-distance exponential kernel, deliberately: a
   park, a clinic or a school is a neighbourhood destination whose
   attractiveness the model has no measurement of, and `:other-home` and
   `:street` are defined by their radius (another resident's home within
   1.5 km, a street node within 500 m)."
  {:retail     {:kernel :power :alpha 1.0 :d0-m 500.0 :beta 1.6 :lambda-m 400.0 :k 64}
   :food       {:kernel :power :alpha 1.0 :d0-m 500.0 :beta 1.6 :lambda-m 400.0 :k 64}
   :school     {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :clinic     {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :outdoors   {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :sports     {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :culture    {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :worship    {:kernel :exp :alpha 1.0 :lambda-m 400.0 :k 16}
   :other-home {:kernel :exp :alpha 1.0 :lambda-m 1500.0 :k 64 :max-m 1500.0}
   :street     {:kernel :exp :alpha 1.0 :lambda-m 1500.0 :k 16 :max-m 500.0}
   :business   {:kernel :exp :alpha 1.0 :lambda-m 1500.0 :k 16}})

(defn venue-kernels
  "The per-class kernel table with the store and restaurant kernels taken
   from a run config's scalar parameters (`city.sim.run/config`). Keys that
   are absent leave the default alone."
  [{:keys [venue-kernel venue-alpha venue-beta venue-d0-m venue-lambda-m k-venues]}]
  (let [spec (cond-> {}
               venue-kernel (assoc :kernel venue-kernel)
               venue-alpha (assoc :alpha venue-alpha)
               venue-beta (assoc :beta venue-beta)
               venue-d0-m (assoc :d0-m venue-d0-m)
               venue-lambda-m (assoc :lambda-m venue-lambda-m)
               k-venues (assoc :k k-venues))]
    (-> default-venue-kernels
        (update :retail merge spec)
        (update :food merge spec))))

(defn- kernel-args
  "One class's kernel spec → the kwarg seq `gravity-table` takes."
  [spec attract]
  (apply concat (cond-> (select-keys (merge {:k 16 :lambda-m 400.0 :alpha 1.0 :kernel :exp} spec)
                                     [:k :lambda-m :alpha :kernel :d0-m :beta :max-m])
                  attract (assoc :attract attract))))

;; ---- venue classes -----------------------------------------------------------------------

(defn- class-table
  "One venue class: the gravity CSR over the grid plus the class's own
   coordinate arrays. A venue index indexes *these* arrays, not the firm table
   — only work, store and restaurant count a visit against a firm."
  [grid ^doubles lon ^doubles lat ^ints flag spec attract]
  (let [n (alength lon)]
    (when (and (pos? n) (pos? (areduce flag i s 0 (+ s (aget flag i)))))
      {:table (apply gravity-table grid {:n n :lon lon :lat lat :alive (int-array n 1)} flag
                     (kernel-args spec attract))
       :lon lon :lat lat})))

(defn venue-classes
  "class → {:table CSR :lon :lat} for every destination the diary needs beyond
   home / workplace / retail / food:

   - the OSM classes (:school :clinic :outdoors :sports :culture :worship) from
     `city.sim.venues`, chosen by the same gravity rule as a store
   - :other-home — the occupied home cells, weighted by how many residents live
     in them and capped at 1.5 km: 'a random other resident's home nearby'
   - :street — a street-graph node within 500 m of the anchor, which is what
     :neighbourhood and :elsewhere are: a destination in the block, not a named
     place. Nodes carry a hashed attractiveness so the top-K is a spread of the
     nodes in reach rather than the first sixteen in graph order
   - :business — an employer firm, weighted by its employees

   Each class's kernel is its entry in `kernels` (default
   `default-venue-kernels`), one documented table a run config can move."
  [grid persons firms & {:keys [venue-table net-ds kernels]}]
  (let [kern (merge default-venue-kernels kernels)
        vt venue-table
        osm (when vt
              (let [^objects cls (:class vt) nv (:n vt)]
                (into {} (for [c [:school :clinic :outdoors :sports :culture :worship]
                               :let [flag (int-array nv)
                                     _ (dotimes [j nv] (when (= c (aget cls j)) (aset flag j 1)))
                                     t (class-table grid (:lon vt) (:lat vt) flag (kern c) nil)]
                               :when t]
                           [c t]))))
        ;; occupied home cells: cell centre, weight = residents
        n (:n persons) ^doubles hlon (:home-lon persons) ^doubles hlat (:home-lat persons)
        pop (int-array (:n grid))
        _ (dotimes [i n] (when-not (Double/isNaN (aget hlon i))
                           (let [c (cell-of grid (aget hlon i) (aget hlat i))] (aset pop c (inc (aget pop c))))))
        occupied (int-array (filter #(pos? (aget pop %)) (range (:n grid))))
        no (alength occupied)
        home-class (when (pos? no)
                     (let [hl (double-array no) ht (double-array no) att (double-array no) flag (int-array no 1)]
                       (dotimes [q no]
                         (let [[clon clat] (cell-center grid (aget occupied q))]
                           (aset hl q (double clon)) (aset ht q (double clat))
                           (aset att q (double (aget pop (aget occupied q))))))
                       (class-table grid hl ht flag (:other-home kern) att)))
        ;; street nodes within 500 m, on whatever graph is loaded (as
        ;; `net/route-fn`). `:net-ds` names a pull explicitly, and a named pull
        ;; that fails to load throws: a nil :street class would silently drop
        ;; every :neighbourhood and :elsewhere episode. Only the implicit case
        ;; stays quiet.
        street (let [nt (if net-ds
                          (do (net/load! :ds net-ds) @net/net)
                          (try (when (nil? @net/net) (net/load!))
                               @net/net
                               (catch Exception _ nil)))]
                 (when nt
                   (let [nn (:n nt) att (double-array nn) flag (int-array nn 1)]
                     (dotimes [j nn] (aset att j (+ 0.05 (uniform 987654321 j 0))))
                     (class-table grid (:lon nt) (:lat nt) flag (:street kern) att))))
        ;; employer firms
        nf (:n firms) ^ints femp (:employees firms)
        emp-flag (int-array nf) emp-att (double-array nf)
        _ (dotimes [j nf] (when (pos? (aget femp j)) (aset emp-flag j 1) (aset emp-att j (double (aget femp j)))))
        business (class-table grid (:lon firms) (:lat firms) emp-flag (:business kern) emp-att)]
    (cond-> (or osm {})
      home-class (assoc :other-home home-class)
      street (assoc :street street)
      business (assoc :business business))))

;; ---- the step --------------------------------------------------------------------------------

(defn prepare
  "Build all tables for a world once.

   `:kernels` overrides entries of the per-class kernel table (see
   `default-venue-kernels`); `:attract` is the per-firm attractiveness the
   store and restaurant kernels raise to α (see `venue-attract`), computed here
   when not supplied. `:retail` is a ready store choice table, normally the
   exact one from `city.sim.candidates/table-dense`; without it the store
   table is a top-K `gravity-table`, which keeps only part of the power
   kernel's mass (see `city.sim.candidates`). `:mode-shares` is the city's
   commute-mode profile (see `mode-table`) and is required."
  [world by-type & {:keys [venue-table mode-shares net-ds kernels attract attract-radius-m retail]}]
  (let [grid (grid-spec world)
        fs (:firms world) ps (:persons world)
        kern (merge default-venue-kernels kernels)
        att (or attract (venue-attract fs :radius-m (or attract-radius-m default-attract-radius-m)))
        vt (if (nil? venue-table) (venues/table-cached (grid-bbox grid)) venue-table)
        retail (or retail
                   (apply gravity-table grid fs (or (:retail fs) (:storefront fs)) (kernel-args (:retail kern) att)))
        food (apply gravity-table grid fs (:food fs) (kernel-args (:food kern) att))
        classes (venue-classes grid ps fs :kernels kern :venue-table vt :net-ds net-ds)
        dt (diary-tables by-type)
        n (:n ps) ^doubles hlon (:home-lon ps) ^doubles hlat (:home-lat ps)
        home-cell (int-array n -1)
        _ (dotimes [i n] (when-not (Double/isNaN (aget hlon i)) (aset home-cell i (int (cell-of grid (aget hlon i) (aget hlat i))))))
        work-cell (int-array (:n fs))
        _ (dotimes [j (:n fs)] (aset work-cell j (int (cell-of grid (aget ^doubles (:lon fs) j) (aget ^doubles (:lat fs) j)))))
        shares (or mode-shares (throw (ex-info "prepare needs :mode-shares, the city's commute mode profile" {})))
        ;; episode code → class table / lon / lat, so the step is an array lookup
        by-loc (fn [f] (object-array (map (fn [c] (when-let [t (classes (class-of-loc c))] (f t))) (range n-loc))))]
    {:grid grid :retail retail :food food :diaries dt :classes classes
     :kernels kern :attract att
     :net-ds (or net-ds @net/net-source)
     :venues (when vt (select-keys vt [:n :receipts]))
     :cls-table (by-loc :table) :cls-lon (by-loc :lon) :cls-lat (by-loc :lat)
     :modes (mode-table ps shares)
     :ptype (person-types ps dt) :home-cell home-cell :work-cell work-cell}))

(defn step-day
  "One weekday for every person, untraced: `{:visits int[nf*24] :counts}`,
   visits by firm and hour. Written as the body of a par/map-void! over
   persons with atomic-add! on visits.

   An out-commuter's work episode has no destination here; `step-day-traces`
   sends it to the person's exit point at the city boundary and counts it in
   `:work-episodes`, so the two counters differ by those episodes while the
   visits agree."
  [world tables ^long seed]
  (let [{:keys [retail food diaries ^ints ptype ^ints home-cell ^ints work-cell
                ^objects cls-table]} tables
        {:keys [^ints type-offsets ^doubles type-cdf ^ints diary-offsets ^ints ep-loc ^ints ep-minute]} diaries
        ps (:persons world) n (:n ps) ^ints work (:work ps) ^ints attsch (:attsch ps) nf (:n (:firms world))
        visits (int-array (* nf 24))
        counts (long-array n-counts)]
    (dotimes [i n]
      (let [t (aget ptype i) wj (aget work i)]
        (when (and (>= t 0) (or (>= (aget home-cell i) 0) (>= wj 0)))
          (let [d (pick-diary type-offsets type-cdf t (uniform seed i 0))
                e0 (aget diary-offsets d) e1 (aget diary-offsets (inc d))
                start-cell (if (>= (aget home-cell i) 0) (aget home-cell i) (aget work-cell wj))]
            (aset counts 0 (inc (aget counts 0)))
            (loop [e e0 anchor start-cell]
              (when (< e e1)
                (let [loc (aget ep-loc e) h (mod (quot (aget ep-minute e) 60) 24) k (- e e0)]
                  (cond
                    (= loc 0) (recur (inc e) (if (>= (aget home-cell i) 0) (aget home-cell i) anchor))
                    (and (= loc 1) (>= wj 0))
                    (do (aset visits (+ (* wj 24) h) (inc (aget visits (+ (* wj 24) h))))
                        (aset counts 1 (inc (aget counts 1)))
                        (recur (inc e) (aget work-cell wj)))
                    (= loc 2) (let [v (pick-from-cdf retail anchor (uniform seed i (inc k)))]
                                (when (>= v 0)
                                  (aset visits (+ (* v 24) h) (inc (aget visits (+ (* v 24) h))))
                                  (aset counts 2 (inc (aget counts 2))))
                                (recur (inc e) anchor))
                    (= loc 3) (let [v (pick-from-cdf food anchor (uniform seed i (inc k)))]
                                (when (>= v 0)
                                  (aset visits (+ (* v 24) h) (inc (aget visits (+ (* v 24) h))))
                                  (aset counts 3 (inc (aget counts 3))))
                                (recur (inc e) anchor))
                    ;; work-or-school without a workplace: a school only for
                    ;; someone actually in school. A resident whose job is
                    ;; outside the district has no destination here — that trip
                    ;; needs the city-wide world, not a local venue.
                    (and (= loc 1) (not= 1 (aget attsch i))) (recur (inc e) anchor)
                    :else
                    (let [tbl (aget cls-table loc)]
                      (when tbl
                        (let [v (pick-from-cdf tbl anchor (uniform seed i (inc k)))
                              c (if (= loc 1) school-count loc)]
                          (if (>= v 0)
                            (aset counts c (inc (aget counts c)))
                            (aset counts no-venue-count (inc (aget counts no-venue-count))))))
                      (recur (inc e) anchor))))))))))
    {:visits visits :counts (zipmap count-names (seq counts))}))

(defn- trace-type [^ints labour ^ints attsch ^long i]
  (cond (<= 1 (aget labour i) 2) :worker
        (= 1 (aget attsch i)) :student
        :else :other))

(defn- leg-timestamps
  "Minute for every vertex of a leg's polyline, linear in distance along it
   between the departure and the arrival minute (constant speed on the leg)."
  [pts ^long depart ^long arrive]
  (let [n (count pts)
        span (double (- arrive depart))]
    (if (< n 2)
      [depart arrive]
      (let [ds (loop [q 1 acc 0.0 out [0.0]]
                 (if (= q n) out
                     (let [a (pts (dec q)) b (pts q)
                           acc (+ acc (w/haversine-m (double (a 0)) (double (a 1)) (double (b 0)) (double (b 1))))]
                       (recur (inc q) acc (conj out acc)))))
            tot (double (peek ds))]
        (if (pos? tot)
          (mapv (fn [d] (+ depart (long (Math/round (* span (/ (double d) tot)))))) ds)
          (mapv (fn [q] (+ depart (long (Math/round (* span (/ (double q) (dec n))))))) (range n)))))))

(defn- access-legs
  "The walk stubs of a transit leg (`city.sim.network/mode-router` :sub-legs)
   as legs of their own: access and egress walking is walking, so the
   pedestrian target has to see it as a walk polyline with its own clock. Their
   minutes are scaled into the parent leg's span, which the diary may have
   compressed or stretched relative to the routed time."
  [subs ^long depart ^long arrive ^double routed]
  (let [span (double (- arrive depart))
        scale (if (pos? routed) (/ span routed) 1.0)]
    (vec (for [{:keys [path meters minutes offset-min]} subs
               :when (>= (count path) 2)
               :let [d (+ depart (long (Math/round (* scale (double offset-min)))))
                     a (min arrive (+ d (max 1 (long (Math/round (* scale (double minutes)))))))
                     d (min d (dec a))]]
           {:purpose "access" :mode "walk" :access true
            :path path :timestamps (leg-timestamps path d a)
            :meters (/ (Math/round (double meters)) 1.0)
            :routed-min (/ (Math/round (* 10.0 (double minutes))) 10.0)}))))

(defn- make-leg
  "One trip leg: the routed polyline from → to, with a minute per vertex.
   `route` is a mode router (`city.sim.network/mode-router`) or nil, in which
   case the leg is the straight line at the diary's own timing.

   Mode rule (mode substitution). Every person draws one mode *profile* per
   day from their home DA's census commute split (`default-mode`; externals,
   who have no DA, draw from the pooled city split). A leg the diary timed
   keeps the diary's own mode on a `p-keep` day and takes the census profile on
   the rest; a leg the diary did not time always takes the census profile. Only
   when there is no census table at all does the leg fall back to the distance
   rule (walk under 1 km, else car). The keep/substitute draw is per
   person-day, so a person walks — or drives — consistently all day.

   Timing rule. When the diary timed the leg *and* its own mode survived, its
   departure and arrival are kept — the diary *measured* them — and the leg is
   only flagged `:slow` when the routed time is more than twice the reported
   one. Otherwise the routed time sets the leg: the person arrives when the
   episode starts and leaves `routed` minutes before that, so the episode's own
   start (which is data) is never contradicted. A substituted mode therefore
   changes both the speed and the clock, because a leg that was driven and is
   now walked does not take the driving time.

   `variant` is the walk route variant (see `city.sim.network/router`); it is
   only used when the leg ends up walked."
  [route alon alat blon blat purpose depart arrive mode-code default-mode census? variant]
  (let [alon (double alon) alat (double alat) blon (double blon) blat (double blat)
        depart (long depart) arrive (long arrive) mode-code (long mode-code) default-mode (long default-mode)
        diary? (>= mode-code 0)
        have-census? (>= default-mode 0)
        substitute? (and have-census? (or (not diary?) (boolean census?)))
        crow (w/haversine-m alon alat blon blat)
        mode (if substitute?
               (profile-mode default-mode crow)
               (net/mode-of-code mode-code :unknown))
        variant (if (= :walk mode) (long variant) 0)
        r (when route (route alon alat blon blat mode variant))
        pts (let [p (:path r)] (if (and p (>= (count p) 2)) p [[alon alat] [blon blat]]))
        routed (when r (double (:minutes r)))
        diary-min (max 1 (- arrive depart))
        keep-timing? (and diary? (not substitute?))
        [depart arrive] (if (or keep-timing? (nil? routed))
                          [depart (max arrive (inc depart))]
                          (let [t (max 1 (long (Math/round routed)))
                                a (max arrive 1)]
                            [(max 0 (- a t)) a]))
        slow? (boolean (and keep-timing? routed (> routed (* 2.0 diary-min))))]
    (cond-> {:purpose purpose :path pts :timestamps (leg-timestamps pts depart arrive)
             :mode (name (or (:mode r) mode))}
      (= :unknown mode) (assoc :mode-from :distance)
      (and substitute? (not= :unknown mode)) (assoc :mode-from :census)
      (and (not substitute?) diary? (not= :unknown mode)) (assoc :mode-from :diary)
      (and substitute? diary?) (assoc :substituted true)
      r (assoc :meters (/ (Math/round (double (:meters r))) 1.0)
               :routed-min (/ (Math/round (* 10.0 (double routed))) 10.0))
      diary? (assoc :diary-min diary-min)
      slow? (assoc :slow true)
      (seq (:sub-legs r)) (assoc :sub-legs (access-legs (:sub-legs r) depart arrive (double routed))))))

(defn step-day-traces
  "Run the same weekday step as `step-day`, additionally recording every
   `stride`-th eligible person's day as a sequence of *trip legs*. A person
   stays put at a venue and moves only during a travel episode: a leg runs
   from the previous location at the diary's departure minute to the new one
   at its arrival minute. `:route`, when given, is a *mode* router
   (lon1 lat1 lon2 lat2 mode) → {:path :meters :minutes}; without it legs are
   straight lines at the diary's own timing. `:leg-stats` reports how the two
   clocks compare: how many legs the diary timed at all, and how many of those
   the network says take more than twice as long as the diary claims.

   `:trace-fn`, when given, is called with each finished
   `{:type :person :legs}` and **nothing is retained** — a city-wide day at
   stride 1 is a million legs, which is a gigabyte of polylines if they are all
   kept and nothing at all if the consumer reduces them as they arrive.

   Two mode/route parameters:
   - `:p-keep` (default `default-p-keep-diary-mode`) — probability that a
     person-day keeps the diary's own travel modes; otherwise every leg of that
     day takes the person's census mode profile (see `make-leg`).
   - `:route-variants` (default `city.sim.network/walk-route-variants`) — how
     many near-shortest alternatives a *walk* leg draws between, so cross-town
     walkers are not all funnelled onto the one shortest diagonal.

   A transit leg's access and egress walk are emitted as extra legs of mode
   `walk` and purpose `access`, flagged `:access`, right after the transit leg
   itself."
  [world tables seed & {:keys [stride route trace-fn p-keep route-variants]
                       :or {stride 10 p-keep default-p-keep-diary-mode
                            route-variants net/walk-route-variants}}]
  (let [stride (max 1 (long stride))
        p-keep (double p-keep)
        route-variants (max 1 (long route-variants))
        {:keys [retail food diaries ^ints ptype ^ints home-cell ^ints work-cell
                ^objects cls-table ^objects cls-lon ^objects cls-lat modes]} tables
        {:keys [^ints type-offsets ^doubles type-cdf ^ints diary-offsets
                ^ints ep-loc ^ints ep-minute ^ints ep-depart ^ints ep-arrive ^ints ep-mode]} diaries
        ps (:persons world) n (:n ps) ^ints work (:work ps)
        ;; out-commuters: no firm to walk to, but a boundary exit point
        ^ints outside (or (:outside ps) (int-array n))
        ^doubles xlon (or (:exit-lon ps) (double-array n Double/NaN))
        ^doubles xlat (or (:exit-lat ps) (double-array n Double/NaN))
        ^ints labour (:labour ps) ^ints attsch (:attsch ps)
        fs (:firms world) nf (:n fs) ^doubles flon (:lon fs) ^doubles flat (:lat fs)
        grid (:grid tables)
        visits (int-array (* nf 24)) counts (long-array n-counts)
        traces (transient []) diary-number (volatile! 0)
        leg-stats (volatile! {})
        moved? (fn [^double alon ^double alat ^double blon ^double blat]
                 (or (> (Math/abs (- alon blon)) 1.0e-7) (> (Math/abs (- alat blat)) 1.0e-7)))]
    (dotimes [i n]
      (let [t (aget ptype i) wj (aget work i)]
        (when (and (>= t 0) (or (>= (aget home-cell i) 0) (>= wj 0)))
          (let [d (pick-diary type-offsets type-cdf t (uniform seed i 0))
                e0 (aget diary-offsets d) e1 (aget diary-offsets (inc d))
                home? (>= (aget home-cell i) 0)
                start-cell (if home? (aget home-cell i) (aget work-cell wj))
                ;; externals (no home in the world) start their day at work
                [base-lon base-lat] (if home?
                                      (let [[clon clat] (cell-center grid (aget home-cell i))]
                                        ;; the home cell centre, so the leg starts on the
                                        ;; street grid rather than in a jittered back yard
                                        [clon clat])
                                      [(aget flon wj) (aget flat wj)])
                ;; one census mode draw per person-day, plus one draw of whether
                ;; this day's legs keep the diary's own modes at all: the mode
                ;; profile is a property of the person-day, not of the leg
                default-mode (sample-mode modes i seed)
                census? (census-day? i seed p-keep)
                trace? (zero? (mod @diary-number stride))
                legs (when trace? (java.util.ArrayList.))
                add-leg! (fn [alon alat blon blat purpose dep arr mode-code]
                           (when (and trace? (moved? alon alat blon blat))
                             (let [variant (long (* route-variants (uniform seed i (+ 3001 (.size legs)))))
                                   leg (make-leg route alon alat blon blat purpose dep arr
                                                 mode-code default-mode census? variant)
                                   subs (:sub-legs leg)]
                               (vswap! leg-stats
                                       (fn [m]
                                         (cond-> (-> m
                                                     (update :legs (fnil inc 0))
                                                     (update (keyword (:mode leg)) (fnil inc 0)))
                                           (:diary-min leg) (update :diary-timed (fnil inc 0))
                                           (= :distance (:mode-from leg)) (update :distance-resolved (fnil inc 0))
                                           (= :census (:mode-from leg)) (update :census-resolved (fnil inc 0))
                                           (= :diary (:mode-from leg)) (update :diary-resolved (fnil inc 0))
                                           (:substituted leg) (update :mode-substituted (fnil inc 0))
                                           (seq subs) (update :access-walk (fnil + 0) (count subs))
                                           (:slow leg) (update :slow (fnil inc 0)))))
                               (.add legs (dissoc leg :sub-legs))
                               (doseq [sl subs] (.add legs sl)))))]
            (vswap! diary-number inc)
            (aset counts 0 (inc (aget counts 0)))
            (loop [e e0 anchor start-cell plon (double base-lon) plat (double base-lat)]
              (if-not (< e e1)
                nil
                (let [loc (aget ep-loc e) minute (aget ep-minute e)
                      dep (aget ep-depart e) arr (aget ep-arrive e)
                      h (mod (quot minute 60) 24) k (- e e0)]
                  (cond
                    (= loc 0)
                    (do (add-leg! plon plat base-lon base-lat "home" dep arr (aget ep-mode e))
                        (recur (inc e) (if home? (aget home-cell i) anchor) (double base-lon) (double base-lat)))

                    (and (= loc 1) (>= wj 0))
                    (do (aset visits (+ (* wj 24) h) (inc (aget visits (+ (* wj 24) h))))
                        (aset counts 1 (inc (aget counts 1)))
                        (add-leg! plon plat (aget flon wj) (aget flat wj) "work" dep arr (aget ep-mode e))
                        (recur (inc e) (aget work-cell wj) (aget flon wj) (aget flat wj)))

                    ;; an out-commuter's workplace is outside the city, so the
                    ;; modelled leg runs to the boundary on the side they leave
                    ;; by — the mirror of an in-commuter entering from theirs.
                    ;; Without this they hold no destination for a work episode
                    ;; and sit at home all day: 122,195 people at 0.597 mobile,
                    ;; which was the whole resident trip-generation gap.
                    (and (= loc 1) (= 1 (aget outside i)) (not (Double/isNaN (aget xlon i))))
                    (do (aset counts 1 (inc (aget counts 1)))
                        (add-leg! plon plat (aget xlon i) (aget xlat i) "work" dep arr (aget ep-mode e))
                        (recur (inc e) anchor (aget xlon i) (aget xlat i)))

                    (= loc 2)
                    (let [v (pick-from-cdf retail anchor (uniform seed i (inc k)))]
                      (if (>= v 0)
                        (do (aset visits (+ (* v 24) h) (inc (aget visits (+ (* v 24) h))))
                            (aset counts 2 (inc (aget counts 2)))
                            (add-leg! plon plat (aget flon v) (aget flat v) "store" dep arr (aget ep-mode e))
                            (recur (inc e) anchor (aget flon v) (aget flat v)))
                        (recur (inc e) anchor plon plat)))

                    (= loc 3)
                    (let [v (pick-from-cdf food anchor (uniform seed i (inc k)))]
                      (if (>= v 0)
                        (do (aset visits (+ (* v 24) h) (inc (aget visits (+ (* v 24) h))))
                            (aset counts 3 (inc (aget counts 3)))
                            (add-leg! plon plat (aget flon v) (aget flat v) "restaurant" dep arr (aget ep-mode e))
                            (recur (inc e) anchor (aget flon v) (aget flat v)))
                        (recur (inc e) anchor plon plat)))

                    ;; see step-day: no workplace and not in school → no destination
                    (and (= loc 1) (not= 1 (aget attsch i)))
                    (recur (inc e) anchor plon plat)

                    :else
                    (let [tbl (aget cls-table loc)]
                      (if (nil? tbl)
                        (recur (inc e) anchor plon plat)
                        (let [v (pick-from-cdf tbl anchor (uniform seed i (inc k)))]
                          (if (neg? v)
                            (do (aset counts no-venue-count (inc (aget counts no-venue-count)))
                                (recur (inc e) anchor plon plat))
                            (let [vlon (aget ^doubles (aget cls-lon loc) v)
                                  vlat (aget ^doubles (aget cls-lat loc) v)
                                  c (if (= loc 1) school-count loc)]
                              (aset counts c (inc (aget counts c)))
                              (add-leg! plon plat vlon vlat
                                        (if (= loc 1) "school" (purpose-of-loc loc))
                                        dep arr (aget ep-mode e))
                              (recur (inc e) anchor vlon vlat))))))))))
            (when (and trace? (pos? (.size legs)))
              (let [tr {:type (trace-type labour attsch i) :person i :legs (vec legs)}]
                (if trace-fn (trace-fn tr) (conj! traces tr))))))))
    {:visits visits
     :counts (zipmap count-names (seq counts))
     :leg-stats (let [m @leg-stats
                      d (double (max 1 (:diary-timed m 0)))]
                  (assoc m :slow-share (/ (Math/round (* 1000.0 (/ (double (:slow m 0)) d))) 1000.0)))
     :traces (persistent! traces)}))

(defn visits-total ^long [^ints visits ^long j] (loop [h 0 s 0] (if (= h 24) s (recur (inc h) (+ s (aget visits (+ (* j 24) h)))))))
