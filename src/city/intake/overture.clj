(ns city.intake.overture
  "Overture Maps Places (CDLA-Permissive 2.0). Bulk parquet on S3, filtered
   by bbox with DuckDB in a helper script, then adopted with a receipt."
  (:require [city.intake.core :as acq]
            [clojure.java.shell :as sh]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]))

(def release "2026-08-19.0")
(def source {:source/id :overture-places
             :source/name "Overture Maps Foundation — Places"
             :source/url "https://docs.overturemaps.org/guides/places/"
             :source/license "CDLA-Permissive 2.0"})

(defn acquire-bbox! [{:keys [west south east north]} & {:keys [note]}]
  (let [url (str "s3://overturemaps-us-west-2/release/" release "/theme=places/type=place/")
        req {:source :overture-places :url url :body (pr-str [west south east north]) :ext "jsonl"}]
    (or (acq/cached-receipt req)
        (let [path (acq/cache-path req)
              _ (io/make-parents path)
              {:keys [exit out err]} (sh/sh "python3" "scripts/overture_places.py" release
                                            (str west) (str south) (str east) (str north) path)]
          (when-not (zero? exit) (throw (ex-info "overture extract failed" {:err err})))
          (acq/adopt! {:source :overture-places :dataset "places" :url url :path path
                       :note (merge {:bbox [west south east north] :rows (Long/parseLong (str/trim out))} note)})))))

(defn read-places [receipt]
  (with-open [r (io/reader (:acq/path receipt))]
    (->> (line-seq r) (mapv #(json/read-str % :key-fn keyword)))))
