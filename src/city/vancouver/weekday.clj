(ns city.vancouver.weekday
  "Age-standardised weekday activity budgets and a respondent-disjoint scorecard.
   The fitted model is a weighted mixture of intact urban BC diaries in each age band."
  (:require [city.synth.sampling :refer [effective-count shuffled]]
            [city.synth.timeuse :as timeuse]
            [city.vancouver.household :as household]
            [city.vancouver.shopping :as shopping]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util Random]))

;; 2021 Census Profile characteristic IDs. 29 already includes ages 85 and over.
(def census-age-ids
  {:a15-24 [14 15], :a25-34 [16 17], :a35-44 [18 19], :a45-54 [20 21]
   :a55-64 [22 23], :a65-74 [25 26], :a75+ [27 28 29]})

(defn- age-counts [m dauid]
  (let [census-count (fn [id]
                       (let [n (first (get m (str id)))]
                         (when-not (and (number? n) (<= 0 n) (== n (long n)))
                           (throw (ex-info "Unavailable census age count" {:dauid dauid :id id :value n})))
                         (long n)))]
    (update-vals census-age-ids #(reduce + (map census-count %)))))

(defn census-population [file]
  (with-open [reader (io/reader file)]
    (let [rows
          (reduce
           (fn [areas line]
             (let [{:strs [local_area dauid m]} (json/read-str line)]
               (when (or (not (seq dauid)) (not (seq local_area)) (contains? areas dauid))
                 (throw (ex-info "Missing geography or duplicate dissemination area" {:dauid dauid})))
               (assoc areas dauid {:area local_area :population (age-counts m dauid)})))
           {} (line-seq reader))]
      (when (empty? rows) (throw (ex-info "Empty census extract" {:file (str file)})))
      (into (sorted-map)
            (for [[area ds] (assoc (group-by :area (vals rows)) "City of Vancouver" (vals rows))]
              [area {:areas (count ds) :age-counts (apply merge-with + (map :population ds))}])))))

(defn- checked-diary [[id {:keys [weight chain] :as diary}]]
  (let [episodes (vec (sort-by :start chain))]
    (when-not (and (number? weight) (Double/isFinite weight) (pos? weight)
                   (= 240 (:start (first episodes)))
                   (every? #(and (integer? (:dur %)) (pos? (:dur %))) episodes)
                   (= (map #(+ (:start %) (:dur %)) episodes)
                      (concat (map :start (rest episodes)) [1680])))
      (throw (ex-info "Expected a weighted diary covering 04:00 to 04:00" {:id id})))
    (assoc diary :chain episodes)))

(defn split-diaries
  "Fix one in five respondents within each age group as holdout. Sort IDs before
   shuffling so file or map iteration order cannot change the split or a seeded draw."
  [diaries]
  (into (sorted-map)
        (for [[age entries] (group-by #(second (:type (val %))) diaries)]
          (let [ordered (shuffled (Random. 2023) (sort-by key entries))]
            [age (reduce (fn [pool [i entry]]
                           (update pool (if (zero? (mod i 5)) :holdout :fit) conj (checked-diary entry)))
                         {:fit [] :holdout []}
                         (map-indexed vector ordered))]))))

(defn- effective-n [ds]
  (effective-count (map :weight ds)))

(defn- household-pool [ds child?]
  (let [donors (when (boolean? child?) (filterv #(= child? (:child-under-15? %)) ds))
        n (effective-n donors)]
    {:donors donors :effective-n n :share (/ n (+ n 5.0))}))

(defn draw-weekday
  "Draw an intact training diary. With a known household flag, mix same-age,
   same-status donors with all donors of that age. nil uses the age baseline."
  ([pools age rng] (draw-weekday pools age nil rng))
  ([pools age child? ^Random rng]
   (let [ds (get-in pools [age :fit])]
     (when-not (seq ds) (throw (ex-info "No fitted diaries for age band" {:age age})))
     (let [{:keys [donors share]} (household-pool ds child?)
           ds (if (and (pos? share) (< (.nextDouble rng) share)) donors ds)
           threshold (* (.nextDouble rng) (reduce + (map :weight ds)))]
       (loop [[d & more] ds x threshold]
         (if (or (< x (:weight d)) (empty? more))
           (:chain d)
           (recur more (- x (:weight d)))))))))

(defn- add-episode [minutes weight {:keys [start dur act]}]
  (let [end (+ start dur)]
    (reduce (fn [m hour]
              (let [overlap (- (min end (* 60 (inc hour))) (max start (* 60 hour)))]
                (update m [act (mod hour 24)] (fnil + 0.0) (* weight overlap))))
            minutes (range (quot start 60) (inc (quot (dec end) 60))))))

(defn- diary-means [ds]
  (when-not (seq ds) (throw (ex-info "No respondents in diary sample" {})))
  (let [weights (map :weight ds)
        total (reduce + weights)
        mean (fn [accumulate]
               (let [totals (reduce (fn [m {:keys [weight chain]}]
                                      (reduce #(accumulate %1 weight %2) m chain))
                                    {} ds)]
                 (update-vals totals #(/ % total))))]
    {:diaries (count ds)
     :effective-n (effective-n ds)
     :minutes (mean add-episode)
     :shopping (mean shopping/add-episode)}))

(defn- standardise [means age-counts metric]
  (let [total (reduce + (vals age-counts))]
    (when-not (pos? total) (throw (ex-info "Empty census domain" {})))
    (reduce-kv (fn [m age n]
                 (if (zero? n) m
                     (let [rates (get-in means [age metric])]
                       (when-not rates (throw (ex-info "Missing diary age band" {:age age})))
                       (merge-with + m (update-vals rates #(* % (/ (double n) total)))))))
               {} age-counts)))

(defn- activity-score [fit holdout pooled {:keys [areas age-counts]}]
  (let [model (standardise fit age-counts :minutes)
        observed (standardise holdout age-counts :minutes)]
    {:dissemination-areas areas
     :rounded-census-residents-15-plus (reduce + (vals age-counts))
     :shopping-per-resident-weekday
     {:age-only (shopping/per-day (standardise fit age-counts :shopping))
      :holdout (shopping/per-day (standardise holdout age-counts :shopping))}
     :minutes-per-resident-weekday
     (into (sorted-map)
           (for [act (conj (set (vals timeuse/activity-classes)) :unknown)
                 :let [hours (fn [m] (mapv #(get m [act %] 0.0) (range 24)))
                       model-hours (hours model)
                       holdout-hours (hours observed)
                       predicted (reduce + model-hours)
                       reference (reduce + holdout-hours)]]
             [act {:model predicted :holdout reference :error (- predicted reference)
                   :age-blind-error (- (reduce + (hours pooled)) reference)
                   :model-by-clock-hour model-hours :holdout-by-clock-hour holdout-hours}]))}))

(defn weekday-baseline [population pools]
  (let [fit (update-vals pools #(diary-means (:fit %)))
        held (update-vals pools #(diary-means (:holdout %)))
        pooled (:minutes (diary-means (mapcat :fit (vals pools))))]
    {:respondents-by-age
     (into (sorted-map) (for [age (keys pools)]
                          [age {:fit (select-keys (fit age) [:diaries :effective-n]) :holdout (select-keys (held age) [:diaries :effective-n])}]))
     :areas (update-vals population #(activity-score fit held pooled %))}))

(defn- daily-minutes [hourly]
  (reduce-kv (fn [m [act _] v] (update m act (fnil + 0.0) v)) {} hourly))

(defn- mix-rates [a b share-b]
  (merge-with + (update-vals a #(* (- 1.0 share-b) %)) (update-vals b #(* share-b %))))

(defn- household-fit [{:keys [fit holdout]}]
  (let [age-means (diary-means fit)
        age-mean (:minutes age-means)]
    (into {:age-only {:minutes (daily-minutes age-mean)}}
          (for [[group status] [[:with-child true] [:without-child false]]
                :let [{:keys [share donors effective-n]} (household-pool fit status)
                      sub-means (when (seq donors) (diary-means donors))
                      hourly (mix-rates age-mean (:minutes sub-means) share)]]
            [group {:fit (count donors) :holdout (count (filter #(= status (:child-under-15? %)) holdout))
                    :effective-n effective-n :share share
                    :minutes (daily-minutes hourly) :hourly hourly
                    :shopping (mix-rates (:shopping age-means) (:shopping sub-means) share)}]))))

(defn- prediction-errors [fits pools activity]
  (let [rows (for [[age {:keys [holdout]}] pools, diary holdout
                   :let [group (case (:child-under-15? diary) true :with-child false :without-child :age-only)
                         actual (reduce + (for [{:keys [act dur]} (:chain diary) :when (= act activity)] dur))
                         error (fn [g] (- (get-in fits [age g :minutes activity] 0.0) actual))]]
               [(:weight diary) (error :age-only) (error group)])
        total (reduce + (map first rows))
        rmse (fn [index]
               (Math/sqrt (/ (reduce + (for [r rows :let [e (nth r index)]] (* (first r) e e))) total)))]
    {:age-only-rmse (rmse 1) :household-rmse (rmse 2)}))

(defn- household-projection [population fits metro metric format-rates]
  (let [means (reduce-kv
               (fn [m age fit]
                 (let [share (get-in metro [age :share-with-child])]
                   (when-not (number? share)
                     (throw (ex-info "Missing metro share" {:age age})))
                   (assoc m age {metric (mix-rates (get-in fit [:without-child metric])
                                                   (get-in fit [:with-child metric]) share)})))
               {} fits)]
    (update-vals population
                 (fn [{:keys [age-counts]}]
                   (format-rates (standardise means age-counts metric))))))

(defn- by-clock-hour [hours]
  (into {} (for [[act daily] (daily-minutes hours)]
             [act {:total daily :by-clock-hour (mapv #(get hours [act %] 0.0) (range 24))}])))

(defn household-comparison [population pools metro]
  (let [fits (update-vals pools household-fit)]
    (cond->
     {:urban-bc-holdout-rmse-minutes
      (into {} (for [act [:childcare :paid-work :travel :shopping]]
                 [act (prediction-errors fits pools act)]))
      :fit-by-age (update-vals fits #(update-vals % (fn [fit] (dissoc fit :hourly :shopping))))
      :vancouver-cma-person-weights-by-age metro}
      metro (assoc :projected-minutes-per-resident-weekday (household-projection population fits metro :hourly by-clock-hour)
                  :projected-shopping-per-resident-weekday (household-projection population fits metro :shopping shopping/per-day)))))

(defn scorecard [project-root]
  (let [derived (io/file project-root "data" "derived")
        population (census-population (io/file derived "vancouver_da_marginals.jsonl"))
        pools (split-diaries (timeuse/load-diaries :project-root project-root))
        pumf (io/file project-root "data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv")
        metro (when (.isFile pumf) (household/metro-composition pumf))
        studies (get (json/read-str (slurp (io/file derived "vancouver_ped_counts_mp.json"))) "counts")]
    (assoc (weekday-baseline population pools)
           :household-model (household-comparison population pools metro)
           :sources {:household "2021 Census hierarchical PUMF, Vancouver CMA 933, person-weighted household roster ages 0–14"
                     :population "2021 Census Profile, Vancouver dissemination areas, rounded age counts"
                     :diaries "Statistics Canada Time Use Survey 2022, urban BC respondents aged 15+, weekdays"
                     :holdout "One in five urban BC respondents by age, standardised to the same census population"}
           :pending {:pedestrian-crossings {:sites (count (set (map #(get % "site") studies)))
                                           :needs "The separate walking replay verifies four sites. Remaining studies need workbook verification and matched routes."}
                     :grocery-entries {:needs "Store entry or transaction observations and dated opening hours"}})))

(defn -main [& args]
  (when (> (count args) 1)
    (throw (ex-info "Usage: clojure -M -m city.vancouver.weekday [project-root]" {})))
  (json/write (scorecard (or (first args) ".")) *out*)
  (newline))
