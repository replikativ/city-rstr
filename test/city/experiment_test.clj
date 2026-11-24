(ns city.experiment-test
  (:require [clojure.test :refer [deftest is]]
            [city.experiment :as experiment]
            [datahike.api :as d]))

(deftest query-a-saved-opening-and-its-residents
  (let [config {:store {:backend :memory :id (random-uuid)}
                :value-caps :default :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database config)
        conn (d/connect config)
        data {"city" "vancouver" "atlas" "population" "day" "weekday" "streets" "roads" "market" "release"
              "rule" "diary" "site" "4654" "address" "2541 Kingsway" "hours" "full"
              "visits" [["DA-1" 7 1 630 "Grocer" "A"] ["DA-1" 7 3 810 "" nil]]}]
    (try
      (let [[id tx] (experiment/transaction data 1)
            [second-id short] (experiment/transaction (assoc data "hours" "short" "basket" 0 "visits" []) 2)
            [other-id other] (experiment/transaction (assoc data "city" "stuttgart") 3)]
        (doseq [transaction [tx tx short other]] (d/transact conn transaction))
        (let [db @conn saved (experiment/opening db id)]
          (is (= #{id second-id} (set (map first (experiment/openings db "vancouver")))))
          (is (= [other-id] (mapv first (experiment/openings db "stuttgart"))))
          (is (= [["DA-1" 7 1 630 "Grocer"] ["DA-1" 7 3 810 ""]] (:visits saved)))
          (is (nil? (:basket saved)))
          (is (nil? (:purchase saved)))
          (is (= "fixed" (nth (first (experiment/openings db "vancouver")) 8)))
          (is (= 0.0 (:basket (experiment/opening db second-id))))
          (is (empty? (:visits (experiment/opening db second-id))))
          (is (= #{["vancouver" "full" 2 1 1] ["vancouver" "short" 0 0 0] ["stuttgart" "full" 2 1 1]}
                 (set (map (juxt :city :hours :visit-count :resident-count :diverted) (experiment/saved-summaries db)))))
          (is (= #{["A"]} (d/q '[:find ?code :in $ ?id :where
                                   [?x :entity/ext-id ?id] [?v :visit/experiment ?x]
                                   [?v :visit/previous-shop ?s] [?s :shop/code ?code]] db id)))))
      (finally (d/release conn) (d/delete-database config)))))

(deftest market-stores-the-bicycle-run-and-visit-mode
  (let [config {:store {:backend :memory :id (random-uuid)} :value-caps :default
                :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database config) conn (d/connect config)
        [id tx] (experiment/transaction {"city" "vancouver" "atlas" "a" "day" "d" "streets" "s"
                                        "market" "m" "rule" "access" "site" "1" "address" "Shop" "hours" "full"
                                        "cycling" "graph" "tours" "outings" "purchase" "bc2010" "localWalk" "full"
                                        "visits" [["DA" 2 1 600 "" nil "bike"]]} 1)]
    (try
      (d/transact conn tx)
      (let [r (experiment/opening @conn id)]
        (is (= ["graph" "outings" "access" "bc2010"] ((juxt :cycling :tours :rule :purchase) r)))
        (is (= ["bc2010" "full"] ((juxt :purchase :localWalk) (first (experiment/saved-summaries @conn)))))
        (is (= [["DA" 2 1 600 "" "bike"]] (:visits r))))
      (finally (d/release conn) (d/delete-database config)))))

(deftest activations-keep-separate-replays-for-the-same-shift
  (let [config {:store {:backend :memory :id (random-uuid)} :value-caps :default
                :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database config) conn (d/connect config)
        visits [["DA" 2 1 600 "" nil "walk"] ["DA" 4 1 720 "" nil "bike"]]
        scenario {"city" "vancouver" "atlas" "a" "day" "d" "streets" "s"
                  "market" "m" "rule" "diary" "site" "1" "address" "Shop" "hours" "full" "visits" visits}
        [planned before] (experiment/transaction scenario 1)
        [played after] (experiment/transaction (assoc scenario "activated" 690 "visits" (subvec visits 1)) 2)
        openings [["1" "full" 690] ["2" "short" 720]]
        paired (assoc scenario "activated" 690 "visits" [] "openings" openings)
        [paired-id paired-tx] (experiment/transaction paired 3)]
    (try
      (doseq [tx [before after after paired-tx]] (d/transact conn tx))
      (let [saved (experiment/opening @conn played)]
        (is (= 690 (:activated saved)))
        (is (= 1 (count (:visits saved))))
        (is (= openings (:openings (experiment/opening @conn paired-id))))
        (is (= paired-id (first (experiment/transaction (assoc paired "openings" (vec (reverse openings))) 4))))
        (is (= 2 (count (:visits (experiment/opening @conn planned)))))
        (is (= #{-1 690} (set (map #(nth % 10) (experiment/openings @conn "vancouver"))))))
      (is (thrown? clojure.lang.ExceptionInfo
                   (experiment/transaction (assoc scenario "activated" 690) 2)))
      (finally (d/release conn) (d/delete-database config)))))

(deftest fitted-shopping-visit-uses-its-archived-market-and-synthetic-slot
  (let [config {:store {:backend :memory :id (random-uuid)} :value-caps :default
                :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database config)
        conn (d/connect config)
        [id tx] (experiment/transaction
                  {"city" "vancouver" "atlas" "a" "day" "d" "streets" "s"
                   "market" "augmented" "shoppingOutings" "fitted" "rule" "diary"
                   "site" "1" "address" "Shop" "hours" "full"
                   "visits" [["DA" 2 -1 710 "Grocer" "G" "walk"]]} 1)]
    (try
      (d/transact conn tx)
      (is (= "fitted" (nth (first (experiment/openings @conn "vancouver")) 11)))
      (is (= ["augmented" "fitted" [["DA" 2 -1 710 "Grocer"]]]
             ((juxt :market :shoppingOutings :visits) (experiment/opening @conn id))))
      (finally (d/release conn) (d/delete-database config)))))

(deftest a-combined-weekday-opening-retains-its-id-alongside-the-base-market
  (let [config {:store {:backend :memory :id (random-uuid)} :value-caps :default
                :initial-tx experiment/schema :schema-flexibility :write}
        _ (d/create-database config)
        conn (d/connect config)
        snapshot {"city" "vancouver" "atlas" "a" "day" "d" "streets" "s" "market" "m"
                  "rule" "tracts" "site" "1" "address" "Shop" "hours" "full" "visits" []}
        [base-id base] (experiment/transaction snapshot 1)
        [joint-id joint] (experiment/transaction (assoc snapshot "jointRun" "combined") 2)]
    (try
      (d/transact conn base)
      (d/transact conn joint)
      (is (not= base-id joint-id))
      (is (nil? (:jointRun (experiment/opening @conn base-id))))
      (is (= "combined" (:jointRun (experiment/opening @conn joint-id))))
      (finally (d/release conn) (d/delete-database config)))))

(deftest city-library-retains-published-versions-and-reopens-older-experiments
  (let [config {:store {:backend :memory :id (random-uuid)}
                :initial-tx experiment/schema :value-caps :default}
        _ (d/create-database config) conn (d/connect config)
        stuttgart {:city "stuttgart" :coverage "city" :release "s" :label "Stuttgart" :population 10 :inbound 2
                  :scenarios [{:key "close" :label "Close centre" :districts [["Mitte" -10.0 -12.0 -8.0]]}]}
        city {:city "vancouver" :coverage "city" :release "v1" :label "City" :population 5
              :atlas "population" :day "weekday" :streets "streets"}
        next-day (assoc city :release "v2" :day "new-weekday" :matchedCensusAreas 2
                            :jointRun "combined" :incomingTransit "incoming" :outboundRoad "outbound" :outboundTransit "transit")
        opening {"city" "vancouver" "atlas" "population" "day" "weekday" "streets" "streets" "market" "market"
                 "site" "A" "address" "Corner shop" "rule" "access" "hours" "short" "basket" 0
                 "cycling" "c" "tours" "t" "visits" [["home" 1 0 920 "" nil "bike"]]}]
    (try
      (d/transact conn (experiment/register-runs @conn [stuttgart city]))
      (let [new (experiment/register-runs @conn [stuttgart next-day])]
        (is (= 1 (count new)))
        (d/transact conn new))
      (is (empty? (experiment/register-runs @conn [city next-day])))
      (is (= {"s" nil "v1" nil "v2" 2}
             (into {} (map (juxt :release :matchedCensusAreas) (experiment/published-runs @conn)))))
      (is (= ["combined" "incoming" "outbound" "transit"]
             ((juxt :jointRun :incomingTransit :outboundRoad :outboundTransit)
              (some #(when (= "v2" (:release %)) %) (experiment/published-runs @conn)))))
      (is (= (:scenarios stuttgart) (:scenarios (first (filter #(= "s" (:release %)) (experiment/published-runs @conn))))))
      (is (= #{["stuttgart" "s" 10 2] ["vancouver" "v1" 5 0] ["vancouver" "v2" 5 0]}
             (set (map (juxt :city :release :population :inbound) (experiment/published-runs @conn)))))
      (let [[id tx] (experiment/transaction opening 123)]
        (d/transact conn tx)
        (is (= [(assoc (dissoc (experiment/opening @conn id) :visits) :visit-count 1 :resident-count 1 :diverted 0)] (experiment/saved-summaries @conn)))
        (is (= ["weekday" "short" 0.0 "access"] ((juxt :day :hours :basket :rule) (first (experiment/saved-summaries @conn))))))
      (finally (d/release conn) (d/delete-database config)))))
