(ns city.vancouver.diary-clock
  "One reproducible phase per roster member within a five-minute reporting bin.
   The discrete engine observes the continuous clock at whole minutes.")

(defn phase [agent]
  ;; Coprime multiplier permutes all residues. Keep this formula in sync with
  ;; scripts/overview_traces.mjs, which publishes the browser geometry.
  (- (* 5.0 (/ (+ 0.5 (mod (* (inc agent) 7919) 10007)) 10007)) 2.5))

(defn minute-offset [agent] (long (Math/ceil (phase agent))))

(defn day-boundary [minute offset]
  ;; Resident diaries cover exactly 04:00 to the next 04:00.
  (if (or (= minute 0) (= minute 1440)) minute
    (min 1440 (max 0 (+ minute offset)))))
