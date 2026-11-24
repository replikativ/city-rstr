(ns city.sim.road-queue-test
  (:require [city.sim.road-queue :as queue]
            [clojure.test :refer [deftest is]]))

(deftest queued-vehicles-are-served-under-the-next-minutes-capacity
  (is (= [[40 25 15 25] [36 36 15 36] [0 15 0 37]]
         (queue/discharge [40 36 0] [1500 2200 2200]))))

(deftest capacity-is-exact-across-a-full-hour
  (let [arrivals (repeat 60 100)
        result (queue/discharge arrivals (repeat 60 3500))]
    (is (= 3500 (reduce + (map second result))))
    (is (= 2500 (nth (peek result) 2)))))

(deftest lane-change-minute-belongs-to-the-new-lane-direction
  (is (= [1 2 2 1]
         (map #(queue/lanes "LionsGateBridge" "weekday" 0 %) [359 360 569 570])))
  (is (= [3 2 2 3]
         (map #(queue/lanes "Ironworkers" "closure" 0 %) [419 420 539 540])))
  (is (= 3 (queue/lanes "Ironworkers" "closure" 1 480))))
