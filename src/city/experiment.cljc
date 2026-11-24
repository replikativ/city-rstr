(ns city.experiment
  "Datahike transactions and queries for release-scoped city experiments."
  (:require [#?(:clj clojure.edn :cljs cljs.reader) :as edn]
            [city.opening-hours :as hours]
            [datahike.api :as d]))

(defn- attr [ident type]
  {:db/ident ident :db/valueType type :db/cardinality :db.cardinality/one})

(def schema
  (into [(assoc (attr :entity/ext-id :db.type/string) :db/unique :db.unique/identity)
         (assoc (attr :run/manifest :db.type/string) :db/maxLength 1048576)
         (assoc (attr :trip/diary :db.type/long) :db/cardinality :db.cardinality/many)
         (assoc (attr :experiment/shop-actions :db.type/ref) :db/cardinality :db.cardinality/many)]
        (mapcat (fn [[type attrs]] (map #(attr % type) attrs)))
        [[:db.type/string [:run/city :run/atlas :run/day :run/streets :run/clock :run/workplaces :run/rule
                           :run/market :run/local-walk :run/purchase :run/shopping-outings :run/joint-day :run/incoming-transit :run/outbound-road :run/outbound-transit :shop/code :shop/address :shop/name :experiment/hours :action/hours :resident/da :visit/previous
                           :scenario/key :scenario/label :outcome/district :run/release :run/coverage :run/label :run/transit :run/cycling :run/tours :visit/mode :trip/source :trip/zone :trip/mode :trip/purpose]]
         [:db.type/ref [:scenario/run :outcome/scenario :experiment/run :experiment/shop :visit/experiment :visit/resident :visit/previous-shop
                        :action/shop :trip/release :trip/example]]
         [:db.type/long [:run/population :run/inbound :run/matched-census-areas :experiment/saved
                         :experiment/activated :action/minute :resident/position :visit/start :visit/slot :trip/adult-fifths :trip/minute]]
         [:db.type/double [:outcome/annual-eur-mean :outcome/annual-eur-q05 :outcome/annual-eur-q95 :experiment/basket]]]))

(defn openings [db city]
  (d/q '[:find ?id ?address ?hours ?saved ?rule ?clock ?basket ?workplaces ?purchase ?local ?activation ?outings ?joint
         :in $ ?city
         :where [?x :entity/ext-id ?id] [?x :experiment/run ?r] [?r :run/city ?city]
                [?x :experiment/shop ?s] [?s :shop/address ?address]
                [?x :experiment/hours ?hours] [?x :experiment/saved ?saved] [?r :run/rule ?rule]
                [(get-else $ ?r :run/clock "") ?clock] [(get-else $ ?x :experiment/basket -1) ?basket]
                [(get-else $ ?r :run/workplaces "") ?workplaces] [(get-else $ ?r :run/local-walk "") ?local]
                [(get-else $ ?r :run/purchase "fixed") ?purchase]
                [(get-else $ ?x :experiment/activated -1) ?activation]
                [(get-else $ ?r :run/shopping-outings "") ?outings]
                [(get-else $ ?r :run/joint-day "") ?joint]]
       db city))

(defn- scheduled-opening? [hours minute]
  (and (hours/activation-minute? minute)
       (when-let [shift (hours/schedule hours)] (hours/admits? shift minute 1))))

(defn- canonical-openings [site hours activated openings]
  (when openings
    (when-not (and (sequential? openings)
                   (every? (fn [row]
                             (and (vector? row) (= 3 (count row))
                                  (string? (row 0)) (seq (row 0))
                                  (scheduled-opening? (row 1) (row 2))))
                           openings)
                   (= (count openings) (count (set (map first openings))))
                   (some #{[site hours activated]} openings))
      (throw (ex-info "The saved market must include the selected storefront and its opening time." {:site site})))
    (when (< 1 (count openings)) (sort-by first openings))))

(defn transaction [snapshot saved]
  (let [{:strs [city atlas day streets clock workplaces cycling tours purchase localWalk shoppingOutings jointRun rule market site address hours basket visits activated openings]}
        snapshot
        _ (when (some? activated)
            (when-not (and (scheduled-opening? hours activated)
                           (every? #(<= activated (nth % 3)) visits))
              (throw (ex-info "The opening and visits must follow the simulated clock." {:activated activated}))))
        actions (canonical-openings site hours activated openings)
        run-id (cond-> (str "run/" city "/" market "/" rule)
                 jointRun (str "/weekday/" jointRun))
        shop-id #(str "shop/" city "/" market "/" %)
        site-id (shop-id site)
        id (str "opening/" city "/" market "/" rule "/" site "/" hours "/" (or basket "-")
                (when jointRun (str "/weekday/" jointRun))
                (when (some? activated) (str "/opened/" activated))
                (when actions (str "/actions/" (pr-str (vec actions)))))
        action-id #(str id "/action/" %)
        run (cond-> {:entity/ext-id run-id :run/city city :run/atlas atlas :run/day day
                     :run/streets streets :run/rule rule :run/market market}
              localWalk (assoc :run/local-walk localWalk)
              shoppingOutings (assoc :run/shopping-outings shoppingOutings)
              jointRun (assoc :run/joint-day jointRun)
              purchase (assoc :run/purchase purchase)
              clock (assoc :run/clock clock)
              cycling (assoc :run/cycling cycling)
              tours (assoc :run/tours tours)
              workplaces (assoc :run/workplaces workplaces))
        opening (cond-> {:entity/ext-id id :experiment/shop [:entity/ext-id site-id]
                         :experiment/run [:entity/ext-id run-id] :experiment/hours hours
                         :experiment/saved saved}
                  (some? basket) (assoc :experiment/basket (double basket))
                  (some? activated) (assoc :experiment/activated activated)
                  actions (assoc :experiment/shop-actions (mapv (fn [[code]] [:entity/ext-id (action-id code)]) actions)))
        action-tx (mapcat (fn [[code shift minute]]
                            [{:entity/ext-id (shop-id code) :shop/code code}
                             {:entity/ext-id (action-id code) :action/shop [:entity/ext-id (shop-id code)]
                              :action/hours shift :action/minute minute}])
                          actions)
        tx (into (conj (into [run {:entity/ext-id site-id :shop/code site :shop/address address}] action-tx) opening)
                 (mapcat (fn [[home-area i slot start previous previous-code mode]]
                           (let [person (str "resident/" city "/" atlas "/" home-area "/" i)
                                 prior (when previous-code (str "grocer/" city "/" market "/" previous-code))]
                             (cond-> [{:entity/ext-id person :resident/da home-area :resident/position i}]
                               prior (conj {:entity/ext-id prior :shop/code (str previous-code) :shop/name previous})
                               true (conj (cond-> {:entity/ext-id (str id "/visit/" home-area "/" i "/" slot)
                                                  :visit/slot slot :visit/start start :visit/previous previous :visit/mode (or mode "walk")
                                                  :visit/experiment [:entity/ext-id id] :visit/resident [:entity/ext-id person]}
                                            prior (assoc :visit/previous-shop [:entity/ext-id prior])))))))
                 visits)]
    [id tx]))

(def opening-fields
  [:db/id :entity/ext-id :experiment/hours :experiment/basket :experiment/saved :experiment/activated
   {:experiment/shop-actions [:action/hours :action/minute {:action/shop [:shop/code]}]}
   {:experiment/run [:run/city :run/atlas :run/day :run/streets :run/market :run/rule
                     :run/clock :run/cycling :run/tours :run/workplaces :run/local-walk :run/purchase
                     :run/shopping-outings :run/joint-day]}
   {:experiment/shop [:shop/code :shop/address]}])

(defn- opening-summary [entity]
  (let [{:experiment/keys [hours basket saved shop run activated shop-actions]} entity
        {:run/keys [city atlas day streets market rule clock cycling tours workplaces purchase local-walk shopping-outings joint-day]} run]
    (cond-> {:city city :atlas atlas :day day :streets streets :market market :rule rule
     :clock clock :cycling cycling :tours tours :localWalk local-walk :purchase purchase :workplaces workplaces :hours hours
             :site (:shop/code shop) :address (:shop/address shop) :basket basket :saved saved :activated activated}
      shopping-outings (assoc :shoppingOutings shopping-outings)
      joint-day (assoc :jointRun joint-day)
      (seq shop-actions) (assoc :openings (->> shop-actions
                                              (map (fn [{:action/keys [shop hours minute]}] [(:shop/code shop) hours minute]))
                                              (sort-by first) vec)))))

(defn saved-summaries [db]
  (let [counts (into {} (map (fn [[eid visits residents]] [eid [visits residents]]))
                     (d/q '[:find ?e (count ?v) (count-distinct ?p)
                            :where [?v :visit/experiment ?e] [?v :visit/resident ?p]] db))
        diverted (into {} (d/q '[:find ?e (count ?v) :where [?v :visit/experiment ?e]
                                 [?v :visit/previous ?prior] [(!= ?prior "")]] db))]
    (for [x (d/q '[:find [(pull ?x pattern) ...] :in $ pattern :where [?x :experiment/run _]]
                  db opening-fields)
          :let [eid (:db/id x) [visits residents] (get counts eid [0 0])]]
      (assoc (opening-summary x) :visit-count visits :resident-count residents :diverted (get diverted eid 0)))))

(defn- scenario-entities [run-id {:keys [key label districts]}]
  (let [id (str run-id "/scenario/" key)]
    (into [{:entity/ext-id id :scenario/key key :scenario/label label :scenario/run [:entity/ext-id run-id]}]
          (for [[district mean q05 q95] districts]
            {:entity/ext-id (str id "/district/" district) :outcome/scenario [:entity/ext-id id]
             :outcome/district district :outcome/annual-eur-mean (double mean)
             :outcome/annual-eur-q05 (double q05) :outcome/annual-eur-q95 (double q95)}))))

(defn register-runs [db runs]
  (into []
        (mapcat (fn [{:keys [city release label coverage population inbound matchedCensusAreas atlas day streets transit scenarios jointRun incomingTransit outboundRoad outboundTransit] :as manifest}]
                  (let [id (str "weekday/" city "/" release)
                        indexed (d/entity db [:entity/ext-id id])
                        stored (:run/manifest indexed)]
                    (cond
                      stored (when-not (= manifest (edn/read-string stored))
                               (throw (ex-info "Conflicting published release" {:id id})))
                      indexed [{:entity/ext-id id :run/manifest (pr-str manifest)}]
                      :else
                      (into [(cond-> {:entity/ext-id id :run/manifest (pr-str manifest) :run/city city :run/release release :run/label label
                                      :run/coverage coverage :run/population population}
                               inbound (assoc :run/inbound inbound)
                               matchedCensusAreas (assoc :run/matched-census-areas matchedCensusAreas)
                               atlas (assoc :run/atlas atlas)
                               day (assoc :run/day day)
                               streets (assoc :run/streets streets)
                               transit (assoc :run/transit transit)
                               jointRun (assoc :run/joint-day jointRun)
                               incomingTransit (assoc :run/incoming-transit incomingTransit)
                               outboundRoad (assoc :run/outbound-road outboundRoad)
                               outboundTransit (assoc :run/outbound-transit outboundTransit))]
                            (mapcat #(scenario-entities id %) scenarios))))))
        runs))

(defn release-manifest
  "Read a complete pinned input manifest as detached values."
  [db city release]
  (some-> (d/entity db [:entity/ext-id (str "weekday/" city "/" release)])
          :run/manifest edn/read-string))

(defn published-runs [db]
  (let [outcomes (group-by first
                   (d/q '[:find ?release ?key ?label ?district ?mean ?q05 ?q95
                          :where [?r :run/release ?release] [?s :scenario/run ?r]
                                 [?s :scenario/key ?key] [?s :scenario/label ?label] [?o :outcome/scenario ?s]
                                 [?o :outcome/district ?district] [?o :outcome/annual-eur-mean ?mean]
                                 [?o :outcome/annual-eur-q05 ?q05] [?o :outcome/annual-eur-q95 ?q95]] db))]
    (for [[city release label coverage population inbound matched joint incoming outbound outbound-transit]
          (d/q '[:find ?city ?release ?label ?coverage ?population ?inbound ?matched ?joint ?incoming ?outbound ?outbound-transit
                 :where [?r :run/release ?release] [?r :run/city ?city] [?r :run/label ?label]
                        [?r :run/coverage ?coverage] [?r :run/population ?population]
                        [(get-else $ ?r :run/inbound 0) ?inbound]
                        [(get-else $ ?r :run/matched-census-areas 0) ?matched]
                        [(get-else $ ?r :run/joint-day "") ?joint]
                        [(get-else $ ?r :run/incoming-transit "") ?incoming]
                        [(get-else $ ?r :run/outbound-road "") ?outbound]
                        [(get-else $ ?r :run/outbound-transit "") ?outbound-transit]] db)]
      (cond-> {:city city :release release :label label :coverage coverage :population population :inbound inbound
               :matchedCensusAreas (when (pos? matched) matched)
               :scenarios (for [[k rows] (sort-by first (group-by second (outcomes release)))]
                            {:key k :label (nth (first rows) 2)
                             :districts (sort-by first (map #(subvec % 3) rows))})}
        (seq joint) (assoc :jointRun joint)
        (seq incoming) (assoc :incomingTransit incoming)
        (seq outbound) (assoc :outboundRoad outbound)
        (seq outbound-transit) (assoc :outboundTransit outbound-transit)))))

(defn opening [db id]
  (let [entity (d/pull db opening-fields [:entity/ext-id id])]
    (when-not (:experiment/run entity)
      (throw (ex-info "This opening could not be found in the local database." {:id id})))
    (assoc (opening-summary entity)
           :visits (sort-by (juxt #(nth % 3) first second)
               (map (fn [row] (if (= "walk" (peek row)) (pop row) row))
                (d/q '[:find ?da ?i ?slot ?start ?prior ?mode :in $ ?id
                      :where [?x :entity/ext-id ?id] [?v :visit/experiment ?x] [?v :visit/resident ?p]
                             [?p :resident/da ?da] [?p :resident/position ?i] [?v :visit/slot ?slot]
                             [?v :visit/start ?start] [?v :visit/previous ?prior]
                             [(get-else $ ?v :visit/mode "walk") ?mode]] db id))))))
