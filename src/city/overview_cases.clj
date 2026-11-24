(ns city.overview-cases
  "Normalize published scenario outcomes for the shared map."
  (:require [city.build-inputs :as inputs]
            [city.opening-hours :as hours]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- read-json [file]
  (with-open [r (io/reader file)] (json/read r :key-fn keyword)))

(defn- stuttgart-shops [features reports]
  ;; Older revenue releases omitted firm IDs. Match only unique observations
  ;; across both tables, including the sampled visit count for collocated shops.
  (let [records (vals (into {} (for [r reports v (get-in r [:visits :venues])]
                                 [(:firm v) v])))
        visit-key (fn [v] [[(:lon v) (:lat v)] (:category v) (:baseline-day v)])
        revenue-key (fn [{:keys [geometry properties]}]
                      [(:coordinates geometry) (:category properties) (reduce + (:visits properties))])
        firms (group-by visit-key records)
        counts (frequencies (map revenue-key features))
        baseline (map-indexed
                  (fn [i {:keys [properties geometry] :as f}]
                    (let [k (revenue-key f) matches (firms k)
                          firm (or (:firm properties)
                                   (when (= 1 (counts k) (count matches)) (:firm (first matches))))]
                      [(if firm (str "firm-" firm) (str "baseline-" i))
                       (:label properties) (:coordinates geometry) (reduce + (:revenue-eur-year properties))]))
                  features)
        outcomes (for [r reports v (:venues r)]
                   [(str "firm-" (:firm v)) (if (= (:firm v) (get-in r [:opened :firm]))
                                              (get-in r [:opened :name]) (:label v))
                    [(:lon v) (:lat v)] (when (= (:firm v) (get-in r [:opened :firm])) 0)])]
    (vals (into (sorted-map) (map (juxt first identity)) (concat (for [v records] [(str "firm-" (:firm v)) (:label v) [(:lon v) (:lat v)] nil])
                                                                outcomes baseline)))))

(defn- stuttgart [root {:keys [release scenarios]}]
  (let [dir (io/file root "stuttgart" release)
        districts (read-json (io/file dir "areas-stadtbezirk.json"))
        names (mapv #(get-in % [:properties :name]) (:features districts))
        geo (assoc districts :features
                   (mapv (fn [i f] (assoc f :id i :properties {:label (names i)})) (range) (:features districts)))
        reports (mapv #(read-json (io/file dir (str "scenario-" (:key %) ".json"))) scenarios)
        shops (stuttgart-shops (:features (read-json (io/file dir "revenue.json"))) reports)
        common {:geometry geo :areas names :venueUnit "€/year"
                :baselineLabel "Revenue, sampled weekday × 365"}
        baseline (into {} (for [d (:districts (first reports))] [(:district d) (reduce + (:baseline d))]))]
    (conj
     (mapv (fn [{:keys [key label districts]} report]
             (let [by-name (into {} (map (juxt first rest) districts))
                   values (mapv #(or (by-name %) (throw (ex-info "Missing district" {:name %}))) names)
                   changes (into {} (for [v (:venues report)] [(str "firm-" (:firm v)) (:delta-total v)]))]
               (merge common
                      {:label label :unit "€/year change in district spending"
                       :venues (mapv (fn [shop] (into shop ((juxt :mean :q05 :q95) (changes (first shop))))) shops)
                       :hourlyVisits (into {} (for [v (get-in report [:visits :venues])]
                                               [(str "firm-" (:firm v)) (:delta-hours v)]))
                       :roles (into {} (for [v (:venues report)] [(str "firm-" (:firm v)) (:role v)]))
                       :changeLabel "Expected spending change" :values [(mapv first values)]
                       :low (mapv second values) :high (mapv last values) :query {:scenario key :view "scenario"}})))
           scenarios reports)
     (merge common {:label "Baseline retail revenue" :venues shops :unit "€/year expected district spending"
                    :values [(mapv baseline names)] :query {:view "economy"}}))))

(defn- grocery-shop [store proposed? baseline change]
  (let [[x y] (:point store)]
    [(str (if proposed? "site-" "store-") (:id store)) (:name store)
     [(- (/ x 72600.0) 123.1) (- 49.26 (/ y 111195.0))] baseline change]))

(defn- vancouver [root {:keys [atlas day coverage streets]} {:keys [policy market]}]
  (let [base (if (= coverage "region") (io/file root "vancouver" "region") (io/file root "vancouver"))
        areas (:areas (read-json (io/file base "cityday" day "day.json")))]
    (concat
     (when policy
       (let [report (read-json policy)]
         (when-not (= [atlas day areas] ((juxt :atlas :day :areas) report))
           (throw (ex-info "Remote-work report has different inputs" {})))
         (mapv (fn [level delta] {:label (str "Remote work · " level "% of eligible workers")
                                  :unit "residents relative to baseline" :values delta :query {:policy level}})
               [50 100] (:delta report))))
     (when market
       (let [catalogue (read-json market)
             site (some #(when (= "3738" (:id %)) %) (:sites catalogue))]
         (when-not (= [atlas day streets] ((juxt :atlas :day :streets) catalogue))
           (throw (ex-info "Grocery catalogue has different parents" {})))
         (when site
           (let [roster (read-json (io/file base "atlas" atlas "atlas.json"))
                 da-list (:das (read-json (io/file base "cityday" day "day.json")))
                 area-of (into {} (for [[area group] (:areas roster) da (:das group)] [da (name area)]))
                 occasions (:occasions catalogue)
                 home (fn [d] (or (area-of (nth da-list d))
                                  (throw (ex-info "Unknown shopper home area" {:district d}))))
                 served (filter #(nat-int? (nth % 5)) occasions)
                 origins (frequencies (map #(home (first %)) served))
                 baseline (frequencies (map #(nth % 5) served))
                 shops (fn [losses total]
                         (conj (mapv (fn [i store]
                                       (grocery-shop store false (get baseline i 0) (- (get losses i 0))))
                                     (range) (:stores catalogue))
                               (grocery-shop site true 0 total)))
                 common (cond-> {:basketCurrency "CAD" :venueUnit "visits/day" :baselineLabel "Baseline walking visits"}
                          (:inventoryCoverage catalogue) (assoc :inventory (:inventoryCoverage catalogue)))]
             (concat
              (for [preset ["full" "short"]
                    :let [schedule (hours/schedule preset)
                          visits (for [[idx _] (:changes site)
                                       :let [[d _ _ start duration incumbent] (nth occasions idx)]
                                       :when (hours/admits? schedule start duration)]
                                   [(home d) incumbent (mod start 1440)])
                          counts (frequencies (map first visits))
                          losses (frequencies (filter nat-int? (map second visits)))
                          diverted (reduce + (vals losses))
                          site-id (str "site-" (:id site))
                          events (vec (sort-by first
                                               (for [[_ incumbent minute] visits]
                                                 [minute (when (nat-int? incumbent)
                                                           (str "store-" (:id (nth (:stores catalogue) incumbent))))])))
                          by-hour (reduce (fn [counts [minute incumbent]]
                                            (let [hour (long (quot minute 60))]
                                            (cond-> (update-in counts [site-id hour] inc)
                                              incumbent (update-in [incumbent hour] dec))))
                                          (zipmap (map first (shops {} 0)) (repeat (vec (repeat 24 0))))
                                          events)]]
                (merge common
                       {:label (str "Open " (:name site) " · " (:label schedule))
                        :unit "opening-site walking visits by home area"
                        :openingSite site-id :visitEvents events :hourlyVisits by-hour :roles {site-id "opened"}
                        :venues (shops losses (count visits)) :changeLabel "Change in walking visits"
                        :summary (str "Shop total · " (count visits) " visits, " diverted
                                      " diverted from existing grocers and " (- (count visits) diverted)
                                      " newly feasible within the diary and store hours.")
                        :values [(mapv #(get counts % 0) areas)] :query {:shop (:id site) :hours preset}}))
              [(merge common {:label "Baseline grocery visits" :unit "incumbent walking visits by home area"
                              :venues (shops {} 0) :values [(mapv #(get origins % 0) areas)]})]))))))))

(defn scenarios
  ([root run]
   (scenarios root run (when (= "vancouver" (:city run)) (inputs/scenario-inputs root run))))
  ([root run inputs]
   (vec (case (:city run)
          "stuttgart" (stuttgart root run)
          "vancouver" (vancouver root run inputs)))))
