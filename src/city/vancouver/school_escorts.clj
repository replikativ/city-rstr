(ns city.vancouver.school-escorts
  "Read candidate students and adults from the same synthetic household."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.outing-opportunities :refer [home-spans]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- candidates [people home plan members school-positions schools]
  (into []
        (keep (fn [i]
                (let [[age _ _ _ _ _ _ template] (people i)]
                  (when-let [school-slot (and (<= 1 age 2) (get school-positions template))]
                    (let [site (get (plan i) school-slot -1)]
                      (when (and (= (home i) (home (first members))) (contains? schools site))
                        [i site]))))))
        members))

(defn -main [atlas-dir day-dir options-file output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json"))
        day (read-json (io/file day-dir "day.json"))
        {:strs [municipalities schools]} (read-json options-file)
        school-set (set schools)
        school-positions (into {}
                               (keep-indexed (fn [i {:strs [childSchedule slots]}]
                                               (when childSchedule
                                                 [i (.indexOf ^java.util.List slots "school")])))
                               (day "templates"))
        by-da (into {} (for [name municipalities da (get-in atlas ["areas" name "das"])] [da name]))
        diaries (mapv #(get % "episodes") (atlas "templates"))
        flexible #{"personal-care" "eating" "housework" "housework-occasional"
                   "childcare" "media" "leisure-out"}
        windows (mapv #(home-spans % flexible) diaries)
        awake (mapv #(home-spans % (fn [activity] (not= "sleep" activity))) diaries)
        drivers (mapv #(boolean (some (fn [[_ _ activity place]]
                                        (and (= activity "travel") (= place "car-driver")))
                                      %)) diaries)]
    (with-open [writer (io/writer output)]
      (doseq [[d da] (map-indexed vector (day "das"))
              :let [municipality (get by-da da)]
              :when municipality]
        (let [file (str da ".json")
              {:strs [people homes]} (read-json (io/file atlas-dir file))
              {:strs [home plans]} (read-json (io/file day-dir file))]
          (doseq [[first-member size] homes
                  :when (<= 0 (home first-member))
                  :let [members (range first-member (+ first-member size))
                        pupils (candidates people home plans members school-positions school-set)]
                  :when (seq pupils)]
            (let [adults (into []
                               (keep (fn [i]
                                       (let [[age _ _ _ _ _ _ template] (people i)]
                                         (when (and (<= 4 age 13) (= (home i) (home first-member)))
                                           [i (windows template) (drivers template) (awake template)]))))
                               members)
                  care-at-home (some (fn [i]
                                       (some #(= "home-care" (nth % 2))
                                             (diaries (peek (people i)))))
                                     members)]
              (json/write [d (home first-member) municipality pupils adults (boolean care-at-home)] writer)
              (.write writer "\n"))))))))
