(ns city.ui.experiments
  "Local city experiments, persisted by Datahike in browser IndexedDB."
  (:require [cljs.core.async :as async]
            [datahike.api :as d]
            [city.experiment :as experiment]
            [konserve.indexeddb]
            [konserve.memory :as memory]
            [konserve.tiered]))

(def store-id #uuid "28667a78-3f36-4714-8f62-2514a2406cc4")
(def store-name "city-rstr-experiments")
(def config {:name store-name
             :store {:backend :tiered :id store-id
                     :frontend-config {:backend :memory :id store-id}
                     :backend-config {:backend :indexeddb :name store-name :id store-id}}
             :value-caps :default
             :schema-flexibility :write :keep-history? false})

(defn- result [ch]
  (js/Promise. (fn [resolve reject]
                 (async/take! ch #(if (instance? js/Error %) (reject %) (resolve %))))))

(defn- ensure-schema [conn]
  (let [known (set (d/q '[:find [?attr ...] :where [_ :db/ident ?attr]] @conn))
        missing (filterv (fn [{:db/keys [ident maxLength]}]
                           (or (not (known ident))
                               (and maxLength (not= maxLength (:db/maxLength (d/entity @conn [:db/ident ident]))))))
                         experiment/schema)]
    (when (seq missing) (result (d/transact! conn missing)))))

(defn- access [operation]
  ;; Each tab opens the latest persisted head under the same origin lock.
  (.request (.-locks js/navigator) store-name
    (fn []
      ;; Konserve retains memory frontends across releases. Another tab may
      ;; have advanced the IndexedDB head since this tab's previous operation.
      (memory/delete-mem-store store-id)
      (-> (result (d/database-exists? config {:sync? false}))
          (.then #(when-not % (result (d/create-database (assoc config :initial-tx experiment/schema)))))
          (.then #(result (d/connect config {:sync? false})))
          (.then (fn [conn]
                   (-> (js/Promise.resolve nil) (.then #(ensure-schema conn)) (.then #(operation conn))
                       (.finally #(d/release conn)))))))))

(defn release-manifest [city release]
  (access #(clj->js (experiment/release-manifest @% city release))))

(defn index-manifest! [record]
  (let [manifest (js->clj record :keywordize-keys true)]
    (access (fn [conn]
              (let [tx (experiment/register-runs @conn [manifest])]
                (-> (js/Promise.resolve (when (seq tx) (result (d/transact! conn tx))))
                    (.then #(clj->js (experiment/release-manifest @conn (:city manifest) (:release manifest))))))))))

(defn run-library [catalog]
  (access
    (fn [conn]
      (let [tx (experiment/register-runs @conn catalog)]
        (-> (js/Promise.resolve (when (seq tx) (result (d/transact! conn tx))))
            (.then (fn [_] {:runs (vec (experiment/published-runs @conn))
                            :openings (vec (experiment/saved-summaries @conn))})))))))
