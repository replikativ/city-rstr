(ns city.ui.remote
  "Small, stateless JSON adapter for the evidence and simulation APIs, or for
   the files of a static export."
  (:require [clojure.string :as str]))

(defn- json-content-type? [^js response]
  (when-let [content-type (.get (.-headers response) "content-type")]
    (let [media-type (-> content-type str/lower-case (str/split #";" 2) first str/trim)]
      (or (= media-type "application/json")
          (and (str/includes? media-type "/")
               (str/ends-with? media-type "+json"))))))

(defn fetch!
  "Fetch and keywordize JSON, rejecting unsuccessful or non-JSON responses."
  [url]
  (-> (js/fetch url)
      (.then (fn [^js response]
               (cond
                 (not (.-ok response))
                 (throw (js/Error.
                         (str "HTTP " (.-status response) " for " url)))

                 (not (json-content-type? response))
                 (throw (js/Error.
                         (str "Expected JSON from " url)))

                 :else (.json response))))
      (.then #(js->clj % :keywordize-keys true))))

(defn- param-string [value]
  (if (keyword? value) (name value) (str value)))

(defn request-url
  "Build a URL using the platform URL encoder. Nil parameter values are absent."
  [base {:keys [path params]}]
  (let [url (js/URL. path base)
        query (.-searchParams url)]
    (doseq [[key value] (sort-by (comp name key) params)
            :when (some? value)]
      (.set query (name key) (param-string value)))
    (.toString url)))

(defn request!
  "Fetch one catalogue request from its separately supplied API base URL.
  URL construction errors are rejected promises, like fetch and parse errors."
  [base request]
  (try
    (fetch! (request-url base request))
    (catch :default error
      (js/Promise.reject error))))
