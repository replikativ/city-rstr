(ns city.vancouver.weekday-attendance
  "Find intact at-home paid shifts and their time budgets."
  (:require [city.commute :as commute]
            [city.vancouver.departures :refer [read-json]]
            [city.vancouver.outing-opportunities :refer [home-spans]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def ^:private adjustable
  #{"personal-care" "eating" "housework" "housework-occasional" "media" "leisure-out"})

(defn shift [episodes]
  (let [work (filterv #(= "paid-work" (nth % 2)) episodes)
        paid (transduce (map second) + 0 work)]
    (when (and (>= paid 120) (every? #(= "home" (peek %)) work))
      (let [start (ffirst work)
            end (+ (first (peek work)) (second (peek work)))
            inside (filter (fn [[t]] (<= start t (dec end))) episodes)
            segments (home-spans episodes adjustable)
            before (some (fn [[a b]] (when (= b start) a)) segments)
            after (some (fn [[a b]] (when (= a end) b)) segments)]
        (when (and before after
                   (every? (fn [[_ n activity place]]
                             (and (= place "home")
                                  (or (= activity "paid-work")
                                      (and (<= n 60) (#{"eating" "personal-care" "media" "leisure-out"} activity)))))
                           inside))
          [before start end after paid])))))

(defn -main [atlas-file day-file output]
  (let [diaries (mapv #(get % "episodes") (get (read-json atlas-file) "templates"))
        plans (get (read-json day-file) "templates")
        records (mapv (fn [episodes plan]
                        {:shift (shift episodes)
                         :paidSlots (vec (sort (commute/paid-slots plan {"episodes" episodes})))
                         :careAtHome (boolean (some #(= "home-care" (nth % 2)) episodes))
                         :awake (home-spans episodes #(not= "sleep" %))})
                      diaries plans)]
    (with-open [writer (io/writer output)]
      (json/write records writer))))
