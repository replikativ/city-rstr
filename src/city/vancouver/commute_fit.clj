(ns city.vancouver.commute-fit
  "Local calibration of usual travel mode for the full known-mode commuter population."
  (:require [city.synth.sampling :refer [shuffled]])
  (:import [java.util Random]))

(defn apportion [weights n]
  (let [total (double (reduce + weights))]
    (when (and (pos? n) (zero? total))
      (throw (ex-info "No observed modes for a populated neighbourhood" {:commuters n})))
    (if (zero? n) (mapv (constantly 0) weights)
        (let [x (mapv #(* n (/ % total)) weights)
              whole (mapv #(long (Math/floor %)) x)]
          (reduce #(update %1 %2 inc) whole
                  (take (- n (reduce + whole)) (sort-by #(- (whole %) (x %)) (range (count x)))))))))

(defn- rake [seed sizes targets]
  (let [columns #(apply mapv + %)
        rescale (fn [row n] (let [s (reduce + row)] (mapv #(* n (/ % s)) row)))]
    (loop [rows (mapv #(mapv (fn [n] (+ 0.5 n)) %) seed) iteration 0]
      (let [normal (mapv rescale rows sizes)
            factors (mapv #(if (zero? %1) 0.0 (/ %1 %2)) targets (columns normal))
            fitted (mapv #(mapv * % factors) normal)
            err (apply max (map #(abs (- %1 (reduce + %2))) sizes fitted))]
        (cond (< err 1.0e-7) fitted
              (> iteration 2000) (throw (ex-info "Local mode fit failed to converge" {:error err}))
              :else (recur fitted (inc iteration)))))))

(defn fit-counts
  "Keep demographic row totals while matching the neighbourhood's six integer mode targets."
  [seed targets]
  (let [sizes (mapv #(reduce + %) seed)
        _ (when-not (= (reduce + sizes) (reduce + targets))
            (throw (ex-info "Work-mode margins differ" {:sizes sizes :targets targets})))
        expected (rake seed sizes targets)
        rounded (mapv apportion expected sizes)]
    (loop [cells rounded miss (mapv - targets (apply mapv + rounded))]
      (if (every? zero? miss) cells
          (let [moves (for [from (range (count miss)) :when (neg? (miss from))
                            to (range (count miss)) :when (pos? (miss to))
                            r (range (count cells)) :when (pos? (get-in cells [r from]))]
                        ;; Change in squared rounding error up to a common scale and offset.
                        [(+ (- (get-in cells [r to]) (get-in expected [r to]))
                            (- (get-in expected [r from]) (get-in cells [r from]))) r from to])
                [_ r from to] (reduce #(if (neg? (compare %2 %1)) %2 %1) moves)]
            (recur (-> cells (update-in [r from] dec) (update-in [r to] inc))
                   (-> miss (update from inc) (update to dec))))))))

(defn fit-area
  "People are [DA index, roster index, original mode, demographic stratum]. Mode codes index labels."
  [people reference ^Random rng]
  (let [k (count reference)
        groups (vals (into (sorted-map) (group-by peek people)))
        seed (mapv (fn [members] (let [counts (frequencies (map #(nth % 2) members))]
                                   (mapv #(get counts % 0) (range k)))) groups)
        target (apportion reference (count people))
        fitted (if (seq seed) (fit-counts seed target) [])
        assigned
        (mapcat (fn [members quotas]
                  (let [by-mode (group-by #(nth % 2) members)
                        buckets (mapv #(shuffled rng (by-mode %)) (range k))
                        keepers (mapcat take quotas buckets)
                        excess (mapcat drop quotas buckets)
                        missing (mapcat (fn [j] (repeat (max 0 (- (quotas j) (count (buckets j)))) j)) (range k))]
                    (concat (map #(subvec % 0 3) keepers)
                            (map (fn [[d i] m] [d i m]) excess (shuffled rng missing)))))
                groups fitted)]
    {:before (if (seq seed) (apply mapv + seed) (vec (repeat k 0)))
     :target target :people (vec assigned)}))

(defn- swap-capacity [external totals from to]
  (mapv (fn [outside all] (min (outside from) (- (all to) (outside to)))) external totals))

(defn- transfer-path [external totals residual]
  ;; Follow an augmenting path when two sparse categories cannot exchange slots directly.
  (let [k (count residual)
        starts (sort-by residual (filter #(neg? (residual %)) (range k)))]
    (loop [paths (mapv vector starts) visited (set starts)]
      (when (seq paths)
        (or (some #(when (pos? (residual (peek %))) %) paths)
            (let [next-paths
                  (for [path paths m (range k)
                        :when (and (not (visited m))
                                   (some pos? (swap-capacity external totals (peek path) m)))]
                    (conj path m))]
              (recur (vec next-paths) (into visited (map peek) next-paths))))))))

(defn external-targets
  "Reallocate mode slots between external and other workers within each neighbourhood.
   Both its mode totals and its external headcount stay fixed."
  [outside totals goal]
  (when-not (and (= (reduce + goal) (reduce + (mapcat identity outside)))
                 (every? true? (map <= (mapcat identity outside) (mapcat identity totals))))
    (throw (ex-info "Inconsistent commuter capacities" {})))
  (loop [cells outside]
    (let [residual (mapv - goal (apply mapv + cells))]
      (if (every? zero? residual) cells
          (let [path (or (transfer-path cells totals residual)
                         (throw (ex-info "Infeasible external mode margin" {:residual residual})))
                steps (partition 2 1 path)
                transfer (apply min (- (residual (first path))) (residual (peek path))
                                (map (fn [[from to]] (reduce + (swap-capacity cells totals from to))) steps))]
            (recur (reduce (fn [matrix [from to]]
                             (let [amounts (apportion (swap-capacity matrix totals from to) transfer)]
                               (mapv (fn [row n] (-> row (update from - n) (update to + n))) matrix amounts)))
                           cells steps)))))))

(defn broad-modes [[driver passenger transit walk bike other]]
  [driver passenger transit (+ walk bike) other])

(defn split-active
  "Retain the local-only walk/bike composition when reducing external active trips.
   Added trips follow the remaining neighbourhood walk/bike capacity."
  [[driver passenger transit active other] original totals]
  (let [seed (subvec original 3 5) capacity (subvec totals 3 5)
        increase (- active (reduce + seed))
        [walk bike] (if (pos? increase) (mapv + seed (apportion (mapv - capacity seed) increase))
                        (apportion seed active))]
    [driver passenger transit walk bike other]))

(def ^:private exchange-cycles [[0 1] [0 2] [1 2] [0 1 2] [0 2 1]])

(defn- best-exchange [cells costs]
  ;; An improving circulation on three mode classes contains a negative 2- or 3-cycle.
  (let [edges
        (reduce-kv (fn [edges p counts]
                     (reduce (fn [edges [from to]]
                               (let [gain (- (get-in costs [p from]) (get-in costs [p to]))
                                     prev (get edges [from to])]
                                 (if (or (nil? prev) (> gain (first prev)))
                                   (assoc edges [from to] [gain p from to (counts from)]) edges)))
                             edges (for [from (range 3) :when (pos? (counts from))
                                         to (range 3) :when (not= from to)] [from to])))
                   {} cells)]
    (first (sort-by (comp - first)
                    (for [cycle exchange-cycles
                          :let [moves (mapv edges (partition 2 1 (conj cycle (first cycle))))]
                          :when (every? some? moves)
                          :let [gain (reduce + (map first moves))]
                          :when (pos? gain)]
                      [gain moves])))))

(defn assign-travel-budgets
  "Within one fixed cohort, exchange fitted mode slots to minimize failed active legs,
   then the number of residents changing mode. Rows are [resident mode walk-misses bike-misses].
   Returns only the changed identities and their new modes."
  [rows walk bike ^Random rng]
  (let [class-of #(cond (= % walk) 1 (= % bike) 2 :else 0)
        grouped (into (sorted-map) (group-by (fn [[_ m w b]] [(class-of m) w b]) rows))
        profiles (vec (keys grouped))
        costs (mapv (fn [[start w b]]
                      (mapv (fn [c misses] (+ (* (inc (count rows)) misses) (if (= c start) 0 1)))
                            (range 3) [0 w b])) profiles)
        initial (mapv (fn [[c :as profile]] (assoc [0 0 0] c (count (grouped profile)))) profiles)
        final (loop [cells initial]
                (if-let [[_ moves] (best-exchange cells costs)]
                  (let [n (reduce min (map peek moves))]
                    (recur (reduce (fn [out [_ p from to _]]
                                     (-> out (update-in [p from] - n) (update-in [p to] + n))) cells moves)))
                  cells))
        moves (mapcat (fn [[start :as profile] counts]
                        (let [destinations (mapcat #(repeat (counts %) %) (remove #{start} (range 3)))]
                          (when (seq destinations)
                            (map vector (shuffled rng (grouped profile)) destinations)))) profiles final)
        neutral (shuffled rng (for [[[_ m] _] moves :when (zero? (class-of m))] m))
        entering (for [[[id] c] moves :when (zero? c)] id)]
    (into (zipmap entering neutral)
          (for [[[id] c] moves :when (pos? c)] [id (if (= c 1) walk bike)]))))
