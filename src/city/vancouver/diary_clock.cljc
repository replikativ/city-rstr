(ns city.vancouver.diary-clock
  "One reproducible phase per roster member within a five-minute reporting bin.
   The discrete engine observes the continuous clock at whole minutes."
  #?(:clj (:require [clojure.data.json :as json])))

(def period 10007)

(defn phase [agent]
  ;; Multiplication precedes division to preserve the published sub-minute clock.
  (- (/ (* 5.0 (+ 0.5 (mod (* (inc agent) 7919) period))) period) 2.5))

(defn minute-offset [agent] (long (Math/ceil (phase agent))))

(defn day-boundary [minute offset]
  ;; Resident diaries cover exactly 04:00 to the next 04:00.
  (if (or (= minute 0) (= minute 1440)) minute
    (min 1440 (max 0 (+ minute offset)))))

#?(:clj
   (defn -main []
     (json/write (mapv phase (range period)) *out*)))
