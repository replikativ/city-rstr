(ns city.street-replay-test
  (:require [city.sim.network :as net]
            [city.street-replay :as replay]
            [city.street-speed :as speed]
            [city.trajectory :as trajectory]
            [city.vancouver.diary-clock :as clock]
            [clojure.data.json :as json]
            [clojure.test :refer [deftest is]]))

(deftest archived-waypoints-keep-street-corners-and-continuous-time
  (let [a [9.0 48.0] corner [9.001 48.0] b [9.001 48.001] off [8.99 47.99]
        remote [9.2 48.2]
        graph (net/scratch (net/build [[a corner b] [remote [9.21 48.21]]]))
        route (#'replay/road-geometry graph)
        path (route [off a b off])
        [start middle end] (speed/timed-path (constantly {:motor 30}) path "car" 480 481)]
    (is (= [a corner b] path))
    (is (= 480.0 start))
    (is (< start middle end))
    (is (= 481.0 end))
    (is (nil? (route [a remote])))
    (is (nil? (route [off a])))))

(deftest segment-speeds-and-diary-feasibility
  (let [a [9.0 48.0] b [9.01 48.0] c [9.02 48.0]
        fast (#'speed/profile {:highway "primary" :maxspeed "30"})
        slow (#'speed/profile {:highway "living_street"})
        edge (fn [from _] (if (= from a) fast slow))
        path [a b c]
        [_ mid end] (speed/timed-path edge path "car" 600 610)]
    (is (= 30.0 (:motor fast)))
    (is (< (- mid 600) (- end mid)))
    (is (some? (speed/timed-path edge path "car" 600 608)))
    (is (nil? (speed/timed-path edge path "car" 480 488)))
    (is (nil? (speed/timed-path edge path "walk" 600 610)))
    (is (nil? (speed/timed-path (constantly (#'speed/profile {:highway "footway"})) path "car" 600 660)))))

(deftest motor-routing-prefers-faster-streets-and-respects-direction
  (let [a [9.0 48.0] b [9.002 48.0] c [9.001 48.001]
        speeds {[a b] 7 [a c] 30 [c b] 30}
        route (speed/motor-router [[a b] [a c b]] #(speeds [%1 %2]))]
    (is (= [[a c b] 0.0 0.0] (route a b)))
    (is (nil? (route b a)))
    (is (nil? (route [9.02 48.0] b)))))

(deftest municipal-replay-preserves-sample-order-and-midnight-clock
  (let [hours (mapv (fn [_] (java.util.ArrayList.)) (range 24))
        job {:id "da/7" :agent 7 :mode "walk" :purpose "home" :sample-order 11
             :request [23 "walk" [0 0] [1 1] 1390 65 false]}
        offset 0.6 duration 7.0]
    (#'trajectory/record-route! hours {} job [[0 0] [1 1] [2 2]] [0 offset duration] duration)
    (doseq [[h start] [[23 1390] [0 -50]]]
      (let [[[rank record]] (hours h)
            times (:times (json/read-str record :key-fn keyword))]
        (is (= 11 rank))
        (is (= (mapv double [start (+ start (* (/ offset duration) 65)) (+ start 65)])
               (mapv double times)))))))

(deftest regional-trajectory-and-roster-share-reporting-clock
  (let [run {:regionalWorkers "cohort" :population 2}
        times (fn [agent] (#'trajectory/leg-times [0 5] 5 240 20 agent run))]
    (is (== 240 (first (times 1))))
    (is (== (+ 260 (clock/phase 1)) (peek (times 1))))
    (is (== (+ 240 (clock/phase 2)) (first (times 2))))))
