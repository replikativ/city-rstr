(ns city.resident
  "Replay a scheduled visit with versioned place IDs supplied by the city.")

(def phase-period 10007)

(defn within-bin-offset
  "Stable per-person offset in minutes, centred on the recorded bin."
  [agent width]
  (- (/ (* width (+ 0.5 (mod (* (inc agent) 7919) phase-period))) phase-period)
     (/ width 2.0)))

(defn- leg-at [phase from to start end minute]
  {:phase phase :from from :to to :start start :end end
   :fraction (/ (double (- minute start)) (- end start))})

(defn visit-at
  "Return the current leg or stop. Each interval includes its start and excludes
  its end. The fraction measures progress along the chosen route."
  [{:keys [depart arrive leave finish from stop to]} minute]
  (when (<= depart minute)
    (cond
      (< minute arrive) (leg-at :inbound from stop depart arrive minute)
      (< minute leave) {:phase :stop :from stop :to stop :start arrive :end leave}
      (< minute finish) (leg-at :outbound stop to leave finish minute))))

(defn trace-at
  "Resolve a sample of timed legs in departure order. A gap can place the
  person when the surrounding legs share an endpoint. A lone arrival only
  supplies a position at its recorded minute."
  [legs minute]
  (let [started (take-while #(<= (first (:timestamps %)) minute) legs)
        next-leg (first (drop (count started) legs))
        latest (when (seq started) (apply max-key (comp peek :timestamps) started))
        active (last (filter #(< minute (peek (:timestamps %))) started))]
    (cond
      active
      (let [{:keys [path timestamps]} active]
        (assoc (leg-at :travel (first path) (peek path) (first timestamps) (peek timestamps) minute)
               :trace active))

      latest
      (let [place (peek (:path latest))
            arrival (peek (:timestamps latest))]
        (cond
          (= minute arrival) {:phase :arrival :to place :start arrival :end arrival :trace latest}
          (= place (first (:path next-leg)))
          {:phase :stop :from place :to place :start arrival :end (first (:timestamps next-leg)) :trace latest})))))
