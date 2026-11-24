(ns city.vancouver.trip-accounting-test
  (:require [clojure.test :refer [deftest is]]
            [city.vancouver.trip-accounting :as trips]))

(deftest opening-affects-both-walks-and-only-the-shopping-interval
  ;; Home area 2. The 08:05–08:50 stop moves from outside Downtown to Downtown.
  (let [{:keys [occupancy-at walking-flow]} (trips/shop-effects 3 0 [[2 485 45 1 0 1 1 10 20]])]
    (is (= [0 1 1 0] (map #(occupancy-at (- % 240) 0) [484 485 529 530])))
    (is (= -1 (occupancy-at 245 1)))
    (is (= 1 (walking-flow 8 2 0) (walking-flow 8 2 1)))
    (is (= 0 (walking-flow 7 2 0) (walking-flow 9 2 1) (walking-flow 8 1 0)))))

(deftest previously-unlocated-shop-and-midnight-return
  (let [{:keys [occupancy-at walking-flow]} (trips/shop-effects 3 0 [[1 1435 15 -1 2 0 0 10 15]])]
    (is (= -1 (occupancy-at 1200 3)))
    (is (= 1 (occupancy-at 1200 2)))
    (is (= 1 (walking-flow 23 1 1) (walking-flow 0 1 0)))))

(deftest shopping-reassignments-use-the-travellers-mode
  (let [{:keys [walking-flow cycling-flow occupancy-at]}
        (trips/shop-effects 3 0 [[2 485 45 1 0 1 1 10 20 "bike"]])]
    (is (= 1 (cycling-flow 8 2 0) (cycling-flow 8 2 1)))
    (is (= 0 (walking-flow 8 2 0) (walking-flow 8 2 1)))
    (is (= 1 (occupancy-at 245 0)))))

(deftest shopping-can-change-mode-without-changing-destination-area
  (let [{:keys [occupancy-at driving-flow walking-flow]}
        (trips/shop-effects 3 0 [[2 485 45 0 0 1 1 10 20 "walk" "car-driver"]])]
    (is (zero? (occupancy-at 245 0)))
    (is (= 1 (walking-flow 8 2 0) (walking-flow 8 2 1)))
    (is (= -1 (driving-flow 8 2 0) (driving-flow 8 2 1)))))
