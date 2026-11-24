(ns city.vancouver.transit-commutes
  "Keep the resident's shift and places while timing their direct transit commute."
  (:require [city.commute :as commute]
            [city.vancouver.departures :as dep]
            [city.vancouver.household-clock :as clock]
            [city.vancouver.outing-opportunities :as outings]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- write! [file data]
  (with-open [w (io/writer file)] (json/write data w)))

(defn- transit-legs [template diary flex? work?]
  (let [paid (commute/paid-slots template diary)
        episodes (diary "episodes")
        parts (template "parts")
        slots (template "slots")
        spans (when flex? (outings/home-spans episodes))]
    (into []
          (keep-indexed
           (fn [i [start duration mode a b]]
             (when (and (not= mode "stop") (= work? (boolean (or (paid a) (paid b)))))
               (let [end (+ start duration)
                     modes (into #{} (keep (fn [[t _ _ m]] (when (<= start t (dec end)) m))) episodes)]
                 (when (modes "transit")
                   (let [[time len kind from] (get parts (dec i))
                         [next-time next-len next-kind to] (get parts (inc i))
                         span (when flex?
                                (cond
                                  (and (paid b) (= "home" (get slots a)) (= kind "stop") (= from a)
                                       (= start (+ time len)))
                                  (some (fn [[lo hi]] (when (= hi start) [(max lo time) hi])) spans)

                                  (and (paid a) (= "home" (get slots b)) (= next-kind "stop") (= to b)
                                       (= next-time end))
                                  (some (fn [[lo hi]] (when (= lo end) [lo (min hi (+ next-time next-len))])) spans)))]
                     [start duration a b (every? #{"walk" "transit"} modes)
                      (if work? (boolean (paid b)) (get slots b "unresolved")) span]))))))
          parts)))

(defn- work-legs [template diary flex?]
  (transit-legs template diary flex? true))

(defn- travel-windows [atlas-dir day-dir atlas day flex? work?]
  (let [candidates (mapv #(transit-legs %1 %2 flex? work?) (day "templates") (atlas "templates"))
        rows (volatile! (transient []))
        excluded (volatile! {"mixed" 0 "unlocated" 0 "samePlace" 0})]
    (visit-residents!
     atlas-dir day-dir atlas (day "das")
     (fn [da person [age _ labour _ _ _ _ tpl] _ plan]
       (when (or (not work?) (and (= 1 labour) (<= 3 age 13)))
         (doseq [[start duration a b pure? next-activity span] (candidates tpl)
                 :when (or (not flex?) span)]
           (let [a (get plan a -1) b (get plan b -1)
                 reason (cond (not pure?) "mixed"
                              (or (neg? a) (neg? b)) "unlocated"
                              (= a b) "samePlace")]
             (if reason
               (vswap! excluded update reason inc)
               (vswap! rows conj! (cond-> [da person start duration a b next-activity]
                                  flex? (conj tpl span)))))))))
    {:rows (persistent! @rows) :excluded @excluded}))

(defn- candidate [template diary]
  (let [{:keys [kind mode minute duration] :as tour} (dep/timed-tour template diary)]
    (when (and (= kind :direct) (= mode "transit"))
      (let [episodes (diary "episodes")
            i (first (keep-indexed #(when (= (first %2) minute) %1) episodes))
            end (+ minute duration)]
        (when (and (pos-int? i)
                   (= "home" (get-in episodes [(dec i) 3]))
                   (not= "shopping" (get-in episodes [(dec i) 2]))
                   (every? #{"walk" "transit"}
                           (map #(nth % 3) (take-while #(< (first %) end) (subvec episodes i)))))
          (assoc tour :episode i))))))

(defn- eligible [atlas-dir day-dir atlas day tours]
  (reduce (fn [rows da]
            (let [file (str da ".json")
                  people ((dep/read-json (io/file atlas-dir file)) "people")
                  plans ((dep/read-json (io/file day-dir file)) "plans")
                  n (get-in atlas ["das" da "private"])]
              (when-not (= (count people) (count plans))
                (throw (ex-info "Transit candidate roster differs from weekday" {:da da})))
              (reduce (fn [rows i]
                        (let [person (people i)
                              t (person 7)
                              {:keys [minute duration from to]} (tours t)
                              plan (plans i)
                              a (get plan from -1)
                              b (get plan to -1)]
                          (if (and minute (dep/usual-commuter? person) (>= a 0) (>= b 0) (not= a b))
                            (conj rows [da i t minute duration a b])
                            rows)))
                      rows (range n))))
          [] (day "das")))

(defn revised-templates [template diary tour departure]
  (let [{:keys [minute duration episode]} tour
        shift (- departure minute)
        parts (template "parts")
        k (first (keep-indexed #(when (= (first %2) minute) %1) parts))
        episodes (diary "episodes")
        end (+ minute duration)
        remaining (drop-while #(< (first %) end) (subvec episodes episode))]
    (when-not (and (< minute departure end) (pos-int? k)
                   (= "stop" (get-in parts [(dec k) 2])))
      (throw (ex-info "Transit departure must follow home and preserve the job start" {:minute minute :departure departure})))
    {:day (assoc template "parts"
                 (-> parts (update-in [(dec k) 1] + shift)
                     (assoc-in [k 0] departure) (update-in [k 1] - shift)))
     :diary (assoc diary "episodes"
                   (into (conj (subvec episodes 0 episode)
                               [minute shift "other" "home"]
                               [departure (- end departure) "travel" "transit"])
                         remaining))}))

(defn- clock-variant [atlas-dir day-dir atlas day edits revise]
  (let [original (day "templates")
        diaries (atlas "templates")
        keys (distinct (for [[_ _ tpl change] edits] [tpl change]))
        index (zipmap keys (iterate inc (count original)))
        appended (mapv (fn [[tpl change]]
                         (revise tpl (original tpl) (diaries tpl) change)) keys)
        zones (+ (count (day "areas")) 2)
        place-zones (mapv (fn [[_ _ area]] (if (neg? area) (dec zones) area))
                          (dep/read-json (io/file day-dir "places.json")))
        edges (int-array (* 1441 zones))
        changes (into (sorted-map)
                      (for [[da rows] (group-by first edits)
                            :let [file (str da ".json")
                                  people ((dep/read-json (io/file atlas-dir file)) "people")
                                  plans ((dep/read-json (io/file day-dir file)) "plans")]]
                        [da (mapv (fn [[_ i old change]]
                                    (when-not (= old (get-in people [i 7]))
                                      (throw (ex-info "Transit revision uses a different resident" {:da da :person i})))
                                    (let [new (index [old change])
                                          plan (plans i)]
                                      (clock/intervals! edges -1 (original old) plan place-zones zones)
                                      (clock/intervals! edges 1 (:day (appended (- new (count original)))) plan place-zones zones)
                                      [i old new]))
                                  rows)]))
        delta (vec (rest (reductions #(mapv + %1 %2) (vec (repeat zones 0)) (partition zones edges))))
        occupancy (mapv #(mapv + %1 %2) (day "occupancy") delta)]
    (when-not (and (every? zero? (peek delta))
                   (every? #(and (every? nat-int? %) (= (day "population") (reduce + %))) occupancy))
      (throw (ex-info "Transit weekday does not conserve population" {})))
    {"atlas" (.getName (io/file atlas-dir)) "day" (.getName (io/file day-dir))
     "changes" changes "occupancy" occupancy "templates" appended}))

(defn- revision [atlas-dir day-dir atlas day tours source out]
  (let [variant (clock-variant atlas-dir day-dir atlas day (source "revisions")
                               (fn [tpl template diary departure] (revised-templates template diary (tours tpl) departure)))
        info (merge (source "report") (select-keys variant ["atlas" "day"]) {"kind" "scheduled-transit"})]
    (write! (io/file out "clock.json")
            (merge variant (select-keys info ["kind" "transit" "streets"])))
    (write! (io/file out "report.json") info)
    (write! (io/file out "rides.json") (source "rides"))))

(defn- borrow-home-time [episodes lo hi]
  (let [extra [lo (- hi lo) "travel" "transit"]
        pieces (mapcat (fn [[start dur :as episode]]
                         (let [end (+ start dur)]
                           (if (and (< start hi) (> end lo))
                             (do
                               (when-not (outings/flexible-at-home? episode)
                                 (throw (ex-info "Transit extension overlaps a protected activity" {:interval [lo hi] :episode episode})))
                               (cond-> []
                                 (< start lo) (conj (assoc episode 1 (- lo start)))
                                 (> end hi) (conj (assoc episode 0 hi 1 (- end hi)))))
                             [episode])))
                       episodes)]
    (vec (sort-by first (conj (vec pieces) extra)))))

(defn flex-templates [template diary edits]
  (let [supported (into {} (for [[start duration _ _ _ out? span] (work-legs template diary true) :when span]
                             [[start (+ start duration)] [out? span]]))]
    (reduce (fn [{:keys [day diary]} [start end departure arrival]]
              (let [parts (day "parts")
                    k (first (keep-indexed #(when (= (subvec %2 0 2) [start (- end start)]) %1) parts))
                    [out? [lo hi]] (supported [start end])
                    left (- start departure)
                    right (- arrival end)
                    home (when (some? k) (if (pos? left) (dec k) (inc k)))]
                (when-not (and (some? k) lo (if out?
                                            (and (pos? left) (zero? right) (<= lo departure))
                                            (and (pos? right) (zero? left) (<= arrival hi)))
                               (= "stop" (get-in parts [home 2]))
                               (> (get-in parts [home 1]) (+ left right)))
                  (throw (ex-info "Invalid extension of a home-to-work transit window" {:edit [start end departure arrival]})))
                {:day (assoc day "parts" (-> parts (assoc-in [k 0] departure)
                                            (assoc-in [k 1] (- arrival departure))
                                            (update-in [home 0] + right)
                                            (update-in [home 1] - (+ left right))))
                 :diary (update diary "episodes" borrow-home-time
                                (if out? departure end) (if out? start arrival))}))
            {:day template :diary diary}
            edits)))

(defn- flex-clock [atlas-dir day-dir atlas day source out]
  (let [variant (clock-variant atlas-dir day-dir atlas day (source "revisions")
                               (fn [_ template diary edits] (flex-templates template diary edits)))
        info (merge (source "report") (select-keys variant ["atlas" "day"]) {"kind" "work-transit-flex"})]
    (write! (io/file out "clock.json")
            (merge variant (select-keys info ["kind" "transit" "streets" "workplaceRun" "workTransitRelease"])))
    (write! (io/file out "report.json") info)))

(defn -main [action atlas-dir day-dir input & [output]]
  (let [atlas (dep/read-json (io/file atlas-dir "atlas.json"))
        day (dep/read-json (io/file day-dir "day.json"))
        _ (when-not (and (= (count (atlas "templates")) (count (day "templates")))
                         (= (set (day "das")) (set (keys (atlas "das")))))
            (throw (ex-info "Transit commute and weekday releases differ" {})))
        tours #(mapv candidate (day "templates") (atlas "templates"))]
    (case action
      "prepare" (write! input (eligible atlas-dir day-dir atlas day (tours)))
      "fixed-windows" (write! input (travel-windows atlas-dir day-dir atlas day false true))
      "flex-windows" (write! input (travel-windows atlas-dir day-dir atlas day true true))
      "personal-windows" (write! input (travel-windows atlas-dir day-dir atlas day false false))
      "flex-clock" (flex-clock atlas-dir day-dir atlas day (dep/read-json input) output)
      "publish" (revision atlas-dir day-dir atlas day (tours) (dep/read-json input) output))))
