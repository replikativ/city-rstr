(ns city.vancouver.departure-clock
  "Spread repeated road and active-mode diary bouts within their original departure hour."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.household-clock :refer [intervals!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def modes #{"walk" "bike" "car-driver" "car-passenger" "taxi" "ridehail" "motorcycle"})
(def flexible #{"eating" "media" "leisure-out" "socializing" "housework" "personal-care"})

(defn- absorb [episodes at other]
  (let [[_ length activity] (episodes at)]
    (if (flexible activity)
      (let [slack (max 0 (- length 5))]
        (if (modes (get-in episodes [other 3])) (quot slack 2) slack))
      0)))

(defn- within-bounds [parts episodes radius]
  (let [starts (into {} (map-indexed (fn [i episode] [(first episode) i]) episodes))]
    (keep-indexed
     (fn [k [start duration mode a b]]
       (let [before (get parts (dec k)) after (get parts (inc k))
             i (get starts start) j (get starts (+ start duration))]
         (when (and (modes mode) (<= 0 a) (<= 0 b) (= "stop" (get before 2) (get after 2))
                    i j (= 0 (mod start 5))
                    (every? #(= mode (nth % 3)) (subvec episodes i j)))
           [k i j
            (- (min radius (mod start 60) (absorb episodes (dec i) (- i 2))))
            (min radius (- 59 (mod start 60)) (absorb episodes j (inc j)))])))
     parts)))

(defn- retime-episodes [episodes changes]
  (let [from (into {} (map (fn [[_ i j delta]] [j delta]) changes))
        to (into {} (map (fn [[_ i _ delta]] [(dec i) delta]) changes))
        travel (into {} (mapcat (fn [[_ i j delta]] (map #(vector % delta) (range i j))) changes))]
    (loop [i 0, end 240, prev nil, result []]
      (if (= i (count episodes))
        result
        (let [[start length activity place] (episodes i)
              start' (+ start (get travel i (if (flexible activity) (get from i 0) 0)))
              end' (+ start length (get travel i (if (flexible activity) (get to i 0) 0)))
              result (cond-> result
                       (< end start') (conj [end (- start' end) "waiting" (if (contains? travel i) prev place)]))]
          (when (or (> end start') (<= end' start'))
            (throw (ex-info "A shifted diary has overlapping or empty activities" {:episode i})))
          (recur (inc i) end' place (conj result [start' (- end' start') activity place])))))))

(defn variants [{:strs [parts] :as day} {:strs [episodes] :as diary} radius]
  (let [windows (when-not (day "childSchedule") (within-bounds parts episodes radius))
        ranks (inc (* 2 radius))]
    (mapv (fn [rank]
            (let [u (/ (+ rank 0.5) ranks)
                  changes (keep (fn [[k i j lo hi]]
                                  (let [delta (+ lo (int (* u (inc (- hi lo)))))]
                                    (when-not (zero? delta) [k i j delta]))) windows)]
              (when (seq changes)
                (let [shift (into {} (map (juxt first peek)) changes)
                      parts' (mapv (fn [i [start duration mode a b]]
                                     (if (= mode "stop")
                                       (let [earlier (get shift (dec i) 0) later (get shift (inc i) 0)]
                                         [(+ start earlier) (+ duration later (- earlier)) mode a b])
                                       [(+ start (get shift i 0)) duration mode a b]))
                                   (range) parts)]
                  {:day (assoc day "parts" parts')
                   :diary (assoc diary "episodes" (retime-episodes episodes changes))
                   :moved (count changes)}))))
          (range ranks))))

(defn- build-bank [templates diaries radius]
  (reduce (fn [{:keys [lookup bank]} [source t diary]]
            (let [candidates (variants t diary radius)
                  unique (vec (distinct (remove nil? candidates)))
                  index (zipmap unique (range (+ (count templates) (count bank)) 65536))]
              {:bank (into bank unique)
               :lookup (conj lookup (mapv #(get index % source) candidates))}))
          {:bank [] :lookup []} (map vector (range) templates diaries)))

(defn- write! [file data]
  (with-open [writer (io/writer file)] (json/write data writer)))

(defn -main [atlas-folder day-folder out]
  (let [atlas-dir (io/file atlas-folder) day-dir (io/file day-folder)
        atlas (read-json (io/file atlas-dir "atlas.json")) day (read-json (io/file day-dir "day.json"))
        source (day "templates") radius 7 seed 20261122
        {:keys [bank lookup]} (build-bank source (atlas "templates") radius)
        templates (into source (map :day bank))
        zones (+ 2 (count (day "areas")))
        place-zones (mapv (fn [[_ _ a]] (if (neg? a) (dec zones) a))
                          (read-json (io/file day-dir "places.json")))
        edges (int-array (* 1441 zones))
        totals (long-array (count templates))
        changes
        (into (sorted-map)
              (for [da (day "das")
                    :let [name (str da ".json")
                          people (get (read-json (io/file atlas-dir name)) "people")
                          plans (get (read-json (io/file day-dir name)) "plans")]]
                (do (when-not (= (count people) (count plans) (get-in atlas ["das" da "population"]))
                      (throw (ex-info "Departure clock roster differs from the weekday" {:da da})))
                    [da (persistent!
                         (reduce-kv
                          (fn [result i p]
                            (let [old (nth p 7)
                                  rank (Math/floorMod (int (hash [seed da i])) (int (inc (* 2 radius))))
                                  tpl (get-in lookup [old rank])]
                              (aset-long totals tpl (inc (aget totals tpl)))
                              (if (= old tpl)
                                result
                                (do (intervals! edges -1 (templates old) (plans i) place-zones zones)
                                    (intervals! edges 1 (templates tpl) (plans i) place-zones zones)
                                    (conj! result [i old tpl])))))
                          (transient []) people))])))
        delta (vec (rest (reductions #(mapv + %1 %2) (vec (repeat zones 0)) (partition zones edges))))
        occupancy (mapv #(mapv + %1 %2) (day "occupancy") delta)
        report {:atlas (.getName atlas-dir) :day (.getName day-dir) :kind "spread-departures"
                :population (day "population") :radius radius :seed seed
                :changedResidents (reduce + (map count (vals changes)))
                :changedTrips (reduce + (map-indexed
                                         (fn [i variant] (* (:moved variant) (aget totals (+ (count source) i)))) bank))}]
    (when-not (and (< (count templates) 65536)
                   (= (reduce + totals) (day "population"))
                   (every? zero? (peek delta))
                   (every? #(and (every? nat-int? %) (= (reduce + %) (day "population"))) occupancy))
      (throw (ex-info "Departure clock must conserve the complete population" {})))
    (write! (io/file out "clock.json")
            (assoc report :changes changes :templates (mapv #(dissoc % :moved) bank) :occupancy occupancy))
    (write! (io/file out "report.json") report)))
