(ns city.econ.day
  "Money on the day: the inputs `city.sim.kernel/store-choices!` needs, derived
   so that a year of simulated days reproduces each person's class potential,
   and the day's visits and revenue from its choices (`money-from-choices`).

   The day kernel counts a store visit and adds a spend. What makes the spend
   honest is the denominator: a person of type `t` makes, in expectation,
   `E_t` store episodes per day — read off the diary tables, Σ_D P(D|t)·(store
   episodes in D) — and a share `π_s` of them are class `s`. So over a year
   they make `365 · E_t · π_s` class-`s` visits, and their class potential
   `m_i · κ_{d(i),s}` divided by that is the spend per visit that sums back to
   the potential in expectation. Nothing is fitted here; `κ` is the measured
   money split per district and class (`city.synth.segments/potential-shares`)
   and `π` is the one input with no local source yet.

   `π`, the class share of shopping *trips*, is `:assumed` until the mobility
   survey's purpose split is in hand: MiD separates everyday-needs shopping
   from other shopping, and the default below, 0.65 / 0.20 / 0.15, is a
   placeholder in that spirit, not a measurement. It is a parameter of every
   result that uses it and is recorded with them."
  (:require [city.synth.segments :as seg]))

(def default-pi
  "Class share of shopping trips, short / medium / long. ASSUMED — see the
   namespace doc. Cumulative form is what the kernel reads."
  [0.65 0.20 0.15])

(defn cumulative [pi] (double-array (reductions + pi)))

(defn store-episodes-per-day
  "double[n-types]: expected store episodes in a day for each person type,
   from the diary tables' weighted chains."
  [{:keys [n-types ^ints type-offsets ^doubles type-cdf ^ints diary-offsets ^ints ep-loc]}]
  (let [out (double-array n-types)]
    (dotimes [t n-types]
      (let [a (aget type-offsets t) b (aget type-offsets (inc t))]
        (loop [d a prev 0.0 acc 0.0]
          (if (= d b) (aset out t acc)
              (let [cur (aget type-cdf d) p (- cur prev)
                    stores (loop [e (aget diary-offsets d) c 0]
                             (if (= e (aget diary-offsets (inc d))) c
                                 (recur (inc e) (if (= 2 (aget ep-loc e)) (inc c) c))))]
                (recur (inc d) cur (+ acc (* p stores))))))))
    out))

(defn household-ids
  "int[n]: a global household id per person. The synthesis numbers households
   within each census cell (`:da`), so `:hh` alone is a per-cell index —
   36,889 Stuttgart residents share the value 0 — and the id is the pair
   (cell, index). In-commuters have no cell and each get their own id."
  [{:keys [n ^objects da ^ints hh ^ints external]}]
  (let [ids (java.util.HashMap.) out (int-array n)]
    (dotimes [i n]
      (let [k (if (and external (= 1 (aget external i))) [:external i] [(aget da i) (aget hh i)])
            id (or (.get ids k) (let [v (.size ids)] (.put ids k v) v))]
        (aset out i (int id))))
    out))

(defn spend-per-visit
  "int[3·n] cents: person i's spend per class-s visit, class-major.

   Money is a household quantity. A person whose type never shops in any
   diary — a child, or an age/activity cell with no store episode in its pool
   — still has purchasing power, and in reality it is spent by whoever in the
   household does the shopping. So the potential is pooled per household
   (`hh` int[n], a household id per person) and divided by the household's
   expected class-s visits per year, Σ_members 365 · E_t · π_s, and every
   shopping member carries that spend. Per person this recovered 83 % of the
   city's resident potential on the first run; the other 17 % was money of
   people who never shop, which the household treatment returns to the day.
   A household with no shopping member at all still leaks, and that number is
   reported by the caller.

   `potential` double[n] annual retail potential in euros; `shares-of` maps
   person index → {:short κ :medium κ :long κ} for their district; `ptype`
   int[n]; `per-day` from `store-episodes-per-day`; `pi` the trip shares."
  [n ^doubles potential shares-of ^ints ptype ^ints hh ^doubles per-day pi]
  (let [hh-pot (java.util.HashMap.) hh-visits (java.util.HashMap.)]
    ;; pool per household: money, and expected store episodes per day
    (dotimes [i n]
      (let [h (aget hh i) m (aget potential i) t (aget ptype i)
            e (if (>= t 0) (aget per-day t) 0.0)]
        (when (or (pos? m) (pos? e))
          (.put hh-pot h (+ (double (or (.get hh-pot h) 0.0)) m))
          (.put hh-visits h (+ (double (or (.get hh-visits h) 0.0)) e)))))
    (let [out (int-array (* 3 n))]
      (dotimes [i n]
        (let [t (aget ptype i) h (aget hh i)]
          (when (and (>= t 0) (pos? (aget per-day t)))
            (let [m (double (or (.get hh-pot h) 0.0)) e (double (or (.get hh-visits h) 0.0)) k (shares-of i)]
              (when (and k (pos? m) (pos? e))
                (dotimes [s 3]
                  (let [share (double (get k (nth seg/segments s) 0.0))
                        visits-per-year (* 365.0 e (double (nth pi s)))]
                    (when (and (pos? share) (pos? visits-per-year))
                      (aset out (+ (* s n) i) (int (Math/round (/ (* 100.0 m share) visits-per-year))))))))))))
      out)))

(defn unspent-potential
  "Euros of potential in households with no shopping member: the money the
   day cannot place. Reported, not hidden."
  [n ^doubles potential ^ints ptype ^ints hh ^doubles per-day]
  (let [shoppers (java.util.HashSet.)]
    (dotimes [i n] (let [t (aget ptype i)] (when (and (>= t 0) (pos? (aget per-day t))) (.add shoppers (aget hh i)))))
    (reduce + 0.0 (for [i (range n) :when (not (.contains shoppers (aget hh i)))] (aget potential i)))))

(defn class-balances
  "{class {:inflow-eur x :leak-share y}} from the published class turnover and
   resident potential: a class that sells more than its residents can spend
   has a net inflow, one that sells less has residents buying elsewhere. The
   attribution — all inflow to in-commuters, all leakage to residents — is the
   stated assumption; the sizes are measured (EZK 2024 class rollups)."
  [seg-targets]
  (into {} (for [s seg/segments
                 :let [u (reduce + (keep #(get-in % [s :umsatz-eur]) (vals seg-targets)))
                       k (reduce + (keep #(get-in % [s :kaufkraft-eur]) (vals seg-targets)))]]
             [s {:inflow-eur (max 0.0 (- u k)) :leak-share (if (pos? k) (max 0.0 (/ (- k u) k)) 0.0)}])))

(defn shares-array
  "The `shares` the kernel reads: cumulative trip shares, then leakage per class."
  [pi balances]
  (double-array (concat (reductions + pi) (map #(:leak-share (get balances %)) seg/segments))))

(defn add-external-spend!
  "Give in-commuters their spend per visit in place: each class's measured
   inflow divided by the in-commuters' expected class visits per year, so
   summed over a year they bring in exactly the inflow. `spend3` int[3·n]."
  [^ints spend3 n ^ints ptype ^ints external ^doubles per-day pi balances]
  (let [ext-visits (double-array 3)]
    (dotimes [i n]
      (when (and (= 1 (aget external i)) (>= (aget ptype i) 0))
        (dotimes [s 3] (aset ext-visits s (+ (aget ext-visits s) (* 365.0 (aget per-day (aget ptype i)) (double (nth pi s))))))))
    (dotimes [i n]
      (when (and (= 1 (aget external i)) (>= (aget ptype i) 0) (pos? (aget per-day (aget ptype i))))
        (dotimes [s 3]
          (let [inflow (:inflow-eur (get balances (nth seg/segments s)))]
            (when (and (pos? inflow) (pos? (aget ext-visits s)))
              (aset spend3 (+ (* s n) i) (int (Math/round (/ (* 100.0 inflow) (aget ext-visits s))))))))))
    {:external-spend-per-visit-eur (into {} (for [s (range 3)] [(nth seg/segments s)
                                                                 (let [inflow (:inflow-eur (get balances (nth seg/segments s)))]
                                                                   (if (pos? (aget ext-visits s)) (/ inflow (aget ext-visits s)) 0.0))]))
     :external-visits-per-year (vec ext-visits)}))

(defn max-store-episodes
  "The most store episodes any diary holds: the width of a person's row in
   `city.sim.kernel/store-choices!`'s choice array."
  ^long [{:keys [^ints diary-offsets ^ints ep-loc]}]
  (let [nd (dec (alength diary-offsets))]
    (loop [d 0 mx 0]
      (if (= d nd) mx
          (recur (inc d) (max mx (loop [e (aget diary-offsets d) c 0]
                                   (if (= e (aget diary-offsets (inc d))) c
                                       (recur (inc e) (if (= 2 (aget ep-loc e)) (inc c) c))))))))))

(defn store-ranks
  "int[episodes]: each store episode's place among its diary's store episodes,
   0, 1, …; −1 for any other episode. `store-choices!` indexes its choices by
   it, as the day functions do by counting."
  ^ints [{:keys [^ints diary-offsets ^ints ep-loc]}]
  (let [out (int-array (alength ep-loc) -1) nd (dec (alength diary-offsets))]
    (dotimes [d nd]
      (loop [e (aget diary-offsets d) r 0]
        (when (< e (aget diary-offsets (inc d)))
          (if (= 2 (aget ep-loc e))
            (do (aset out e r) (recur (inc e) (inc r)))
            (recur (inc e) r)))))
    out))

(defn money-from-choices
  "The economic day from `store-choices!`' decisions: `{:revenue3 :visits3
   :counts}`, candidate-indexed with the classes stacked,
   `[(class·nc + candidate)·24 + hour]`, revenue in cents, the hour that of the
   episode's minute. `counts` = [diaries store-visits class-short class-medium
   class-long leaked-short leaked-medium leaked-long]; an episode whose anchor
   reaches no venue counts nowhere."
  [{:keys [^ints diary ^ints choice max-s]} {:keys [^ints diary-offsets ^ints ep-loc ^ints ep-minute]}
   ^ints spend3 n nc]
  (let [n (long n) nc (long nc) max-s (long max-s)
        rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)]
    (dotimes [i n]
      (let [d (aget diary i)]
        (when (>= d 0)
          (aset cnt 0 (inc (aget cnt 0)))
          (loop [e (aget diary-offsets d) r 0]
            (when (< e (aget diary-offsets (inc d)))
              (if (= 2 (aget ep-loc e))
                (let [code (aget choice (+ (* i max-s) r))]
                  (cond
                    (>= code 0)
                    (let [q (quot code 3) s (rem code 3)
                          cell (+ (* (+ (* s nc) q) 24) (mod (quot (aget ep-minute e) 60) 24))]
                      (aset vis cell (inc (aget vis cell)))
                      (aset rev cell (+ (aget rev cell) (aget spend3 (+ (* s n) i))))
                      (aset cnt 1 (inc (aget cnt 1)))
                      (aset cnt (+ 2 s) (inc (aget cnt (+ 2 s)))))
                    (>= code -3)
                    (aset cnt (+ 5 (- -1 code)) (inc (aget cnt (+ 5 (- -1 code))))))
                  (recur (inc e) (inc r)))
                (recur (inc e) r)))))))
    {:revenue3 rev :visits3 vis :counts (vec cnt)}))
