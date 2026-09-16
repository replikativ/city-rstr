(ns city.ui.explorer
  "The city explorer: overlays, the published run, the posterior and the
   policy scenarios. It reads published outputs, from the two APIs or from a
   static export's files (marked by a `city-data` meta tag), and computes
   nothing on the UI thread."
  (:require [clojure.string :as str]
            [city.ui.catalog :as catalog]
            [city.ui.remote :as remote]
            [city.ui.city-layers :as layers]
            [city.ui.city-panels :as panels]
            [city.ui.timeline :as time]))

(def definitions
  [[:areas "Area boundaries" :areas]
   [:population "Population / 100 m cells" :cells] [:rent "Rent / €/m²" :cells]
   [:storefront "Observed storefronts" :points] [:licence "Issued licences" :points]
   [:place "Mapped places" :points] [:poi "OSM points of interest" :points]
   [:building "Mapped building points" :points] [:parcel "Parcel points" :points]
   [:buildings3d "3D basemap buildings" nil]
   [:visits "Visits / selected hour" :visits]
   [:revenue "Revenue / economic day, by demand class" :revenue]
   [:scenario "Revenue change / districts and venues" :scenario]
   [:scenario-visits "Visit change / venues at the playhead" :scenario]
   [:trips "Trips / purpose-colored trails" :trips]
   [:people "People / position at playhead" :trips] [:stops "Transit stops / GTFS" :stops]
   [:od "Trips between areas / top 60" :aggregates]])

(def overlay-groups
  "The picker's headings, in the order a reader of a scenario needs them."
  [["Scenario effect" [:scenario :scenario-visits]]
   ["Economy" [:revenue :visits]]
   ["Movement" [:trips :people :stops :od]]
   ["Who lives where" [:areas :population :rent :buildings3d]]
   ["Observed records" [:storefront :licence :place :poi :building :parcel]]])

(def views
  "What the map shows for each question; the checkboxes under customize stay
   available for anything else."
  [[:scenario "Scenario effect" #{:areas :scenario :scenario-visits}]
   [:economy "Baseline economy" #{:areas :revenue :visits}]
   [:movement "Movement" #{:areas :trips :people :stops :od}]
   [:residents "Who lives where" #{:areas :population :buildings3d}]])

(def default-scenario "close-milaneo")

(def observed-kinds #{:storefront :licence :place :poi :building :parcel})
(def simulation-kinds #{:visits :revenue :scenario :scenario-visits :trips :people :stops :od})
(defonce state (atom {:active? true :city :stuttgart :area nil :year 2024 :hour 8.0 :month 1
                      :clock-kind :day :playing? false :speed 60 :trail 30 :three-d true
                      :elevation-scale 1 :overlays #{:areas :population} :scenario nil :view nil
                      :payloads {} :statuses {} :generation 0 :request-ids {}}))
(defonce handles (atom {}))
(defonce playback (atom nil))
(defonce move-timer (atom nil))
(defonce clock-observer (atom nil))
(defn ^js el [id] (js/document.getElementById id))
(defn text! [id value] (set! (.-textContent (el id)) value))
(defn html! [id value] (set! (.-innerHTML (el id)) value))
(defn esc [s] (-> (str s) (str/replace "&" "&amp;") (str/replace "<" "&lt;") (str/replace ">" "&gt;") (str/replace "\"" "&quot;")))
(defn bind! [id event f] (aset (el id) (str "on" event) f))
(defn active? [] (:active? @state))
(defn fmt [x] (if (number? x) (.toLocaleString (js/Math.round x) "en-GB") "—"))
(defn- meur [x] (if (number? x) (str (if (pos? x) "+" "") (.toFixed (/ x 1e6) 1) " M€") "—"))
(defn- map-object [] (some-> (:map @handles) deref))
(defn- overlay-object [] (some-> (:overlay @handles) deref))
(declare choose-view! draw! render! load-context! load-model! load-observed! load-spatial! select-area! inspect! sync-url! stop! render-time!)

(defn- reset-selection! []
  (swap! state assoc :selection-token (random-uuid))
  (when-let [^js selection (el "selection")]
    (set! (.-hidden selection) true)))

(defn- cancel-move! []
  (when @move-timer (js/clearTimeout @move-timer))
  (reset! move-timer nil))

(defn- bbox []
  (when-let [^js m (map-object)]
    (let [^js b (.getBounds m)] (str/join "," [(.getWest b) (.getSouth b) (.getEast b) (.getNorth b)]))))

(defn- static? [] (some? (:static-data @state)))

(defn- viewport-scoped? []
  (let [{:keys [area run-key]} @state]
    ;; a static export holds the whole city in one file per layer, so the
    ;; viewport never changes what is requested
    (and (not (static?))
     (or (nil? area)
        (not= (str (:eid area)) (str run-key))))))

(defn- context []
  (let [{:keys [city area year overlays run-key scenario]} @state]
    {:city city :level (if (= city :stuttgart) "stadtteil" "local-area") :area (:eid area)
     :year year :kinds (set (filter observed-kinds overlays))
     :bbox (when (viewport-scoped?) (bbox)) :stride 20 :run-key run-key :scenario scenario}))

(defn- request-status [key payload]
  (if (or (and (= key :econ) (empty? (:rows payload)) (empty? (:summary payload)))
          (and (= key :series) (empty? payload))
          (and (= key :aggregates) (:note payload)))
    {:status :missing :message (or (:note payload) "Not included in this published run")}
    {:status :ready}))

(defn- observed-status-key [kind] (keyword (str "observed-" (name kind))))

(defn- request!
  ([key request after] (request! key request after nil))
  ([key request after failed]
   (let [generation (:generation @state)
         id (inc (get-in @state [:request-ids key] 0))
         current? #(and (= generation (:generation @state)) (= id (get-in @state [:request-ids key])))
         ;; a static export answers from one file per response; what it does
         ;; not carry is reported missing, never fetched from an API
         file (when (static?) (catalog/static-path request))]
     (swap! state assoc-in [:request-ids key] id)
     (swap! state assoc-in [:statuses key] {:status :loading})
     (if (and (static?) (nil? file))
       (do (swap! state update :payloads dissoc key)
           (swap! state assoc-in [:statuses key] {:status :missing :message "Not part of this published export."})
           (when failed (failed (js/Error. "not exported")))
           (render!))
       ;; The second callback handles only fetch/parse rejection. Exceptions in
       ;; `after` or rendering must not relabel a successful response as HTTP failure.
       (.then (if file
                (remote/fetch! (str (:static-data @state) file))
                (remote/request! (get @state (if (= :store (:base request)) :api :sim-api)) request))
              (fn [data]
                (when (current?)
                  (swap! state assoc-in [:payloads key] data)
                  (swap! state assoc-in [:statuses key] (request-status key data))
                  (when after (after data))
                  (render!)))
              (fn [e]
                (when (current?)
                  (swap! state update :payloads dissoc key)
                  (swap! state assoc-in [:statuses key]
                         {:status (if (str/includes? (.-message e) "HTTP 404") :missing :error)
                          :message (.-message e)})
                  (when failed (failed e))
                  (render!))))))))

(defn- selected-months [] (sort (map :month (get-in @state [:payloads :series]))))

(defn- run-absent? []
  (and (= :ready (get-in @state [:statuses :runs :status]))
       (:run-key @state)
       (not (some #{(:run-key @state)}
                  (map str (get-in @state [:payloads :runs :areas]))))))

(defn- no-run-message []
  (if (= :stuttgart (:city @state))
    (if (:area @state)
      "No simulation run is available for this region."
      "No whole-city simulation run is available.")
    "No simulation run is available for this selection."))

(defn- clear-output! [key status]
  ;; Invalidate responses already in flight when the selection changes.
  (swap! state update-in [:request-ids key] (fnil inc 0))
  (swap! state update :payloads dissoc key)
  (swap! state assoc-in [:statuses key] status))

(defn- scenario-options! [data]
  (let [current (:scenario @state)]
    (html! "scenario-select"
           (str "<option value=''>baseline — no intervention</option>"
                (apply str (for [s (:scenarios data)]
                             (str "<option value='" (esc (:key s)) "'" (when (= (:key s) current) " selected") ">"
                                  (esc (:label s)) "</option>")))))))

(defn- load-scenario! []
  ;; a scenario is a published result under the run's posterior; the UI only
  ;; reads it, so a missing one is a status, never a computation
  (let [reqs (catalog/requests (context))]
    (if (and (:scenario @state) (:scenario reqs) (not (run-absent?)))
      (request! :scenario (:scenario reqs) nil)
      (clear-output! :scenario {:status :missing :message "no scenario selected"}))))

(defn load-model! []
  (let [{:keys [city area]} @state
        runs (set (map str (get-in @state [:payloads :runs :areas])))
        area-key (some-> area :eid str)
        run-key (cond (and area-key (runs area-key)) area-key
                      (= city :stuttgart) "stuttgart"
                      :else "city")]
    (swap! state assoc :run-key run-key)
    (let [reqs (catalog/requests (context))]
      (doseq [key [:meta :aggregates :econ :scenarios]]
        (if (run-absent?)
          (clear-output! key {:status :blocked :message (no-run-message)})
          (request! key (reqs key)
                    (when (= key :scenarios) scenario-options!))))
      (load-scenario!)
      (load-spatial!)
      (sync-url!))))

(defn load-spatial! []
  (when (active?)
    (let [reqs (catalog/requests (context))
          on (:overlays @state)
          needed (cond-> #{}
                   (or (on :visits) (on :hexagons)) (conj :visits)
                   (on :revenue) (conj :revenue)
                   (on :firms) (conj :firms)
                   (or (on :trips) (on :people)) (conj :trips)
                   (on :stops) (conj :stops))]
      (doseq [key [:visits :revenue :firms :trips :stops]]
        (cond
          (not (needed key)) (clear-output! key {:status :idle})
          ;; GTFS stops are source data and do not require a simulation run.
          (= key :stops) (request! key (reqs key) nil)
          (not (:context-initialized? @state))
          (clear-output! key {:status :blocked :message "Discovering available simulation runs…"})
          (run-absent?) (clear-output! key {:status :blocked :message (no-run-message)})
          :else (request! key (reqs key) nil)))
      (swap! state assoc :last-spatial-bbox (when (viewport-scoped?) (bbox)))
      (render!))))

(defn load-observed! []
  (let [reqs (catalog/requests (context))
        generation (:generation @state)
        id (inc (get-in @state [:request-ids :points] 0))
        requests (:points reqs)
        kinds (set (filter observed-kinds (:overlays @state)))]
    (swap! state assoc-in [:request-ids :points] id)
    (swap! state update :payloads dissoc :points :points-by-kind :summary)
    (swap! state update :statuses #(apply dissoc % :points :summary (map observed-status-key observed-kinds)))
    (if (seq requests)
      (do
        (doseq [{:keys [kind] :as request} requests]
          (let [status-key (observed-status-key kind)]
            (swap! state assoc-in [:statuses status-key] {:status :loading})
            (-> (remote/request! (:api @state) request)
                (.then (fn [response]
                         (when (and (= generation (:generation @state)) (= id (get-in @state [:request-ids :points])))
                           (let [features (vec (:features response))]
                             (swap! state assoc-in [:payloads :points-by-kind kind] features)
                             (swap! state assoc-in [:payloads :points]
                                    (vec (mapcat val (get-in @state [:payloads :points-by-kind]))))
                             (swap! state assoc-in [:statuses status-key]
                                    (if (seq features)
                                      {:status :ready :count (count features)}
                                      {:status :empty :message "Request succeeded; no records match this region and year"}))
                             (render!)))))
                (.catch (fn [e]
                          (when (and (= generation (:generation @state)) (= id (get-in @state [:request-ids :points])))
                            (swap! state assoc-in [:statuses status-key] {:status :error :message (.-message e)})
                            (render!))))))))
      (doseq [kind kinds]
        (swap! state assoc-in [:statuses (observed-status-key kind)]
               {:status :blocked :message "Choose a region above or click a map boundary"})))
    (when-let [r (:summary reqs)] (request! :summary r nil))
    (render!)))

(defn- area-options! [fc]
  (html! "area-select" (str "<option value=''>whole city (no observed records)</option>"
                           (apply str (for [f (sort-by #(get-in % [:properties :name]) (:features fc))
                                            :let [p (:properties f)]]
                                        (str "<option value='" (esc (:eid p)) "'>" (esc (:name p)) "</option>")))))
  (set! (.-value (el "area-select")) (str (get-in @state [:area :eid] ""))))

(defn- apply-requested-view! []
  (when-let [^js m (map-object)]
    (let [{:keys [requested-center requested-zoom requested-pitch]} @state]
      (when (or requested-center requested-zoom (some? requested-pitch))
        (.jumpTo m (clj->js (cond-> {}
                              requested-center (assoc :center requested-center)
                              requested-zoom (assoc :zoom requested-zoom)
                              (some? requested-pitch) (assoc :pitch requested-pitch)))))))
  (swap! state dissoc :requested-center :requested-zoom :requested-pitch))

(defn- finish-context! [part]
  (swap! state update :context-settled (fnil conj #{}) part)
  (when (and (= #{:areas :runs} (:context-settled @state))
             (not (:context-initialized? @state)))
    (let [{:keys [city requested-area]} @state
          whole (if (= city :stuttgart) "stuttgart" "city")
          fc (get-in @state [:payloads :areas])
          selected (when (and requested-area (not= requested-area whole))
                     (some #(when (= (str requested-area) (str (get-in % [:properties :eid])))
                              (:properties %))
                           (:features fc)))]
      (swap! state assoc :context-initialized? true)
      (when requested-area (swap! state dissoc :requested-area))
      (when selected (select-area! selected false))
      (apply-requested-view!)
      (load-observed!)
      (load-model!)
      (when-let [id (:requested-inspect @state)]
        (swap! state dissoc :requested-inspect)
        (inspect! :entity {:eid id})))))

(defn load-context! []
  (stop!)
  (cancel-move!)
  (reset-selection!)
  (swap! state #(-> % (update :generation inc)
                    (assoc :payloads {} :statuses {} :run-key nil
                           :last-spatial-bbox nil :context-settled #{}
                           :context-initialized? false)))
  (let [reqs (catalog/requests (context))]
    (request! :areas (:areas reqs)
              (fn [fc]
                (area-options! fc)
                (finish-context! :areas))
              (fn [_] (finish-context! :areas)))
    (when-let [r (:districts reqs)] (request! :districts r nil))
    (if-let [r (:cells reqs)]
      (request! :cells r nil)
      (swap! state assoc-in [:statuses :cells]
             {:status :missing :message "No population/rent grid is available for Vancouver"}))
    ;; Failure still settles discovery; load-model! then uses the city run key.
    (request! :runs (:runs reqs)
              (fn [_] (finish-context! :runs))
              (fn [_] (finish-context! :runs)))))

(defn select-area!
  ([area] (select-area! area true))
  ([area load?]
   (stop!)
   (cancel-move!)
   (reset-selection!)
   (when load? (swap! state dissoc :requested-area))
   (swap! state assoc :area area :playing? false :last-spatial-bbox nil)
   (swap! state update :request-ids #(reduce (fn [ids k] (update ids k (fnil inc 0))) % [:meta :series :aggregates :econ :visits :firms :trips :stops :points :summary]))
   (swap! state update :payloads #(select-keys % [:areas :cells :runs]))
   (swap! state update :statuses #(select-keys % [:areas :cells :runs]))
   (set! (.-value (el "area-select")) (str (:eid area "")))
   (when-let [^js m (map-object)]
     (let [f (some #(when (= (:eid area) (get-in % [:properties :eid])) %) (get-in @state [:payloads :areas :features]))
           r (some-> f :geometry layers/ring)]
       (when (seq r) (.fitBounds m (clj->js [[(apply min (map first r)) (apply min (map second r))]
                                            [(apply max (map first r)) (apply max (map second r))]]) #js {:padding 70 :duration 0}))))
   (when (and load? (:context-initialized? @state))
     (load-observed!)
     (load-model!))))

(defn- record-html [record]
  (str "<table class='city-table'>"
       (apply str (for [[k v] (sort-by (comp str key) record)]
                    (str "<tr><th>" (esc (if (keyword? k) (subs (str k) 1) k)) "</th><td>"
                         (if (and (string? v) (re-find #"^https?://" v))
                           (str "<a href='" (str/replace (esc v) "'" "&#39;") "' target='_blank' rel='noopener'>" (esc v) " ↗</a>")
                           (esc (if (coll? v) (pr-str v) v))) "</td></tr>"))) "</table>"))

(defn- evidence-record-html [record]
  (str (record-html (dissoc record :acq))
       (if-let [receipt (:acq record)]
         (str "<h4>Acquisition receipt</h4>" (record-html receipt))
         "<p class='hint'>No acquisition receipt supplied for this record.</p>")))

(defn- receipts-html [{:keys [entity links]}]
  (str "<h3>Evidence and linked records</h3>"
       (evidence-record-html entity)
       (apply str (map-indexed (fn [i record]
                                (str "<details><summary>Linked record " (inc i) "</summary>"
                                     (evidence-record-html record) "</details>")) links))))

(defn inspect! [kind data]
  (let [props (or (:properties data) data)
        id (:eid props)
        selection (random-uuid)]
    (swap! state assoc :selection-token selection)
    (set! (.-hidden (el "selection")) false)
    (html! "selection"
           (str "<button id='close-city-selection' aria-label='Close inspector'>×</button><div class='section-label'>"
                (esc (name kind)) " / " (if (#{:entity :cell :stop :area} kind) "SOURCE DATA" "SIMULATION") "</div><h3>"
                (esc (or (:name props) (:label props) (:area props) (:pid props) "Selected record")) "</h3>"
                (when (= kind :cell)
                  (str "<p>" (fmt (:population props)) " residents per approximately 100 m cell; ≈ "
                       (fmt (when (:population props) (* 100 (:population props)))) " residents/km².</p>"))
                (when (= kind :firm) "<p>Published firm snapshot. The month control does not rewind this record.</p>")
                (when (= kind :district-delta)
                  (str "<p>Scenario minus baseline, resident retail revenue per year: " (meur (:delta props))
                       " (90% band " (meur (:q05 props)) " to " (meur (:q95 props)) "), posterior mean over the particles.</p>"))
                (when (= kind :scenario-visits)
                  (str "<p>Same economic day, same seed: " (fmt (:baseline-day props)) " visits in the baseline, " (fmt (:scenario-day props))
                       " under the scenario (" (let [d (- (:scenario-day props) (:baseline-day props))] (str (when (pos? d) "+") d)) " for the day).</p>"))
                (when (= kind :scenario)
                  (let [dt (:delta-total props)]
                    (str "<p>" (case (name (or (:role props) "other")) "closed" "Closed in this scenario. " "opened" "Opened in this scenario. " "")
                         "Expected resident revenue " (meur (:mean dt)) " / year (90% band " (meur (:q05 dt)) " to " (meur (:q95 dt)) "); by class "
                         (str/join " · " (map (fn [c v] (str c " " (meur v))) ["short" "medium" "long"] (:delta props))) ".</p>")))
                (record-html (case kind
                               :scenario (select-keys props [:name :label :role])
                               :district-delta (select-keys props [:name :population])
                               :scenario-visits (select-keys props [:name :label])
                               props))
                (when (= kind :area) "<button id='inspect-select-area' class='quiet'>explore this area →</button>")
                "<div id='city-receipts'></div>"))
    (bind! "close-city-selection" "click" (fn [_] (reset-selection!)))
    (when (= kind :area) (bind! "inspect-select-area" "click" (fn [_] (select-area! props))))
    (when (and id (not (static?)) (#{:entity :cell} kind))
      (let [generation (:generation @state)]
        (text! "city-receipts" "Loading source receipts…")
        (-> (remote/request! (:api @state) {:path (str "/api/entity/" id) :params {}})
            (.then (fn [data]
                     (when (and (= generation (:generation @state)) (= selection (:selection-token @state)) (el "city-receipts"))
                       (html! "city-receipts" (receipts-html data)))))
            (.catch (fn [e] (when (and (= selection (:selection-token @state)) (el "city-receipts")) (text! "city-receipts" (str "Evidence unavailable: " (.-message e)))))))))))

(defn draw! []
  (when (active?)
    (when-let [^js o (overlay-object)]
      (.setProps o #js {:layers (layers/layers @state
                                               (fn [kind data]
                                                 (let [props (or (:properties data) data)
                                                       area-id (:area-eid props)
                                                       area-props (when area-id
                                                                    (some #(when (= (str area-id) (str (get-in % [:properties :eid])))
                                                                             (:properties %))
                                                                          (get-in @state [:payloads :areas :features])))]
                                                   (cond
                                                     (= kind :area) (select-area! props)
                                                     (and (= kind :cell) (nil? (:area @state)) area-props) (select-area! area-props)
                                                     :else (inspect! kind data)))))}))))

(defn render-time! []
  (let [{:keys [hour clock-kind month playing?]} @state
        day? (= clock-kind :day) months (selected-months)
        available? (if day? (or (seq (get-in @state [:payloads :trips])) (seq (get-in @state [:payloads :visits :features]))
                                 (seq (get-in @state [:payloads :scenario :visits :venues]))) (seq months))
        minute (int (* hour 60))]
    (when (and playing? (not available?)) (stop!))
    (text! "time-label" (if day? (str (.padStart (str (quot minute 60)) 2 "0") ":" (.padStart (str (mod minute 60)) 2 "0")) (str "month " month)))
    (text! "time-play" (if (:playing? @state) "pause" "play"))
    (set! (.-min (el "time-slider")) (if day? 0 (or (first months) 1)))
    (set! (.-max (el "time-slider")) (if day? 1439 (or (last months) 1)))
    (set! (.-value (el "time-slider")) (if day? minute month))
    (doseq [id ["time-play" "time-slider" "time-back" "time-forward"]] (set! (.-disabled (el id)) (not available?)))
    (set! (.-disabled (el "trip-trail")) (not day?))
    (text! "time-note" (if day?
                         (if available?
                           "Playback reads a representative published weekday; it does not rerun the model."
                           (if (run-absent?) (no-run-message)
                               "Playback needs visits, trips or a scenario's visit change. Choose a view that shows one."))
                         "Month selects the firm chart only. No historical per-firm spatial snapshots are available."))))

(defn- overlay-status [kind source statuses payloads area]
  (let [status (get statuses (if (observed-kinds kind) (observed-status-key kind) source) {:status :unloaded})
        status (cond
                 (and (= :ready (:status status)) (= kind :choropleth) (empty? (get-in payloads [:aggregates :areas])))
                 {:status :empty :message "Published response has no area rates"}
                 (and (= :ready (:status status)) (= kind :od) (empty? (get-in payloads [:aggregates :od])))
                 {:status :empty :message "Published response has no area-to-area trips"}
                 (and (= :ready (:status status)) (#{:visits :hexagons} kind) (empty? (get-in payloads [:visits :features])))
                 {:status :empty :message "Published response has no visits in this view"}
                 (and (= :ready (:status status)) (= kind :revenue) (empty? (get-in payloads [:revenue :features])))
                 {:status :empty :message "Published run carries no economic day, or none in this view"}
                 (and (= :ready (:status status)) (= kind :firms) (empty? (get-in payloads [:firms :features])))
                 {:status :empty :message "Published response has no firms in this view"}
                 (and (= :ready (:status status)) (#{:trips :people} kind) (empty? (:trips payloads)))
                 {:status :empty :message "Published response has no sampled trips in this view"}
                 (and (= :ready (:status status)) (= kind :stops) (empty? (get-in payloads [:stops :features])))
                 {:status :empty :message "Published response has no stops in this view"}
                 (and (= :ready (:status status)) (= kind :rent)
                      (not-any? number? (map #(get-in % [:properties :rent]) (get-in payloads [:cells :features]))))
                 {:status :empty :message "Cell grid has no rent values"}
                 :else status)
        label (case (:status status)
                :ready (str "available"
                            (when-let [n (:count status)] (str " · " (fmt n) " records")))
                :loading "loading…"
                :empty (str "0 results · " (:message status))
                :blocked (:message status)
                :missing (str "not published · " (or (:message status) "this layer is absent"))
                :error (str (if (simulation-kinds kind) "simulation API unavailable" "evidence API unavailable") " · check Data connections")
                :idle (or (:message status) "not loaded")
                :unloaded (if (and (observed-kinds kind) (nil? area)) "choose a region to load" "select to load")
                "")]
    (assoc status :label label)))

(defn- scenario-metrics
  "The four numbers of a scenario: what the closed venues earned, where the
   posterior mean of that money lands — inside Mitte, at the rebuilt venue or
   the other districts — and what it does to the medium-class shopping trip.
   Every candidate venue lies in one of the 23 districts, so the money stays
   with city venues by construction; leakage is a class balance, not a move."
  [sc]
  (let [venues (:venues sc) closed (filter #(= "closed" (name (or (:role %) "other"))) venues)
        removed (- (reduce + 0 (map #(get-in % [:delta-total :mean] 0) closed)))
        districts (:districts sc)
        dist (fn [d] (some #(when (= d (:district %)) (:delta-total %)) districts))
        mitte (dist "Mitte") target (:target sc) tgt (when target (dist target))
        others (reduce + 0 (map #(get-in % [:delta-total :mean] 0) (remove #(#{"Mitte" target} (:district %)) districts)))
        km (some #(when (= "medium" (name (:class %))) (:delta %)) (:expected-km sc))
        m (fn [x] (if (number? x) (str (if (pos? x) "+" "") (.toFixed (* 1000 x) 0) " m") "—"))
        pct (fn [x] (if (and (number? x) (pos? removed)) (str (.toFixed (* 100 (/ x removed)) 0) "%") "—"))
        band (fn [b] (str "90% band " (meur (:q05 b)) " to " (meur (:q95 b))))]
    [["revenue removed" (meur (- removed)) (str (count closed) " closed venues · resident money · posterior mean")]
     ["re-absorbed in Mitte" (pct (+ removed (:mean mitte 0))) (str "Mitte net " (meur (:mean mitte)) " · " (band mitte))]
     [(if target (str "captured in " target) "other districts") (pct (if target (:mean tgt 0) others))
      (if target (str "the rebuilt venue's district · " (band tgt)) "sum over the other 22 districts")]
     ["clothing trip, expected" (m (:mean km)) (str "medium class, straight line per resident · " (m (:q05 km)) " to " (m (:q95 km)))]]))

(defn- render-outcomes! []
  (let [{:keys [payloads hour month]} @state
        meta (:meta payloads)
        hourly (when (seq (get-in payloads [:visits :features]))
                 (reduce + (map #(get-in % [:properties :hours (int hour)] 0) (get-in payloads [:visits :features]))))]
    (html! "city-outcomes"
     (if-let [sc (and (:scenario @state) (:scenario payloads))]
       (str "<div class='outcome-title'><span class='section-label'>POLICY SCENARIO</span><strong>" (esc (:label sc))
            "</strong><small>interventional prediction under " (count (:particles sc)) " posterior particles · same residents, same money</small></div>"
            (apply str (for [[label value note] (scenario-metrics sc)]
                         (str "<div class='metric'><span>" label "</span><strong>" value "</strong><small>" note "</small></div>"))))
           (str "<div class='outcome-title'><span class='section-label'>" (if (run-absent?) "NO SIMULATION RUN" "PUBLISHED RUN") "</span><strong>" (esc (:run-key @state)) "</strong><small>" (cond (run-absent?) "NO PUBLISHED OUTPUTS FOR THIS SELECTION"
                                                                                                                                                      (:fixture meta) "SYNTHETIC UI TEST FIXTURE"
                                                                                                                                                      :else "viewing outputs, not rerunning") "</small></div>"
                (apply str (for [[label value note] [["modeled persons" (:persons meta) "run population; may include commuters"]
                                                      ["visits / selected hour" hourly "loaded viewport; expected visits"]
                                                      ["sampled people" (when (seq (:trips payloads)) (count (set (map :pid (:trips payloads))))) "loaded trajectories, not total population"]
                                                      ["policy scenarios" (count (get-in payloads [:scenarios :scenarios])) "published under the posterior · choose one on the left"]]]
                             (str "<div class='metric'><span>" label "</span><strong>" (fmt value) "</strong><small>" note "</small></div>"))))))))

(defn render! []
  (when (active?)
    (let [{:keys [city area overlays statuses payloads]} @state
          failures (for [[k s] statuses
                         :when (and (#{:error :missing} (:status s))
                                    ;; a scenario that is not selected is not a failure
                                    (not (and (= :missing (:status s)) (= k :scenario))))]
                     (str (name k) ": " (or (:message s) (name (:status s)))))
          loading (count (filter #(= :loading (:status %)) (vals statuses)))]
      (text! "camera" (if (:three-d @state) "3D view" "2D view"))
      (.setAttribute (el "camera") "aria-pressed" (str (:three-d @state)))
      (.setAttribute (el "lab-map") "aria-label" (str (name city) " city data and simulation map"))
      (when-let [^js scope (.querySelector js/document ".project-name span")]
        (set! (.-textContent scope) (str "/ " (str/capitalize (name city)))))
      (text! "map-scope" (str/upper-case (str (name city) " / " (or (:name area) "whole city"))))
      (text! "map-heading" (cond (get-in payloads [:meta :fixture]) "synthetic UI test fixture"
                                  :else "observe. simulate. compare."))
      (text! "status" (cond (pos? loading) (str "Loading " loading " data layers…")
                            (seq failures) "Some data is unavailable. See layer status and evidence; missing is not zero."
                            (run-absent?) (no-run-message)
                            :else (str "Run " (:run-key @state) " · seed " (get-in payloads [:meta :seed] "—") " · playback does not rerun the model")))
      (text! "city-data-status" (str/join " · " failures))
      (text! "scenario-question"
             (let [sc (:scenario payloads) st (get-in statuses [:scenario :status])]
               (cond (not (:scenario @state)) "Scenarios are evaluated on the server under the fitted posterior; choosing one reads a published result, it does not rerun the model."
                     (= st :loading) "Loading the published scenario…"
                     sc (str (:question sc) " Evaluated under " (count (:particles sc)) " posterior particles; see the evidence column.")
                     :else "This scenario is not published on the selected run.")))
      (doseq [^js box (array-seq (.querySelectorAll js/document "[data-overlay]"))]
        (set! (.-checked box) (boolean (overlays (keyword (.. box -dataset -overlay))))))
      (doseq [[k _ key] definitions]
        (when-let [^js s (el (str "overlay-status-" (name k)))]
          (let [{:keys [status label]} (overlay-status k key statuses payloads area)]
            (set! (.-textContent s) (if (and (overlays k) key) label ""))
            (if (and (overlays k) key)
              (.setAttribute s "data-state" (name status))
              (.removeAttribute s "data-state")))))
      (text! "area-explanation"
             (if area
               (str (:name area) " selected. Observed overlays filter to this region; simulation overlays read published run “" (:run-key @state) "” when available. Selection does not create a run.")
               "Choose a district here or click its boundary on the map. A district is required for observed record overlays. Selecting one filters existing data and published outputs; it does not run a new simulation."))
      (text! "city-elevation-value" (str (:elevation-scale @state) "×"))
      (set! (.-textContent (.querySelector js/document ".map-caption"))
            (str (cond
                   (overlays :rent) "Columns: rent €/m²; grey means rent unavailable. "
                   (overlays :population) (str "Residents / ~100 m cell; height " (:elevation-scale @state) "×. ")
                   :else "")
                 (when (overlays :buildings3d) "Basemap building heights may be inferred (8 m fallback). ")
                 "Trips and people are a sample of the population; visits and revenue are the whole city."))
      (set! (.-innerHTML (.querySelector js/document ".map-key"))
            (layers/legend @state))
      (panels/render! (el "city-evidence") @state)
      (render-time!) (render-outcomes!) (draw!))))

(defn sync-url! []
  (when (active?)
    (let [u (js/URL. (.-href js/location)) q (.-searchParams u)]
      (doseq [[k v] {"mode" "city" "city" (name (:city @state)) "year" (:year @state)
                      "hour" (:hour @state) "month" (:month @state)
                      "clock-kind" (name (:clock-kind @state))
                      "elevation" (:elevation-scale @state)
                      "overlays" (str/join "," (sort (map name (:overlays @state))))}]
        (.set q k (str v)))
      (if-let [a (:eid (:area @state))] (.set q "area" (str a)) (.delete q "area"))
      (if-let [sc (:scenario @state)] (.set q "scenario" sc) (.delete q "scenario"))
      (if-let [v (:view @state)] (.set q "view" (name v)) (.delete q "view"))
      (js/history.replaceState nil "" (.toString u)))))

(defn stop! []
  (when @playback (js/cancelAnimationFrame @playback))
  (reset! playback nil)
  (swap! state assoc :playing? false))

(defn- tick! [previous stamp]
  (when (and (active?) (:playing? @state))
    (let [{:keys [clock-kind speed hour month]} @state dt (/ (- stamp previous) 1000)]
      (if (= clock-kind :day)
        (swap! state update :hour time/advance-hour dt speed)
        (when (>= dt 1)
          (let [months (selected-months) later (first (filter #(> % (:month @state)) months))]
            (swap! state assoc :month (or later (first months))))))
      (render-time!) (render-outcomes!) (draw!)
      ;; Monthly charts refresh on integer frame changes; daily charts once per second.
      (when (or (not= month (:month @state)) (not= (int hour) (int (:hour @state)))) (panels/render! (el "city-evidence") @state))
      (reset! playback (js/requestAnimationFrame #(tick! (if (or (= clock-kind :day) (>= dt 1)) stamp previous) %))))))

(defn- buildings! []
  (when-let [^js m (map-object)]
    (when (.getSource m "openmaptiles")
      (when-not (.getLayer m "city-buildings")
        (.addLayer m (clj->js {:id "city-buildings" :type "fill-extrusion" :source "openmaptiles" :source-layer "building" :minzoom 13
                              :paint {:fill-extrusion-color "#c4c8ca" :fill-extrusion-opacity 0.7
                                      :fill-extrusion-height ["coalesce" ["get" "render_height"] 8]
                                      :fill-extrusion-base ["coalesce" ["get" "render_min_height"] 0]}})))
      (.setLayoutProperty m "city-buildings" "visibility" (if (and (active?) ((:overlays @state) :buildings3d)) "visible" "none")))))

(defn- home! []
  (when-let [^js m (map-object)]
    (.jumpTo m (clj->js {:center (if (= :stuttgart (:city @state)) [9.18 48.78] [-123.11 49.27])
                         :zoom 11.5 :pitch (if (:three-d @state) 45 0) :bearing 0}))))

(defn start! []
  (stop!)
  (cancel-move!)
  (reset-selection!)
  (.add (.-classList js/document.body) "city-mode")
  (set! (.-hidden (el "selection")) true)
  (home!) (load-context!)
  (buildings!))

(defn choose-view!
  "Show one question's overlays. The scenario view needs a scenario, so it
   selects the default one when none is chosen."
  [view]
  (when-let [[_ _ overlays] (some #(when (= view (first %)) %) views)]
    (when (and (= view :scenario) (nil? (:scenario @state)))
      (swap! state assoc :scenario default-scenario)
      (set! (.-value (el "scenario-select")) default-scenario)
      (load-scenario!))
    (swap! state assoc :view view :overlays overlays)
    (doseq [^js box (array-seq (.querySelectorAll js/document "[data-overlay]"))]
      (set! (.-checked box) (contains? overlays (keyword (.. box -dataset -overlay)))))
    (doseq [^js b (array-seq (.querySelectorAll js/document "[data-view]"))]
      (.setAttribute b "aria-pressed" (str (= (name view) (.. b -dataset -view)))))
    (load-spatial!) (render!) (sync-url!)))

(defn init! [options]
  (reset! handles options)
  (when @clock-observer (.disconnect ^js @clock-observer))
  (let [observer (js/ResizeObserver.
                  (fn [_]
                    (.setProperty (.-style (.closest (el "city-time") ".map-stage"))
                                  "--city-clock-height" (str (.-height (.getBoundingClientRect (el "city-time"))) "px"))))]
    (.observe observer (el "city-time"))
    (reset! clock-observer observer))
  (let [q (.-searchParams (js/URL. (.-href js/location)))
        area-param (.get q "area")
        city (if (.has q "city")
               (if (= "vancouver" (.get q "city")) :vancouver :stuttgart)
               (cond
                 (= area-param "stuttgart") :stuttgart
                 (or (.has q "area") (.has q "sim")) :vancouver
                 :else :stuttgart))
        number-param (fn [k default] (let [n (js/parseFloat (.get q k))] (if (js/isFinite n) n default)))
        old-sim (set (map keyword (remove empty? (str/split (or (.get q "sim") "") #","))))
        legacy-overlays (cond-> old-sim
                          (seq old-sim) (into #{:choropleth :od})
                          (:visits old-sim) (conj :hexagons)
                          (:trips old-sim) (into #{:people :stops}))
        requested (set (map keyword (remove empty? (str/split (or (.get q "overlays") "") #","))))
        center (let [[lon lat & more] (str/split (or (.get q "center") "") #",")
                     lon (js/parseFloat lon) lat (js/parseFloat lat)]
                 (when (and (empty? more) (js/isFinite lon) (js/isFinite lat)) [lon lat]))
        zoom (let [z (js/parseFloat (.get q "zoom"))] (when (js/isFinite z) z))
        clock-kind (if (= "month" (.get q "clock-kind")) :month :day)
        base (.get q "base")]
    (swap! state assoc :city city :year (number-param "year" 2024) :month (number-param "month" 1) :hour (mod (number-param "hour" 8) 24)
           :clock-kind clock-kind :speed (if (= clock-kind :month) 1 60)
           :elevation-scale (max 0.25 (min 3 (number-param "elevation" 1)))
           :api (or (.get q "api") "http://localhost:8090") :sim-api (or (.get q "sim-api") "http://localhost:8092")
           ;; <meta name="city-data" content="data/stuttgart/"> marks a static export
           :static-data (some-> (.querySelector js/document "meta[name=city-data]") (.getAttribute "content"))
           :requested-area area-param :requested-inspect (.get q "inspect")
           :scenario (not-empty (or (.get q "scenario") ""))
           :requested-center center :requested-zoom zoom
           :requested-pitch (case base "3d" 55 "osm" 0 nil)
           :three-d (if base (= base "3d") true)
           :overlays (if (.has q "overlays") requested (into #{:areas :population} legacy-overlays)))
    ;; a bare address opens on the intervention, not on a population map; a
    ;; link naming a scenario or a view without overlays gets that view's layers
    (when-not (or (.has q "overlays") (.has q "sim"))
      (let [v (or (some #(when (= (.get q "view") (name (first %))) (first %)) views) :scenario)]
        (swap! state assoc :view v :overlays (last (some #(when (= v (first %)) %) views)))
        (when (and (= v :scenario) (not (.has q "scenario")))
          (swap! state assoc :scenario default-scenario))))
    (when-let [v (and (.has q "overlays") (some #(when (= (.get q "view") (name (first %))) (first %)) views))]
      (swap! state assoc :view v))
    (when (= base "3d") (swap! state update :overlays conj :buildings3d))
    (.toggle (.-classList js/document.body) "static-export" (static?))
    (when-let [^js m (map-object)]
      (when (= base "3d") (.setStyle m "https://tiles.openfreemap.org/styles/positron"))
      (when (= base "osm") (.setPitch m 0)))
    (set! (.-value (el "city-select")) (name city))
    (set! (.-value (el "observed-year")) (:year @state))
    (set! (.-value (el "city-elevation")) (:elevation-scale @state))
    (set! (.-value (el "clock-kind")) (name clock-kind))
    (html! "time-speed" (if (= clock-kind :day)
                           "<option value='15'>15 min / sec</option><option value='60' selected>60 min / sec</option><option value='180'>180 min / sec</option>"
                           "<option value='1'>1 month / sec</option>"))
    (set! (.-value (el "store-api")) (:api @state)) (set! (.-value (el "simulation-api")) (:sim-api @state))
    (html! "overlay-picker"
           (let [labels (into {} (map (fn [[k label _]] [k label]) definitions))]
             (apply str
                    (for [[heading ks] overlay-groups
                          :let [ks (remove #(and (static?) (observed-kinds %)) ks)]
                          :when (seq ks)]
                      (str "<div class='overlay-group'>" heading "</div>"
                           (apply str (for [key ks]
                                        (str "<label class='overlay-option'><input type='checkbox' data-overlay='" (name key) "' "
                                             (when ((:overlays @state) key) "checked") "><span>" (labels key) "<small id='overlay-status-" (name key) "'></small></span></label>"))))))))
    (html! "view-picker"
           (apply str (for [[k label _] views]
                        (str "<button class='view-button' data-view='" (name k) "' aria-pressed='" (= k (:view @state)) "'>" label "</button>"))))
    (doseq [^js b (array-seq (.querySelectorAll js/document "[data-view]"))]
      (set! (.-onclick b) (fn [_] (choose-view! (keyword (.. b -dataset -view))))))
    (doseq [^js box (array-seq (.querySelectorAll js/document "[data-overlay]"))]
      (set! (.-onchange box)
            (fn [_] (let [k (keyword (.. box -dataset -overlay))]
                      (swap! state update :overlays #(if (.-checked box) (conj % k) (disj % k)))
                      (swap! state assoc :view nil)
                      (doseq [^js b (array-seq (.querySelectorAll js/document "[data-view]"))] (.setAttribute b "aria-pressed" "false"))
                      (when (= k :buildings3d)
                        (when-let [^js m (map-object)]
                          (if (.getSource m "openmaptiles") (buildings!) (.setStyle m "https://tiles.openfreemap.org/styles/positron"))))
                      (if (observed-kinds k) (load-observed!) (load-spatial!))
                      (render!) (sync-url!)))))
    (bind! "city-select" "change" (fn [^js e]
                                    (swap! state assoc :city (keyword (.. e -target -value)) :area nil :requested-area nil)
                                    (home!) (load-context!) (sync-url!)))
    (bind! "area-select" "change" (fn [^js e]
                                    (select-area! (some #(when (= (.. e -target -value) (str (get-in % [:properties :eid]))) (:properties %))
                                                        (get-in @state [:payloads :areas :features])))))
    (bind! "scenario-select" "change" (fn [^js e]
                                        (let [v (not-empty (.. e -target -value))]
                                          (swap! state assoc :scenario v)
                                          (load-scenario!)
                                          (choose-view! (if v :scenario :economy)))))
    (bind! "observed-year" "change" (fn [^js e] (let [year (js/parseInt (.. e -target -value))]
                                                  (when (<= 1900 year 2100) (swap! state assoc :year year) (load-observed!) (sync-url!)))))
    (bind! "city-elevation" "input" (fn [^js e]
                                       (swap! state assoc :elevation-scale (js/parseFloat (.. e -target -value)))
                                       (text! "city-elevation-value" (str (:elevation-scale @state) "×"))
                                       (draw!) (sync-url!)))
    (bind! "refresh-city" "click" (fn [_] (load-context!)))
    (bind! "connect-city" "click" (fn [_]
                                     (swap! state assoc :api (.-value (el "store-api")) :sim-api (.-value (el "simulation-api")))
                                     (let [u (js/URL. (.-href js/location))]
                                       (.set (.-searchParams u) "api" (:api @state)) (.set (.-searchParams u) "sim-api" (:sim-api @state))
                                       (js/history.replaceState nil "" (.toString u))) (load-context!)))
    (bind! "clock-kind" "change" (fn [^js e]
                                   (stop!) (swap! state assoc :clock-kind (keyword (.. e -target -value)))
                                   (html! "time-speed" (if (= :day (:clock-kind @state)) "<option value='15'>15 min / sec</option><option value='60' selected>60 min / sec</option><option value='180'>180 min / sec</option>" "<option value='1'>1 month / sec</option>"))
                                   (swap! state assoc :speed (if (= :day (:clock-kind @state)) 60 1)) (render!) (sync-url!)))
    (bind! "time-slider" "input" (fn [^js e]
                                   (stop!) (swap! state assoc (if (= :day (:clock-kind @state)) :hour :month)
                                                (/ (js/parseFloat (.. e -target -value)) (if (= :day (:clock-kind @state)) 60 1)))
                                   (when (= :month (:clock-kind @state))
                                     (when-let [row (time/month-row (get-in @state [:payloads :series]) (:month @state))]
                                       (swap! state assoc :month (:month row))))
                                   (render!) (sync-url!)))
    (bind! "time-speed" "change" (fn [^js e] (swap! state assoc :speed (js/parseFloat (.. e -target -value)))))
    (bind! "trip-trail" "change" (fn [^js e] (swap! state assoc :trail (js/parseFloat (.. e -target -value))) (draw!)))
    (doseq [[id direction] [["time-back" -1] ["time-forward" 1]]]
      (bind! id "click" (fn [_]
                         (stop!)
                         (if (= :day (:clock-kind @state)) (swap! state update :hour #(mod (+ % (* direction 0.25)) 24))
                             (let [months (selected-months) current (:month @state)
                                   next (if (pos? direction) (first (filter #(> % current) months)) (last (filter #(< % current) months)))]
                               (when next (swap! state assoc :month next)))) (render!) (sync-url!))))
    (bind! "time-play" "click" (fn [_]
                                  (if (:playing? @state) (stop!)
                                      (do (swap! state assoc :playing? true)
                                          (reset! playback (js/requestAnimationFrame #(tick! % %))))) (render-time!)))
    (when-let [^js m (map-object)]
      (.on m "load" (fn [_] (when (active?) (draw!))))
      (.on m "style.load" (fn [_] (buildings!)))
      (.on m "moveend" (fn [_]
                          (when (and (active?) (:run-key @state) (viewport-scoped?)
                                     (not= (bbox) (:last-spatial-bbox @state)))
                            (when @move-timer (js/clearTimeout @move-timer))
                            (reset! move-timer (js/setTimeout load-spatial! 400))))))
    (start!)
    (set! (.-cityExplorer js/window)
          #js {:state (fn [] (clj->js (dissoc @state :payloads)))
               :payload (fn [key] (clj->js (get-in @state [:payloads (keyword key)])))
               :inspect (fn [kind record] (inspect! (keyword kind) (js->clj record :keywordize-keys true)))})))

(defn camera! []
  (swap! state update :three-d not)
  (when-let [^js m (map-object)] (.setPitch m (if (:three-d @state) 45 0)))
  (text! "camera" (if (:three-d @state) "3D view" "2D view")) (draw!))

(defn recenter! [] (home!))
