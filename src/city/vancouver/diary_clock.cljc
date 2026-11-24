(ns city.vancouver.diary-clock
  "One reproducible phase per roster member within a five-minute reporting bin.
   The discrete engine observes the continuous clock at whole minutes."
  (:require [city.resident :as resident]
            #?(:clj [clojure.data.json :as json])))

(def period resident/phase-period)

(defn phase [agent]
  ;; Multiplication precedes division to preserve the published sub-minute clock.
  (resident/within-bin-offset agent 5.0))

(defn minute-offset [agent] (long (Math/ceil (phase agent))))

(defn day-boundary [minute offset]
  ;; Resident diaries cover exactly 04:00 to the next 04:00.
  (if (or (= minute 0) (= minute 1440)) minute
    (min 1440 (max 0 (+ minute offset)))))

#?(:clj
   (defn -main []
     (json/write (mapv phase (range period)) *out*)))
