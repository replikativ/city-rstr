(ns city.replay-test
  (:require [clojure.test :refer [deftest is]]
            [city.replay :as replay]))

(def old-city {:city "vancouver" :coverage "city" :release "original"})
(def combined-city {:city "vancouver" :coverage "city" :release "combined" :jointRun "joint"})
(def regional {:city "vancouver" :coverage "region" :release "regional"})
(def stuttgart {:city "stuttgart" :coverage "city" :release "stuttgart-day"})
(def runs [old-city combined-city regional stuttgart])

(deftest shared-catalogue-selection
  (is (= combined-city (replay/preferred-run runs "vancouver" "city")))
  (is (= regional (replay/preferred-run runs "vancouver" "region")))
  (is (= stuttgart (replay/preferred-run runs "stuttgart" "city")))
  (is (= [old-city combined-city] (vec (replay/order-runs [combined-city old-city] #{"original"})))))

(deftest coverage-switch-keeps-the-clock-and-service
  (let [result (replay/change-study-area
                {"dayRun" "combined" "jointRun" "joint" "minute" "510.5" "service" "99"
                 "marketRun" "market" "person" "42" "shop" "shop" "inspector" "evidence"}
                "#market" runs "region")]
    (is (= {:query {"dayRun" "regional" "coverage" "region" "minute" "510.5"
                    "service" "99" "inspector" "evidence"}
            :anchor ""} result))
    (is (= {"dayRun" "combined" "minute" "510.5" "service" "99" "inspector" "evidence"}
           (:query (replay/change-study-area (:query result) "" runs "city"))))))

(deftest link-formats-and-clock-compatibility
  (is (= {:city "stuttgart" :coverage "city" :release "stuttgart-day" :minute "20" :service nil}
         (replay/read-context (assoc (replay/weekday-query stuttgart) "minute" "20") "vancouver")))
  (is (= {"coverage" "region" "minute" "500" "service" "99"}
         (:query (replay/change-study-area {"minute" "500" "service" "99"} "" [] "region"))))
  (is (= {"dayRun" "combined" "minute" "480"}
         (:query (replay/change-study-area {"coverage" "region" "clock" "prior" "minute" "480"}
                                          "" runs "city")))))

(deftest city-switches-use-published-weekdays-and-the-displayed-time
  (is (= {:path "lab.html" :query {"city" "stuttgart" "release" "stuttgart-day" "hour" "1.25"}}
         (replay/change-city runs "stuttgart" 1515)))
  (is (= {:path "cityday.html" :query {"coverage" "region" "dayRun" "regional" "minute" "1515"}}
         (replay/change-city runs "vancouver" 75)))
  (is (= {:path "cityday.html" :query {"coverage" "region" "dayRun" "regional"}}
         (replay/change-city runs "vancouver" nil)))
  (is (nil? (replay/change-city runs "other" 480))))
