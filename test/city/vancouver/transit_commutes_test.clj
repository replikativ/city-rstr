(ns city.vancouver.transit-commutes-test
  (:require [city.vancouver.transit-commutes :as transit]
            [clojure.test :refer [deftest is]]))

(deftest later-departure-keeps-shift-and-return
  (let [template {"slots" ["home" "job" "home"]
                  "parts" [[240 210 "stop" 0 0] [450 60 "transit" 0 1] [510 470 "stop" 1 1]
                           [980 40 "car-passenger" 1 2] [1020 660 "stop" 2 2]]}
        diary {"episodes" [[240 180 "sleep" "home"] [420 30 "personal-care" "home"]
                           [450 8 "travel" "walk"] [458 52 "travel" "transit"]
                           [510 470 "paid-work" "work-or-school"] [980 40 "travel" "car-passenger"]
                           [1020 660 "sleep" "home"]]}
        tour {:minute 450 :duration 60 :episode 2}
        {:keys [day diary]} (transit/revised-templates template diary tour 475)]
    (is (= ["home" "job" "home"] (day "slots")))
    (is (= [[240 235 "stop" 0 0] [475 35 "transit" 0 1]] (subvec (day "parts") 0 2)))
    (is (= (subvec (template "parts") 2) (subvec (day "parts") 2)))
    (is (= [[240 180 "sleep" "home"] [420 30 "personal-care" "home"] [450 25 "other" "home"] [475 35 "travel" "transit"]]
           (subvec (diary "episodes") 0 4)))
    (is (= [[510 470 "paid-work" "work-or-school"] [980 40 "travel" "car-passenger"] [1020 660 "sleep" "home"]]
           (subvec (diary "episodes") 4)))))

(deftest flex-windows-borrow-only-adjacent-home-leisure
  (let [template {"slots" ["home" "job" "home"]
                  "parts" [[240 240 "stop" 0 0] [480 40 "transit" 0 1] [520 380 "stop" 1 1]
                           [900 60 "transit" 1 2] [960 720 "stop" 2 2]]}
        diary {"episodes" [[240 190 "sleep" "home"] [430 50 "media" "home"]
                           [480 10 "travel" "walk"] [490 30 "travel" "transit"]
                           [520 380 "paid-work" "work-or-school"] [900 60 "travel" "transit"]
                           [960 10 "leisure-out" "home"] [970 30 "media" "home"] [1000 680 "sleep" "home"]]}
        {changed :day time-use :diary} (transit/flex-templates template diary [[480 520 465 520] [900 960 900 980]])]
    (is (= [[240 225 "stop" 0 0] [465 55 "transit" 0 1] [520 380 "stop" 1 1]
            [900 80 "transit" 1 2] [980 700 "stop" 2 2]] (changed "parts")))
    (is (= [[240 190 "sleep" "home"] [430 35 "media" "home"] [465 15 "travel" "transit"]
            [480 10 "travel" "walk"] [490 30 "travel" "transit"] [520 380 "paid-work" "work-or-school"]
            [900 60 "travel" "transit"] [960 20 "travel" "transit"] [980 20 "media" "home"] [1000 680 "sleep" "home"]]
           (time-use "episodes")))
    (is (thrown? clojure.lang.ExceptionInfo
                 (transit/flex-templates template diary [[900 960 900 1010]])))))
