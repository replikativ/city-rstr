(ns city.overview
  "Publish the same minute-by-area product for both city explorers."
  (:require [city.weekday :as weekday]
            [city.overview-cases :as cases]
            [city.sim.schedule-pack :as pack]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.nio.file Files StandardCopyOption]
           [java.security MessageDigest]
           [java.util HexFormat]))

(defn- read-json [file]
  (with-open [r (io/reader file)] (json/read r :key-fn keyword)))

(defn- geography [root {:keys [city atlas coverage release]}]
  (case city
    "stuttgart" (into {} (for [f (:features (read-json (io/file root city release "areas-stadtteil.json")))]
                            [(get-in f [:properties :eid]) (:geometry f)]))
    "vancouver" (let [dir (if (= coverage "region") (io/file root city "region") (io/file root city))]
                  (into {} (for [[area v] (:areas (read-json (io/file dir "atlas" atlas "atlas.json")))]
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

(defn- publish-file! [file bytes]
  (io/make-parents file)
  (let [path (.toPath file)
        temp (Files/createTempFile (.getParent path) ".scene-" ".tmp" (make-array java.nio.file.attribute.FileAttribute 0))]
    (try (with-open [out (io/output-stream (.toFile temp))] (.write out ^bytes bytes))
         (.setReadable (.toFile temp) true false)
         (Files/move temp path (into-array StandardCopyOption [StandardCopyOption/ATOMIC_MOVE StandardCopyOption/REPLACE_EXISTING]))
         (finally (Files/deleteIfExists temp)))))

(defn publish-cases! [root run]
  (let [bytes (.getBytes (json/write-str (cases/scenarios root run)) "UTF-8")
        hash (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") bytes))
        dir (io/file root "overview")]
    (publish-file! (io/file dir (str hash ".json")) bytes)
    (publish-file! (io/file dir (str (:release run) "-cases.json"))
                   (.getBytes (json/write-str {:release (:release run) :cases hash}) "UTF-8"))))

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
            bytes (Files/readAllBytes (.toPath temp))
            hash (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") bytes))]
        (when-not (= n @seen) (throw (ex-info "Incomplete agent positions" {:expected n :actual @seen})))
        (publish-file! (io/file dir (str hash ".gz")) bytes)
        [day hash])
      (finally (Files/deleteIfExists (.toPath temp))))))

(defn -main [data-root release]
  (when-not (re-matches #"[0-9a-f]{64}" release) (throw (ex-info "Expected a published run ID" {})))
  (let [root (io/file data-root)
        run (read-json (io/file root "runs" (str release ".json")))
        _ (when-not (= release (:release run)) (throw (ex-info "Release identity mismatch" {})))
        city (:city run)
        dir (if (= "region" (:coverage run)) (io/file root city "region") (io/file root city))
        [prepared agents] (prepare-positions! root (assoc run :root (.getPath dir)
                                   :boundary-file (io/file root city release "areas-stadtteil.json")))
        result (weekday/execute prepared :jvm #{:presence :trip-ends :od-flows})
        bytes (.getBytes (json/write-str (scene result (geography root run))) "UTF-8")
        hash (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") bytes))]
    (publish-file! (io/file root "overview" (str hash ".json")) bytes)
    (let [dir (io/file root "overview")
          temp (java.io.File/createTempFile ".schedules-" ".gz" dir)]
      (try
        (pack/write-pack! temp prepared)
        (let [bytes (Files/readAllBytes (.toPath temp))
              digest (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") bytes))]
          (publish-file! (io/file dir (str digest ".gz")) bytes)
          (publish-file! (io/file dir (str release ".json"))
                         (.getBytes (json/write-str {:release release :scene hash :schedules digest :agents agents}) "UTF-8")))
        (finally (Files/deleteIfExists (.toPath temp)))))
    (publish-cases! root run)
    (println city release hash)))
