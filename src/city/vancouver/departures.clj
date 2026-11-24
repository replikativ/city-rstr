(ns city.vancouver.departures
  "Compare diary departures with published usual commute times on the same home geography."
  (:require [city.vancouver.outbound :as outbound]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn profile-band [minute]
  (let [hour (mod (quot minute 60) 24)]
    (cond (<= 5 hour 8) (- hour 5)
          (<= 9 hour 11) 4
          :else 5)))

(defn timed-tour
  "Trace the first paid job stop back to the most recent home. Each change of
   location needs a recorded travel bout. A day can start away from home."
  [{:strs [parts slots] :as template} diary]
  (let [paid (outbound/paid-slots template diary)
        work-index (first (keep-indexed (fn [i [_ _ mode slot]]
                                          (when (and (= mode "stop") (paid slot)) i)) parts))]
    (if (nil? work-index)
      {:kind :noJobStop}
      (loop [i work-index stops 0]
        (let [[start duration mode a b] (get parts (dec i))
              [_ _ prior from] (get parts (- i 2))
              dest (get-in parts [i 3])]
          (cond
            (or (< i 2) (= mode "stop") (not= prior "stop") (not= b dest) (not= a from))
            {:kind :untraced}
            (= "home" (slots a)) (if (zero? stops)
                                   {:kind :direct :minute start :duration duration :mode mode :from a :to b}
                                   {:kind :via :minute start})
            :else (recur (- i 2) (inc stops))))))))

(defn first-tour [template diary]
  (select-keys (timed-tour template diary) [:kind :minute]))

(defn read-json [file]
  (with-open [r (io/reader file)] (json/read r)))

(defn usual-commuter? [[age _ labour _ _ _ mode]]
  ;; A reported commute mode establishes 15+ for workers with a masked age.
  (and (= labour 1) (or (<= 3 age 13) (= age 88)) (<= 1 mode 7)))

(defn workers [people n da replacements]
  (reduce-kv
    (fn [groups i [_ _ _ _ _ _ _ tpl :as person]]
      ;; Private household roster precedes residual rows.
      (if (and (< i n) (usual-commuter? person))
        (update groups (get replacements i tpl) (fn [[c example]] [(inc (or c 0)) (or example [da i])]))
        groups))
    {} people))

(defn- sum-groups [a b] [(+ (first a) (first b)) (second a)])

(defn- summarize [ids observed observed-by-da roster tours]
  (let [covered (if observed ids (filterv observed-by-da ids))
        census (or observed (when (seq covered) (apply mapv + (map observed-by-da covered))))
        counts (reduce #(merge-with sum-groups %1 (roster %2)) {} covered)
        groups (for [[tpl [n ex]] (sort counts)] (assoc (tours tpl) :n n :tpl tpl :example ex))
        coverage (reduce (fn [m {:keys [kind n]}] (update m kind (fnil + 0) n)) {} groups)
        timed (filter :minute groups)
        by-band (fn [rows] (reduce (fn [v {:keys [minute n]}] (update v (profile-band minute) + n))
                                   [0 0 0 0 0 0] rows))
        peak (first (sort-by (fn [[minute rows]] [(- (reduce + (map :n rows))) minute])
                             (group-by :minute timed)))
        [minute rows] peak
        donor (first (sort-by (juxt (comp - :n) :tpl) rows))]
    {:census census :directObservation (boolean observed) :covered (count covered) :total (count ids)
     :model (by-band timed) :direct (by-band (filter #(= :direct (:kind %)) timed))
     :coverage coverage
     :peak (when peak {:minute minute :count (reduce + (map :n rows))
                       :templates (count rows) :largest (:n donor) :example (:example donor)})}))

(defn report [atlas-id day-id atlas day obs tours roster]
  (let [ids (day "das")
        areas (into (sorted-map) (map (fn [[k v]] [k (v "das")]) (atlas "areas")))
        overall (if (contains? (obs "direct") "All city residents") "All city residents" "All regional residents")]
    (when-not (and (= (set ids) (set (keys (atlas "das"))) (set (keys (obs "das"))))
                   (= (frequencies ids) (frequencies (mapcat val areas)))
                   (= (count (day "templates")) (count (atlas "templates"))))
      (throw (ex-info "Population, geography and weekday inputs disagree" {})))
    {:atlas atlas-id :day day-id :overall overall :characteristics (range 2617 2624)
     :source "2021 Census Profile, British Columbia, 98-401-X2021006"
     :areas (into (sorted-map) (for [[name ds] (assoc areas overall ids)]
                                 [name (summarize ds (get-in obs ["direct" name]) (obs "das") roster tours)]))}))

(defn -main [atlas-dir day-dir reference target]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        tours (mapv first-tour (day "templates") (atlas "templates"))
        roster (into {} (for [da (day "das")]
                          [da (workers (get (read-json (io/file atlas-dir (str da ".json"))) "people")
                                       (get-in atlas ["das" da "private"]) da {})]))]
    (with-open [w (io/writer target)]
      (json/write (report (.getName (io/file atlas-dir)) (.getName (io/file day-dir))
                          atlas day (read-json reference) tours roster) w))))
