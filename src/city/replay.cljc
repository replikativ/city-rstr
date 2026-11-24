(ns city.replay
  "Published weekday selection and portable replay links.")

(defn order-runs [runs current]
  (sort-by (juxt #(if (contains? current (:release %)) 0 1)
                 #(if (:jointRun %) 0 1)
                 :coverage :release)
           runs))

(defn preferred-run [runs city coverage]
  (first (order-runs (filter #(and (= city (:city %)) (= coverage (:coverage %))) runs)
                     (into #{} (map :release) runs))))

(defn weekday-query [{:keys [city coverage release]}]
  (case city
    "stuttgart" (if release {"city" city "release" release} {"mode" "city"})
    "vancouver" (cond-> {}
                  (= coverage "region") (assoc "coverage" coverage)
                  release (assoc "dayRun" release))
    {}))

(defn change-city
  "Open the target city's published weekday at the displayed local time."
  [runs city minute]
  (when-let [run (or (when (= city "vancouver") (preferred-run runs city "region"))
                     (preferred-run runs city "city"))]
    (let [minute (some-> minute (mod 1440))]
      {:path (if (= city "stuttgart") "lab.html" "cityday.html")
       :query (cond-> (weekday-query run)
                (and minute (= city "stuttgart")) (assoc "hour" (str (/ minute 60.0)))
                (and minute (= city "vancouver")) (assoc "minute" (str (if (< minute 240) (+ minute 1440) minute))))})))

(defn read-context
  "Read the shared replay selection from current and archived link formats."
  [query default-city]
  (let [city (get query "city" default-city)]
    {:city city
     :coverage (if (= "region" (get query "coverage")) "region" "city")
     :release (get query (if (= city "stuttgart") "release" "dayRun"))
     :minute (get query "minute")
     :service (get query "service")}))

(def ^:private scope-specific-keys
  ["street" "at" "edge" "camera" "look" "roadSection" "hiredRides" "dispatchRun"
   "departureClock" "homeBlock" "bridgeChoice" "bridgeDestination" "housingRun" "shelterShock"
   "voting" "votingRun" "votingLayout" "votingSite" "votingDate" "votingSchedule"
   "workTransit" "personalTransit" "outingsRun" "outings" "recreationRun" "recreation"
   "schoolRun" "schools" "attendanceRun" "attendance" "easternOutingRun" "easternOutings"
   "granvilleRun" "granville" "granvilleGuest" "jointRun" "jointSite" "incomingTransit" "roadGate"
   "roadDirection" "roadVehicles" "outboundRoad" "outboundTransit" "outboundClock" "shoppingClock"
   "tripTiming" "transitShopping" "da" "area" "roster" "person" "resident" "shop" "hours"
   "shopPlay" "opened" "openings" "walks" "place" "cafe" "cohort" "policy" "policyArea"
   "commuters" "downtown" "workplaces" "workplaceRun" "workplaceBasis" "commute" "zones"
   "crossing" "crossingRun" "transitWalks" "riderRun" "marketRun" "dayRun" "coverage" "basket"
   "grocery" "shopCheck" "accessCheck" "localWalk" "bikeRoutes" "follow" "cycleTours" "tourZone"
   "tourPurpose" "scheduled" "clock"])

(def ^:private scope-specific-anchors
  #{"#granville-visitors" "#joint-weekday" "#joint-counts" "#incoming-road-crossings"
    "#outbound-road-jobs" "#outbound-transit-work" "#voting" "#trip-timing" "#shopping-clock-info"
    "#transit-shopping-info" "#market"})

(defn change-study-area
  "Carry portable playback state into the preferred run of the new study area.
   Resident IDs and interventions are tied to the source roster and release."
  [query anchor runs coverage]
  (let [{:keys [city minute service]} (read-context query "vancouver")
        run (preferred-run runs city coverage)
        base (apply dissoc query scope-specific-keys)
        target (weekday-query {:city city :coverage coverage :release (:release run)})]
    {:query (cond-> (merge base target)
              minute (assoc "minute" minute)
              service (assoc "service" service)
              (contains? query "roadTraffic") (assoc "roadTraffic" "observed")
              (not= "tags" (get query "buildingHeights")) (dissoc "buildingHeights")
              (and (contains? query "clock") (not (contains? query "scheduled")) (not (:jointRun run)))
              (assoc "clock" "household"))
     :anchor (if (contains? scope-specific-anchors anchor) "" anchor)}))
