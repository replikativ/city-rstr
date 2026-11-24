(ns city.vancouver.tract-workplaces
  "Paired weekday with census tract workplace opportunities, on the original resident roster."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]
            [city.vancouver.outbound :as outbound]))

(defn- read-json [dir file]
  (with-open [r (io/reader (io/file dir file))] (json/read r)))

(defn- write-json [file data]
  (with-open [w (io/writer file)] (json/write data w)))

(defn trip-constraints
  "The non-workplace endpoint and duration of every journey touching paid work.
   Consecutive stops at a workplace boundary have no measured time for relocation."
  [template paid direct]
  (let [parts (template "parts")
        boundary? (fn [[_ _ m a b]] (and (not= m "stop") (not= (contains? paid a) (contains? paid b))))
        timed (vec (for [[s dur mode a b :as leg] parts :when (boundary? leg)]
                     [(if (paid a) b a) dur mode (contains? direct s) s (contains? paid a)]))]
    {:untimed (some (fn [[[_ _ m a] [_ _ next-mode b]]]
                      (and (= m "stop" next-mode) (not= (contains? paid a) (contains? paid b))))
                    (partition 2 1 (conj parts (first parts))))
     :trips (mapv #(subvec % 0 4) timed)
     :timed-trips timed}))

(defn- extract [atlas-dir day-dir out-dir matched-dir target & [mode-policy]]
  (let [atlas (read-json atlas-dir "atlas.json") day (read-json day-dir "day.json")
        preserve? (= mode-policy "diary")
        report (read-json out-dir "report.json") matched (read-json matched-dir "worksites.json")
        external (read-json out-dir "assignments.json") modes (read-json out-dir "local-modes.json")
        changes (into {} (map (fn [[d i _ _ site]] [[d i] site]) (matched "changes")))
        paid (mapv vec (report "slots")) templates (day "templates")
        constraints (mapv #(trip-constraints %1 (set %2) (set %3)) templates paid (report "directStarts"))
        mode-keys (report "modeKeys")
        eligible-sites (into #{} (keep-indexed (fn [i [_ _ a label]] (when (and (<= 0 a) (= "Workplace" label)) i))
                                                (read-json day-dir "places.json")))]
    (when-not (and (= (report "day") (matched "day") (.getName (io/file day-dir)))
                   (= (report "atlas") (matched "atlas") (.getName (io/file atlas-dir)))
                   (= (matched "outbound") (.getName (io/file out-dir))))
      (throw (ex-info "Workplace scenario inputs refer to different releases" {})))
    (write-json target
      (vec (mapcat
        (fn [d da]
          (let [file (str da ".json") {:strs [home plans]} (read-json day-dir file)
                people (get (read-json atlas-dir file) "people")
                outside (into #{} (map first) (external d)) fitted (into {} (modes d))]
            (for [i (range (get-in atlas ["das" da "private"])) :when (not (outside i))
                  :let [t (peek (people i)) slots (paid t) plan (plans i)]
                  :when (seq slots)
                  :let [original (plan (first slots)) site (if preserve? original (get changes [d i] original))]
                  :when (and (eligible-sites site) (every? #(= original (plan %)) slots))]
              (let [mode (get mode-keys (get fitted i))
                    {:keys [untimed timed-trips]} (constraints t)
                    legs (mapv (fn [[slot dur recorded direct? _ from-job?]]
                                 (if preserve?
                                   [(get plan slot -1) dur recorded from-job?]
                                   [(get plan slot -1) dur (if (and direct? mode) mode recorded)])) timed-trips)
                    protect (or untimed
                                (some #(or (neg? (first %)) (and (not preserve?) (#{"walk" "bike"} (nth % 2)))) legs)
                                (< (count slots) (count (filter #{"job"} (get-in templates [t "slots"])))))]
                [d i (home i) site (boolean protect) legs]))))
        (range) (day "das"))))))

(defn- increment! [^ints values i n] (aset-int values i (+ n (aget values i))))

(defn- move-stop! [intervals n start dur old-area new-area]
  (doseq [[area sign] [[old-area -1] [new-area 1]]]
    (increment! intervals (+ area (* n (- start 240))) sign)
    (increment! intervals (+ area (* n (- (+ start dur) 240))) (- sign))))

(defn- move-trip! [flows zones core n k area m start dur a b before after]
  (doseq [[plan sign] [[before -1] [after 1]]
          :let [direction (outbound/crossing (get zones (get plan a) -1) (get zones (get plan b) -1) core)]
          :when (some? direction)]
    (let [h (mod (quot (if (zero? direction) (+ start dur) start) 60) 24)]
      (outbound/add-flow! flows n k area [h direction m sign]))))

(defn- evaluate [atlas-dir day-dir out-dir matched-dir moves-file output]
  (let [day (read-json day-dir "day.json") atlas (read-json atlas-dir "atlas.json")
        report (read-json out-dir "report.json") matched (read-json matched-dir "worksites.json")
        places (read-json day-dir "places.json") areas (day "areas") n (count areas)
        zones (mapv #(nth % 2) places) core (.indexOf areas "Downtown")
        paid (mapv set (report "slots")) templates (day "templates")
        mode-index (zipmap (report "modeKeys") (range)) k (count mode-index)
        local (read-json out-dir "local-modes.json")
        matches (group-by first (matched "changes"))
        solution (with-open [r (io/reader moves-file)] (json/read r))
        preserve? (true? (solution "preserveDiaryModes"))
        moves (group-by first (solution "moves"))
        flows (int-array (* 24 n 2 k)) intervals (int-array (* 1441 n))
        examples (object-array 9) geo (solution "siteZones")
        fitted-delta (get-in report ["neighbourhoodFit" "delta"])
        results (java.util.ArrayList.)
        starts-by-template (mapv set (report "directStarts"))
        home-areas (into {} (for [[a group] (atlas "areas") da (group "das")] [da (.indexOf areas a)]))]
    (doseq [[d da] (map-indexed vector (day "das")) :when (or (moves d) (and (not preserve?) (matches d)))]
      (let [file (str da ".json") plans (get (read-json day-dir file) "plans")
            people (get (read-json atlas-dir file) "people") modes (into {} (local d))
            old-match (if preserve? {} (into {} (for [[_ i s _ to] (matches d)] [i [s to]])))
            by-person (into {} (for [[_ i old new] (moves d)] [i [old new]]))
            area (home-areas da)]
        (doseq [i (sort (into (set (keys old-match)) (keys by-person)))]
          (let [t (peek (people i)) template (templates t) slots (paid t) plan (plans i)
                [s matched-site] (old-match i)
                before (if (some? s) (assoc plan s matched-site) plan)
                [old site] (by-person i)
                after (if site (reduce #(assoc %1 %2 site) before slots) before)]
            (when (and site (not-every? #(= old (before %)) slots))
              (throw (ex-info "Tract assignment does not match the published workplace" {:da da :i i})))
            (doseq [slot (sort slots) :when (not= (plan slot) (after slot))]
              (.add results [d i slot (plan slot) (after slot)]))
            (when site
              (let [old-area (zones old) new-area (zones site) fitted (get modes i)
                    starts (starts-by-template t)]
                (doseq [[start dur mode a b] (template "parts") :when (or (slots a) (slots b))]
                  (if (= mode "stop")
                    (do (move-stop! intervals n start dur old-area new-area)
                        (when-let [z (get geo (str site))]
                          (when (and (<= 0 z 8) (not= z (get geo (str old))) (nil? (aget examples z)))
                            (aset examples z [da i (+ start (quot dur 2)) old site]))))
                    (let [m (if (and (not preserve?) fitted (starts start)) fitted (get mode-index mode (dec k)))]
                      (move-trip! flows zones core n k area m start dur a b before after))))))))))
    (let [clock (vec (rest (reductions #(mapv + %1 %2) (vec (repeat n 0)) (partition n intervals))))
          changes (vec results) delta (outbound/hourly-table flows n k)]
      (when-not (and (every? zero? (peek clock)) (every? #(zero? (reduce + %)) clock))
        (throw (ex-info "Tract scenario changed total city occupancy" {})))
      (write-json output
        (merge (dissoc solution "moves" "siteZones")
               {:atlas (report "atlas") :day (report "day") :outbound (matched "outbound")
                :worksites (.getName (io/file matched-dir)) :changes changes :examples (vec examples)
                :occupancyDelta (pop clock)
                :delta (if preserve? delta
                         (mapv (fn [original extra] (mapv (fn [a b] (mapv #(mapv + %1 %2) a b)) original extra))
                               fitted-delta delta))})))))

(defn -main [phase & args]
  (case phase "extract" (apply extract args) "evaluate" (apply evaluate args)))
