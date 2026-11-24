(ns city.vancouver.outing-opportunities
  "Locate uninterrupted at-home discretionary time in existing resident diaries."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def ^:private discretionary-activities #{"media" "leisure-out"})

(defn flexible-at-home? [[_ _ activity place]]
  (and (= place "home") (discretionary-activities activity)))

(defn home-spans
  ([episodes] (home-spans episodes discretionary-activities))
  ([episodes allowed-activity?]
   (reduce (fn [result [start duration activity place]]
             (if (and (= place "home") (allowed-activity? activity))
               (let [end (+ start duration)]
                 (if (= start (peek (peek result)))
                   (conj (pop result) [(first (peek result)) end])
                   (conj result [start end])))
               result))
           [] episodes)))

(defn windows [episodes]
  (filterv (fn [[a b]] (>= (- (min 1260 b) (max 420 a)) 10)) (home-spans episodes)))

(defn- recorded-home-loops [mode {:strs [parts slots]} episodes]
  (into []
        (keep (fn [[start minutes travel a b]]
                (when (and (= mode travel) (= "home" (get slots a) (get slots b))
                           (every? (fn [[_ _ act loc]] (and (= "travel" act) (= mode loc)))
                                   (filter (fn [[t]] (<= start t (dec (+ start minutes)))) episodes)))
                  [start minutes a b])))
        parts))

(defn -main [atlas-dir day-dir input output & [detail clock-path]]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        municipalities (read-json input)
        home-groups (into {} (for [name municipalities da (get-in atlas ["areas" name "das"])] [da name]))
        das (day "das") index (zipmap das (range))
        clock (when clock-path (read-json clock-path))
        revisions (get clock "templates")
        changes (update-vals (get clock "changes" {}) #(into {} (map (fn [[i original revised]] [i [original revised]]) %)))
        diaries (mapv #(get % "episodes") (into (atlas "templates") (map #(get % "diary") revisions)))
        templates (into (day "templates") (map #(get % "day") revisions))
        loop-mode ({"with-loops" "walk" "with-bicycle-loops" "bike"} detail)
        with-access (= detail "with-access")
        adults-only (= detail "adults-only")
        opportunities (mapv (if loop-mode home-spans windows) diaries)
        recorded (when loop-mode (mapv (partial recorded-home-loops loop-mode) templates diaries))
        drivers (mapv #(boolean (some (fn [e] (= (peek e) "car-driver")) %)) diaries)
        riders (mapv #(boolean (some (fn [e] (= (peek e) "bike")) %)) diaries)
        residents (java.util.ArrayList.)
        adults (java.util.ArrayList.)
        adult-counts (volatile! {})
        home-loops (java.util.ArrayList.)]
    (visit-residents! atlas-dir day-dir atlas (filter #(contains? home-groups %) das)
      (fn [da i [age _ _ _ _ _ _ template] home plan]
        (let [[original revised] (get-in changes [da i] [template template])]
          (when (not= original template)
            (throw (ex-info "Clock template and resident diary differ" {:da da :i i})))
          (when (<= 3 age 13)
            (when with-access
              (.add adults [(index da) i (home-groups da) (riders revised)]))
            (when (and adults-only (<= 4 age))
              (vswap! adult-counts update (home-groups da) (fnil inc 0)))
            (when (and (seq (opportunities revised)) (or (not adults-only) (<= 4 age)))
              (.add residents (cond-> [(index da) i home revised (home-groups da) (and (<= 4 age) (drivers revised))]
                                (or loop-mode adults-only) (conj age))))
            (when loop-mode
              (doseq [[start minutes a b] (recorded revised)
                      :when (and (<= 0 home) (= home (get plan a) (get plan b)))]
                (.add home-loops [(index da) i home start minutes age (home-groups da)])))))))
    (with-open [w (io/writer output)]
      (json/write (cond-> {:windows opportunities :residents (vec residents)}
                    with-access (assoc :adults (vec adults))
                    adults-only (assoc :adultsByArea @adult-counts)
                    loop-mode (assoc :recorded (vec home-loops))) w))))
