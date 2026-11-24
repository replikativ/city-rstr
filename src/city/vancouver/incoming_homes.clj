(ns city.vancouver.incoming-homes
  "Reassign incoming commuter home locations to the Census transit margin."
  (:require [clojure.data.json :as json]))

(def distance-bounds [1000 3000 5000 7000 10000 15000 20000 25000 30000 35000])
(def ^:private distance-squares (mapv #(* % %) distance-bounds))
(def ^:private prior-weight 40)

(defn- distance-squared [[x y] [u v]]
  (+ (* (- x u) (- x u)) (* (- y v) (- y v))))

(defn distance-band [a b]
  (let [squared (distance-squared a b)]
    (count (take-while #(<= % squared) distance-squares))))

(defn- count-at-home [rows size]
  (reduce (fn [stock [home]] (update stock home inc)) (vec (repeat size 0)) rows))

(defn transit-targets [stock transit margins]
  (let [observations (keep identity margins)
        total (reduce + transit)
        size (reduce + stock)]
    (if (or (empty? observations) (zero? total) (= total size))
      transit
      (let [mean (/ (double (transduce (map second) + observations)) (transduce (map first) + observations))
            prior (max 0.00001 (min 0.99999 mean))
            logits (mapv (fn [[n m]]
                           (let [share (/ (+ (or m 0) (* prior-weight prior)) (+ (or n 0) prior-weight))]
                             (Math/log (/ share (- 1.0 share))))) margins)
            mass (fn [shift] (mapv (fn [n odds] (/ n (+ 1.0 (Math/exp (- (+ odds shift)))))) stock logits))
            fitted (loop [lo -40.0 hi 40.0 step 0]
                     (let [mid (/ (+ lo hi) 2.0) cells (mass mid)]
                       (cond (= step 48) cells
                             (< (reduce + cells) total) (recur mid hi (inc step))
                             :else (recur lo mid (inc step)))))
            rounded (mapv #(long (Math/floor %)) fitted)
            residual (- total (reduce + rounded))
            rank (sort-by (fn [i] [(- (rounded i) (fitted i)) i])
                          (filter #(< (rounded %) (stock %)) (range (count stock))))]
        (when-not (<= 0 residual (count rank))
          (throw (ex-info "Commute margin rounding failed" {:stock size :transit total :unassigned residual})))
        (reduce #(update %1 %2 inc) rounded (take residual rank))))))

(defn- stratum [person]
  [(person 2) (person 3) (person 8)])

(defn fit-group [{:keys [people points margins]} jobs transit-mode]
  (let [n (count points)
        ids (range (count people))
        riders (filterv #(= transit-mode ((people %) 4)) ids)
        stock (count-at-home people n)
        baseline (count-at-home (map people riders) n)
        target (transit-targets stock baseline margins)
        counts (int-array baseline)
        moved? (boolean-array (count people))
        job-points (mapv #(jobs (% 1)) people)
        bands (mapv (fn [i] (distance-band (points ((people i) 0)) (job-points i))) ids)
        other (reduce (fn [m i]
                        (let [row (people i)]
                          (if (= transit-mode (row 4)) m
                            (update m [(row 0) (stratum row)] (fnil conj []) i)))) {} ids)
        under (filterv #(< (baseline %) (target %)) (range n))
        nearby (memoize (fn [home]
                          (sort-by (fn [to] [(distance-squared (points home) (points to)) to]) under)))
        ordered (sort-by (fn [i] (let [home ((people i) 0)] [(- (target home) (baseline home)) i])) riders)
        changes (reduce
                 (fn [out i]
                   (let [from ((people i) 0)]
                     (if (<= (aget counts from) (target from)) out
                       (if-let [[to other-id]
                                (some (fn [to]
                                        (when (and (< (aget counts to) (target to))
                                                   (= (bands i) (distance-band (points to) (job-points i))))
                                          (when-let [j (some (fn [j]
                                                              (when (and (not (aget moved? j))
                                                                         (= (bands j) (distance-band (points from) (job-points j)))) j))
                                                            (get other [to (stratum (people i))]))]
                                            [to j])))
                                      (nearby from))]
                         (do (aset-boolean moved? other-id true)
                             (aset-int counts from (dec (aget counts from)))
                             (aset-int counts to (inc (aget counts to)))
                             (conj out [i from to] [other-id to from]))
                         out)))) [] ordered)
        fitted (vec counts)
        error (fn [actual] (reduce + (map #(abs (- %1 %2)) actual target)))]
    {:changes (vec (sort-by first changes)) :moved (count changes) :population (count people)
     :transit (count riders) :supportedWorkers (reduce + (map #(if %1 %2 0) margins stock))
     :errorBefore (error baseline) :errorAfter (error fitted)
     :areas (mapv vector stock margins target baseline fitted)}))

(defn -main [input output]
  (let [{:keys [groups jobs mode]} (json/read-str (slurp input) :key-fn keyword)
        results (into (sorted-map) (map (fn [[group cohort]] [group (fit-group cohort jobs mode)])) groups)]
    (spit output (json/write-str {:groups results :distanceLowerMeters (into [0] distance-bounds)
                                 :publishedCountPrior prior-weight}))))
