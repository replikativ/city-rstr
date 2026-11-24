(ns city.vancouver.booking-scorecard
  "REPL entry points for the paired Downtown transit booking experiment."
  (:require [city.calibration :as calibration]
            [city.vancouver.departures :refer [read-json]]
            [clojure.java.io :as io]))

(defn- load-report [data-root release suffix]
  (let [file (io/file data-root "vancouver" "downtown-audit" (str release suffix ".json"))
        report (read-json file)]
    (when-not (and (= release (get report "release")) (= 1 (get report "schema")))
      (throw (ex-info "Booking evidence belongs to a different weekday" {:release release})))
    report))

(defn load-experiment [data-root release]
  (load-report data-root release "-booking"))

(defn load-workplace-timing [data-root release]
  (load-report data-root release "-workplace-timing"))

(defn- percent [counts]
  (let [total (reduce + counts)]
    (mapv #(/ (* 100.0 %) total) counts)))

(defn- workplace-share [{:strs [northShore holdoutWorkplaces holdoutSource]} fitted?]
  (let [groups (vals northShore)
        total (transduce (map #(get % "total")) + groups)
        downtown (transduce (map #(get % (if fitted? "after" "before"))) + groups)]
    (calibration/score
     {:id :north-shore-workplaces :role :held-out :unit :percentage-points
      :geography "North Shore homes, Vancouver and UEL workplaces"
      :population "2025 commuters by all modes, used as a comparison for the modeled transit cohort"
      :period "2025 North Shore Transportation Survey, Table 54"
      :cells ["Vancouver CBD and West End share"]
      :source holdoutSource :reference [(first (percent holdoutWorkplaces))]}
     [(/ (* 100.0 downtown) total)])))

(defn scorecard
  "Score the baseline and each experiment with fixed reference populations."
  [{:strs [observedStationPeakCounts stationSource durationSource durationBands scenarios northShore]
    :as report}]
  (mapv
   (fn [{:strs [extraMinutes added downtownPeakBookings stationPeakCounts duration workplaces]}]
     (let [{:strs [compared observedExpected replay]} duration
           stations {:id :skytrain-events :role :held-out :unit :passenger-events
                     :geography "Six Downtown Vancouver SkyTrain stations"
                     :population "All observed weekday riders"
                     :period "2025 weekdays"
                     :cells ["07:00–09:00 alightings" "16:00–18:00 boardings"]
                     :source stationSource :reference observedStationPeakCounts}
           duration-target {:id :commute-duration :role :held-out :unit :percentage-points
                            :geography "Home municipality and straight-line distance"
                            :population "2021 usual-workplace transit commuters standardized to the fixed modeled origin and distance mix"
                            :period "2021 Census" :source durationSource
                            :cells durationBands :compared compared :reference (percent observedExpected)}]
       (cond-> {:extra-minutes extraMinutes :added added :peak-bookings downtownPeakBookings
                :stations (calibration/score stations stationPeakCounts)
                :duration (calibration/score duration-target (percent replay))}
         northShore (assoc :workplaces workplaces :workplace-share (workplace-share report workplaces)))))
   scenarios))
