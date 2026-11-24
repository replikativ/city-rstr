(ns city.weekday
  "Prepare a versioned city dataset and execute resident weekday products."
  (:require [city.sim.weekday :as engine]
            [city.sim.schedule-pack :as pack]
            [clojure.edn :as edn]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.security MessageDigest DigestInputStream]
           [java.util HexFormat]))

(def execute engine/execute)

(defn presence [producer backend]
  (execute (engine/prepare-batches producer) backend))

(def ^:private datasets
  (edn/read-string (slurp (io/resource "city/datasets.edn"))))

(defn- prepare-source [{:keys [city schedules coverage release] :as spec}]
  (if (contains? spec :schedules)
    (cond-> (engine/prepare-batches
             (assoc (select-keys spec [:city :release :population :areas :day-start])
                    :batches! (fn [submit!] (submit! schedules))))
      release (assoc :source-release release))
    (let [{:keys [producer roots]} (get datasets (keyword city))
          root (get roots (or coverage "city"))]
      (when-not producer
        (throw (ex-info "Unknown weekday producer" {:city city})))
      (when (and roots (nil? root))
        (throw (ex-info "Unknown dataset coverage" {:city city :coverage coverage})))
      (let [inputs (cond-> spec
                     (and root (nil? (:root spec))) (assoc :root root))
            day (engine/prepare-batches ((requiring-resolve producer) inputs))]
        (when (and (:population spec) (not= (+ (:population spec) (if (:regionalWorkers spec) (:inbound spec) 0)) (:population day)))
          (throw (ex-info "Prepared population disagrees with release" {:release release})))
        (cond-> day release (assoc :source-release release))))))

(defn prepare [{:keys [schedule-pack release] :as spec}]
  (if schedule-pack
    (let [day (pack/read-pack schedule-pack)]
      (when (and release (not= release (:source-release day)))
        (throw (ex-info "Schedule pack belongs to another release" {:release release})))
      (when (some #(contains? spec %) [:seed :trip-rate :schedules :context :posterior])
        (throw (ex-info "A packed day has pinned generation parameters" {})))
      day)
    (prepare-source spec)))

(defn prepare-release
  "Load a published, checksummed schedule pack with no source database or city producer."
  [root release]
  (when-not (and (string? release) (re-matches #"[0-9a-f]{64}" release))
    (throw (ex-info "Invalid weekday release ID" {:release release})))
  (let [dir (io/file root "overview")
        ptr (with-open [r (io/reader (io/file dir (str release ".json")))]
              (json/read r :key-fn keyword))
        hash (:schedules ptr)
        digest (MessageDigest/getInstance "SHA-256")]
    (when-not (and (= release (:release ptr)) (string? hash) (re-matches #"[0-9a-f]{64}" hash))
      (throw (ex-info "Invalid weekday schedule pointer" {:release release})))
    (with-open [stream (DigestInputStream. (io/input-stream (io/file dir (str hash ".gz"))) digest)]
      (let [day (prepare {:schedule-pack stream :release release})]
        (when-not (= hash (.formatHex (HexFormat/of) (.digest digest)))
          (throw (ex-info "Weekday schedule checksum mismatch" {:release release})))
        day))))

(defn run [{:keys [backend products] :or {backend :jvm products #{:presence}} :as spec}]
  (let [day (if (:data-root spec)
              (do (when (seq (dissoc spec :data-root :release :backend :products))
                    (throw (ex-info "A published run takes a release, backend and products" {})))
                  (prepare-release (:data-root spec) (:release spec)))
              (prepare spec))]
    (execute day backend products)))

(defn -main [spec]
  (prn (run (edn/read-string spec))))
