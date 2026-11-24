(ns city.run-catalog
  "Publish the city library from an existing Stuttgart static export and Vancouver releases."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]
            [city.intake.core :as intake])
  (:import [java.io FileOutputStream]
           [java.nio.file CopyOption Files StandardCopyOption]
           [java.nio.file.attribute FileAttribute PosixFilePermissions]
           [java.security MessageDigest]
           [java.util HexFormat]))

(defn- load-json [file]
  (json/read-str (slurp file :encoding "UTF-8") :key-fn keyword))

(def ^:private public-permissions
  (into-array FileAttribute [(PosixFilePermissions/asFileAttribute (PosixFilePermissions/fromString "rw-r--r--"))]))

(defn- write-bytes! [file bytes]
  (io/make-parents file)
  (let [path (.toPath file)
        tmp (Files/createTempFile (.getParent path) ".publish-" ".tmp" public-permissions)]
    (try
      (with-open [out (io/output-stream (.toFile tmp))] (.write out ^bytes bytes))
      (Files/move tmp path (into-array CopyOption [StandardCopyOption/ATOMIC_MOVE StandardCopyOption/REPLACE_EXISTING]))
      (finally (Files/deleteIfExists tmp)))))

(defn- write-json! [file value]
  (write-bytes! file (.getBytes (json/write-str value) "UTF-8")))

(defn- release [metadata]
  (assoc metadata :release (intake/sha256-str (json/write-str (into (sorted-map) metadata)))))

(defn- district-outcomes [read-file scenarios]
  (mapv (fn [{:keys [key label]}]
          (let [rows (:districts (read-file (str "scenario-" key ".json")))]
            (when (or (empty? rows) (not= (count rows) (count (set (map :district rows)))))
              (throw (ex-info "Missing or repeated scenario districts" {:scenario key})))
            {:key key :label label
             :districts (mapv (fn [{:keys [district delta-total]}]
                                (let [{:keys [mean q05 q95]} delta-total]
                                  (when-not (and (string? district) (every? number? [mean q05 q95]) (<= q05 q95))
                                    (throw (ex-info "Invalid district turnover distribution" {:district district :scenario key})))
                                  [district mean q05 q95])) rows)}))
        scenarios))

(defn- stuttgart! [root source]
  (let [read-bytes (memoize #(Files/readAllBytes (.toPath (io/file source %))))
        read-file #(json/read-str (String. ^bytes (read-bytes %) "UTF-8") :key-fn keyword)
        meta (read-file "meta.json")
        residents (get-in meta [:world :persons])
        commuters (get-in meta [:world :commute :external-in-commuters])
        scenarios (:scenarios (read-file "scenarios.json"))
        _ (when-not (and (= "stuttgart" (:city meta)) (pos-int? residents) (nat-int? commuters)
                         (= (:persons meta) (+ residents commuters))
                         (every? #(re-matches #"[a-z0-9-]+" (:key %)) scenarios))
            (throw (ex-info "Invalid Stuttgart simulation export" {:source source})))
        names (concat ["layers.json" "meta.json" "scenarios.json" "series.json" "stops.json" "trips.json"
                       "aggregates.json" "econ.json" "revenue.json" "visits.json" "cells.json"
                       "areas-stadtteil.json" "areas-stadtbezirk.json"]
                      (map #(str "scenario-" (:key %) ".json") scenarios))
        files (into (sorted-map) (for [n names] [n (read-bytes n)]))
        hashes (into (sorted-map)
                     (for [[n bytes] files]
                       [n (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") ^bytes bytes))]))
        run (release {:city "stuttgart" :coverage "city" :label "Stuttgart weekday" :population residents :inbound commuters
                      :files hashes :scenarios (district-outcomes read-file scenarios)})]
    (doseq [[n bytes] files] (write-bytes! (io/file root "stuttgart" (:release run) n) bytes))
    run))

(defn- vancouver [root region? & [requested-day requested-atlas requested-streets]]
  (let [base (if region? (io/file root "vancouver" "region") (io/file root "vancouver"))
        read-file #(load-json (io/file base %))
        versions (if region? (select-keys (read-file "current.json") [:atlas :day :streets :transit])
                     (let [{:keys [atlas version]} (read-file "cityday/current.json")]
                       {:atlas atlas :day version :streets (:version (read-file "streets/current.json"))}))
        versions (cond-> versions
                   requested-day (assoc :day requested-day)
                   requested-atlas (assoc :atlas requested-atlas)
                   requested-streets (assoc :streets requested-streets))
        _ (when-not (every? #(and (string? %) (re-matches #"[a-f0-9]{20}" %))
                            (map versions (cond-> [:atlas :day :streets] region? (conj :transit))))
            (throw (ex-info "Invalid Vancouver weekday release" versions)))
        day (read-file (str "cityday/" (:day versions) "/day.json"))
        atlas (read-file (str "atlas/" (:atlas versions) "/atlas.json"))
        worker-file (io/file base "incoming-workers" (str (:atlas versions) ".json"))
        worker-id (when (and region? (.isFile worker-file)) (:version (load-json worker-file)))
        workers (when worker-id (read-file (str "incoming-workers/" worker-id "/commuters.json")))
        _ (when (and workers (not= [(:atlas versions) (:places workers)]
                                    [(:atlas workers) (intake/sha256-str (slurp (io/file base "cityday" (:day versions) "places.json")))]))
            (throw (ex-info "Regional workers and weekday places disagree" versions)))
        audit-file (io/file base "atlas" (str "boundary-" (:atlas versions) ".json"))
        audit (when (.isFile audit-file) (load-json audit-file))
        matched? (and audit (= (:atlas versions) (:atlas audit))
                      (= (:population day) (:municipalPopulation audit))
                      (= (count (:das atlas)) (:inReplay audit) (:municipalAreas audit))
                      (= {} (:adjacent audit) (:missing audit)))]
    (when-not (and (pos-int? (:population day)) (= (:population day) (get-in atlas [:city :population]))
                   (.isFile (io/file base "streets" (:streets versions) "streets.json")))
      (throw (ex-info "Vancouver weekday, population and streets must be present and agree" versions)))
    (let [label (if region? "Vancouver, UBC & North Shore" "City of Vancouver")]
      (release (merge versions (when workers {:regionalWorkers worker-id
                                               :inbound (transduce (map :attending) + (vals (:groups workers)))})
                      (when matched? {:matchedCensusAreas (:municipalAreas audit)})
                      (when-let [placement (:homePlacement day)] {:homePlacement placement})
                      (when-let [fit (:diaryFit day)] {:diaryFit fit})
                      {:city "vancouver" :coverage (if region? "region" "city")
                       :label (cond-> label
                                (:homePlacement day) (str " · Census-block homes")
                                (= "household-income" (get-in day [:diaryFit :kind])) (str " · Income-fitted diaries")
                                (= "income-and-home-zone" (get-in day [:diaryFit :kind])) (str " · Income- and home-zone-fitted diaries"))
                       :population (:population day)})))))

(defn- publish-block-day! [root region? day]
  (when-not (and (string? day) (re-matches #"[a-f0-9]{20}" day))
    (throw (ex-info "Expected the fitted weekday identifier" {:day day})))
  (let [base (if region? (io/file root "vancouver" "region") (io/file root "vancouver"))
        folder (io/file base "cityday" day)
        stats (load-json (io/file folder "home-placement.json"))
        fit (vancouver root region? day (:atlas stats))
        {:keys [kind baselineDay]} (:homePlacement fit)]
    (when-not (and (= "census-blocks" kind) (= (:atlas stats) (:atlas fit)) (= (:baselineDay stats) baselineDay)
                   (= (:population fit) (get-in stats [:summary :population]))
                   (= (count (:sample (load-json (io/file folder "day.json")))) (get-in stats [:summary :animationSample]))
                   (= 0 (get-in stats [:summary :homeError])))
      (throw (ex-info "The census-block home report and weekday differ" {:day day})))
    (let [baseline (vancouver root region? baselineDay (:atlas stats))
          pair {:atlas (:atlas fit) :baselineDay baselineDay :day day
                :baselineRun (:release baseline) :dayRun (:release fit)}]
      (doseq [run [baseline fit]] (write-json! (io/file root "runs" (str (:release run) ".json")) run))
      (write-json! (io/file base "home-placement" (str (:atlas fit) "_" baselineDay ".json")) pair)
      pair)))

(defn- publish-diary-day! [root day]
  (when-not (and (string? day) (re-matches #"[a-f0-9]{20}" day))
    (throw (ex-info "Expected the diary-fitted weekday identifier" {:day day})))
  (let [base (io/file root "vancouver")
        model (load-json (io/file base "cityday" day "day.json"))
        {:keys [kind baselineAtlas baselineDay fittedAtlas]} (:diaryFit model)
        report (load-json (io/file base "diary-fit" (str fittedAtlas ".json")))
        fit (vancouver root false day fittedAtlas)
        baseline (vancouver root false baselineDay baselineAtlas)
        pair-file (io/file base "diary-fit" (str baselineAtlas "_" baselineDay ".json"))
        previous (when (.isFile pair-file) (load-json pair-file))]
    (when-not (and (#{"household-income" "income-and-home-zone"} kind) (= baselineAtlas (:atlas report))
                   (= fittedAtlas (:fittedAtlas report))
                   (= (select-keys fit [:atlas :day :streets]) (:locations report))
                   (= (:streets baseline) (:streets fit))
                   (= (:population baseline) (:population fit)))
      (throw (ex-info "The diary calibration and weekday differ" {:day day})))
    (doseq [run [baseline fit]]
      (write-json! (io/file root "runs" (str (:release run) ".json")) run))
    (let [pair (if (= kind "income-and-home-zone")
                 (do
                   (when-not (and (= (:release baseline) (:baselineRun previous)) (= (:incomeFit report) (:fittedAtlas previous)))
                     (throw (ex-info "The geographic diary fit requires its published income comparison" {:day day})))
                   (assoc previous :zoneRun (:release fit) :zonalAtlas fittedAtlas))
                 (cond-> {:baselineRun (:release baseline) :fittedRun (:release fit) :fittedAtlas fittedAtlas}
                   (= fittedAtlas (:fittedAtlas previous)) (merge (select-keys previous [:zoneRun :zonalAtlas]))))]
      (write-json! pair-file pair)
      pair)))

(defn- publish-catalog! [root runs]
  (let [index (io/file root "runs" "current.json")
        key-for (juxt :city :coverage #(boolean (:jointRun %)))]
    (doseq [run runs] (write-json! (io/file root "runs" (str (:release run) ".json")) run))
    ;; Two separate city builds may publish concurrently. Switch their entries together.
    (with-open [out (FileOutputStream. (io/file root "runs" ".publish.lock") true)
                lock (.lock (.getChannel out))]
      (let [previous (when (.isFile index) (load-json index))
            catalog (into (sorted-map) (map (juxt key-for identity)) (concat previous (map #(dissoc % :files) runs)))]
        (write-json! index (vec (vals catalog)))))
    (mapv (juxt :label :release) runs)))

(defn- publish-combined-weekday! [root id requested-incoming requested-outbound requested-transit]
  (let [valid? #(and (string? %) (re-matches #"[a-f0-9]{20}" %))
        _ (when-not (valid? id)
            (throw (ex-info "Expected the combined weekday identifier" {:jointRun id})))
        base (io/file root "vancouver")
        joint (load-json (io/file base "joint-weekday" id "report.json"))
        {atlas :atlas day :day :as versions} (:versions joint)
        incoming-id (or requested-incoming (:version (load-json (io/file base "incoming-transit" (str id ".json")))))
        _ (when-not (valid? incoming-id)
            (throw (ex-info "Expected the incoming transit identifier" {:incomingTransit incoming-id})))
        incoming (load-json (io/file base "incoming-transit" incoming-id "report.json"))
        fit-id (get-in incoming [:homeFit :version])
        _ (when (and fit-id (not (valid? fit-id)))
            (throw (ex-info "Invalid incoming home fit identifier" {:incomingTransit incoming-id})))
        fit (when fit-id (load-json (io/file base "incoming-home-fit" fit-id "report.json")))
        _ (when (and requested-outbound (not (valid? requested-outbound)))
            (throw (ex-info "Expected the mapped outbound workplace identifier" {:outboundRoad requested-outbound})))
        outbound (when requested-outbound
                   (load-json (io/file base "outbound-road-jobs" requested-outbound "report.json")))
        outgoing-counts (when outbound (load-json (io/file base "outbound-road-counts" (str requested-outbound ".json"))))
        metro-map (when outbound (load-json (io/file base "commuter-basemap" (str (:network outbound) ".json"))))
        paired-road-fit (when outbound (or fit-id (:version (load-json (io/file base "incoming-home-fit" (str id ".json"))))))
        incoming-drives (when outbound (load-json (io/file base "incoming-drives" (str paired-road-fit ".json"))))
        _ (when (and requested-transit (not (valid? requested-transit)))
            (throw (ex-info "Expected the outbound transit identifier" {:outboundTransit requested-transit})))
        outbound-transit (when requested-transit
                           (load-json (io/file base "outbound-transit" requested-transit "report.json")))
        transit-audit (when outbound-transit
                        (load-json (io/file base "outbound-transit-audit" (str requested-transit ".json"))))
        worker-cohort (load-json (io/file base "commuters" (:commuters joint) "commuters.json"))
        resident (vancouver root false day atlas (:streets versions))]
    (when-not (and (= (select-keys resident [:atlas :day :streets]) versions (:versions incoming))
                   (= (select-keys versions [:atlas :day]) (:versions worker-cohort))
                   (= (:population resident) (:people joint))
                   (:capacityChecked joint) (:transfers joint) (= 0 (get-in incoming [:bus :above]))
                   (= id (:joint incoming)) (= (:riders joint) (:residentRiders incoming))
                   (= (:commuters joint) (:workerRelease incoming))
                   (or (nil? fit) (and (= id (:joint fit)) (= (:commuters joint) (:workerRelease fit))
                                      (= (get-in incoming [:homeFit :fitBasis] (get-in incoming [:homeFit :baseline])) (:baseline fit)))))
      (throw (ex-info "The combined weekday and incoming transit release disagree" {:jointRun id :incomingTransit incoming-id})))
    (when (and outbound
               (not (and (= id (:joint outbound) (:joint outgoing-counts) (:joint incoming-drives))
                         (= versions (:versions outbound))
                         (= (:workplaces joint) (:workplaces outbound))
                         (= (:network outbound) (:network outgoing-counts) (:network metro-map) (:network incoming-drives))
                         (= "free-flow" (:clock outbound) (:clock outgoing-counts) (:basis incoming-drives))
                         (= requested-outbound (:jobs outgoing-counts))
                         (= 1440 (count (get-in outgoing-counts [:workClock :counts])))
                         (= (transduce (keep :locatedDriverLegs) + (vals (:coverage outbound)))
                            (get-in outgoing-counts [:coverage :legs])))))
      (throw (ex-info "The combined weekday and mapped outbound workplaces disagree" {:jointRun id :outboundRoad requested-outbound})))
    (when (and outbound-transit
               (not (and (= id (:joint outbound-transit) (:joint transit-audit))
                         (= incoming-id (:incoming outbound-transit))
                         (= versions (:versions outbound-transit))
                         (= (:workplaces joint) (:workplaces outbound-transit))
                         (= (:timetable incoming) (:timetable outbound-transit) (:timetable transit-audit))
                         (= requested-transit (:release transit-audit))
                         (= requested-outbound (:road transit-audit))
                         (= 0 (get-in outbound-transit [:bus :above]))
                         (= 1440 (count (get-in transit-audit [:workClock :counts])))
                         (= (:journeys outbound-transit) (+ (:direct transit-audit) (:oneTransfer transit-audit) (:twoTransfers transit-audit))))))
      (throw (ex-info "The outbound transit release and its audit differ from the combined weekday" {:jointRun id :outboundTransit requested-transit})))
    (publish-catalog! root [(release (cond-> (assoc (dissoc resident :release)
                                               :label "City of Vancouver · Combined weekday"
                                               :jointRun id :incomingTransit incoming-id
                                               :inbound (transduce (map :attending) + (vals (:groups worker-cohort))))
                                      outbound (assoc :outboundRoad requested-outbound)
                                      outbound-transit (assoc :outboundTransit requested-transit)))])))

(defn publish! [root scope stuttgart-source]
  (let [runs (case scope
               "all" [(stuttgart! root stuttgart-source) (vancouver root false) (vancouver root true)]
               "stuttgart" [(stuttgart! root stuttgart-source)]
               "vancouver" [(vancouver root false)]
               "region" [(vancouver root true)]
               (throw (ex-info "Expected all, stuttgart, vancouver or region" {:scope scope})))]
    (publish-catalog! root runs)))

(defn -main [& [scope source root incoming outgoing outgoing-transit]]
  (let [root (or root "public/data")]
    (cond
      (#{"vancouver-block-homes" "region-block-homes"} scope)
      (prn (publish-block-day! root (= scope "region-block-homes") source))
      (= "vancouver-diary-fit" scope)
      (prn (publish-diary-day! root source))
      (= "vancouver-combined-weekday" scope)
      (prn (publish-combined-weekday! root source incoming outgoing outgoing-transit))
      :else
      (prn (publish! root (or scope "all") (or source "dist/lab/data/stuttgart"))))))
