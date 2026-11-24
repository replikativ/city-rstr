(ns city.vancouver.downtown-audit
  (:require [city.vancouver.departures :refer [read-json]]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.nio.file CopyOption Files StandardCopyOption]
           [java.nio.file.attribute FileAttribute]))

(def windows
  [{:label "07:00–09:00" :hours [7 9] :peakHours [6 11]}
   {:label "16:00–18:00" :hours [16 18] :peakHours [15 20]}])

(def ^:private bridge-keys ["BurrardBridge" "GranvilleStBridge" "CambieBridge"])
(def ^:private road-source "counts_vancouver_arcgis_TCSPermanentCounts_sample.json")

(defn- require-match [what actual expected]
  (when (or (nil? expected) (not= actual expected))
    (throw (ex-info (str "Incompatible " what) {:actual actual :expected expected}))))

(defn- valid-profile? [counts]
  (and (vector? counts) (= 24 (count counts))
       (every? #(and (number? %) (Double/isFinite (double %)) (not (neg? %))) counts)))

(defn- peak-starts [profile hours]
  (let [window (subvec profile (first hours) (second hours))
        biggest (apply max window)]
    (if (pos? biggest)
      (filterv #(= biggest (profile %)) (apply range hours))
      [])))

(defn comparison [observed cohorts]
  (when-not (and (seq cohorts) (valid-profile? observed) (every? valid-profile? (vals cohorts)))
    (throw (ex-info "Expected 24 nonnegative hourly counts per series" {})))
  (let [modeled (apply mapv + (vals cohorts))]
    {:hourly {:observed observed :modeled modeled :cohorts cohorts}
     :windows (mapv (fn [{:keys [hours peakHours]}]
                      (let [total #(reduce + (subvec % (first hours) (second hours)))
                            n (total observed)
                            m (total modeled)]
                        {:observed n :modeled m
                         :modeledToObserved (when (pos? n) (/ (double m) n))
                         :cohorts (update-vals cohorts total)
                         :observedPeakStarts (peak-starts observed peakHours)
                         :modeledPeakStarts (peak-starts modeled peakHours)}))
                    windows)}))

(defn- site [report key]
  (or (some #(when (= key (get % "key")) %) (get report "sites"))
      (throw (ex-info "Missing road count site" {:key key}))))

(defn- road-site [resident incoming outbound key]
  (let [{:strs [name counters directions source layers] :as base} (site resident key)
        fitted (site incoming key)
        extra (site outbound key)
        location #(select-keys % ["point" "directions" "counters" "source"])]
    (require-match (str key " incoming counter") (location fitted) (location base))
    (require-match (str key " outbound counter") (location extra) (location base))
    (require-match (str key " counter directions") (mapv #(get % "direction") counters) directions)
    (require-match (str key " approach order") directions ["Southbound" "Northbound"])
    {:key key :label name :unit "Vehicles" :source source
     :matchedReferencePeriod (apply = (map #(select-keys % ["month" "year"]) counters))
     :directions (mapv (fn [i counter label]
                         (assoc (comparison (get counter "counts")
                                            {:residentWork (get-in layers ["residentWork" "counts" i])
                                             :outboundWork (get-in extra ["counts" i])
                                             :residentOther (get-in layers ["residentOther" "counts" i])
                                             :incomingWork (get-in fitted ["counts" 1 i])
                                             :scheduledBus (get-in layers ["buses" i])})
                                :label label :reference (dissoc counter "counts")))
                       (range) counters ["Southbound out of Downtown" "Northbound toward Downtown"])}))

(defn- rail-site [resident incoming outbound]
  (let [{:strs [observed stations]} resident
        counts-in-direction #(apply mapv vector %)]
    (doseq [report [incoming outbound]]
      (require-match "SkyTrain observations" (get report "observed") observed)
      (require-match "SkyTrain stations" (get report "stations") stations))
    (doseq [profile (cons observed (map #(get % "matched") [resident incoming outbound]))]
      (when-not (and (= 24 (count profile)) (every? #(= 2 (count %)) profile))
        (throw (ex-info "Expected two SkyTrain directions across 24 hours" {}))))
    {:key "downtownSkyTrain" :label "Six Downtown SkyTrain stations" :unit "Passenger events"
     :source "https://www.translink.ca/tspr" :stations stations
     :matchedReferencePeriod true
     :directions (mapv (fn [i label]
                         (assoc (comparison ((counts-in-direction observed) i)
                                            {:resident (get (counts-in-direction (get resident "matched")) i)
                                             :incomingWork (get (counts-in-direction (get incoming "matched")) i)
                                             :outboundWork (get (counts-in-direction (get outbound "matched")) i)})
                                :label label :reference {:year 2025 :dayType "Monday–Friday average"}))
                       (range 2) ["Alightings" "Boardings"])}))

(defn build [data-root release clock-id]
  (let [run (read-json (io/file data-root "runs" (str release ".json")))
        {:strs [jointRun incomingTransit outboundRoad outboundTransit]} run
        load-json #(read-json (apply io/file data-root "vancouver" %&))]
    (require-match "weekday release" (get run "release") release)
    (require-match "city" (get run "city") "vancouver")
    (require-match "coverage" (get run "coverage") "city")
    (doseq [id [jointRun incomingTransit outboundRoad outboundTransit]]
      (when-not (and (string? id) (re-matches #"[a-f0-9]{20}" id))
        (throw (ex-info "The audit needs a combined weekday with pinned commuter releases" {}))))
    (let [joint (load-json "joint-weekday" jointRun "report.json")
          {:strs [versions riders transit commuters workplaces]} joint
          resident-transit (load-json "transit-riders" riders "downtown.json")
          incoming (load-json "incoming-transit" incomingTransit "report.json")
          outbound (load-json "outbound-transit" outboundTransit "report.json")
          clock (or clock-id (get (load-json "outbound-transit-clock" (str outboundTransit ".json")) "version"))
          outbound-clock (load-json "outbound-transit-clock" clock "clock.json")
          fit (get-in incoming ["homeFit" "version"])
          resident-road (load-json "resident-road-crossings" (str jointRun ".json"))
          incoming-road (load-json "incoming-road-crossings" (str fit ".json"))
          outbound-road (load-json "outbound-road-counts" (str outboundRoad ".json"))
          service-date (get incoming "serviceDate")
          digest (get-in resident-road ["sources" road-source])]
      (require-match "atlas, weekday and streets" (select-keys run ["atlas" "day" "streets"]) versions)
      (doseq [report [incoming outbound outbound-clock resident-road incoming-road outbound-road]]
        (require-match "joint weekday" (get report "joint") jointRun))
      (doseq [report [incoming outbound resident-road]]
        (require-match "parent versions" (get report "versions") versions))
      (doseq [report [outbound resident-road]]
        (require-match "workplace releases" (get report "workplaces") workplaces))
      (doseq [report [incoming incoming-road]]
        (require-match "incoming commuter cohort" (get report "workerRelease") commuters))
      (doseq [report [incoming-road outbound-road]]
        (require-match "road graph" (get report "network") (get resident-road "network"))
        (require-match "road clock" (get report "clock") (get resident-road "clock")))
      (doseq [report [incoming-road outbound-road]]
        (require-match "road observation digest" (get-in report ["sources" road-source]) digest))
      (doseq [report [outbound outbound-clock]]
        (require-match "regional timetable" (get report "timetable") (get incoming "timetable")))
      (require-match "joint resident rail assignment" (get resident-transit "joint") true)
      (require-match "resident riders" (get incoming "residentRiders") riders)
      (require-match "incoming transit parent" (get outbound "incoming") incomingTransit)
      (require-match "outbound transit clock" (get outbound-clock "release") outboundTransit)
      (require-match "outbound transit bookings" (get outbound-clock "journeys") (get outbound "journeys"))
      (require-match "outbound road with transit clock" (get outbound-clock "road") outboundRoad)
      (require-match "resident timetable" (get resident-road "timetable") transit)
      (require-match "road jobs" (get outbound-road "jobs") outboundRoad)
      (require-match "road home fit" (get incoming-road "homeFit") fit)
      (require-match "bus service date" (get-in resident-road ["schedule" "date"]) service-date)
      (require-match "outbound transit service date" (get outbound "serviceDate") service-date)
      {:schema 1 :release release :windows windows :serviceDate service-date
       :parents {:jointRun jointRun :residentRiders riders :incomingTransit incomingTransit
                 :outboundTransit outboundTransit :outboundClock clock :outboundRoad outboundRoad
                 :incomingHomes fit :roadGraph (get resident-road "network")
                 :roadClock (get resident-road "clock") :municipalTimetable transit
                 :regionalTimetable (get incoming "timetable")}
       :roadObservation {:file road-source :sha256 digest}
       :sites (conj (mapv #(road-site resident-road incoming-road outbound-road %) bridge-keys)
                    (rail-site (get resident-transit "rail") (get incoming "rail") (get outbound-clock "rail")))})))

(defn -main [data-root release & [clock-id]]
  (when-not (and data-root (re-matches #"[a-f0-9]{64}" (or release ""))
                 (or (nil? clock-id) (re-matches #"[a-f0-9]{20}" clock-id)))
    (throw (ex-info "Usage: city.vancouver.downtown-audit DATA_ROOT DAY_RUN [OUTBOUND_CLOCK]" {})))
  (let [report (build data-root release clock-id)
        file (io/file data-root "vancouver" "downtown-audit" (str release ".json"))
        path (.toPath file)]
    (io/make-parents file)
    (let [temp (Files/createTempFile (.getParent path) ".audit-" ".tmp" (make-array FileAttribute 0))]
      (try
        (with-open [out (io/writer (.toFile temp) :encoding "UTF-8")]
          (json/write report out :escape-unicode false :escape-slash false))
        (Files/move temp path (into-array CopyOption [StandardCopyOption/ATOMIC_MOVE StandardCopyOption/REPLACE_EXISTING]))
        (finally (Files/deleteIfExists temp))))
    (println (.getPath file))))
