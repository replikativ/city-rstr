(ns city.overview
  "Publish the same minute-by-area product for both city explorers."
  (:require [city.artifact :as artifact]
            [city.weekday :as weekday]
            [city.overview-cases :as cases]
            [city.sim.schedule-pack :as pack]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.nio.file Files]))

(defn- read-json [file]
  (with-open [r (io/reader file)] (json/read r :key-fn keyword)))

(defn- geography [root {:keys [city atlas coverage release]} inputs]
  (case city
    "stuttgart" (into {} (for [f (:features (read-json (io/file root city release "areas-stadtteil.json")))]
                            [(get-in f [:properties :eid]) (:geometry f)]))
    "vancouver" (let [base (if (= coverage "region") (io/file root city "region") (io/file root city))
                      roster (or (:roster inputs) (io/file base "atlas" atlas))]
                  (into {} (for [[area v] (:areas (read-json (io/file roster "atlas.json")))]
                             [(name area) (:geometry v)])))))

(defn scene [day shapes]
  (let [features (keep-indexed
                  (fn [i area]
                    (when-not (keyword? area)
                      (let [id (if (map? area) (:eid area) area)]
                        {:type "Feature" :id i :properties {:label (if (map? area) (:name area) area)}
                         :geometry (or (get shapes id) (throw (ex-info "Missing area geometry" {:area area})))})))
                  (:areas day))]
    {:version 1 :population (:population day) :dayStart (:day-start day)
     :basis (:schedule-basis day) :release (:source-release day)
     :areas (mapv #(if (map? %) (:name %) (name %)) (:areas day))
     :geography {:type "FeatureCollection" :features (vec features)}
     :flows (:od-flows day) :presence (:presence day) :arrivals (get-in day [:trip-ends :arrivals])
     :departures (get-in day [:trip-ends :departures])}))

(defn publish-cases!
  ([root run] (publish-cases! root run nil))
  ([root run inputs]
   (let [scenarios (if inputs (cases/scenarios root run inputs) (cases/scenarios root run))
         bytes (.getBytes (json/write-str scenarios) "UTF-8")
         hash (artifact/sha256 bytes)
         dir (io/file root "overview")]
     (artifact/publish-file! (io/file dir (str hash ".json")) bytes)
     (artifact/publish-file! (io/file dir (str (:release run) "-cases.json"))
                             (.getBytes (json/write-str {:release (:release run) :cases hash}) "UTF-8")))))

(defn- write-agent! [^java.io.DataOutputStream out stops]
  (let [append (fn [rows [minute lon lat]]
                 (when-not (and (<= 0 minute 1439) (<= -180 lon 180) (<= -90 lat 90))
                   (throw (ex-info "Invalid agent anchor" {:minute minute :coordinates [lon lat]})))
                 (let [prior (peek rows)
                       row [(int minute) (Math/round (* 1e5 (double lon))) (Math/round (* 1e5 (double lat)))]]
                   (cond
                     (and prior (<= minute (first prior))) (conj (pop rows) (assoc row 0 (first prior)))
                     (= (next row) (next prior)) rows
                     :else (conj rows row))))
        records (reduce append [] stops)]
    (when-not (= 0 (ffirst records)) (throw (ex-info "An agent needs a starting anchor" {})))
    (.writeShort out (count records))
    (doseq [[minute lon lat] records]
      (.writeShort out minute)
      (.writeInt out lon)
      (.writeInt out lat))))

(defn- prepare-positions! [root spec]
  (let [dir (io/file root "overview")
        _ (.mkdirs dir)
        temp (java.io.File/createTempFile ".agents-" ".gz" dir)
        n (+ (:population spec) (or (:inbound spec) 0))
        seen (volatile! 0)]
    (try
      (let [day (with-open [out (java.io.DataOutputStream.
                                 (java.io.BufferedOutputStream. (java.util.zip.GZIPOutputStream. (io/output-stream temp))))]
                  (.writeInt out 0x43524131)
                  (.writeInt out n)
                  (weekday/prepare
                   (assoc spec :position-fn
                          (fn [stops]
                            (write-agent! out stops)
                            (vswap! seen inc)))))
            hash (artifact/sha256-file temp)]
        (when-not (= n @seen) (throw (ex-info "Incomplete agent positions" {:expected n :actual @seen})))
        (artifact/publish-staged-file! temp (io/file dir (str hash ".gz")))
        [day hash])
      (finally (Files/deleteIfExists (.toPath temp))))))

(defn publish-day!
  "Prepare and publish the roster, packed schedules, numerical products and scenarios."
  [root {:keys [release] :as run} inputs]
  (let [root (io/file root)
        city (:city run)
        dir (if (= "region" (:coverage run)) (io/file root city "region") (io/file root city))
        [prepared agents] (prepare-positions! root (assoc run :root (.getPath dir) :producer-inputs inputs
                                                          :boundary-file (io/file root city release "areas-stadtteil.json")))
        result (weekday/execute prepared :jvm #{:presence :trip-ends :od-flows})
        bytes (.getBytes (json/write-str (scene result (geography root run inputs))) "UTF-8")
        hash (artifact/sha256 bytes)]
    (artifact/publish-file! (io/file root "overview" (str hash ".json")) bytes)
    (let [dir (io/file root "overview")
          temp (java.io.File/createTempFile ".schedules-" ".gz" dir)]
      (try
        (pack/write-pack! temp prepared)
        (let [digest (artifact/sha256-file temp)]
          (artifact/publish-staged-file! temp (io/file dir (str digest ".gz")))
          (artifact/publish-file! (io/file dir (str release ".json"))
                         (.getBytes (json/write-str {:release release :scene hash :schedules digest :agents agents}) "UTF-8")))
        (finally (Files/deleteIfExists (.toPath temp)))))
    (publish-cases! root run inputs)
    {:city city :release release :scene hash}))

(defn -main [data-root release]
  (when-not (re-matches #"[0-9a-f]{64}" release)
    (throw (ex-info "Expected a published run ID" {})))
  (let [run (read-json (io/file data-root "runs" (str release ".json")))]
    (when-not (= release (:release run))
      (throw (ex-info "Release identity mismatch" {})))
    (println (publish-day! data-root run nil))))
