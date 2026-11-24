(ns city.vancouver.household
  "Household composition from the 2021 hierarchical Census PUMF, Vancouver CMA."
  (:require [clojure.data.csv :as csv]
            [clojure.java.io :as io]))

(def age-band
  {3 :a15-24, 4 :a15-24, 5 :a25-34, 6 :a25-34, 7 :a35-44, 8 :a35-44,
   9 :a45-54, 10 :a45-54, 11 :a55-64, 12 :a65-74, 13 :a75+})

(defn composition
  "Classify households on the complete roster, then count person weights for ages 15+.
   An unavailable age makes child absence indeterminate unless a child is present."
  [households]
  (let [counts
        (reduce (fn [counts people]
                  (let [ages (map :age people)
                        status (cond (some #{1 2} ages) :with-child
                                     (some #{88} ages) :unknown
                                     :else :without-child)]
                    (reduce (fn [counts {:keys [age weight]}]
                              (if-let [band (age-band age)]
                                (update-in counts [band status] (fnil + 0.0) weight)
                                counts))
                            counts people)))
                (sorted-map) households)]
    (update-vals counts
                 (fn [weights]
                   (let [known (+ (:with-child weights 0.0) (:without-child weights 0.0))]
                     (assoc weights :share-with-child
                            (when (pos? known) (/ (:with-child weights 0.0) known))))))))

(defn metro-composition [file]
  (with-open [r (io/reader file)]
    (let [[columns & rows] (csv/read-csv r)
          index (zipmap columns (range))
          [cma hh age weight] (map index ["CMA" "HH_ID" "AGEGRP" "WEIGHT"])]
      (when-not (every? some? [cma hh age weight])
        (throw (ex-info "Missing household PUMF columns" {:file (str file)})))
      (let [groups (reduce (fn [homes row]
                             (if (= "933" (nth row cma))
                               (let [code (Long/parseLong (nth row age))
                                     w (Double/parseDouble (nth row weight))]
                                 (when-not (and (or (<= 1 code 13) (= 88 code))
                                                (Double/isFinite w) (pos? w))
                                   (throw (ex-info "Invalid census age or person weight" {:age code :weight w})))
                                 (update homes (nth row hh) (fnil conj []) {:age code :weight w}))
                               homes))
                           {} rows)]
        (when (empty? groups) (throw (ex-info "Missing Vancouver CMA households" {})))
        (composition (vals groups))))))
