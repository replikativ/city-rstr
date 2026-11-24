(ns city.resident-test
  (:require [city.resident :as resident]
            [clojure.test :refer [deftest is]]))

(deftest visit-boundaries
  (let [visit {:depart 720 :arrive 735 :leave 740 :finish 750
               :from 3 :stop 4 :to 5}]
    (is (nil? (resident/visit-at visit 719.9)))
    (is (= {:phase :inbound :from 3 :to 4 :start 720 :end 735 :fraction 0.0}
           (resident/visit-at visit 720)))
    (is (= 0.5 (:fraction (resident/visit-at visit 727.5))))
    (is (= {:phase :stop :from 4 :to 4 :start 735 :end 740}
           (resident/visit-at visit 735)))
    (is (= {:phase :outbound :from 4 :to 5 :start 740 :end 750 :fraction 0.0}
           (resident/visit-at visit 740)))
    (is (nil? (resident/visit-at visit 750)))))

(deftest immediate-return
  (let [visit {:depart 0 :arrive 10 :leave 10 :finish 20
               :from 3 :stop 4 :to 3}]
    (is (= :outbound (:phase (resident/visit-at visit 10))))))
