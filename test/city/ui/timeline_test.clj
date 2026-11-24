(ns city.ui.timeline-test
  (:require [clojure.test :refer [deftest is]] [city.ui.timeline :as t]))

(def trips [{:pid 1 :purpose "work" :path [[0 0] [10 20]] :timestamps [60 120]}
            {:pid 1 :purpose "home" :path [[10 20] [0 0]] :timestamps [180 240]}])

(deftest playback-interpolates-and-parks
  (let [legs (first (t/group-trips (reverse trips)))]
    (is (= [0 0] (:position (t/person-at legs 0))))
    (is (= [5N 10N] (:position (t/person-at legs 90))))
    (is (= [10 20] (:position (t/person-at legs 150))))
    (is (false? (:moving? (t/person-at legs 150))))
    (is (= [0 0] (:position (t/person-at legs 300))))
    (is (nil? (t/position-at {:path [] :timestamps []} 90)))))

(deftest clocks-do-not-invent-snapshots
  (is (< (Math/abs (- 0.15 (t/advance-hour 23.9 0.25 60))) 1e-9))
  (is (= (t/advance-hour 5 100 60) (t/advance-hour 5 0.25 60)))
  (is (= {:month 3 :firms 90} (t/month-row [{:month 1 :firms 100} {:month 3 :firms 90}] 4))))

(deftest followed-traces-are-limited-to-available-legs
  (let [legs (first (t/group-trips trips))
        followed #(t/traced-person-at legs %)]
    (is (nil? (followed 59)))
    (is (= [5N 10N] (:position (followed 90))))
    (is (= :arrival (:phase (followed 120))))
    (is (= :stop (:phase (followed 150))))
    (is (= :travel (:phase (followed 180))))
    (is (nil? (followed 241)))
    (is (nil? (t/traced-person-at [(first legs)] 150)))
    (is (nil? (t/traced-person-at (assoc-in legs [1 :path 0] [1 2]) 150)))))

(deftest playback-preserves-minute-boundaries
  (is (== 485 (t/minute-at-hour (/ 485.0 60.0)))))
