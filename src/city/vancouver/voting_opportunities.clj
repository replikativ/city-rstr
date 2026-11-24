(ns city.vancouver.voting-opportunities
  "Export municipal adults and their existing at-home discretionary windows."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.outing-opportunities :refer [home-spans]]
            [city.vancouver.trip-demand :refer [visit-residents!]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def ^:private housework #{"housework" "housework-occasional"})
(def ^:private flexible-home (into #{"media" "leisure-out"} housework))

(defn -main [atlas-dir day-dir output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        das (day "das")
        home-area (into {} (for [[area group] (atlas "areas") da (group "das")] [da area]))
        index (zipmap das (range))
        diaries (mapv #(get % "episodes") (atlas "templates"))
        windows (mapv home-spans diaries)
        flexible (mapv #(home-spans % flexible-home) diaries)
        chores (mapv (fn [episodes]
                       (into [] (keep (fn [[start duration activity place]]
                                        (when (and (= place "home") (housework activity))
                                          [start duration activity]))) episodes))
                     diaries)
        drivers (mapv #(boolean (some (fn [e] (= (peek e) "car-driver")) %)) diaries)
        residents (java.util.ArrayList.)]
    (visit-residents! atlas-dir day-dir atlas das
      (fn [da i [age _ labour _ _ _ _ template] home _]
        (when (<= 4 age 13)
          (.add residents [(index da) i home template (home-area da) (drivers template) age (= 1 labour)]))))
    (with-open [writer (io/writer output)]
      (json/write {:residents (vec residents) :windows windows :flexible flexible :chores chores} writer))))
