(ns city.vancouver.trip-accounting
  "Account for relocated stops and their trips on the municipal weekday clock.")

(defn crossing [a b downtown]
  (when (and (<= 0 a) (<= 0 b) (not= a b))
    (cond (= b downtown) 0 (= a downtown) 1)))

(defn- counts-array [n] #?(:clj (int-array n) :cljs (js/Int32Array. n)))

(defn- add! [counts index amount]
  (aset counts index (+ (aget counts index) amount)))

(defn shop-effects
  "Each row gives home area, start, dwell, previous and chosen shop areas, the areas
   before and after the outing, and both leg durations. Area n is unresolved in occupancy."
  [n downtown visits]
  (let [stride (inc n)
        occupancy (counts-array (* 1441 stride))
        flows (counts-array (* 24 n 2)) cycles (counts-array (* 24 n 2)) cars (counts-array (* 24 n 2))
        bin (fn [hour home direction] (+ direction (* 2 (+ home (* n hour)))))]
    (doseq [[home start dwell old new prior next-area inbound onward mode previous-mode] visits
            :when (or (not= old new) (and previous-mode (not= previous-mode mode)))
            [area sign] [[old -1] [new 1]]]
      (let [z (if (neg? area) n area)
            offset (+ z (* (- start 240) stride))]
        (add! occupancy offset sign)
        (add! occupancy (+ offset (* dwell stride)) (- sign)))
      (doseq [[a b depart arrive] [[prior area (- start inbound) start]
                                   [area next-area (+ start dwell) (+ start dwell onward)]]
              :let [direction (crossing a b downtown)] :when (some? direction)]
        (let [hour (mod (quot (if (zero? direction) arrive depart) 60) 24)]
          (add! (case (if (neg? sign) (or previous-mode mode) mode)
                  "bike" cycles "car-driver" cars flows) (bin hour home direction) sign))))
    (dotimes [i (* 1440 stride)]
      (add! occupancy (+ i stride) (aget occupancy i)))
    {:occupancy-at (fn [offset area] (aget occupancy (+ area (* stride offset))))
     :driving-flow (fn [hour home direction] (aget cars (bin hour home direction)))
     :walking-flow (fn [hour home direction] (aget flows (bin hour home direction)))
     :cycling-flow (fn [hour home direction] (aget cycles (bin hour home direction)))}))
