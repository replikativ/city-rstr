(ns city.vancouver.cycle-tours
  "Extract complete home-based discretionary driver tours for a paired cycling scenario."
  (:require [city.vancouver.departures :refer [read-json]]
            [clojure.java.io :as io]
            [clojure.data.json :as json]))

(def purposes #{"Shopping" "Dining" "Recreation" "Social"})
(def commitments #{"paid-work" "study" "childcare" "adult-care" "helping"})

(defn tours [{:strs [parts slots]} {:strs [episodes]} by-start]
  (let [home? (fn [[_ _ mode a]] (and (= "stop" mode) (= "home" (get slots a))))
        homes (keep-indexed #(when (home? %2) %1) parts)]
    (vec
      (for [[start end] (partition 2 1 homes)
            :let [inside (subvec parts (inc start) end)
                  legs (vec (range (inc start) end 2))
                  first-away (get-in by-start [(get-in parts [(inc start) 0])])
                  [t dur] (parts start) from (+ t dur) to (first (parts end))
                  during (filter #(<= from (first %) (dec to)) episodes)]
            :when (and (>= (count inside) 3) (odd? (count inside))
                       (every? #(= "car-driver" (nth % 2)) (take-nth 2 inside))
                       (every? #(= "stop" (nth % 2)) (take-nth 2 (rest inside)))
                       (every? #(purposes (by-start (first (parts %)))) (butlast legs))
                       (every? (fn [[_ _ activity loc]]
                                 (and (not (commitments activity))
                                      (not (#{"work-or-school" "unknown" "elsewhere"} loc)))) during)
                       (every? (fn [idx]
                                 (let [[s n] (parts idx)]
                                   (every? #(= "car-driver" (nth % 3))
                                           (filter #(<= s (first %) (dec (+ s n))) during)))) legs))]
        {:purpose first-away :legs legs}))))

(defn -main [atlas-dir day-dir inputs output]
  (let [atlas (read-json (io/file atlas-dir "atlas.json")) day (read-json (io/file day-dir "day.json"))
        {:strs [zone codes purposes]} (read-json inputs)
        templates (day "templates")
        tours-by-template (mapv tours templates (atlas "templates")
                                (map #(into {} (map (fn [[s p]] [s p])) %) purposes))]
    (with-open [out (io/writer output)]
      (doseq [[d da] (map-indexed vector (day "das"))]
        (let [f (str da ".json") people (get (read-json (io/file atlas-dir f)) "people")
              {:strs [home plans]} (read-json (io/file day-dir f))]
          (when-not (= (count plans) (count people) (count home) (get-in atlas ["das" da "population"]))
            (throw (ex-info "Resident and spatial releases disagree" {:da da})))
          (dotimes [i (get-in atlas ["das" da "private"])]
            (let [person (people i) tpl (peek person) plan (plans i)]
              (when (<= 4 (first person) 13)
                (doseq [{:keys [purpose legs]} (tours-by-template tpl)]
                  (let [bundle (mapv (fn [k]
                                       (let [[s n _ a b] (get-in templates [tpl "parts" k])]
                                         [s n (plan a) (plan b)])) legs)]
                    (when-not (= (home i) (nth (first bundle) 2) (peek (peek bundle)))
                      (throw (ex-info "Home tour endpoints disagree" {:da da :i i})))
                    (json/write [d i tpl (get codes (get zone (home i) -1) "unmapped") purpose bundle] out)
                    (.write out "\n")))))))))))
