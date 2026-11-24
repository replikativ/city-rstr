(ns city.vancouver.household-clock
  "Resample complete commuter days against the household donor's usual departure band."
  (:require [city.synth.sampling :refer [shuffled]]
            [city.vancouver.departures :as dep]
            [city.vancouver.outbound :as outbound]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util Random]))

(defn pumf-band [minute]
  (let [hour (mod (quot minute 60) 24)]
    (cond (<= 5 hour 8) (- hour 4) (<= 9 hour 15) 5 :else 6)))

(defn options [templates diaries sources tours fixed-lengths?]
  (let [entries (mapv (fn [i [role age weight]]
                        (let [t (templates i) legs (remove #(= "stop" (nth % 2)) (t "parts"))]
                          {:id i :weight weight :role role :band (some-> (get-in tours [i :minute]) pumf-band)
                           :lengths (mapv second legs)
                           :pattern [age (t "slots") (mapv #(subvec % 2) (t "parts"))
                                     (outbound/paid-slots t (diaries i))]}))
                      (range) sources)
        pools (group-by :pattern (filter #(and (= "worker" (:role %)) (:band %)) entries))]
    (mapv (fn [{:keys [pattern lengths band role]}]
            (when (and band (= role "worker"))
              (group-by :band (filter #(if fixed-lengths? (= lengths (:lengths %))
                                           (every? true? (map <= lengths (:lengths %)))) (pools pattern)))))
          entries)))

(defn- draw [^Random rng choices]
  (let [total (reduce + (map :weight choices))]
    (loop [x (* total (.nextDouble rng)) [row & more] choices]
      (if (and more (>= x (:weight row))) (recur (- x (:weight row)) more) (:id row)))))

(defn- assign [^Random rng people times tours choices]
  (reduce-kv
    (fn [{:keys [changes] :as result} i code]
      (let [[_ _ labour _ _ _ mode tpl] (people i)
            minute (get-in tours [tpl :minute])]
        (if (and (= labour 1) (<= 1 mode 7) minute (<= 1 code 6))
          (let [old (pumf-band minute)]
            (if (= code old)
              (update result :already inc)
              (let [result (update result :surplus #(-> % (update old inc) (update code dec)))]
                (if-let [pool (get-in choices [tpl code])]
                  (assoc result :changes (conj changes [i tpl (draw rng pool)]))
                  (update result :unsupported inc)))))
          result)))
    {:changes [] :already 0 :unsupported 0 :surplus (vec (repeat 7 0))} times))

(defn balance
  "Accept a candidate only while both household-band residuals improve.
   Candidate order is seeded and independent of census Profile observations."
  [surplus candidates]
  (second
    (reduce (fn [[remaining accepted] [da i from to]]
              (if (and (pos? (remaining from)) (neg? (remaining to)))
                [(-> remaining (update from dec) (update to inc)) (update accepted da (fnil conj #{}) i)]
                [remaining accepted]))
            [surplus {}] candidates)))

(defn intervals! [^ints edges sign template plan place-zones zones]
  (doseq [[s dur mode from] (template "parts")]
    (let [z (if (= mode "stop") (get place-zones (plan from) (dec zones)) (- zones 2))
          a (+ (* (- s 240) zones) z) b (+ a (* dur zones))]
      (aset-int edges a (+ (aget edges a) sign))
      (aset-int edges b (- (aget edges b) sign)))))

(defn- write! [file payload] (with-open [w (io/writer file)] (json/write payload w)))

(defn -main [atlas-dir day-dir reference source out]
  (let [atlas (dep/read-json (io/file atlas-dir "atlas.json")) day (dep/read-json (io/file day-dir "day.json"))
        input (dep/read-json source) templates (day "templates") ids (day "das")
        zones (+ (count (day "areas")) 2)
        place-zones (mapv (fn [[_ _ a]] (if (neg? a) (dec zones) a)) (dep/read-json (io/file day-dir "places.json")))
        tours (mapv dep/first-tour templates (atlas "templates"))
        choices (options templates (atlas "templates") (input "diaries") tours (input "fixedLengths"))
        edges (int-array (* 1441 zones))
        proposals (into {} (for [da ids
                                 :let [file (str da ".json") people (get (dep/read-json (io/file atlas-dir file)) "people")
                                       times (get-in input ["times" da])]]
                             (do (when-not (= (count times) (get-in atlas ["das" da "private"]))
                                   (throw (ex-info "Missing private household time codes" {:da da})))
                                 [da (assign (Random. (+ 20261124 (Long/parseLong da))) people times tours choices)])))
        band-of (fn [id] (pumf-band (:minute (tours id))))
        accepted (when (input "balance")
                   (apply merge
                          (for [[area group] (atlas "areas")
                                :let [das (group "das")
                                      surplus (apply mapv + (map #(get-in proposals [% :surplus]) das))
                                      candidates (for [da das [i old new] (get-in proposals [da :changes])]
                                                   [da i (band-of old) (band-of new)])]]
                            (balance surplus (shuffled (Random. (+ 20261124 (.hashCode ^String area))) candidates)))))
        rows (mapv (fn [da]
                     (let [file (str da ".json") people (get (dep/read-json (io/file atlas-dir file)) "people")
                           plans (get (dep/read-json (io/file day-dir file)) "plans")
                           n (get-in atlas ["das" da "private"])]
                       (when-not (= (count people) (count plans))
                         (throw (ex-info "Household clock roster differs from weekday" {:da da})))
                       (let [proposal (proposals da) all (:changes proposal)
                             changes (if (input "balance") (filterv #(contains? (accepted da) (first %)) all) all)
                             counts (assoc (select-keys proposal [:already :unsupported])
                                           :matched (count changes) :retained (- (count all) (count changes)))
                             by-person (into {} (map (fn [[i _ tpl]] [i tpl]) changes))]
                         (doseq [[i old new] changes]
                           (intervals! edges -1 (templates old) (plans i) place-zones zones)
                           (intervals! edges 1 (templates new) (plans i) place-zones zones))
                         {:changes changes :counts counts :workers (dep/workers people n da by-person)}))) ids)
        delta (vec (rest (reductions #(mapv + %1 %2) (vec (repeat zones 0)) (partition zones edges))))
        occupancy (mapv #(mapv + %1 %2) (day "occupancy") delta)
        changes (into (sorted-map) (map vector ids (map :changes rows)))
        report (dep/report (.getName (io/file atlas-dir)) (.getName (io/file day-dir)) atlas day
                           (dep/read-json reference) tours (zipmap ids (map :workers rows)))
        by-da (zipmap ids (map :counts rows))
        detail (fn [ds]
                 (let [[da [i old new]] (some #(when-let [row (first (changes %))] [% row]) ds)]
                   (assoc (apply merge-with + (map by-da ds))
                          :example (when da [da i (get-in tours [old :minute]) (get-in tours [new :minute])]))))]
    (when-not (and (every? zero? (peek delta)) (every? #(and (every? nat-int? %) (= (reduce + %) (day "population"))) occupancy))
      (throw (ex-info "Household weekday does not conserve population" {})))
    (write! (io/file out "clock.json") {:atlas (:atlas report) :day (:day report) :changes changes :occupancy occupancy})
    (write! (io/file out "report.json")
            (assoc report :householdSource {:catalogue "2021 Census Hierarchical PUMF v2" :cma "933" :field "PWLEAVE" :seed 20261124}
                   :diarySource "2022 Canadian Time Use Survey, urban BC weekday training diaries"
                   :ambiguousHouseholds (input "ambiguous") :balanced (boolean (input "balance")) :fixedLengths (boolean (input "fixedLengths"))
                   :matching (into (sorted-map) (for [[name ds] (assoc (update-vals (atlas "areas") #(get % "das")) (:overall report) ids)]
                                                  [name (detail ds)]))))))
