(ns city.opening-hours-test
  (:require [city.opening-hours :as hours]
            [clojure.test :refer [deftest is]]))

(deftest schedule-identities
  (is (= (hours/schedule "full") (hours/schedule "08:00-20:00")))
  (is (= (hours/schedule "short") (hours/schedule "10:00-18:00")))
  (doseq [spec [nil "custom" "00:00-00:00" "00:30-24:00" "23:99-01:00"]]
    (is (nil? (hours/schedule spec)))))

(deftest complete-visit-must-fit-a-continuous-opening
  (let [open? (partial hours/admits? (hours/schedule "22:00-02:00"))]
    (is (open? 1320 240))
    (is (open? 1430 30))
    (is (open? 1500 60))
    (is (open? 60 60))
    (is (not (open? 1559 2)))
    (is (not (open? 1319 2))))
  (is (hours/admits? (hours/schedule "24h") 1430 1440))
  (is (hours/admits? (hours/schedule "03:00-05:00") 240 60)))

(deftest opening-affects-departures-on-the-simulation-clock
  (let [shift (hours/schedule "20:00-08:00")]
    (is (hours/admits-after-activation? shift 1445 1460 10 15))
    (is (not (hours/admits-after-activation? shift 1446 1460 10 15)))
    (is (not (hours/admits-after-activation? shift 1445 1460 10 nil)))
    (is (not (hours/admits-after-activation? shift 450 470 20 15)))
    (is (not (hours/admits-after-activation? shift nil 1460 10 15)))))

(deftest quarter-hour-staffing-uses-complete-visits
  (is (= {:start 1320 :count 2 :ties 1}
         (hours/best-shift [[1320 60] [1670 130] [800 500]] 480)))
  (is (= 540 (:start (hours/best-shift [[720 30]] 480))))
  (is (zero? (:count (hours/best-shift [[600 481]] 480)))))
