(ns city.vancouver.occupancy-run
  "Run the same schedule phase over weighted itineraries or individual residents."
  (:require [city.sim.occupancy :as occ]
            [clojure.java.io :as io]
            [clojure.data.json :as json]
            [city.vancouver.int-columns :refer [read-ints write-ints]]))

(def ^:private columns [:offsets :starts :ends :shifts :ranks])
(def evaluate occ/evaluate)

(defn run [dir backend fidelity]
  (let [{:keys [zones steps levels] :or {levels [0 50 100]}} (json/read-str (slurp (io/file dir "shape.json")) :key-fn keyword)
        tables (into {} (for [k columns] [k (read-ints dir k)]))
        population (read-ints dir :population)
        groups (read-ints dir :group-sizes)
        inputs (assoc tables :ids (if (= fidelity "agents") population (int-array (range (alength groups))))
                      :weights (if (= fidelity "agents") (int-array (alength population) 1) groups)
                      :settings (int-array 2) :changes (int-array (* 1441 zones)))
        results (evaluate inputs levels steps backend)]
    (doseq [[level result] (map vector levels results)]
      (write-ints (io/file dir (str fidelity "-" level ".i32")) result))))

(defn -main [dir backend & fidelities]
  (doseq [fidelity fidelities] (run dir backend fidelity))
  (shutdown-agents))
