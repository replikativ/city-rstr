(ns city.vancouver.household-market
  "Count households reachable by a candidate store, by income and incumbent access."
  (:require [city.vancouver.int-columns :refer [read-ints write-ints]]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [raster.arrays :as arr]
            [raster.core :refer [deftm]]
            [raster.par :as par])
  (:import [java.util Arrays]))

(deftm reach!
  [ids :- (Array int), weights :- (Array int), bins :- (Array int),
   distance :- (Array int), existing :- (Array int), settings :- (Array int),
   counts :- (Array int), n :- Long] :- Void
  (par/map-void! i n
    (let [r (int (arr/aget ids i))
          d (int (arr/aget distance r))
          limit (int (arr/aget settings 0))]
      (when (<= d limit)
        (let [w (int (arr/aget weights i))
              b (int (arr/aget bins r))
              e (int (arr/aget existing r))]
          (par/atomic-add! counts b w)
          (when (< d e)
            (let [offset (int (if (<= e limit) (int 6) (int 12)))]
              (par/atomic-add! counts (unchecked-add-int b offset) w))))))))

(defn- household-ids [^ints multiplicity]
  (let [ids (int-array (reduce + multiplicity))]
    (loop [i 0, start 0]
      (when (< i (alength multiplicity))
        (let [end (+ start (aget multiplicity i))]
          (Arrays/fill ids (int start) (int end) (int i))
          (recur (inc i) end))))
    ids))

(defn- gpu [k] (requiring-resolve (symbol "raster.gpu.core" (name k))))

(defn- run-batch [dir backend fidelity sites radii]
  (let [mass (read-ints dir :multiplicity)
        ids (if (= fidelity "agents") (household-ids mass) (int-array (range (alength ^ints mass))))
        n (alength ^ints ids)
        weights (if (= fidelity "agents") (int-array n 1) mass)
        inputs (into {:ids ids :weights weights :settings (int-array 1) :counts (int-array (* sites 18))}
                     (for [k [:bins :distance :existing]] [k (read-ints dir k)]))
        device (when (and (pos? n) (not= backend "jvm")) ((gpu :make-session) (keyword backend)))]
    (try
      (when device
        ((gpu :compile-phases!) device {:market #'reach!} {:dtype :float})
        ((gpu :alloc!) device (into {} (for [[k ^ints a] inputs] [k [:int (alength a) a]]))))
      (doseq [radius radii]
        (let [settings (int-array [(* radius 1000)])
              counts (int-array (* sites 18))
              output (cond
                       (zero? n) counts
                       device (do ((gpu :upload!) device :settings settings)
                                  ((gpu :upload!) device :counts counts)
                                  ((gpu :invoke!) device :market {} [] n)
                                  ((gpu :download) device :counts))
                       :else (do (reach! ids weights (:bins inputs) (:distance inputs) (:existing inputs)
                                         settings counts n)
                                 counts))]
          (write-ints (io/file dir (str fidelity "-" radius ".i32")) output)))
      (finally (when device ((gpu :close-session!) device))))))

(defn -main [work backend & verify]
  (let [{:keys [radii sites]} (json/read-str (slurp (io/file work "model.json")) :key-fn keyword)
        starts (sort (for [f (.listFiles (io/file work)) :when (.isDirectory f)] (parse-long (.getName f))))]
    (doseq [[start end] (partition 2 1 (concat starts [(count sites)]))
            fidelity (cons "groups" verify)]
      (run-batch (io/file work (str start)) backend fidelity (- end start) radii)))
  (shutdown-agents))
