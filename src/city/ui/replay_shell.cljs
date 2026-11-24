(ns city.ui.replay-shell
  "Controls shared by the city replay pages. City adapters provide the data and
  own their clocks, cameras and evidence.")

(defn- ^js find-node [^js root selector]
  (.querySelector root selector))

(defn- nodes [^js root selector]
  (array-seq (.querySelectorAll root selector)))

(defn mount-inspector! [{:keys [initial reveal? anchor-view on-change]}]
  (let [panel (find-node js/document "[data-replay-inspector]")
        toggle (find-node js/document "[data-replay-toggle]")
        tabs (nodes panel "[data-replay-tab]")
        sections (into {} (map (fn [^js node] [(.getAttribute node "data-replay-section") node]))
                       (nodes panel "[data-replay-section]"))
        current (volatile! nil)
        fragment #(subs (or (not-empty (.-hash js/location)) "#") 1)
        target (fn [id]
                 (when (seq id)
                   (or (.getElementById js/document id)
                       (find-node panel (str "[data-detail=" (js/CSS.escape id) "]")))))
        linked-view (fn []
                      (let [id (fragment)]
                        (or (some-> ^js (target id) (.closest "[data-replay-section]")
                                    (.getAttribute "data-replay-section"))
                            (when anchor-view (anchor-view id)))))
        tab-view (fn [^js tab] (.getAttribute tab "data-replay-tab"))]
    (letfn [(set-open! [open?]
              (set! (.-hidden panel) (not open?))
              (.setAttribute toggle "aria-expanded" (str open?))
              (when on-change (on-change @current open?)))
            (select! [view remember? open?]
              (when (contains? sections view)
                (vreset! current view)
                (doseq [[key ^js node] sections]
                  (set! (.-hidden node) (not= key view)))
                (doseq [^js tab tabs]
                  (.setAttribute tab "aria-pressed" (str (= view (tab-view tab)))))
                (when remember?
                  (let [url (js/URL. (.-href js/location))]
                    (.set (.-searchParams url) "inspector" view)
                    (when-let [linked (linked-view)]
                      (when (not= linked view) (set! (.-hash url) "")))
                    (js/history.replaceState nil "" (.-href url))))
                (set-open! open?)))
            (open-anchor! []
              (when (and (not (.-hidden panel)) (= @current (linked-view)))
                (when-let [^js anchor (target (fragment))]
                  (loop [^js details (.closest anchor "details")]
                    (when details
                      (set! (.-open details) true)
                      (recur (.closest (.-parentElement details) "details"))))
                  (.scrollIntoView anchor #js {:block "nearest"}))))
            (follow-anchor! []
              (when-let [view (linked-view)]
                (select! view false true)
                (open-anchor!)))]
      (doseq [^js tab tabs]
        (set! (.-onclick tab) #(select! (tab-view tab) true true)))
      (set! (.-onclick toggle)
            (fn []
              (let [open? (.-hidden panel)]
                (set-open! open?)
                (when open?
                  (when-let [^js tab (some #(when (= @current (tab-view %)) %) tabs)]
                    (.focus tab))))))
      (.addEventListener js/document "keydown"
                         (fn [^js event]
                           (when (and (= "Escape" (.-key event))
                                      (not (.-defaultPrevented event))
                                      (not (.-hidden panel))
                                      (nil? (find-node js/document "dialog[open]")))
                             (.preventDefault event)
                             (.stopPropagation event)
                             (set-open! false)
                             (.focus toggle))))
      (.addEventListener js/window "hashchange" follow-anchor!)
      (.addEventListener js/document "click"
                         (fn [^js event]
                           (let [^js clicked (.-target event)]
                             (when (and (not (.-defaultPrevented event)) (instance? js/Element clicked))
                               (when-let [^js link (.closest clicked "a[href^='#']")]
                                 (when (and (= (.getAttribute link "href") (.-hash js/location)) (linked-view))
                                   (.preventDefault event)
                                   (follow-anchor!)))))))
      (let [requested (.get (js/URLSearchParams. (.-search js/location)) "inspector")
            linked (or (linked-view) (when (contains? sections requested) requested))]
        (select! (or linked initial) false (boolean (or linked reveal?))))
      {:select! select! :show! #(set-open! true) :open-anchor! open-anchor!})))

(defn mount-clock! [{:keys [play seek step speed]}]
  (let [root (find-node js/document "[data-replay-clock]")
        control #(find-node root (str "[data-clock=" % "]"))
        play-button (control "play")
        slider (control "seek")
        back (control "back")
        forward (control "forward")
        label (control "label")]
    (set! (.-onclick play-button) play)
    (set! (.-oninput slider) #(seek (js/Number (.-value slider))))
    (set! (.-onclick back) #(step -1))
    (set! (.-onclick forward) #(step 1))
    (when speed
      (let [speed-select (control "speed")]
        (set! (.-onchange speed-select) #(speed (js/Number (.-value speed-select))))))
    (fn [{:keys [text minute playing? available? minimum maximum back-text forward-text back-label forward-label]}]
      (when (some? text) (set! (.-textContent label) text))
      (when (some? playing?) (set! (.-textContent play-button) (if playing? "Pause" "Play")))
      (when (some? minimum) (set! (.-min slider) minimum))
      (when (some? maximum) (set! (.-max slider) maximum))
      (when (some? minute) (set! (.-value slider) minute))
      (when (some? available?)
        (doseq [^js node [play-button slider back forward]]
          (set! (.-disabled node) (not available?))))
      (when back-text (set! (.-textContent back) back-text))
      (when forward-text (set! (.-textContent forward) forward-text))
      (when back-label (.setAttribute back "aria-label" back-label))
      (when forward-label (.setAttribute forward "aria-label" forward-label)))))

(defn render-result! [result]
  (let [node (find-node js/document "[data-replay-result]")]
    (set! (.-hidden node) (nil? result))
    (when-let [{:keys [label value note href intervention]} result]
      (let [link (find-node node "a")]
        (.toggleAttribute node "data-intervention" (boolean intervention))
        (.setAttribute link "href" href)
        (set! (.-textContent (find-node link "span")) label)
        (set! (.-textContent (find-node link "strong")) value)
        (set! (.-textContent (find-node link "small")) note)))))
