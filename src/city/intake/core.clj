(ns city.intake.core
  "Acquisition with receipts.

   Every fetch lands in a content-addressed local cache and produces a
   receipt: source, url, sha256, size, time, local path. Receipts are the
   provenance handle every derived entity points back to. Re-fetching the
   same url reuses the cached bytes and receipt, so loads are idempotent
   and `clean!` is the one way to start over."
  (:require [hato.client :as http]
            [clojure.java.io :as io]
            [clojure.edn :as edn]
            [clojure.string :as str])
  (:import [java.security MessageDigest]
           [java.io InputStream File]
           [java.time Instant]))

(def ^:dynamic *cache-dir* "data/raw")

(defn- hex [^bytes bs]
  (apply str (map #(format "%02x" (bit-and % 0xff)) bs)))

(defn sha256-str [^String s]
  (hex (.digest (MessageDigest/getInstance "SHA-256") (.getBytes s "UTF-8"))))

(defn- copy-hashing!
  "Stream `in` to `file`, returning [sha256 byte-count]."
  [^InputStream in ^File file]
  (let [md (MessageDigest/getInstance "SHA-256")
        buf (byte-array 65536)]
    (io/make-parents file)
    (with-open [out (io/output-stream file)]
      (loop [n 0]
        (let [k (.read in buf)]
          (if (neg? k)
            [(hex (.digest md)) n]
            (do (.update md buf 0 k)
                (.write out buf 0 k)
                (recur (+ n k)))))))))

(defn cache-path
  "Deterministic cache location for a request: <cache>/<source>/<sha(url+body)>.<ext>"
  [{:keys [source url body ext]}]
  (str *cache-dir* "/" (name source) "/" (sha256-str (str url "\n" body)) "." (or ext "bin")))

(defn- receipt-path [path] (str path ".receipt.edn"))

(defn cached-receipt [req]
  (let [p (receipt-path (cache-path req))]
    (when (.exists (io/file p))
      (edn/read-string (slurp p)))))

(defn acquire!
  "Fetch `url` (GET, or POST when `body` is given) into the cache and return
   a receipt. `source` is a keyword naming the provider; `dataset` and
   `note` are free-form and travel with the receipt. Cached requests return
   the stored receipt without touching the network unless `:force? true`."
  [{:keys [source url body ext dataset note headers force? method]
    :or {method (if body :post :get)} :as req}]
  (or (when-not force? (cached-receipt req))
      (let [path (cache-path req)
            resp (http/request (cond-> {:method method :url url :as :stream
                                        ;; never hang a load on a stalled server (Overpass has done it for hours)
                                        :timeout 600000 :connect-timeout 30000
                                        :headers (merge {"user-agent" "city-sim/0.1 (research; contact via repo)"} headers)}
                                 body (assoc :body body
                                             :content-type :x-www-form-urlencoded)))
            _ (when-not (<= 200 (:status resp) 299)
                (throw (ex-info "acquire failed" {:status (:status resp) :url url})))
            [sha n] (copy-hashing! (:body resp) (io/file path))
            receipt {:acq/id (random-uuid)
                     :acq/source source
                     :acq/dataset dataset
                     :acq/url url
                     :acq/body body
                     :acq/sha256 sha
                     :acq/bytes n
                     :acq/fetched-at (java.util.Date.)
                     :acq/path path
                     :acq/status (:status resp)
                     :acq/note note}]
        (spit (receipt-path path) (pr-str receipt))
        receipt)))

(defn receipts
  "All receipts in the cache, newest first."
  []
  (->> (file-seq (io/file *cache-dir*))
       (filter #(str/ends-with? (.getName ^File %) ".receipt.edn"))
       (map #(edn/read-string (slurp %)))
       (sort-by :acq/fetched-at #(compare %2 %1))))

(defn clean!
  "Delete the cache for one source, or everything when called without args."
  ([] (clean! nil))
  ([source]
   (let [dir (io/file (cond-> *cache-dir* source (str "/" (name source))))]
     (doseq [f (reverse (file-seq dir))] (.delete ^File f))
     (str "cleaned " dir))))

(defn adopt!
  "Register a file that was downloaded outside `acquire!` (large bulk pulls
   done with curl, DuckDB extracts) as a receipt. The file stays where it is."
  [{:keys [source url path dataset note]}]
  (let [f (io/file path)
        _ (when-not (.exists f) (throw (ex-info "adopt!: file missing" {:path path})))
        [sha n] (with-open [in (io/input-stream f)]
                  (let [md (MessageDigest/getInstance "SHA-256") buf (byte-array 65536)]
                    (loop [n 0] (let [k (.read in buf)]
                                  (if (neg? k) [(hex (.digest md)) n]
                                      (do (.update md buf 0 k) (recur (+ n k))))))))
        receipt {:acq/id (random-uuid) :acq/source source :acq/dataset dataset :acq/url url
                 :acq/sha256 sha :acq/bytes n :acq/fetched-at (java.util.Date. (.lastModified f))
                 :acq/path path :acq/status 200 :acq/note note}]
    (spit (receipt-path path) (pr-str receipt))
    receipt))
