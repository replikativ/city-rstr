(ns city.vancouver.outbound
  "Assign usual workplace municipalities to existing Vancouver residents and replay their diaries."
  (:require [city.commute :as commute]
            [city.synth.sampling :refer [effective-count shuffled]]
            [city.vancouver.occupancy-run :as raster]
            [city.vancouver.commute-fit :as fit]
            [city.vancouver.trip-accounting :as accounting]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util Random]))

(defn- read-data [file]
  (with-open [r (io/reader file)] (json/read r)))

(defn- write-data! [file data]
  (with-open [w (io/writer file)] (json/write data w)))

(defn bounded-counts
  "Allocate an integer margin across areas, exhausting capacity before redistributing overflow."
  [weights capacity total]
  (when-not (and (<= 0 total (reduce + capacity)) (every? nat-int? capacity) (every? #(<= 0 %) weights)
                 (= (count weights) (count capacity)))
    (throw (ex-info "Infeasible workplace controls" {:total total})))
  (loop [counts (mapv (constantly 0) capacity)]
    (let [remaining (- total (reduce + counts))]
      (if (zero? remaining) counts
          (let [room (mapv - capacity counts)
                source (mapv #(if (pos? %2) %1 0) weights room)
                w (if (some pos? source) source room)
                weight-sum (reduce + w)
                x (mapv #(* remaining (/ (double %) weight-sum)) w)
                whole (mapv #(min %1 (long %2)) room x)
                next-counts (mapv + counts whole)]
            (if (some true? (map > x room))
              (recur next-counts)
              (reduce #(update %1 %2 inc) next-counts
                      (take (- total (reduce + next-counts))
                            (sort-by #(double (- (whole %) (x %))) (range (count w)))))))))))

(defn- allocate-gender [people local stocks gender ^Random rng]
  (let [groups (mapv (fn [rows] (group-by #(= 4 (nth % 2)) (filter #(= gender (second %)) rows))) people)
        capacity (mapv #(reduce + (map count (vals %))) groups)
        target (reduce + stocks)
        available (reduce + capacity)
        share (if (pos? available) (/ (double target) available) 0.0)
        weights (mapv #(or (get %1 (dec gender)) (* share %2)) local capacity)
        quotas (bounded-counts weights capacity target)
        chosen (mapcat (fn [d group n]
                         (let [cross (shuffled rng (group false)) local (shuffled rng (group true))]
                           (map (fn [[i]] [d i]) (take n (concat cross local)))))
                       (range) groups quotas)
        destinations (shuffled rng (mapcat #(repeat %2 %1) (range) stocks))]
    {:rows (mapv conj chosen destinations)
     :eligible available
     :reassigned (reduce + (map #(max 0 (- %1 (count (%2 false)))) quotas groups))}))

(defn assign [{:strs [seed candidates local destinations]}]
  (let [stock (mapv #(get % "total") destinations)
        women (mapv (fn [{:strs [total women men]}]
                      (long (Math/rint (* total (if (pos? (+ women men)) (/ (double women) (+ women men)) 0.5)))))
                    destinations)
        groups (mapv (fn [gender stocks] (allocate-gender candidates local stocks gender (Random. (+ seed gender))))
                     [1 2] [women (mapv - stock women)])
        by-da (group-by first (mapcat :rows groups))
        rows (mapv #(mapv (fn [[_ i dest]] [i dest]) (sort-by second (by-da %))) (range (count candidates)))
        destination-counts (frequencies (mapcat (partial map second) rows))]
    (when-not (= (mapv #(get destination-counts % 0) (range (count stock))) stock)
      (throw (ex-info "Assigned stock differs from census flows" {})))
    {:assignments rows :stock stock :women women :eligible (reduce + (map :eligible groups))
     :reassignedWithin (reduce + (map :reassigned groups))}))

(def paid-slots commute/paid-slots)
(def direct-commute? commute/direct-commute?)
(def crossing accounting/crossing)

(def ^:private age-groups
  {3 "15–24", 4 "15–24", 5 "25–34", 6 "25–34", 7 "35–44", 8 "35–44",
   9 "45–54", 10 "45–54", 11 "55–64", 12 "65+", 13 "65+"})

(defn events
  "One resident's paired work intervals, Downtown crossing deltas and first direct commute mode."
  [template paid plan zones downtown external mode-index]
  (let [zone (fn [k] (get zones (get plan k) -1))
        parts (get template "parts")]
    (reduce
     (fn [acc [start dur mode i j :as part]]
       (cond
         (= mode "stop")
         (if (paid i) (update acc :intervals conj [(- start 240) (- (+ start dur) 240)
                                                  (let [a (zone i)] (if (neg? a) external a))]) acc)
         (or (paid i) (paid j))
         (let [a (zone i) b (zone j)
               before (crossing a b downtown)
               after (crossing (if (paid i) external a) (if (paid j) external b) downtown)
               idx (get mode-index mode (get mode-index "other"))
               hour (fn [direction] (mod (quot (if (zero? direction) (+ start dur) start) 60) 24))]
           (cond-> acc
             (direct-commute? (get template "slots") paid part)
             (update :direct conj [start dur idx after])
             (and (nil? (:commute acc)) (= "home" (get (get template "slots") i)) (paid j)) (assoc :commute idx)
             (and (some? before) (not= before after)) (update :flows conj [(hour before) before idx -1])
             (and (some? after) (not= before after)) (update :flows conj [(hour after) after idx 1])))
         :else acc))
     {:intervals [] :flows [] :direct []} parts)))

(defn add-flow! [^ints table zones modes area [h direction mode change]]
  (let [k (+ mode (* modes (+ direction (* 2 (+ area (* zones h))))))]
    (aset-int table k (+ (aget table k) change))))

(defn usual-flow-changes [[start dur recorded direction] usual]
  (when (and (some? direction) (<= 0 usual) (not= usual recorded))
    (let [h (mod (quot (if (zero? direction) (+ start dur) start) 60) 24)]
      [[h direction recorded -1] [h direction usual 1]])))

(defn hourly-table [table zones modes]
  (->> table (partition modes) (map vec) (partition 2) (map vec) (partition zones) (mapv vec)))

(defn- count-pair [summary age template diary usual]
  (let [count-mode (fn [groups label]
                     (-> groups
                         (update-in [label :diary diary] (fnil inc 0))
                         (update-in [label :usual usual] (fnil inc 0))
                         (update-in [label :templates template] (fnil inc 0))
                         (update-in [label :changed] (fnil + 0) (if (= diary usual) 0 1))))]
    (update summary :paired #(-> % (count-mode "All ages") (count-mode age)))))

(defn- diary-support [{:keys [templates] :as group}]
  (assoc (dissoc group :templates) :templateCount (count templates)
         :effectiveTemplates (effective-count (vals templates))))

(defn- relocation-clock [groups zones backend]
  (if (empty? groups)
    (vec (repeat 1440 (vec (repeat zones 0))))
    (let [patterns (vec (sort (keys groups)))
          intervals (mapcat identity patterns)
          index (fn [time zone] (+ (* time zones) zone))
          inputs {:ids (int-array (range (count patterns))) :weights (int-array (map groups patterns))
                  :offsets (int-array (reductions + 0 (map count patterns)))
                  :starts (int-array (map (fn [[s _ z]] (index s z)) intervals))
                  :ends (int-array (map (fn [[_ e z]] (index e z)) intervals))
                  :shifts (int-array (count intervals)) :ranks (int-array (count patterns))
                  :changes (int-array (* 1441 zones)) :settings (int-array 2)}
          changes (first (raster/evaluate inputs [0] (apply max (map count patterns)) backend))
          clock (vec (rest (reductions #(mapv + %1 %2) (vec (repeat zones 0)) (partition zones changes))))]
      (when (some (complement zero?) (peek clock)) (throw (ex-info "Unbalanced interval changes" {})))
      (pop clock))))

(defn replay [atlas-dir day-dir rows input backend]
  (let [{:strs [areas das templates occupancy population]} (read-data (io/file day-dir "day.json"))
        atlas (read-data (io/file atlas-dir "atlas.json"))
        zones (mapv #(nth % 2) (read-data (io/file day-dir "places.json")))
        paid (mapv paid-slots templates (get atlas "templates"))
        home-area (into {} (for [[area group] (get atlas "areas") da (get group "das")] [da (.indexOf areas area)]))
        n (count areas) downtown (.indexOf areas "Downtown")
        {:strs [destinations modes modeIndex censusMode seed]} input
        modes-n (count modes)
        mode-id (zipmap modes (range))
        rng (Random. seed)
        trip-rng (Random. (+ seed 17))
        hourly-delta (int-array (* 24 n 2 modes-n))
        usual-delta (int-array (alength hourly-delta))
        annotated (object-array (count rows))
        trip-examples (object-array (count destinations))
        changed-legs (int-array (count destinations))
        area-stock (int-array n) attend (int-array (count destinations)) examples (object-array (count destinations))
        initial {:groups {} :usual {} :diary {}}
        summary
        (reduce
         (fn [acc [d da assignments]]
           (if (empty? assignments) acc
               (let [roster (get (read-data (io/file atlas-dir (str da ".json"))) "people")
                     plans (get (read-data (io/file day-dir (str da ".json"))) "plans")
                     area (home-area da)
                     workers (mapv (fn [[i dest]]
                                     [i dest (get mode-id (get censusMode (str (nth (roster i) 6))) -1)])
                                   assignments)]
                 (aset annotated d workers)
                 (reduce
                  (fn [acc [i dest usual-id]]
                    (let [person (roster i) t (peek person)
                          usual (get censusMode (str (nth person 6)) "Unknown")
                          acc (update-in acc [:usual usual] (fnil inc 0))]
                      (aset-int area-stock area (inc (aget area-stock area)))
                      (if (empty? (paid t)) acc
                          (let [{:keys [intervals flows commute direct]}
                                (events (templates t) (paid t) (plans i) zones downtown n modeIndex)]
                            (doseq [flow flows] (add-flow! hourly-delta n modes-n area flow))
                            (doseq [[start dur recorded :as leg] direct
                                    :when (and (<= 0 usual-id) (not= usual-id recorded))]
                              (aset-int changed-legs dest (inc (aget changed-legs dest)))
                              (when (zero? (.nextInt trip-rng (aget changed-legs dest)))
                                (aset trip-examples dest [da i (+ start (quot dur 2))]))
                              (doseq [change (usual-flow-changes leg usual-id)]
                                (add-flow! usual-delta n modes-n area change)))
                            (aset-int attend dest (inc (aget attend dest)))
                            (when (zero? (.nextInt rng (aget attend dest)))
                              (aset examples dest [da i (+ 240 (ffirst intervals))]))
                            (cond-> (update-in acc [:groups intervals] (fnil inc 0))
                              (some? commute) (update-in [:diary (modes commute)] (fnil inc 0))
                              (some? commute) (count-pair (get age-groups (first person) "Unknown age") t
                                                         (modes commute) (get modes usual-id (modes commute))))))))
                  acc workers))))
         initial (map vector (range) das rows))
        moved (relocation-clock (:groups summary) (inc n) backend)]
    (doseq [[counts relocated] (map vector occupancy moved)]
      (let [original (conj (subvec counts 0 n) (peek counts))
            remaining (mapv - original relocated)]
        (when-not (and (every? nat-int? relocated) (every? nat-int? remaining)
                       (= population (+ (counts n) (reduce + remaining) (reduce + relocated))))
          (throw (ex-info "Workplace replay lost residents" {})))))
    {:areas areas :modes modes :modeKeys (mapv first (sort-by val modeIndex)) :attend (vec attend) :examples (vec examples)
     :assignments (mapv vec annotated)
     :directStarts (mapv (fn [template paid]
                           (mapv first (filter #(direct-commute? (get template "slots") paid %)
                                               (get template "parts")))) templates paid)
     :usualDelta (hourly-table usual-delta n modes-n) :changedLegs (reduce + changed-legs)
     :tripExamples (vec trip-examples)
     :observedByAge (get input "observedByAge")
     :pairedByAge (update-vals (:paired summary) diary-support)
     :slots (mapv #(vec (sort %)) paid) :relocated moved :externalByMinute (mapv #(reduce + %) moved)
     :areaStock (vec area-stock) :modeCheck {:observed (get input "observed") :usual (:usual summary) :diary (:diary summary)}
     :delta (hourly-table hourly-delta n modes-n)
     :execution {:backend backend :weightedPatterns (count (:groups summary))}}))

(defn- fit-neighbourhoods [atlas-dir day atlas assignments input]
  (let [{:strs [areas das]} day
        {:strs [modeProfile profileModes censusMode modes seed observed]} input
        _ (when-not (= profileModes ["Car driver" "Car passenger" "Public transit" "Walking" "Bicycle" "Other"])
            (throw (ex-info "Unexpected census mode classification" {:labels profileModes})))
        profile-id (zipmap profileModes (range)) simulation-id (mapv #(.indexOf modes %) profileModes)
        da-index (zipmap das (range))
        by-da (object-array (count das)) local-only (object-array (count das))
        local-fits
        (mapv
         (fn [area name]
           (let [indices (mapv da-index (get-in atlas ["areas" name "das"]))
                 profiles (keep modeProfile indices)
                 reference (reduce #(mapv + %1 %2) (vec (repeat (count profileModes) 0)) profiles)
                 donors
                 (vec (mapcat
                       (fn [d]
                         (let [da (das d) outbound (into #{} (map first) (assignments d))
                               roster (get (read-data (io/file atlas-dir (str da ".json"))) "people")]
                           (keep-indexed
                            (fn [i person]
                              (when-some [m (profile-id (censusMode (str (nth person 6))))]
                                [d i m [(get age-groups (first person) "Unknown age") (second person) (contains? outbound i)]]))
                            (take (get-in atlas ["das" da "private"]) roster))))
                       indices))
                 {:keys [before target people]} (fit/fit-area donors reference (Random. (+ seed 1100 area)))
                 outside-modes (int-array (count profileModes))]
             (doseq [[d members] (group-by first people)]
               (let [outside (into #{} (map first) (assignments d))]
                 (aset local-only d
                       (into {} (for [[_ i m] members :when (outside i)]
                                  (do (aset-int outside-modes m (inc (aget outside-modes m))) [i (simulation-id m)]))))))
             {:donors donors :outside (vec outside-modes) :census reference :before before :fitted target
              :covered (count profiles) :das (count indices)}))
         (range) areas)
        outside (mapv #(fit/broad-modes (:outside %)) local-fits)
        totals (mapv #(fit/broad-modes (:fitted %)) local-fits)
        categories ["Car driver" "Car passenger" "Public transit" "Walking or bicycle" "Other"]
        goal (fit/apportion (mapv observed categories) (reduce + (mapcat identity outside)))
        targets (fit/external-targets outside totals goal)
        fit-reports
        (mapv (fn [area {:keys [donors fitted outside] :as local} target]
                (let [jobs (group-by #(peek (peek %)) donors)
                      external (fit/split-active target outside fitted)
                      rng (Random. (+ seed 3100 area))
                      balance (fn [workers quotas]
                                (:people (fit/fit-area workers quotas rng)))
                      rows (concat (balance (jobs true) external)
                                   (balance (jobs false) (mapv - fitted external)))]
                  (doseq [[d members] (group-by first rows)]
                    (aset by-da d (mapv (fn [[_ i m]] [i (simulation-id m)]) (sort-by second members))))
                  (assoc (dissoc local :donors :outside) :external external)))
              (range) local-fits targets)]
    {:assignments (mapv vec by-da) :localOnly local-only :areas fit-reports :externalTarget goal}))

(defn- leg-distances [places routes from to]
  (when (and (<= 0 from) (<= 0 to))
    (let [[x y] (places from) [u v] (places to)]
      [(Math/hypot (- x u) (- y v))
       (if (= from to) 0.0 (get (:walk routes) [(min from to) (max from to)] Double/POSITIVE_INFINITY))
       (if (= from to) 0.0 (get (:bike routes) [from to] Double/POSITIVE_INFINITY))])))

(defn- travel-budget-fit [atlas-dir day-dir day area-of places routes direct assignments local-rows modes speeds seed]
  (let [walk (.indexOf modes "Walking") bike (.indexOf modes "Bicycle")
        groups (java.util.HashMap.)]
    (doseq [[d da workers] (map vector (range) (get day "das") local-rows) :when (seq workers)]
      (let [outside (into #{} (map first) (assignments d))
            people (get (read-data (io/file atlas-dir (str da ".json"))) "people")
            plans (get (read-data (io/file day-dir (str da ".json"))) "plans")]
        (doseq [[i fitted] workers :when (not (outside i))
                :let [p (people i) tpl (peek p) legs (direct tpl) plan (plans i)]
                :when (and (seq legs) (every? (fn [[_ _ _ a b]] (<= 0 (min (plan a) (plan b)))) legs))]
          (let [group [(area-of da) tpl (get age-groups (first p) "Unknown age") (second p)]
                misses (reduce (fn [[w c] [_ dur _ a b]]
                                 (let [[line path ride] (leg-distances places routes (plan a) (plan b))]
                                   [(if (> path (* dur (speeds "Walking"))) (inc w) w)
                                    (if (> ride (* dur (speeds "Bicycle"))) (inc c) c)])) [0 0] legs)]
            (.put groups group (conj (.getOrDefault groups group []) [[d i] fitted (first misses) (second misses)]))))))
    (let [rng (Random. (+ 5700 seed))]
      (into {} (mapcat (fn [[_ rows]] (fit/assign-travel-budgets rows walk bike rng)) (sort-by key groups))))))

(defn- local-replay [atlas-dir day-dir report input]
  (let [day (read-data (io/file day-dir "day.json")) atlas (read-data (io/file atlas-dir "atlas.json"))
        {:strs [areas das templates]} day
        {:keys [modes assignments directStarts]} report
        {local-rows :assignments fit-areas :areas :keys [localOnly externalTarget]} (fit-neighbourhoods atlas-dir day atlas assignments input)
        n (count areas) downtown (.indexOf areas "Downtown") k (count modes)
        area-of (into {} (for [[a ds] (get atlas "areas") da (get ds "das")] [da (.indexOf areas a)]))
        places (read-data (io/file day-dir "places.json"))
        direct (mapv (fn [template starts]
                       (let [starts (set starts)]
                         (filterv #(starts (first %)) (get template "parts")))) templates directStarts)
        modes-by-key (get input "modeIndex")
        delta (int-array (* 24 n 2 k))
        examples (object-array (* 2 n)) seen (int-array (* 2 n)) rng (Random. (+ 2200 (get input "seed")))
        paired (atom {}) only-paired (atom {}) stock (int-array k) changes (int-array 2)
        speeds (get input "activeSpeeds") distances (atom {}) budgets (atom {})
        routes (into {} (for [[mode field] [[:walk "walkDistances"] [:bike "bikeDistances"]]]
                          [mode (into {} (for [[a b metres] (get input field)] [[a b] metres]))]))
        changes-by-id (travel-budget-fit atlas-dir day-dir day area-of places routes direct assignments local-rows modes speeds (get input "seed"))
        final-rows (mapv (fn [d workers] (mapv (fn [[i m]] [i (get changes-by-id [d i] m)]) workers)) (range) local-rows)]
    (doseq [[d da workers] (map vector (range) das local-rows) :when (seq workers)]
      (let [area (area-of da)
            roster (get (read-data (io/file atlas-dir (str da ".json"))) "people")
            plans (get (read-data (io/file day-dir (str da ".json"))) "plans")
            outside (into #{} (map first) (assignments d))]
        (doseq [[i marginal] workers]
          (let [fitted (get changes-by-id [d i] marginal) person (roster i) plan (plans i) t (peek person) legs (direct t)
                external? (contains? outside i) slots (get (templates t) "slots")
                home-start? (fn [slot] (= "home" (slots slot)))
                zone (fn [slot] (if (and external? (not (home-start? slot))) n (get (get places (plan slot)) 2 -1)))
                original-name ((get input "censusMode") (str (nth person 6)))]
            (when (not= original-name (modes fitted))
              (aset-int changes 0 (inc (aget changes 0))))
            (when external?
              (aset-int stock fitted (inc (aget stock fitted)))
              (when (some #(home-start? (nth % 3)) legs)
                (doseq [age ["All ages" (get age-groups (first person) "Unknown age")]]
                  (swap! paired update-in [age (modes fitted)] (fnil inc 0))
                  (swap! only-paired update-in [age (modes (get (aget localOnly d) i))] (fnil inc 0)))))
            (doseq [[start dur mode a b] legs
                    :let [recorded (get modes-by-key mode (get modes-by-key "other"))]]
              (when-not external?
                (when-let [[line path ride] (leg-distances places routes (plan a) (plan b))]
                  (doseq [[rule m] [[:diary recorded] [:marginal marginal] [:fitted fitted]]
                          :let [label (modes m) speed (get speeds label)] :when speed
                          [counts metres] [[distances line] [budgets (if (= label "Walking") path ride)]]]
                    (swap! counts update-in [area rule label]
                           (fn [[trips over]] [(inc (or trips 0)) (+ (or over 0) (if (> metres (* dur speed)) 1 0))])))))
              (when (not= fitted recorded)
                (aset-int changes 1 (inc (aget changes 1)))
                (when-not external?
                  (when-let [[line path ride] (leg-distances places routes (plan a) (plan b))]
                    (let [label (modes fitted) metre-limit (when-let [v (speeds label)] (* dur v))
                          walking? (= label "Walking") index (if walking? area (+ n area))]
                      (when (and metre-limit (pos? line) (<= (if walking? path ride) metre-limit))
                        (aset-int seen index (inc (aget seen index)))
                        (when (zero? (.nextInt rng (aget seen index)))
                          (aset examples index [da i (+ start (quot dur 2))]))))))
                (doseq [change (usual-flow-changes [start dur recorded (crossing (zone a) (zone b) downtown)] fitted)]
                  (add-flow! delta n k area change))))))))
    {:rows final-rows
     :report {:modes (get input "profileModes") :areas fit-areas :pairedByAge @paired :localOnlyByAge @only-paired
              :externalTarget externalTarget :externalStock (vec stock)
              :activeSpeeds speeds :streets (get input "streets") :cycling (get input "cycling") :budgetChanges (count changes-by-id)
              :budgetCheck (mapv #(get @budgets % {}) (range n)) :distanceCheck (mapv #(get @distances % {}) (range n))
              :changedWorkers (aget changes 0) :changedLegs (aget changes 1)
              :examples (subvec (vec examples) 0 n) :bikeExamples (subvec (vec examples) n)
              :delta (hourly-table delta n k)}}))

(defn -main [input-path atlas-dir day-dir output backend]
  (let [input (read-data input-path)
        {:keys [assignments] :as allocation} (assign input)
        report (merge (dissoc allocation :assignments) (replay atlas-dir day-dir assignments input backend)
                      {:seed (get input "seed") :usualWithin (get input "inside") :atlas (.getName (io/file atlas-dir))
                       :day (.getName (io/file day-dir)) :ambiguousHouseholds (get input "ambiguous")
                       :fallbackMargins (count (filter nil? (mapcat identity (get input "local"))))
                       :destinations (mapv #(get % "work") (get input "destinations"))})
        local (local-replay atlas-dir day-dir report input)]
    (write-data! (io/file output "assignments.json") (:assignments report))
    (write-data! (io/file output "local-modes.json") (:rows local))
    (write-data! (io/file output "report.json") (assoc (dissoc report :assignments) :neighbourhoodFit (:report local))))
  (shutdown-agents))
