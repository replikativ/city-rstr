(ns city.vancouver.cycle-tour-clock
  "Project the mode of eligible drivers at each minute with Raster's weekday interval phase."
  (:require [city.vancouver.departures :refer [read-json]]
            [city.vancouver.occupancy-run :as occupancy]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util Arrays]))

(defn- schedule [zone-index outings]
  (let [[_ _ _ z _ _ access] (first outings)
        intervals (sort (for [[_ _ _ zone _ legs eligible] outings [s duration] legs]
                          (do (when-not (= [z access] [zone eligible])
                                (throw (ex-info "Resident changes home zone or bicycle access during the day" {})))
                              [(- s 240) (- (+ s duration) 240)])))]
    (when-not (and (every? (fn [[s e]] (<= 0 s (dec e) 1439)) intervals)
                   (every? (fn [[[a end] [start b]]] (<= end start)) (partition 2 1 intervals)))
      (throw (ex-info "Outing travel intervals overlap or exceed the weekday" {})))
    [(zone-index z) (if access 1 2) (vec intervals)]))

(defn project [zones rows backend]
  (let [z (count zones) cols (* 2 z) zone-index (zipmap zones (range))
        people (mapv #(schedule zone-index %) (vals (group-by (juxt first second) rows)))
        groups (vec (sort (distinct people))) group-index (zipmap groups (range))
        weights (frequencies people) n (* 1441 cols) levels [0 1 2]
        events (mapcat (fn [[zone _ intervals]]
                         (map (fn [[s e]] [(+ (* s cols) zone) (+ (* e cols) zone)]) intervals)) groups)
        columns {:offsets (int-array (reductions + 0 (map #(count (peek %)) groups)))
                 :starts (int-array (map first events)) :ends (int-array (map second events))
                 :shifts (int-array (count events) z) :ranks (int-array (map second groups))
                 :settings (int-array 2) :changes (int-array n)}
        steps (reduce max 0 (map #(count (peek %)) groups))
        run (fn [ids masses]
              (occupancy/evaluate (assoc columns :ids (int-array ids) :weights (int-array masses)) levels steps backend))
        grouped (run (range (count groups)) (map weights groups))
        agents (run (map group-index people) (repeat (count people) 1))
        counts
        (mapv (fn [level ^ints delta ^ints detailed]
                (when-not (Arrays/equals delta detailed)
                  (throw (ex-info "Grouped and resident Raster results differ" {:level level})))
                ;; Direct enumeration includes each travel minute, independently of the event phase.
                (let [expected (int-array n)]
                  (doseq [[_ _ _ zone _ legs access] rows [s d] legs]
                    (let [column (+ (zone-index zone) (if (or (= level 2) (and (= level 1) access)) z 0))]
                      (dotimes [dt d]
                        (let [i (+ column (* cols (+ (- s 240) dt)))]
                          (aset-int expected i (inc (aget expected i)))))))
                  (dotimes [i (- n cols)]
                    (aset-int delta (+ i cols) (+ (aget delta i) (aget delta (+ i cols)))))
                  (when-not (Arrays/equals expected delta)
                    (throw (ex-info "Raster projection differs from the resident replay" {:level level})))
                  (mapv #(subvec (vec %) z) (take 1440 (partition cols delta)))))
              levels grouped agents)]
    {:zones zones :agents (count people) :groups (count groups) :backend backend
     :access (counts 1) :ride (counts 2)}))

(defn -main [release out backend]
  (let [report (read-json (io/file release "report.json")) rows (read-json (io/file release "tours.json"))
        zones (mapv #(get % "code") (rest (report "zones")))
        result (project zones rows backend)]
    (with-open [w (io/writer out)]
      (json/write (assoc result :tours (.getName (io/file release)) :versions (report "versions")) w)))
  (shutdown-agents))
