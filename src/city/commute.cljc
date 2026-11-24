(ns city.commute
  "Definitions shared by workplace assignment and commute diagnostics.")

(defn paid-slots [{:strs [parts slots]} {:strs [episodes]}]
  (let [work (keep (fn [[start _ activity]] (when (= "paid-work" activity) start)) episodes)]
    (into #{} (keep (fn [[start duration mode i]]
                      (when (and (= "stop" mode)
                                 (= "job" (slots i))
                                 (some #(and (<= start %) (< % (+ start duration))) work))
                        i)))
          parts)))

(defn direct-commute? [slots paid [_ _ mode i j]]
  (and (not= mode "stop")
       (or (and (paid j) (= "home" (get slots i)))
           (and (paid i) (= "home" (get slots j))))))

(defn home-work-arrivals
  "Return the outbound legs that go directly from a home slot to paid work."
  [{:strs [parts slots]} paid]
  (filter (fn [[_ _ mode i j]]
            (and (not= "stop" mode) (= "home" (get slots i)) (paid j)))
          parts))
