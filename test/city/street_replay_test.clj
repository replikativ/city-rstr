(ns city.street-replay-test
  (:require [city.sim.network :as net]
            [city.street-replay :as replay]
            [city.street-speed :as speed]
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
