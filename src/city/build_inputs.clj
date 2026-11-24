(ns city.build-inputs
  "Resolve the immutable input recipe of a published weekday before executing it."
  (:require [city.artifact :as artifact]
            [clojure.data.json :as json]
            [clojure.edn :as edn]
            [clojure.java.io :as io])
  (:import [java.io File]
           [java.nio.charset StandardCharsets]
           [java.security MessageDigest]
           [java.util HexFormat]))

(def ^:private recipes
  (delay (edn/read-string (slurp (io/resource "city/weekday-builds.edn")))))

(defn- read-json [file]
  (with-open [r (io/reader file)] (json/read r :key-fn keyword)))

(defn- sha256 [^File file]
  (if (.isFile file)
    (artifact/sha256-file file)
    (let [digest (MessageDigest/getInstance "SHA-256")]
      ;; These producer releases are flat. Include names as well as file bytes.
      (doseq [^File child (sort-by #(.getName ^File %) (.listFiles file))]
        (when-not (.isFile child)
          (throw (ex-info "Unexpected directory in a pinned release" {:file (.getPath child)})))
        (.update digest (.getBytes (str (artifact/sha256-file child) "  " (.getName child) "\n")
                                   StandardCharsets/UTF_8)))
      (.formatHex (HexFormat/of) (.digest digest)))))

(defn- checked-file [root [path expected]]
  (let [file (.getAbsoluteFile (io/file root path))]
    (when-not (.exists file)
      (throw (ex-info "Missing weekday build input" {:file (.getPath file)})))
    (let [actual (sha256 file)]
      (when-not (= expected actual)
        (throw (ex-info "Weekday build input checksum differs" {:file (.getPath file) :expected expected :actual actual}))))
    file))

(defn- checked-files [root entries]
  (into {} (map (fn [[k reference]] [k (checked-file root reference)])) entries))

(defn- recipe [root {:keys [release] :as run}]
  (let [entry (get-in @recipes [:builds release])]
    (when-not entry
      (throw (ex-info "Unknown pinned weekday build" {:release release})))
    (let [f (checked-file root [(str "runs/" release ".json") (:run-sha256 entry)])
          published (read-json f)]
      (when-not (and (= (select-keys entry [:city :coverage]) (select-keys published [:city :coverage]))
                     (= release (:release published))
                     (or (= published run) (= (dissoc published :files) run)))
        (throw (ex-info "Weekday build metadata differs from the pinned run" {:release release})))
      [entry published])))

(defn scenario-inputs
  "Verify just the Vancouver scenario files for standalone publication."
  [root run]
  (let [[entry _] (recipe root run)]
    (checked-files root (select-keys (:files entry) [:policy :market]))))

(defn- source-receipts [root archive release {:keys [sources city]} verify-sources?]
  ;; A separate producer-data directory still uses this project's source register.
  (let [beside-data (.getParentFile (.getCanonicalFile (io/file root)))
        public (if (.isFile (io/file beside-data "sources/weekday.json"))
                 beside-data (.getCanonicalFile (io/file "public")))
        register (json/read-str (slurp (checked-file public ["sources/weekday.json" (:source-register-sha256 @recipes)])))
        project (.getParentFile public)
        ids (if (= :published sources)
              (or (some #(when (and (= release (get % "release")) (= city (get % "city")))
                           (get % "sources")) (get register "runs"))
                  (throw (ex-info "Missing published source list" {:release release})))
              sources)]
    (into {}
          (for [source ids
                :let [record (or (get-in register ["sources" source])
                                 (throw (ex-info "Missing weekday source record" {:source source})))
                      archive-files (get record "files")
                      repository-files (get record "repositoryFiles")]]
            (do
              (when verify-sources?
                (doseq [reference archive-files] (checked-file archive reference))
                (doseq [reference repository-files] (checked-file project reference)))
              [source {:title (get record "title") :role (get record "role")
                       :locator (get record "locator") :url (get record "url")
                       :archive-files archive-files :repository-files repository-files}])))))

(defn resolve-inputs
  "Check a catalogue entry or complete run against its input pins. Returns absolute
   Files for the named build inputs, the Vancouver route-cache ID, and source receipts.
   root holds the producer datasets. archive contains Stuttgart's source world.
   :verify-sources? also rehashes cited archive/repository files for a scientific audit."
  ([root archive run] (resolve-inputs root archive run {}))
  ([root archive run {:keys [verify-sources?] :or {verify-sources? false}}]
   (let [[entry published] (recipe root run)
         release (:release published)
         files (checked-files root (:files entry))
         evidence (checked-files root (:evidence entry))
         archive-files (checked-files archive (:archive-files entry))
         city-files (when-let [dir (:release-files entry)]
                      (into {} (for [[k digest] (:files published)]
                                 [k (checked-file (io/file root dir) [(name k) digest])])))]
     (doseq [[k file] evidence]
       (when-not (= release (:release (read-json file)))
         (throw (ex-info "Evidence points at a different weekday" {:stage k :release release}))))
     (when-let [dir (:route-files files)]
       (let [m (read-json (io/file dir "manifest.json"))
             parents [:day :atlas :streets]]
         (when-not (and (= (select-keys published parents) (select-keys m parents))
                        (= (:driveProfileDigest m) (second (get-in entry [:files :drive-profile]))))
           (throw (ex-info "Route cache parents differ from weekday build" {:release release})))))
     (merge files {:release release :route-cache (:route-cache entry)
                   :archive-files archive-files :release-files city-files
                   :evidence evidence :source-bytes-verified? verify-sources?
                   :sources (source-receipts root archive release entry verify-sources?)}))))
