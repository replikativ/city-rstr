(ns city.ui.timeline
  "Display-time operations. They never step or rewrite a simulation.")

(defn advance-hour [hour elapsed-seconds minutes-per-second]
  (mod (+ hour (/ (* (max 0.0 (min 0.25 elapsed-seconds)) minutes-per-second) 60.0)) 24.0))

(defn position-at [{:keys [path timestamps]} minute]
  (let [n (min (count path) (count timestamps))]
    (when (pos? n)
      (cond
        (<= minute (first timestamps)) (first path)
        (>= minute (nth timestamps (dec n))) (nth path (dec n))
        :else (let [i (first (filter #(<= minute (nth timestamps %)) (range 1 n)))
                    t0 (nth timestamps (dec i)) t1 (nth timestamps i)
                    fraction (if (> t1 t0) (/ (- minute t0) (- t1 t0)) 0.0)
                    a (nth path (dec i)) b (nth path i)]
                (mapv #(+ %1 (* fraction (- %2 %1))) a b))))))

(defn person-at [legs minute]
  (when (seq legs)
    (let [leg (or (last (take-while #(<= (first (:timestamps %)) minute) legs)) (first legs))]
      {:pid (:pid leg) :purpose (:purpose leg) :mode (:mode leg)
       :moving? (and (<= (first (:timestamps leg)) minute) (< minute (last (:timestamps leg))))
       :position (position-at leg minute)})))

(defn group-trips [trips]
  (->> trips
       (filter #(and (seq (:path %)) (= (count (:path %)) (count (:timestamps %)))))
       (group-by :pid) vals (mapv #(vec (sort-by (comp first :timestamps) %)))))

(defn month-row [series month]
  (or (last (sort-by :month (filter #(<= (:month %) month) series)))
      (first (sort-by :month series))))
