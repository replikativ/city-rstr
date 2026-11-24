(ns city.vancouver.worksites
  "Compare fixed-capacity assignments of municipal workplaces for walking commuters."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- read-file [dir file]
  (with-open [r (io/reader (io/file dir file))] (json/read r)))

(defn- write-file [file data]
  (with-open [w (io/writer file)] (json/write data w)))

(defn commute-pattern
  "All direct walking-mode candidate legs. Exchanging a site is allowed only if every
   arrival and departure at that job is accounted for and there is a single job slot."
  [{:strs [parts slots]} starts]
  (let [direct (set starts)
        legs (for [[start dur _ a b] parts :when (direct start)]
               (if (= "job" (slots a)) [b a dur start] [a b dur start]))
        jobs (set (map second legs))
        job (first jobs)
        ;; Adjacent stops can imply an unobserved journey at their shared boundary.
        touches? #(some #{job} (drop 3 %))
        complete? (and (= 1 (count jobs))
                       (= 1 (count (filter #{"job"} slots)))
                       (every? (fn [[s _ mode :as p]]
                                 (or (not (touches? p)) (= mode "stop") (direct s))) parts)
                       (every? (fn [[a b]]
                                 (or (not= "stop" (nth a 2) (nth b 2))
                                     (= (nth a 3) (nth b 3))
                                     (not (or (touches? a) (touches? b)))))
                               (partition 2 1 (conj parts (first parts)))))]
    {:legs (vec legs) :exchange (boolean complete?) :jobSlot job}))

(defn- extract [atlas-dir day-dir outbound-dir out]
  (let [day (read-file day-dir "day.json") atlas (read-file atlas-dir "atlas.json")
        report (read-file outbound-dir "report.json") fit (report "neighbourhoodFit")
        places (read-file day-dir "places.json") walking (.indexOf (report "modes") "Walking")
        areas (zipmap (day "areas") (range)) home-area (into {} (for [[area data] (atlas "areas") da (data "das")] [da (areas area)]))
        patterns (mapv commute-pattern (day "templates") (report "directStarts"))
        rows (mapv (fn [d da modes jobs]
                     (let [people (get (read-file atlas-dir (str da ".json")) "people")
                           plans (get (read-file day-dir (str da ".json")) "plans")
                           outside (into #{} (map first jobs))]
                       (vec (for [[i m] modes :when (and (= walking m) (not (outside i)))
                                  :let [person (people i) {:keys [legs exchange jobSlot]} (patterns (peek person))
                                        plan (plans i)
                                        known (vec (for [[h j dur s] legs :let [home (plan h) job (plan j)]
                                                         :when (and (<= 0 home) (<= 0 job))]
                                                     [home job dur s]))]
                                  :when (seq known)]
                              {:d d :i i :homeArea (home-area da) :occupation (nth person 5) :slot jobSlot
                               :eligible (and exchange (= (count known) (count legs))
                                              (= 1 (count (set (map first known))))
                                              (<= 1 (nth person 5) 10))
                               :legs known}))))
                   (range) (day "das") (read-file outbound-dir "local-modes.json") (read-file outbound-dir "assignments.json"))]
    (write-file out {:workers (vec (mapcat identity rows)) :areas (day "areas")
                     :workplaces (vec (keep-indexed (fn [i [_ _ area label]]
                                                       (when (and (= "Workplace" label) (<= 0 area)) [i area])) places))
                     :speed (get-in fit ["activeSpeeds" "Walking"]) :streets (fit "streets")
                     :day (report "day") :atlas (report "atlas") :outbound (.getName (io/file outbound-dir))})))

(defn- load-model [roster-file routes-file]
  (let [read-path (fn [path] (with-open [r (io/reader path)] (json/read r :key-fn keyword)))
        {:keys [workers workplaces] :as roster} (read-path roster-file)
        {:keys [distances nearest city]} (read-path routes-file)
        areas (into {} workplaces)
        job-of #(get-in % [:legs 0 1])
        groups (->> workers (filter :eligible)
                    (group-by #(vector (areas (job-of %)) (:occupation %))) (into (sorted-map)) vals)]
    (assoc roster :groups groups :site-area areas :city-nearest (into {} city)
           :metres (into {} (map (fn [[h j m]] [[h j] m]) distances))
           :nearest (into {} (map (fn [[h a m]] [[h a] m]) nearest)))))

(defn- too-far? [metres speed duration]
  (or (nil? metres) (> metres (* speed duration))))

(defn- misses [{:keys [metres speed]} worker site]
  (let [length (metres [(get-in worker [:legs 0 0]) site])]
    (count (filter #(too-far? length speed (nth % 2)) (:legs worker)))))

(defn cost-matrix
  "Each column is a distinct site. Numerical matching expands its existing worker slots.
   A whole leg takes priority over every possible address change in this cohort."
  [model workers]
  (let [current (mapv #(get-in % [:legs 0 1]) workers)
        sites (vec (sort (distinct current))) index (zipmap sites (range)) weight (inc (count workers))]
    {:siteSlots (mapv index current)
     :costs (mapv (fn [worker original]
                    (let [before (misses model worker original)]
                      (mapv (fn [site]
                              (let [after (misses model worker site)]
                                (when (<= after before)
                                  (+ (* weight after) (if (= original site) 0 1))))) sites)))
                  workers current)}))

(defn- apply-permutation [model workers permutation]
  (when-not (= (sort permutation) (range (count workers)))
    (throw (ex-info "Assignment did not preserve the workplace slots" {})))
  (into {} (for [[worker j] (map vector workers permutation)
                 :let [original (get-in worker [:legs 0 1]) site (get-in workers [j :legs 0 1])]
                 :when (not= site original)]
             (do (when (> (misses model worker site) (misses model worker original))
                   (throw (ex-info "A worker lost a feasible trip" {:worker (select-keys worker [:d :i])})))
                 [[(:d worker) (:i worker)] site]))))

(defn- evaluate [{:keys [workers areas site-area speed metres nearest city-nearest groups] :as model} permutations]
  (when-not (= (count permutations) (count groups))
    (throw (ex-info "Mismatched occupation and destination groups" {})))
  (let [moves (into {} (mapcat #(apply-permutation model %1 %2) groups permutations))
        zero-counts {:legs 0 :failed 0 :nearestFailed 0 :cityFailed 0 :matchedFailed 0 :eligibleLegs 0 :eligibleFailed 0 :workers 0 :eligibleWorkers 0 :moved 0}
        changes (vec (for [{:keys [d i slot legs]} workers :let [site (moves [d i])] :when site]
                       [d i slot (second (first legs)) site]))
        examples (object-array (count areas))
        summary
        (reduce (fn [stats {:keys [d i legs homeArea eligible]}]
                  (let [site (moves [d i])
                        counts (cond-> (update (stats homeArea) :workers inc)
                                 site (update :moved inc) eligible (update :eligibleWorkers inc))]
                    (assoc stats homeArea
                           (reduce (fn [counts [h j dur start]]
                                     (let [before (too-far? (metres [h j]) speed dur)
                                           after (too-far? (metres [h (or site j)]) speed dur)
                                           even-nearest (too-far? (nearest [h (site-area j)]) speed dur)
                                           even-city (too-far? (city-nearest h) speed dur)]
                                       (when (or (and after (not before)) (and even-nearest (not after)) (and even-city (not even-nearest)))
                                         (throw (ex-info "Inconsistent route or same-area lower bound" {:d d :i i})))
                                       (when (and before (not after) (nil? (aget examples homeArea)))
                                         (aset examples homeArea [d i (+ start (quot dur 2))]))
                                       (cond-> (update counts :legs inc)
                                         eligible (update :eligibleLegs inc)
                                         (and eligible before) (update :eligibleFailed inc)
                                         before (update :failed inc) after (update :matchedFailed inc)
                                         even-city (update :cityFailed inc) even-nearest (update :nearestFailed inc)))) counts legs))))
                (vec (repeat (count areas) zero-counts)) workers)]
    (merge (select-keys model [:outbound :atlas :day :streets :speed :areas])
           {:changes changes :summary summary :examples (vec examples) :sites (count site-area)
            :total (apply merge-with + summary)})))

(defn -main [phase & args]
  (if (= "extract" phase)
    (apply extract args)
    (let [[roster routes file output] args model (load-model roster routes)]
      (case phase
        "costs" (write-file file (mapv #(cost-matrix model %) (:groups model)))
        "match" (write-file output (evaluate model (with-open [r (io/reader file)] (json/read r))))))))
