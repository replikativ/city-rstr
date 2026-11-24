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

(deftest city-switches-use-published-weekdays-and-the-displayed-time
  (is (= {:path "lab.html" :query {"city" "stuttgart" "release" "stuttgart-day" "hour" "1.25"}}
         (replay/change-city runs "stuttgart" 1515)))
  (is (= {:path "explorer.html" :query {"city" "vancouver" "release" "regional" "minute" "75"}}
         (replay/change-city runs "vancouver" 75)))
  (is (= {:path "explorer.html" :query {"city" "vancouver" "release" "regional"}}
         (replay/change-city runs "vancouver" nil)))
  (is (nil? (replay/change-city runs "other" 480))))
