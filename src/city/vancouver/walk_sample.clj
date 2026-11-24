(ns city.vancouver.walk-sample
  "Stream seeded, age-stratified synthetic weekdays with a census expansion weight."
  (:require [city.synth.timeuse :as timeuse]
            [city.vancouver.weekday :as weekday]
            [city.vancouver.shopping :as shopping]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util Random]))

(defn- strata [line]
  (let [{:strs [dauid local_area lon lat m]} (json/read-str line)
        target (if (< (Math/hypot (* 72750 (- lon -123.105))
                                  (* 111195 (- lat 49.262))) 2600) 12 90)]
    (for [[age ids] (sort weekday/census-age-ids)
          :let [pop (reduce + (map #(first (get m (str %))) ids))
                n (long (Math/ceil (/ pop target)))]
          :when (pos? n)]
      {:da dauid :age age :n n :home [lon lat] :area local_area :weight (/ (double pop) n)})))

(defn -main [root & seeds]
  (let [pools (weekday/split-diaries (timeuse/load-diaries :project-root root))
        groups (with-open [r (io/reader (io/file root "data/derived/vancouver_da_marginals.jsonl"))]
                 (into [] (mapcat strata) (line-seq r)))]
    (doseq [seed (map parse-long (or (seq seeds) ["2023"]))
            :let [rng (Random. (long seed))]
            {:keys [da age n home area weight]} groups
            i (range n)
            :let [chain (weekday/draw-weekday pools age rng)]
            :when (some #(= :walk (:loc %)) chain)]
      (json/write {:seed seed :id (str da "-" (name age) "-" i) :area area :age (subs (name age) 1)
                   :home home :weight weight
                   :goods (keep-indexed (fn [idx e] (when (= :goods-at-store (shopping/category e)) idx)) chain)
                   :chain (mapv (juxt :start :dur :act :loc) chain)} *out*)
      (newline))))
