(() => {
    const MIN_PLAYERS = 2;
    const MAX_PLAYERS = 9;
    const DEFAULT_PLAYERS = MAX_PLAYERS;
    const MAX_HOLE_CARDS = 4;
    const DEFAULT_PLAYER_STACK = 1000;
    const DEFAULT_SMALL_BLIND = 1;
    const DEFAULT_BIG_BLIND = 2;
    const GAME_VARIANTS = Object.freeze({
        texas: Object.freeze({
            id: "texas",
            label: "\u05d8\u05e7\u05e1\u05e1 \u05d4\u05d5\u05dc\u05d3\u05dd No-Limit",
            holeCards: 2
        }),
        omaha: Object.freeze({
            id: "omaha",
            label: "\u05d0\u05d5\u05de\u05d4\u05d4 4 \u05e7\u05dc\u05e4\u05d9\u05dd Limit",
            holeCards: 4
        })
    });
    const DEFAULT_GAME_VARIANT = GAME_VARIANTS.texas.id;
    const ECONOMY_FIELDS = Object.freeze({
        stack: 'stack',
        pendingBet: 'pendingBet'
    });
    const ECONOMY_FIELD_ORDER = Object.freeze([
        ECONOMY_FIELDS.stack,
        ECONOMY_FIELDS.pendingBet
    ]);
    const ECONOMY_LABELS = Object.freeze({
        stack: '\u05e1\u05d8\u05d0\u05e7',
        pendingBet: '\u05d4\u05d9\u05de\u05d5\u05e8'
    });
    const TABLE_POT_LABEL = '\u05e7\u05d5\u05e4\u05d4';
    const PLAYER_COMMITTED_LABEL = '\u05d1\u05e7\u05d5\u05e4\u05d4';
    const LIVE_RAISE_PRESETS = Object.freeze([
        { id: '0.5', factor: 0.5, descriptor: '\u05d7\u05e6\u05d9 \u05e7\u05d5\u05e4\u05d4' },
        { id: '0.75', factor: 0.75, descriptor: '75% \u05e7\u05d5\u05e4\u05d4' },
        { id: '1', factor: 1, descriptor: '\u05e7\u05d5\u05e4\u05d4 \u05de\u05dc\u05d0\u05d4' },
        { id: '1.5', factor: 1.5, descriptor: '150% \u05e7\u05d5\u05e4\u05d4' },
        { id: 'all-in', type: 'all-in', descriptor: '\u05d0\u05d5\u05dc \u05d0\u05d9\u05df' }
    ]);
    const SEAT_ACTIONS = Object.freeze([
        { id: 'fold', label: '\u05e7\u05d9\u05e4\u05d5\u05dc', className: 'seat-action--fold' },
        { id: 'check', label: "\u05e6'\u05e7 / \u05e7\u05d5\u05dc", className: 'seat-action--check' },
        { id: 'raise', label: '\u05e8\u05d9\u05d9\u05d6', className: 'seat-action--raise' }
    ]);
    const SEAT_LAYOUTS = Object.freeze({
        2: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "104%", left: "50%" }
        ]),
        3: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "70%", left: "97%" },
            { top: "70%", left: "3%" }
        ]),
        4: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "48%", left: "102%" },
            { top: "104%", left: "62%" },
            { top: "104%", left: "38%" }
        ]),
        5: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "26%", left: "94%" },
            { top: "83%", left: "84%" },
            { top: "83%", left: "16%" },
            { top: "26%", left: "6%" }
        ]),
        6: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "24%", left: "92%" },
            { top: "68%", left: "101%" },
            { top: "104%", left: "50%" },
            { top: "68%", left: "-1%" },
            { top: "24%", left: "8%" }
        ]),
        7: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "18%", left: "82%" },
            { top: "50%", left: "102%" },
            { top: "88%", left: "80%" },
            { top: "105%", left: "50%" },
            { top: "88%", left: "20%" },
            { top: "50%", left: "-2%" }
        ]),
        8: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "15%", left: "76%" },
            { top: "45%", left: "102%" },
            { top: "82%", left: "86%" },
            { top: "105%", left: "50%" },
            { top: "82%", left: "14%" },
            { top: "45%", left: "-2%" },
            { top: "15%", left: "24%" }
        ]),
        9: Object.freeze([
            { top: "-4%", left: "50%" },
            { top: "12%", left: "74%" },
            { top: "38%", left: "100%" },
            { top: "72%", left: "98%" },
            { top: "99%", left: "70%" },
            { top: "103%", left: "30%" },
            { top: "72%", left: "2%" },
            { top: "38%", left: "0%" },
            { top: "12%", left: "26%" }
        ])
    });

    const BOARD_PLACEHOLDERS = [
        "\u05e4\u05dc\u05d5\u05e4 \u0031",
        "\u05e4\u05dc\u05d5\u05e4 \u0032",
        "\u05e4\u05dc\u05d5\u05e4 \u0033",
        "\u05d8\u05e8\u05df",
        "\u05e8\u05d9\u05d1\u05e8"
    ];

    const PROBABILITY_PLACEHOLDER = "-";
    const ENUMERATION_LIMIT = 200000; // Increased for more exact calculations
    const PREFLOP_SIMULATIONS = 40000; // Increased accuracy for Monte Carlo
    const PROBABILITY_UPDATE_DELAY = 0; // Immediate updates
    const HIGHLIGHT_EPSILON = 1e-9;
    const WIN_LABEL = "\u05e0\u05d9\u05e6\u05d7\u05d5\u05df";
    const TIE_LABEL = "\u05ea\u05d9\u05e7\u05d5";

    const DEFAULT_SOLVER_SETTINGS = Object.freeze({
        potSize: 10,
        effectiveStack: 100,
        betSizePercent: 75,
        opponentProfile: "balanced",
        iterations: 20000
    });

    const SOLVER_PROFILES = new Set(["balanced", "tight", "loose", "aggressive"]);

    const SOLVER_MESSAGES = Object.freeze({
        default: "\u05d1\u05d7\u05e8\u05d5 \u05e7\u05dc\u05e4\u05d9\u05dd \u05d5\u05d2\u05d3\u05d9\u05e8\u05d5 \u05e4\u05e8\u05de\u05d8\u05e8\u05d9\u05dd \u05db\u05d3\u05d9 \u05dc\u05d4\u05e4\u05e2\u05d9\u05dc \u05d0\u05ea \u05d4\u05e1\u05d5\u05dc\u05d1\u05e8.",
        heroCardsRequired: "\u05d4\u05e7\u05e6\u05d4 \u05dc\u05e9\u05d7\u05e7\u05df 1 \u05e9\u05e0\u05d9 \u05e7\u05dc\u05e4\u05d9\u05dd \u05db\u05d3\u05d9 \u05dc\u05d4\u05e4\u05e2\u05d9\u05dc \u05d0\u05ea \u05d4\u05e1\u05d5\u05dc\u05d1\u05e8.",
        boardTooLong: "\u05de\u05e1\u05e4\u05e8 \u05e7\u05dc\u05e4\u05d9 \u05d4\u05e7\u05d4\u05d9\u05dc\u05d4 \u05d7\u05d5\u05e8\u05d2 \u05de\u05d4\u05de\u05d5\u05ea\u05e8.",
        insufficientDeck: "\u05dc\u05d0 \u05e0\u05d5\u05ea\u05e8\u05d5 \u05de\u05e1\u05e4\u05d9\u05e7 \u05e7\u05dc\u05e4\u05d9\u05dd \u05dc\u05d1\u05e0\u05d9\u05d9\u05ea \u05d8\u05d5\u05d5\u05d7 \u05d9\u05e8\u05d9\u05d1.",
        rangeUnavailable: "\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d2\u05d1\u05e9 \u05d8\u05d5\u05d5\u05d7 \u05d9\u05e8\u05d9\u05d1 \u05e2\u05d1\u05d5\u05e8 \u05e4\u05e8\u05de\u05d8\u05e8\u05d9\u05dd \u05d0\u05dc\u05d5.",
        simulationFailed: "\u05d4\u05e1\u05d9\u05de\u05d5\u05dc\u05e6\u05d9\u05d4 \u05dc\u05d0 \u05d4\u05e6\u05dc\u05d9\u05d7\u05d4 \u05dc\u05e8\u05d5\u05e5. \u05e0\u05e1\u05d4 \u05dc\u05d4\u05e4\u05d7\u05d9\u05ea \u05d0\u05ea \u05de\u05e1\u05e4\u05e8 \u05d4\u05e9\u05d7\u05e7\u05e0\u05d9\u05dd \u05d0\u05d5 \u05dc\u05d0\u05e4\u05e1 \u05d0\u05ea \u05d4\u05d9\u05d3.",
        betParametersMissing: "\u05e7\u05d1\u05e2\u05d5 \u05d2\u05d5\u05d3\u05dc \u05e7\u05d5\u05e4\u05d4 \u05d5\u05e1\u05d8\u05d0\u05e7 \u05d0\u05e4\u05e7\u05d8\u05d9\u05d1\u05d9 \u05d7\u05d9\u05d5\u05d1\u05d9 \u05db\u05d3\u05d9 \u05dc\u05d4\u05e4\u05e2\u05d9\u05dc \u05d4\u05d9\u05de\u05d5\u05e8 GTO.",
        villainMustFold: "\u05d4\u05d9\u05e8\u05d9\u05d1 \u05e6\u05e8\u05d9\u05da \u05dc\u05e7\u05e4\u05dc \u05d0\u05ea \u05d4\u05d8\u05d5\u05d5\u05d7 \u05d4\u05de\u05dc\u05d0 \u05de\u05d5\u05dc \u05d4\u05d4\u05d9\u05de\u05d5\u05e8 \u05d4\u05de\u05d5\u05e6\u05e2."
    });
    const POSITION_SEQUENCE = [
        "דילר",
        "סמול בליינד",
        "ביג בליינד",
        "UTG",
        "UTG+1",
        "UTG+2",
        "מידל פוזישן",
        "הייג'ק",
        "קאט-אוף"
    ];
    const HEADS_UP_POSITIONS = [
        "דילר / סמול בליינד",
        "ביג בליינד"
    ];
    const GG_READER_API_BASE = "http://127.0.0.1:8787";
    const GG_READER_WS_URL = "ws://127.0.0.1:8787/ws/gg-reader";
    const GG_READER_MOCK_URL = "mock/gg_snapshot_example.json";
    const GG_READER_CONFIDENCE_MIN = 0.75;
    const GG_READER_CONFIDENCE_DIRECT = 0.9;
    const GG_READER_HISTORY_LIMIT = 80;
    const GG_READER_BROWSER_FPS = 2;
    const GG_READER_BROWSER_FRAME_INTERVAL_MS = Math.round(1000 / GG_READER_BROWSER_FPS);
    const GG_READER_RENDER_INTERVAL_MS = 250;
    const GG_READER_BROWSER_MAX_FRAME_WIDTH = 1920;
    const GG_READER_BROWSER_JPEG_QUALITY = 0.9;
    const GG_READER_MAX_IN_FLIGHT_FRAMES = 2;
    const GG_READER_PROBABILITY_THROTTLE_MS = 5000;
    const GG_READER_STATUS_LOG_INTERVAL_MS = 1000;
    const GG_READER_LIVE_ENUMERATION_LIMIT = 50000;
    const GG_READER_LIVE_PREFLOP_SIMULATIONS = 8000;


    let probabilityUpdateTimer = null;
    let solverUpdateTimer = null;
    let dealerDragState = null;

    const suits = [
        { id: "S", symbol: "\u2660", name: "\u05e2\u05dc\u05d4", color: "black" },
        { id: "H", symbol: "\u2665", name: "\u05dc\u05d1", color: "red" },
        { id: "D", symbol: "\u2666", name: "\u05d9\u05d4\u05dc\u05d5\u05dd", color: "red" },
        { id: "C", symbol: "\u2663", name: "\u05ea\u05dc\u05ea\u05df", color: "black" }
    ];

    const ranks = [
        { id: "2", label: "2", name: "\u05e9\u05ea\u05d9\u05d9\u05dd" },
        { id: "3", label: "3", name: "\u05e9\u05dc\u05d5\u05e9" },
        { id: "4", label: "4", name: "\u05d0\u05e8\u05d1\u05e2" },
        { id: "5", label: "5", name: "\u05d7\u05de\u05e9" },
        { id: "6", label: "6", name: "\u05e9\u05e9" },
        { id: "7", label: "7", name: "\u05e9\u05d1\u05e2" },
        { id: "8", label: "8", name: "\u05e9\u05de\u05d5\u05e0\u05d4" },
        { id: "9", label: "9", name: "\u05ea\u05e9\u05e2" },
        { id: "10", label: "10", name: "\u05e2\u05e9\u05e8" },
        { id: "J", label: "J", name: "\u05e0\u05e1\u05d9\u05da" },
        { id: "Q", label: "Q", name: "\u05de\u05dc\u05db\u05d4" },
        { id: "K", label: "K", name: "\u05de\u05dc\u05da" },
        { id: "A", label: "A", name: "\u05d0\u05e1" }
    ];

    const rankValue = new Map(ranks.map((rank, index) => [rank.id, index]));
    const rankByValue = new Map(ranks.map((rank, index) => [index, rank]));

    const state = {
        deck: [],
        cardById: new Map(),
        slotByKey: new Map(),
        cardAssignments: new Map(),
        activeSlot: null,
        playersCount: DEFAULT_PLAYERS,
        gameVariant: DEFAULT_GAME_VARIANT,
        seats: [],
        seatMeta: [],
        probabilityDisplays: [],
        playerEconomy: Array.from({ length: MAX_PLAYERS }, () => createDefaultEconomy()),
        dealerSeatIndex: 0,
        isAutoAdvancePaused: false,
        showSeatProbabilities: true,
        deferProbabilityUpdate: false,
        mode: "equity",
        activeView: "equity",
        ggReader: createInitialGgReaderState(),
        isSettingsMenuOpen: false,
        openToolbarMenu: null,
        isSolverPanelOpen: false,
        solverSettings: { ...DEFAULT_SOLVER_SETTINGS },
        resultsObserver: null,
        lastSolverAnalysis: null,
        liveGame: createInitialLiveGameState()
    };

    function createInitialLiveGameState() {
        return {
            active: false,
            handActive: false,
            stage: "idle",
            deck: [],
            players: [],
            boardCards: [],
            boardIndex: 0,
            pot: 0,
            currentBet: 0,
            bigBlind: DEFAULT_BIG_BLIND,
            smallBlind: DEFAULT_SMALL_BLIND,
            heroIndex: 0,
            villainProfile: DEFAULT_SOLVER_SETTINGS.opponentProfile,
            awaitingHero: false,
            log: [],
            lastAnalysis: null,
            raiseSelection: null
        };
    }

    const elements = {
        table: document.getElementById("table"),
        board: document.getElementById("board-cards"),
        tablePot: document.getElementById("table-pot"),
        deck: document.getElementById("deck"),
        deckOverlay: document.getElementById("deck-overlay"),
        deckOverlayClose: document.getElementById("deck-overlay-close"),
        dealerButton: null,
        appShell: document.querySelector(".app-shell"),
        playerCountLabel: document.getElementById("player-count-label"),
        playerCountMenu: document.getElementById("player-count-menu"),
        gameTypeLabel: document.getElementById("game-type-label"),
        gameTypeMenu: document.getElementById("game-type-menu"),
        readGgTable: document.getElementById("read-gg-table"),
        ggReaderStatus: document.getElementById("gg-reader-status"),
        ggReaderStatusText: document.getElementById("gg-reader-status-text"),
        ggReaderConfidence: document.getElementById("gg-reader-confidence"),
        ggReaderMonitor: document.getElementById("gg-reader-monitor"),
        ggReaderStop: document.getElementById("gg-reader-stop"),
        ggReaderHistoryToggle: document.getElementById("gg-reader-history-toggle"),
        ggReaderHistory: document.getElementById("gg-reader-history"),
        ggReaderHistoryList: document.getElementById("gg-reader-history-list"),
        ggReaderHistoryDownload: document.getElementById("gg-reader-history-download"),
        ggReaderDebug: document.getElementById("gg-reader-debug"),
        ggReaderTableInfo: document.getElementById("gg-reader-table-info"),
        ggReaderSeats: document.getElementById("gg-reader-seats"),
        ggReaderDebugOutput: document.getElementById("gg-reader-debug-output"),
        ggReaderRoiOverlay: document.getElementById("gg-reader-roi-overlay"),
        ggReaderFieldCrops: document.getElementById("gg-reader-field-crops"),
        dealRandom: document.getElementById("deal-random"),
        liveGame: document.getElementById("live-game"),
        clearAll: document.getElementById("clear-all"),
        calculate: document.getElementById("calculate"),
        reset: document.getElementById("reset"),
        errors: document.getElementById("errors"),
        results: document.getElementById("results"),
        controls: document.querySelector(".controls"),
        modeToggle: document.getElementById("mode-toggle"),
        settingsToggle: document.getElementById("settings-menu-toggle"),
        settingsMenu: document.getElementById("settings-menu"),
        settingsPlayerCount: document.getElementById("settings-player-count"),
        solverControls: document.getElementById("solver-controls"),
        solverResults: document.getElementById("solver-results"),
        solverPotSize: document.getElementById("solver-pot-size"),
        solverEffectiveStack: document.getElementById("solver-effective-stack"),
        solverBetSize: document.getElementById("solver-bet-size"),
        solverOpponentProfile: document.getElementById("solver-opponent-profile"),
        solverIterations: document.getElementById("solver-iterations"),
        solverRun: document.getElementById("solver-run"),
        solverReset: document.getElementById("solver-reset"),
        solverSettingsToggle: document.getElementById("solver-settings-toggle"),
        appMenu: document.getElementById("app-menu"),
        calculatorView: document.getElementById("calculator-view"),
        statisticsView: document.getElementById("statistics-view"),
        calculatorLayout: document.querySelector(".calculator-layout"),
        liveGamePanel: document.getElementById("live-game-panel"),
        liveGameStatus: document.getElementById("live-game-status"),
        liveGameLog: document.getElementById("live-game-log"),
        liveGameExit: document.getElementById("live-game-exit"),
        liveActionFold: document.getElementById("live-action-fold"),
        liveActionCheck: document.getElementById("live-action-check"),
        liveActionRaise: document.getElementById("live-action-raise"),
        liveActionRaiseOptions: document.getElementById("live-action-raise-options"),
        liveActionNext: document.getElementById("live-action-next"),
        menuButtons: []
    };

    document.addEventListener("DOMContentLoaded", init);
    document.addEventListener("app:settings-live-game", handleLiveGameStartRequest);

    function createInitialGgReaderState() {
        return {
            running: false,
            status: "idle",
            lastSnapshot: null,
            latestSnapshot: null,
            latestSnapshotSeq: 0,
            lastRenderedSnapshotSeq: 0,
            pendingSnapshot: null,
            history: [],
            connection: null,
            browserStream: null,
            browserVideo: null,
            browserCanvas: null,
            browserCrop: null,
            browserFrameTimer: null,
            browserFrameInFlight: false,
            browserFrameInFlightCount: 0,
            browserFrameNextAt: 0,
            browserFrameSeq: 0,
            browserFrameInFlightStartedAt: 0,
            browserFrameInFlightStartedAts: [],
            renderTimer: null,
            frameTimes: [],
            captureTimes: [],
            responseTimes: [],
            renderTimes: [],
            actualFps: 0,
            captureFps: 0,
            parseFps: 0,
            renderFps: 0,
            lastFrameMs: null,
            lastParseMs: null,
            lastDecodeMs: null,
            lastCropMs: null,
            lastReaderParseMs: null,
            lastEncodeMs: null,
            lastImageBytes: 0,
            lastFrameBytes: 0,
            lastInFlightMs: 0,
            lastSnapshotReceivedAt: 0,
            latestServerReceivedAt: 0,
            lastResponseAt: 0,
            lastRenderAt: 0,
            lastApplySnapshotMs: 0,
            lastProbabilityMs: 0,
            lastProbabilitySnapshotSignature: "",
            lastProbabilityUpdateAt: 0,
            lastPipelineLogAt: 0,
            droppedFrames: 0,
            staleResponsesIgnored: 0,
            failedReads: 0,
            errors: [],
            potOverride: null,
            isHistoryOpen: false,
            lastStatusText: "GG מנותק"
        };
    }

    function init() {
        if (!elements.table || !elements.board || !elements.deck) {
            console.warn("Alpha Poker UI: missing core elements, aborting init.");
            return;
        }

        buildDeck();
        renderDeck();
        buildBoard();
        buildSeats();
        initializePlayerEconomy();
        initDealerButton();
        updateGameVariantUI();
        updateSeatStates();
        updatePlayerCountLabel();
        updateSeatPositionLabels();
        bindControls();
        bindModeControls();
        bindToolbarActions();
        bindToolbarChoiceMenus();
        bindGgReaderControls();
        bindSolverControls();
        bindSolverPanelToggle();
        bindMenuNavigation();
        bindSettingsMenu();
        setSeatProbabilitiesVisible(state.showSeatProbabilities);
        refreshSettingsMenu();
        bindDeckOverlay();
        bindLiveGameControls();
        setupResultsLayoutObserver();
        syncSolverInputs();
        updateModeUI();
        updateActiveView();
        setTimeout(() => setActiveView("equity"), 0);
        ensureActiveSlot();
        scheduleImmediateProbabilityUpdate();
        renderGgReaderStatus();
        refreshSettingsMenu();
    }

    function buildDeck() {
        state.deck = [];
        state.cardById.clear();

        suits.forEach((suit) => {
            ranks.forEach((rank) => {
                const suitIndex = getSuitIndex(suit.id);
                const card = {
                    id: `${rank.id}${suit.id}`,
                    rank,
                    suit,
                    rankValue: rankValue.get(rank.id),
                    suitIndex
                };
                state.deck.push(card);
                state.cardById.set(card.id, card);
            });
        });
    }

    function renderDeck() {
        if (!elements.deck) {
            return;
        }

        elements.deck.innerHTML = "";
        const fragment = document.createDocumentFragment();

        suits.forEach((suit) => {
            const row = document.createElement("div");
            row.className = `deck-row deck-row-${suit.id.toLowerCase()}`;
            row.dataset.suit = suit.id;

            const label = document.createElement("div");
            label.className = "deck-row-label";
            label.innerHTML = `<span class="suit-symbol${suit.color === "red" ? " red" : ""}">${suit.symbol}</span>`;
            label.title = suit.name;

            const cardsContainer = document.createElement("div");
            cardsContainer.className = "deck-row-cards";

            ranks.forEach((rank) => {
                const cardId = `${rank.id}${suit.id}`;
                const card = state.cardById.get(cardId);
                if (!card) {
                    return;
                }
                const cardEl = document.createElement("button");
                cardEl.type = "button";
                cardEl.className = `deck-card deck-card--${card.suit.id.toLowerCase()}`;
                cardEl.dataset.suit = card.suit.id;
                cardEl.dataset.cardId = card.id;
                cardEl.innerHTML = `<span class="rank">${card.rank.label}</span><span class="suit">${card.suit.symbol}</span>`;
                cardEl.addEventListener("click", () => handleDeckCardClick(card));
                cardsContainer.appendChild(cardEl);
            });

            row.append(label, cardsContainer);
            fragment.appendChild(row);
        });

        elements.deck.appendChild(fragment);
    }

    function buildBoard() {
        elements.board.innerHTML = "";
        BOARD_PLACEHOLDERS.forEach((placeholder, index) => {
            const slot = createCardSlot({
                key: `board-${index}`,
                placeholder,
                type: "board",
                order: index
            });
            elements.board.appendChild(slot);
        });
    }

    function buildSeats() {
        for (let i = 0; i < MAX_PLAYERS; i += 1) {
            const seat = createSeat(i);
            state.seats.push(seat);
            elements.table.appendChild(seat);
        }
    }

    function getActiveGameVariant() {
        return GAME_VARIANTS[state.gameVariant] || GAME_VARIANTS[DEFAULT_GAME_VARIANT];
    }

    function isOmahaVariant() {
        return getActiveGameVariant().id === GAME_VARIANTS.omaha.id;
    }

    function getRequiredHoleCards() {
        return getActiveGameVariant().holeCards;
    }

    function getPlayerCardSlots(playerIndex) {
        const slots = [];
        for (let c = 0; c < MAX_HOLE_CARDS; c += 1) {
            const slot = state.slotByKey.get(`player-${playerIndex}-${c}`);
            if (slot) {
                slots.push(slot);
            }
        }
        return slots;
    }

    function getSlotHoleIndex(slot) {
        const value = Number(slot?.dataset?.holeIndex);
        return Number.isFinite(value) ? value : 0;
    }

    function isSlotActiveForCurrentGame(slot) {
        if (!slot) {
            return false;
        }
        if (slot.dataset.slotType !== "player") {
            return true;
        }
        const playerIndex = Number(slot.dataset.playerIndex);
        if (!Number.isInteger(playerIndex) || playerIndex < 0 || playerIndex >= state.playersCount) {
            return false;
        }
        return getSlotHoleIndex(slot) < getRequiredHoleCards();
    }

    function clearPlayerSlots(playerIndex, options = {}) {
        getPlayerCardSlots(playerIndex).forEach((slot) => clearSlot(slot, options));
    }

    function updateGameVariantUI(options = {}) {
        const { suppressUpdate = false } = options;
        const previousDefer = state.deferProbabilityUpdate;
        state.deferProbabilityUpdate = true;

        state.slotByKey.forEach((slot) => {
            if (slot.dataset.slotType !== "player") {
                return;
            }
            const isActive = isSlotActiveForCurrentGame(slot);
            slot.hidden = !isActive;
            slot.classList.toggle("card-slot--inactive-game", !isActive);
            slot.setAttribute("aria-hidden", isActive ? "false" : "true");
            if (!isActive) {
                clearSlot(slot, { suppressUpdate: true });
            }
        });

        if (state.activeSlot && !isSlotActiveForCurrentGame(state.activeSlot)) {
            setActiveSlot(null);
        }

        if (elements.table) {
            elements.table.dataset.gameVariant = getActiveGameVariant().id;
        }
        if (elements.appShell) {
            elements.appShell.dataset.gameVariant = getActiveGameVariant().id;
        }

        state.deferProbabilityUpdate = previousDefer;
        refreshToolbarControls();
        ensureActiveSlot("player");

        if (!suppressUpdate && !state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
    }

    function createSeat(index) {
        const seat = document.createElement("div");
        seat.className = `seat seat-${index}`;
        seat.dataset.playerIndex = String(index);

        const probability = document.createElement("div");
        probability.className = "seat-probability";

        const tieLine = document.createElement("div");
        tieLine.className = "probability-line probability-tie";
        tieLine.textContent = `${TIE_LABEL}: ${PROBABILITY_PLACEHOLDER}`;

        const winLine = document.createElement("div");
        winLine.className = "probability-line probability-win";
        winLine.textContent = `${WIN_LABEL}: ${PROBABILITY_PLACEHOLDER}`;

        probability.append(tieLine, winLine);

        const label = document.createElement("div");
        label.className = "seat-label";
        const labelName = document.createElement("span");
        labelName.className = "seat-label__name";
        labelName.textContent = `שחקן ${index + 1}`;
        const positionLabel = document.createElement("span");
        positionLabel.className = "seat-position";
        label.append(labelName, positionLabel);

        const cardsRow = document.createElement("div");
        cardsRow.className = "card-row";

        for (let c = 0; c < MAX_HOLE_CARDS; c += 1) {
            const slot = createCardSlot({
                key: `player-${index}-${c}`,
                placeholder: `קלף ${c + 1}`,
                type: "player",
                order: index * MAX_HOLE_CARDS + c,
                playerIndex: index,
                holeIndex: c
            });
            cardsRow.appendChild(slot);
        }

        const betDisplay = document.createElement('div');
        betDisplay.className = 'seat-bet';
        betDisplay.setAttribute('aria-hidden', 'true');

        const actionDisplay = document.createElement("div");
        actionDisplay.className = "seat-live-action";
        actionDisplay.hidden = true;
        actionDisplay.setAttribute("aria-hidden", "true");

        const economyControls = createSeatEconomyControls(index);

        seat.append(probability, cardsRow, label, actionDisplay, betDisplay, economyControls.container);
        state.seatMeta[index] = {
            label,
            nameEl: labelName,
            positionEl: positionLabel,
            actionDisplay,
            betDisplay,
            economyInputs: economyControls.inputs,
            betButton: economyControls.betButton,
            committedDisplay: economyControls.committedDisplay,
            actionRow: economyControls.actionsRow,
            actionButtons: economyControls.actionButtons
        };
        state.probabilityDisplays[index] = {
            container: probability,
            tie: tieLine,
            win: winLine
        };
        return seat;
    }

    function createSeatEconomyControls(playerIndex) {
        const container = document.createElement('div');
        container.className = 'seat-economy';
        container.dataset.playerIndex = String(playerIndex);

        const inputs = {};
        let betButton = null;

        ECONOMY_FIELD_ORDER.forEach((fieldKey) => {
            const field = document.createElement('label');
            field.className = 'seat-economy__field';
            field.dataset.economyField = fieldKey;

            const caption = document.createElement('span');
            caption.className = 'seat-economy__label';
            caption.textContent = ECONOMY_LABELS[fieldKey] || fieldKey;
            field.appendChild(caption);

            const input = document.createElement('input');
            input.type = 'number';
            input.className = 'seat-economy__input';
            input.inputMode = 'decimal';
            input.min = '0';
            input.step = '0.5';
            input.dataset.playerIndex = String(playerIndex);
            input.dataset.economyField = fieldKey;
            input.addEventListener('input', handleEconomyInput);
            input.addEventListener('change', handleEconomyInput);
            input.addEventListener('blur', handleEconomyInput);

            if (fieldKey === ECONOMY_FIELDS.pendingBet) {
                const controlRow = document.createElement('div');
                controlRow.className = 'seat-economy__bet-control';
                controlRow.appendChild(input);

                const commitButton = document.createElement('button');
                commitButton.type = 'button';
                commitButton.className = 'seat-economy__commit';
                commitButton.textContent = '\u05d4\u05de\u05e8';
                commitButton.dataset.playerIndex = String(playerIndex);
                commitButton.addEventListener('click', handleCommitBetClick);

                controlRow.appendChild(commitButton);
                field.appendChild(controlRow);
                betButton = commitButton;
            } else {
                field.appendChild(input);
            }

            container.appendChild(field);
            inputs[fieldKey] = input;
        });

        const committedDisplay = document.createElement('div');
        committedDisplay.className = 'seat-economy__committed';
        committedDisplay.textContent = `${PLAYER_COMMITTED_LABEL}: 0`;
        container.appendChild(committedDisplay);

        const actionsRow = document.createElement('div');
        actionsRow.className = 'seat-actions';
        actionsRow.dataset.playerIndex = String(playerIndex);

        const actionButtons = SEAT_ACTIONS.map((definition) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `seat-action ${definition.className}`;
            button.textContent = definition.label;
            button.dataset.playerIndex = String(playerIndex);
            button.dataset.seatAction = definition.id;
            button.addEventListener('click', handleSeatActionClick);
            actionsRow.appendChild(button);
            return button;
        });

        container.appendChild(actionsRow);

        return {
            container,
            inputs,
            betButton,
            committedDisplay,
            actionsRow,
            actionButtons
        };
    }

    function initializePlayerEconomy() {
        for (let i = 0; i < MAX_PLAYERS; i += 1) {
            state.playerEconomy[i] = createDefaultEconomy();
        }
        applyDefaultBlinds();
        syncPlayerEconomyInputs();
    }

    function createDefaultEconomy() {
        return {
            stack: DEFAULT_PLAYER_STACK,
            pendingBet: 0,
            committedBet: 0
        };
    }

    function ensurePlayerEconomy(index) {
        if (!state.playerEconomy[index]) {
            state.playerEconomy[index] = createDefaultEconomy();
        }
        return state.playerEconomy[index];
    }

    function isGgSeatActiveInLastSnapshot(index) {
        const snapshot = state.ggReader && state.ggReader.lastSnapshot;
        const seats = Array.isArray(snapshot?.seats) ? snapshot.seats : [];
        const seat = seats.find((item) => Number(item?.physicalSeatIndex) === Number(index));
        if (!seat) {
            return index < state.playersCount;
        }
        return seat.active !== false;
    }

    function applyDefaultBlinds() {
        for (let i = 0; i < state.playersCount; i += 1) {
            const economy = ensurePlayerEconomy(i);
            economy.pendingBet = 0;
            economy.committedBet = 0;
        }
        if (state.playersCount >= 1) {
            const smallBlind = ensurePlayerEconomy(0);
            smallBlind.pendingBet = DEFAULT_SMALL_BLIND;
            commitPendingBetForPlayer(0);
        }
        if (state.playersCount >= 2) {
            const bigBlind = ensurePlayerEconomy(1);
            bigBlind.pendingBet = DEFAULT_BIG_BLIND;
            commitPendingBetForPlayer(1);
        }
        for (let i = 0; i < state.playersCount; i += 1) {
            updateSeatBetDisplay(i);
        }
        updateTablePotDisplay();
    }

    function syncPlayerEconomyInputs() {
        state.seatMeta.forEach((meta, index) => {
            if (!meta || !meta.economyInputs) {
                return;
            }
            const data = ensurePlayerEconomy(index);
            const isActive = index < state.playersCount && isGgSeatActiveInLastSnapshot(index);

            const stackInput = meta.economyInputs[ECONOMY_FIELDS.stack];
            updateEconomyInput(stackInput, data.stack, isActive);

            const pendingInput = meta.economyInputs[ECONOMY_FIELDS.pendingBet];
            updateEconomyInput(pendingInput, data.pendingBet, isActive);

            if (meta.betButton) {
                const canCommit = isActive && data.pendingBet > 0 && data.stack > 0;
                meta.betButton.disabled = !canCommit;
            }

            if (meta.committedDisplay) {
                meta.committedDisplay.textContent = `${PLAYER_COMMITTED_LABEL}: ${formatChipAmount(data.committedBet)}`;
            }
            if (Array.isArray(meta.actionButtons) && meta.actionButtons.length) {
                meta.actionButtons.forEach((button) => {
                    if (button instanceof HTMLButtonElement) {
                        button.disabled = !isActive;
                        if (!isActive) {
                            button.classList.remove('is-selected');
                        }
                    }
                });
            }
            updateSeatBetDisplay(index);
        });
        updateTablePotDisplay();
    }

    function calculateTotalBetAmount() {
        let total = 0;
        for (let i = 0; i < state.playersCount; i += 1) {
            const economy = ensurePlayerEconomy(i);
            if (economy && Number.isFinite(economy.committedBet)) {
                total += economy.committedBet;
            }
        }
        return Math.max(0, Math.round(total * 100) / 100);
    }

    function formatChipAmount(amount) {
        if (!Number.isFinite(amount)) {
            return '0';
        }
        return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
    }

    function updateSeatBetDisplay(index) {
        if (!Number.isInteger(index) || index < 0 || index >= MAX_PLAYERS) {
            return;
        }
        const meta = state.seatMeta[index];
        if (!meta || !meta.betDisplay) {
            return;
        }
        const isSeatActive = index < state.playersCount && isGgSeatActiveInLastSnapshot(index);
        const economy = ensurePlayerEconomy(index);
        const totalBet = sanitizeEconomyValue((economy.pendingBet || 0) + (economy.committedBet || 0));
        if (isSeatActive && totalBet > 0) {
            const betLabel = ECONOMY_LABELS.pendingBet || 'הימור';
            meta.betDisplay.textContent = `${betLabel}: ${formatChipAmount(totalBet)}`;
            meta.betDisplay.classList.add('seat-bet--visible');
            meta.betDisplay.setAttribute('aria-hidden', 'false');
            return;
        }
        meta.betDisplay.textContent = '';
        meta.betDisplay.classList.remove('seat-bet--visible');
        meta.betDisplay.setAttribute('aria-hidden', 'true');
    }

    function updateTablePotDisplay() {
        if (!elements.tablePot) {
            return;
        }
        const importedPot = state.ggReader && Number.isFinite(state.ggReader.potOverride)
            ? state.ggReader.potOverride
            : null;
        const totalPot = importedPot !== null ? importedPot : calculateTotalBetAmount();
        elements.tablePot.textContent = `${TABLE_POT_LABEL}: ${formatChipAmount(totalPot)}`;
    }

    function commitPendingBetForPlayer(index) {
        if (!Number.isInteger(index) || index < 0 || index >= MAX_PLAYERS) {
            return 0;
        }
        const economy = ensurePlayerEconomy(index);
        const pending = sanitizeEconomyValue(economy.pendingBet);
        const stackAvailable = sanitizeEconomyValue(economy.stack);
        if (pending <= 0 || stackAvailable <= 0) {
            economy.pendingBet = pending;
            return 0;
        }
        const commitAmount = Math.min(pending, stackAvailable);
        const committed = sanitizeEconomyValue(economy.committedBet);
        economy.committedBet = sanitizeEconomyValue(committed + commitAmount);
        economy.stack = sanitizeEconomyValue(stackAvailable - commitAmount);
        economy.pendingBet = sanitizeEconomyValue(pending - commitAmount);
        updateSeatBetDisplay(index);
        return commitAmount;
    }

    function handleCommitBetClick(event) {
        const button = event.currentTarget;
        if (!(button instanceof HTMLButtonElement)) {
            return;
        }
        const playerIndex = Number(button.dataset.playerIndex);
        if (!Number.isInteger(playerIndex) || playerIndex < 0 || playerIndex >= MAX_PLAYERS) {
            return;
        }
        if (playerIndex >= state.playersCount) {
            return;
        }
        commitPendingBetForPlayer(playerIndex);
        syncPlayerEconomyInputs();
    }

    function handleSeatActionClick(event) {
        const button = event.currentTarget;
        if (!(button instanceof HTMLButtonElement)) {
            return;
        }
        const action = button.dataset.seatAction || '';
        const playerIndex = Number(button.dataset.playerIndex);
        if (!action || !Number.isInteger(playerIndex) || playerIndex < 0 || playerIndex >= MAX_PLAYERS) {
            return;
        }
        const container = button.parentElement;
        if (container && container.classList.contains('seat-actions')) {
            container.querySelectorAll('.seat-action').forEach((actionButton) => {
                if (actionButton instanceof HTMLButtonElement) {
                    actionButton.classList.toggle('is-selected', actionButton === button);
                }
            });
        }
        const seatEvent = new CustomEvent('app:seat-action', {
            detail: { playerIndex, action },
            bubbles: true
        });
        button.dispatchEvent(seatEvent);
    }

    function updateEconomyInput(input, value, isActive) {
        if (!input) {
            return;
        }
        const sanitized = Number.isFinite(value) ? value : 0;
        const normalized = Math.round(sanitized * 100) / 100;
        const normalizedText = normalized.toString();
        if (input.value !== normalizedText) {
            input.value = normalizedText;
        }
        input.disabled = !isActive;
    }

    function sanitizeEconomyValue(rawValue) {
        if (!Number.isFinite(rawValue)) {
            return 0;
        }
        return Math.max(0, Math.round(rawValue * 100) / 100);
    }

    function handleEconomyInput(event) {
        const input = event.target;
        if (!(input instanceof HTMLInputElement)) {
            return;
        }
        const { economyField } = input.dataset;
        const playerIndex = Number(input.dataset.playerIndex);
        if (!Number.isInteger(playerIndex) || playerIndex < 0 || playerIndex >= MAX_PLAYERS) {
            return;
        }
        if (!economyField || !ECONOMY_FIELD_ORDER.includes(economyField)) {
            return;
        }
        const economy = ensurePlayerEconomy(playerIndex);
        const rawValue = Number.parseFloat(input.value);
        const sanitized = sanitizeEconomyValue(rawValue);
        const sanitizedText = sanitized.toString();
        if (input.value !== sanitizedText) {
            input.value = sanitizedText;
        }

        if (economyField === ECONOMY_FIELDS.pendingBet) {
            economy.pendingBet = sanitized;
            const meta = state.seatMeta[playerIndex];
            if (meta && meta.betButton) {
                const canCommit = playerIndex < state.playersCount && economy.pendingBet > 0 && economy.stack > 0;
                meta.betButton.disabled = !canCommit;
            }
            updateSeatBetDisplay(playerIndex);
            return;
        }

        economy[economyField] = sanitized;
        syncPlayerEconomyInputs();
    }

    function initDealerButton() {
        if (!elements.table || elements.dealerButton) {
            return;
        }

        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "dealer-chip";
        chip.textContent = "D";
        chip.setAttribute("aria-label", "אסימון דילר");
        chip.addEventListener("pointerdown", handleDealerPointerDown);
        elements.dealerButton = chip;
        placeDealerButton();
    }

    function ensureDealerSeatIndex() {
        if (state.playersCount < MIN_PLAYERS) {
            state.dealerSeatIndex = 0;
            return state.dealerSeatIndex;
        }
        const normalized = ((state.dealerSeatIndex % state.playersCount) + state.playersCount) % state.playersCount;
        if (normalized !== state.dealerSeatIndex) {
            state.dealerSeatIndex = normalized;
        }
        return state.dealerSeatIndex;
    }

    function getPositionSequence(count) {
        if (count < MIN_PLAYERS) {
            return [];
        }
        if (count === 2) {
            return HEADS_UP_POSITIONS.slice(0, count);
        }
        return POSITION_SEQUENCE.slice(0, Math.min(count, POSITION_SEQUENCE.length));
    }

    function updateSeatPositionLabels() {
        if (!state.seatMeta || !state.seatMeta.length) {
            return;
        }

        const activeCount = state.playersCount;
        if (activeCount < MIN_PLAYERS) {
            state.seatMeta.forEach((meta) => {
                if (meta && meta.positionEl) {
                    meta.positionEl.textContent = "";
                    meta.label?.classList.remove("has-position");
                }
            });
            placeDealerButton();
            return;
        }

        ensureDealerSeatIndex();
        const positions = getPositionSequence(activeCount);

        state.seatMeta.forEach((meta, index) => {
            if (!meta || !meta.positionEl) {
                return;
            }
            if (index >= activeCount) {
                meta.positionEl.textContent = "";
                meta.label?.classList.remove("has-position");
                return;
            }
            const relativeIndex = (index - state.dealerSeatIndex + activeCount) % activeCount;
            const positionName = positions[relativeIndex] || "";
            if (positionName) {
                meta.positionEl.textContent = `(${positionName})`;
                meta.label?.classList.add("has-position");
            } else {
                meta.positionEl.textContent = "";
                meta.label?.classList.remove("has-position");
            }
        });
        placeDealerButton();
    }

    function placeDealerButton() {
        if (!elements.dealerButton || !elements.table || !state.seats.length) {
            return;
        }
        ensureDealerSeatIndex();
        const seat = state.seats[state.dealerSeatIndex];
        const label = seat ? seat.querySelector(".seat-label") : null;
        if (!label) {
            return;
        }
        if (elements.dealerButton.parentElement !== label) {
            label.appendChild(elements.dealerButton);
        }
        elements.dealerButton.classList.remove("is-dragging");
        elements.dealerButton.style.removeProperty("position");
        elements.dealerButton.style.removeProperty("left");
        elements.dealerButton.style.removeProperty("top");
        elements.dealerButton.style.removeProperty("transform");
        elements.dealerButton.style.removeProperty("z-index");
        elements.dealerButton.setAttribute("aria-label", `אסימון דילר - שחקן ${state.dealerSeatIndex + 1}`);
    }

    function setDealerSeatIndex(index) {
        if (!Number.isFinite(index)) {
            return;
        }
        const count = state.playersCount;
        if (count < MIN_PLAYERS) {
            state.dealerSeatIndex = 0;
            placeDealerButton();
            return;
        }
        const normalized = ((Number(index) % count) + count) % count;
        if (normalized === state.dealerSeatIndex) {
            updateSeatPositionLabels();
            return;
        }
        state.dealerSeatIndex = normalized;
        updateSeatPositionLabels();
    }

    function handleDealerPointerDown(event) {
        if (!elements.dealerButton) {
            return;
        }
        event.preventDefault();
        elements.dealerButton.setPointerCapture(event.pointerId);
        const rect = elements.dealerButton.getBoundingClientRect();
        const offsetX = event.clientX - rect.left;
        const offsetY = event.clientY - rect.top;
        dealerDragState = { pointerId: event.pointerId, offsetX, offsetY };
        elements.dealerButton.classList.add("is-dragging");
        elements.dealerButton.style.position = "fixed";
        elements.dealerButton.style.left = `${event.clientX - offsetX}px`;
        elements.dealerButton.style.top = `${event.clientY - offsetY}px`;
        elements.dealerButton.style.transform = "none";
        elements.dealerButton.style.zIndex = "4000";
        window.addEventListener("pointermove", handleDealerPointerMove);
        window.addEventListener("pointerup", handleDealerPointerUp);
        window.addEventListener("pointercancel", handleDealerPointerCancel);
    }

    function handleDealerPointerMove(event) {
        if (!dealerDragState || event.pointerId !== dealerDragState.pointerId || !elements.dealerButton) {
            return;
        }
        event.preventDefault();
        const { offsetX = elements.dealerButton.offsetWidth / 2, offsetY = elements.dealerButton.offsetHeight / 2 } = dealerDragState;
        elements.dealerButton.style.left = `${event.clientX - offsetX}px`;
        elements.dealerButton.style.top = `${event.clientY - offsetY}px`;
    }

    function handleDealerPointerUp(event) {
        if (!dealerDragState || event.pointerId !== dealerDragState.pointerId) {
            return;
        }
        event.preventDefault();
        if (elements.dealerButton) {
            elements.dealerButton.releasePointerCapture(event.pointerId);
        }
        const target = document.elementFromPoint(event.clientX, event.clientY);
        const seat = target ? target.closest('.seat') : null;
        const seatIndex = seat ? Number(seat.dataset.playerIndex) : NaN;
        cleanupDealerDrag();
        if (Number.isInteger(seatIndex) && seatIndex < state.playersCount) {
            setDealerSeatIndex(seatIndex);
        } else {
            placeDealerButton();
        }
    }

    function handleDealerPointerCancel() {
        cleanupDealerDrag();
        placeDealerButton();
    }

    function cleanupDealerDrag() {
        window.removeEventListener("pointermove", handleDealerPointerMove);
        window.removeEventListener("pointerup", handleDealerPointerUp);
        window.removeEventListener("pointercancel", handleDealerPointerCancel);
        dealerDragState = null;
    }

    function createCardSlot({ key, placeholder, type, order, playerIndex, holeIndex }) {
        const slot = document.createElement("div");
        slot.className = "card-slot";
        slot.dataset.slotKey = key;
        slot.dataset.slotType = type;
        slot.dataset.order = order;
        slot.dataset.placeholder = placeholder;
        if (typeof playerIndex === "number") {
            slot.dataset.playerIndex = String(playerIndex);
        }
        if (typeof holeIndex === "number") {
            slot.dataset.holeIndex = String(holeIndex);
        }
        slot.innerHTML = `
            <span class="card-placeholder">${placeholder}</span>
            <span class="card-value"><span class="rank"></span><span class="suit"></span></span>
        `;
        slot.addEventListener("click", () => handleSlotClick(slot));
        slot.addEventListener("dblclick", (event) => {
            event.preventDefault();
            if (slot.dataset.locked === "true") {
                return;
            }
            if (!slot.dataset.cardId) {
                return;
            }
            clearSlot(slot, { keepFocus: true });
            showError("");
        });
        state.slotByKey.set(key, slot);
        return slot;
    }

    function handleSlotClick(slot) {
        if (slot.dataset.locked === "true") {
            return;
        }
        if (!isSlotActiveForCurrentGame(slot)) {
            return;
        }

        if (slot.dataset.cardId) {
            clearSlot(slot, { keepFocus: true });
            showError("");
            return;
        }

        if (state.activeSlot === slot) {
            if (elements.deckOverlay && elements.deckOverlay.hidden) {
                setActiveSlot(slot, { openOverlay: true });
                showError("\u05d1\u05d7\u05e8\u05d5 \u05e7\u05dc\u05e3 \u05de\u05d4\u05d7\u05e4\u05d9\u05e1\u05d4 \u05dc\u05d4\u05e6\u05d1\u05ea\u05d5.");
            } else {
                setActiveSlot(null);
                showError("");
            }
            return;
        }

        setActiveSlot(slot, { openOverlay: true });
        showError("\u05d1\u05d7\u05e8\u05d5 \u05e7\u05dc\u05e3 \u05de\u05d4\u05d7\u05e4\u05d9\u05e1\u05d4 \u05dc\u05d4\u05e6\u05d1\u05ea\u05d5.");
    }

    function handleDeckCardClick(card) {
        if (state.liveGame && state.liveGame.active && state.liveGame.handActive) {
            showError("במשחק חי אין אפשר לבחור קלפים מידנית.");
            return;
        }

        const deckButton = elements.deck.querySelector(`[data-card-id="${card.id}"]`);
        if (!deckButton) {
            return;
        }

        if (deckButton.classList.contains("used")) {
            releaseCard(card.id);
            showError("");
            return;
        }

        if (!state.activeSlot) {
            ensureActiveSlot();
        }

        if (!state.activeSlot) {
            showError("\u05d1\u05d7\u05e8\u05d5 \u05ea\u05d7\u05d9\u05dc\u05d4 \u05de\u05e9\u05d1\u05e6\u05ea \u05dc\u05d4\u05e6\u05d1\u05ea \u05d4\u05e7\u05dc\u05e3.");
            return;
        }

        assignCardToSlot(card, state.activeSlot);
        showError("");
    }
    function assignCardToSlot(card, slot, options = {}) {
        if (!slot) {
            return;
        }
        if (!isSlotActiveForCurrentGame(slot)) {
            return;
        }

        const { hidden = false, lock = false, suppressUpdate = false } = options;

        const valueEl = slot.querySelector(".card-value");
        const rankEl = valueEl.querySelector(".rank");
        const suitEl = valueEl.querySelector(".suit");
        const placeholderEl = slot.querySelector(".card-placeholder");

        const applyVisibility = () => {
            if (hidden) {
                slot.classList.add("card-slot--hidden");
                slot.dataset.liveHidden = "true";
                rankEl.textContent = "";
                suitEl.textContent = "";
                delete valueEl.dataset.suit;
                if (placeholderEl) {
                    placeholderEl.textContent = "??";
                }
            } else {
                slot.classList.remove("card-slot--hidden");
                delete slot.dataset.liveHidden;
                rankEl.textContent = card.rank.label;
                suitEl.textContent = card.suit.symbol;
                valueEl.dataset.suit = card.suit.id;
                if (placeholderEl) {
                    placeholderEl.textContent = slot.dataset.placeholder || placeholderEl.textContent;
                }
            }
        };

        const applyLock = () => {
            if (lock) {
                slot.dataset.locked = "true";
                slot.classList.add("card-slot--locked");
            } else {
                delete slot.dataset.locked;
                slot.classList.remove("card-slot--locked");
            }
        };

        if (slot.dataset.cardId === card.id) {
            applyVisibility();
            applyLock();
            if (!state.isAutoAdvancePaused && !lock) {
                advanceActiveSlot(slot);
            } else {
                setActiveSlot(null);
            }
            return;
        }

        const occupyingSlot = state.cardAssignments.get(card.id);
        if (occupyingSlot) {
            clearSlot(occupyingSlot, { suppressUpdate: true });
        }

        if (slot.dataset.cardId) {
            clearSlot(slot, { keepFocus: true, suppressUpdate: true });
        } else {
            setActiveSlot(slot);
        }

        slot.dataset.cardId = card.id;
        slot.dataset.suit = card.suit.id;
        slot.classList.add("filled");

        applyVisibility();
        applyLock();

        const deckButton = elements.deck.querySelector(`[data-card-id="${card.id}"]`);
        if (deckButton) {
            deckButton.classList.add("used");
        }

        state.cardAssignments.set(card.id, slot);

        if (!state.isAutoAdvancePaused && !lock) {
            advanceActiveSlot(slot);
        } else {
            setActiveSlot(null);
        }

        if (!suppressUpdate) {
            scheduleImmediateProbabilityUpdate();
            if (!state.deferProbabilityUpdate && state.mode === "equity") {
                updateWinProbabilities();
            }
        }
    }


    function markSlotHidden(slot, options = {}) {
        if (!slot || !isSlotActiveForCurrentGame(slot)) {
            return;
        }

        const { display = "X", lock = true } = options;
        if (slot.dataset.cardId) {
            clearSlot(slot, { suppressUpdate: true });
        }

        slot.classList.add("card-slot--hidden", "card-slot--gg-hidden");
        slot.classList.remove("filled");
        slot.dataset.ggHidden = "true";
        delete slot.dataset.cardId;
        delete slot.dataset.suit;
        delete slot.dataset.liveHidden;
        if (lock) {
            slot.dataset.locked = "true";
            slot.classList.add("card-slot--locked");
        }

        const valueEl = slot.querySelector(".card-value");
        if (valueEl) {
            delete valueEl.dataset.suit;
            const rankEl = valueEl.querySelector(".rank");
            const suitEl = valueEl.querySelector(".suit");
            if (rankEl) {
                rankEl.textContent = "";
            }
            if (suitEl) {
                suitEl.textContent = "";
            }
        }

        const placeholderEl = slot.querySelector(".card-placeholder");
        if (placeholderEl) {
            placeholderEl.textContent = display || "X";
        }
    }

    function clearHiddenMarker(slot) {
        if (!slot || !slot.classList.contains("card-slot--hidden")) {
            return;
        }
        slot.classList.remove("card-slot--hidden", "card-slot--gg-hidden", "card-slot--locked");
        delete slot.dataset.ggHidden;
        delete slot.dataset.liveHidden;
        delete slot.dataset.locked;

        const valueEl = slot.querySelector(".card-value");
        if (valueEl) {
            delete valueEl.dataset.suit;
            const rankEl = valueEl.querySelector(".rank");
            const suitEl = valueEl.querySelector(".suit");
            if (rankEl) {
                rankEl.textContent = "";
            }
            if (suitEl) {
                suitEl.textContent = "";
            }
        }

        const placeholderEl = slot.querySelector(".card-placeholder");
        if (placeholderEl) {
            placeholderEl.textContent = slot.dataset.placeholder || "";
        }
    }


    function clearSlot(slot, options = {}) {
        if (!slot) {
            return;
        }

        const { keepFocus = false, suppressUpdate = false } = options;
        const cardId = slot.dataset.cardId;
        if (!cardId) {
            clearHiddenMarker(slot);
            if (keepFocus) {
                setActiveSlot(slot);
            } else if (state.activeSlot === slot) {
                setActiveSlot(null);
                ensureActiveSlot();
            }
            return;
        }

        slot.classList.remove("filled", "card-slot--hidden", "card-slot--locked");
        delete slot.dataset.cardId;
        delete slot.dataset.suit;
        delete slot.dataset.liveHidden;
        delete slot.dataset.ggHidden;
        delete slot.dataset.locked;

        const valueEl = slot.querySelector(".card-value");
        delete valueEl.dataset.suit;
        valueEl.querySelector(".rank").textContent = "";
        valueEl.querySelector(".suit").textContent = "";

        const placeholderEl = slot.querySelector(".card-placeholder");
        if (placeholderEl) {
            placeholderEl.textContent = slot.dataset.placeholder || placeholderEl.textContent;
        }

        state.cardAssignments.delete(cardId);

        const deckButton = elements.deck.querySelector(`[data-card-id="${cardId}"]`);
        if (deckButton) {
            deckButton.classList.remove("used");
        }

        if (keepFocus) {
            setActiveSlot(slot);
        } else if (state.activeSlot === slot) {
            setActiveSlot(null);
        }

        if (!suppressUpdate) {
            scheduleImmediateProbabilityUpdate();
            if (!state.deferProbabilityUpdate && state.mode === "equity") {
                updateWinProbabilities();
            }
            if (!keepFocus) {
                ensureActiveSlot(slot.dataset.slotType);
            }
        }
    }


    function releaseCard(cardId) {
        const slot = state.cardAssignments.get(cardId);
        if (slot) {
            clearSlot(slot);
        }
    }


    function setActiveSlot(slot, options = {}) {
        const { openOverlay = false } = options;
        if (slot && !isSlotActiveForCurrentGame(slot)) {
            slot = null;
        }
        const overlayWasOpen = Boolean(elements.deckOverlay && !elements.deckOverlay.hidden);
        const shouldOpenOverlay = Boolean(slot) && (openOverlay || overlayWasOpen);
        if (state.activeSlot === slot) {
            if (slot) {
                if (shouldOpenOverlay) {
                    openDeckOverlay(slot);
                } else {
                    closeDeckOverlay();
                }
            } else {
                closeDeckOverlay();
            }
            return;
        }

        if (state.activeSlot) {
            state.activeSlot.classList.remove("active");
        }

        state.activeSlot = slot;

        if (state.activeSlot) {
            state.activeSlot.classList.add("active");
            if (shouldOpenOverlay) {
                openDeckOverlay(state.activeSlot);
            } else {
                closeDeckOverlay();
            }
        } else {
            closeDeckOverlay();
        }
    }


function advanceActiveSlot(fromSlot) {
        if (state.isAutoAdvancePaused) {
            return;
        }

        if (fromSlot) {
            const type = fromSlot.dataset.slotType;
            const order = Number(fromSlot.dataset.order);
            const sameTypeSlots = getSlotsByType(type);
            const nextSameType = sameTypeSlots.find((candidate) => Number(candidate.dataset.order) > order && !candidate.dataset.cardId);
            if (nextSameType) {
                setActiveSlot(nextSameType);
                return;
            }
            const alternativeType = type === "player" ? "board" : "player";
            const nextAlternative = findFirstEmptySlot(alternativeType);
            if (nextAlternative) {
                setActiveSlot(nextAlternative);
                return;
            }
        }

        ensureActiveSlot();
    }

    function ensureActiveSlot(preferredType) {
        if (state.activeSlot) {
            const slot = state.activeSlot;
            const isInactivePlayer = slot.dataset.slotType === "player" && !isSlotActiveForCurrentGame(slot);
            if (!slot.isConnected || slot.dataset.cardId || isInactivePlayer) {
                setActiveSlot(null);
            }
        }

        if (!state.activeSlot) {
            const next = findFirstEmptySlot(preferredType);
            if (next) {
                setActiveSlot(next);
            }
        }
    }

    function findFirstEmptySlot(preferredType) {
        const candidates = [];
        if (preferredType) {
            candidates.push(preferredType);
        }
        candidates.push("player", "board");
        const seen = new Set();
        for (const type of candidates) {
            if (seen.has(type)) {
                continue;
            }
            seen.add(type);
            if (type !== "player" && type !== "board") {
                continue;
            }
            const slots = getSlotsByType(type);
            const empty = slots.find((slot) => !slot.dataset.cardId);
            if (empty) {
                return empty;
            }
        }
        return null;
    }

    function showError(message) {
        if (!elements.errors) {
            return;
        }
        elements.errors.textContent = message;
    }

    function updateSeatStates() {
        const wasDeferred = state.deferProbabilityUpdate;
        state.deferProbabilityUpdate = true;
        state.seats.forEach((seat, index) => {
            const isActive = index < state.playersCount;
            seat.classList.toggle("active", isActive);
            seat.hidden = !isActive;
            seat.setAttribute("aria-hidden", isActive ? "false" : "true");
            if (!isActive) {
                clearPlayerSlots(index, { suppressUpdate: true });
            }
        });
        updateGameVariantUI({ suppressUpdate: true });
        applySeatLayout();
        state.deferProbabilityUpdate = wasDeferred;
        if (!state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
        ensureActiveSlot("player");
        updateSeatPositionLabels();
        syncPlayerEconomyInputs();
    }

    function applySeatLayout() {
        const layout = SEAT_LAYOUTS[state.playersCount] || SEAT_LAYOUTS[MAX_PLAYERS];

        state.seats.forEach((seat, index) => {
            if (!(seat instanceof HTMLElement)) {
                return;
            }
            if (index >= state.playersCount) {
                seat.style.removeProperty("top");
                seat.style.removeProperty("left");
                seat.style.removeProperty("--seat-offset-x");
                seat.style.removeProperty("--seat-offset-y");
                return;
            }

            const position = layout[index] || layout[layout.length - 1];
            if (!position) {
                return;
            }

            seat.style.top = position.top;
            seat.style.left = position.left;
            seat.style.setProperty("--seat-offset-x", "0px");
            seat.style.setProperty("--seat-offset-y", "0px");
        });

        if (elements.table) {
            elements.table.dataset.playersCount = String(state.playersCount);
        }
    }

    function updatePlayerCountLabel() {
        if (elements.playerCountLabel) {
            elements.playerCountLabel.textContent = `${state.playersCount} \u05e9\u05d7\u05e7\u05e0\u05d9\u05dd`;
        }
        refreshToolbarControls();
    }

    function setPlayersCount(count) {
        const next = Math.min(MAX_PLAYERS, Math.max(MIN_PLAYERS, count));
        if (next === state.playersCount) {
            return;
        }

        const previousCount = state.playersCount;

        for (let i = next; i < state.playersCount; i += 1) {
            clearPlayerSlots(i, { suppressUpdate: true });
        }

        state.playersCount = next;

        if (next > previousCount) {
            for (let i = previousCount; i < next; i += 1) {
                state.playerEconomy[i] = createDefaultEconomy();
            }
        }

        updateSeatStates();
        updatePlayerCountLabel();
        refreshToolbarControls();
        showError("");
        if (elements.results) {
            elements.results.innerHTML = "";
        }

        for (let i = next; i < state.probabilityDisplays.length; i += 1) {
            const display = state.probabilityDisplays[i];
            if (display) {
                updateProbabilityLabel(i, { win: PROBABILITY_PLACEHOLDER, tie: PROBABILITY_PLACEHOLDER });
                display.container.classList.remove("is-leading");
            }
        }

        if (!state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
    }

    function setGameVariant(variantId) {
        const next = GAME_VARIANTS[variantId] ? variantId : DEFAULT_GAME_VARIANT;
        if (state.gameVariant === next) {
            refreshToolbarControls();
            return;
        }

        if (next !== GAME_VARIANTS.texas.id && state.mode !== "equity") {
            setMode("equity");
        }
        if (next !== GAME_VARIANTS.texas.id && state.liveGame && state.liveGame.active) {
            finishLiveGameSession();
        }

        state.gameVariant = next;
        evaluationCache.clear();
        updateGameVariantUI({ suppressUpdate: true });
        updateModeUI();
        showError("");
        if (elements.results) {
            elements.results.innerHTML = "";
        }
        refreshToolbarControls();
        scheduleImmediateProbabilityUpdate();
    }

    function setToolbarMenuOpen(menuName) {
        state.openToolbarMenu = menuName;
        if (menuName && state.isSettingsMenuOpen) {
            setSettingsMenuOpen(false);
        }
        refreshToolbarControls();
    }

    function refreshToolbarControls() {
        const variant = getActiveGameVariant();
        if (elements.playerCountLabel) {
            elements.playerCountLabel.textContent = `${state.playersCount} \u05e9\u05d7\u05e7\u05e0\u05d9\u05dd`;
        }
        if (elements.gameTypeLabel) {
            elements.gameTypeLabel.textContent = variant.label;
        }

        const syncMenu = (trigger, menu, isOpen) => {
            if (trigger) {
                trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
            }
            if (menu) {
                menu.classList.toggle("is-open", isOpen);
                menu.setAttribute("aria-hidden", isOpen ? "false" : "true");
            }
        };

        syncMenu(elements.playerCountLabel, elements.playerCountMenu, state.openToolbarMenu === "players");
        syncMenu(elements.gameTypeLabel, elements.gameTypeMenu, state.openToolbarMenu === "game");

        document.querySelectorAll("[data-player-count]").forEach((button) => {
            const isSelected = Number(button.dataset.playerCount) === state.playersCount;
            button.classList.toggle("is-selected", isSelected);
            button.setAttribute("aria-checked", isSelected ? "true" : "false");
        });

        document.querySelectorAll("[data-game-variant]").forEach((button) => {
            const isSelected = button.dataset.gameVariant === variant.id;
            button.classList.toggle("is-selected", isSelected);
            button.setAttribute("aria-checked", isSelected ? "true" : "false");
        });
    }

    function bindToolbarChoiceMenus() {
        const countButton = elements.playerCountLabel;
        const countMenu = elements.playerCountMenu;
        const gameButton = elements.gameTypeLabel;
        const gameMenu = elements.gameTypeMenu;

        if (countMenu && !countMenu.children.length) {
            const fragment = document.createDocumentFragment();
            for (let count = MIN_PLAYERS; count <= MAX_PLAYERS; count += 1) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "toolbar-choice-item";
                button.dataset.playerCount = String(count);
                button.setAttribute("role", "menuitemradio");
                button.textContent = `${count} \u05e9\u05d7\u05e7\u05e0\u05d9\u05dd`;
                fragment.appendChild(button);
            }
            countMenu.appendChild(fragment);
        }

        if (gameMenu && !gameMenu.children.length) {
            const fragment = document.createDocumentFragment();
            Object.values(GAME_VARIANTS).forEach((variant) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "toolbar-choice-item";
                button.dataset.gameVariant = variant.id;
                button.setAttribute("role", "menuitemradio");
                button.textContent = variant.label;
                fragment.appendChild(button);
            });
            gameMenu.appendChild(fragment);
        }

        if (countButton && countMenu) {
            countButton.addEventListener("click", (event) => {
                event.stopPropagation();
                setToolbarMenuOpen(state.openToolbarMenu === "players" ? null : "players");
            });
            countMenu.addEventListener("click", (event) => {
                event.stopPropagation();
                const target = event.target instanceof Element ? event.target.closest("[data-player-count]") : null;
                if (!target) {
                    return;
                }
                const count = Number(target.dataset.playerCount);
                if (Number.isInteger(count)) {
                    setPlayersCount(count);
                    setToolbarMenuOpen(null);
                    countButton.focus();
                }
            });
        }

        if (gameButton && gameMenu) {
            gameButton.addEventListener("click", (event) => {
                event.stopPropagation();
                setToolbarMenuOpen(state.openToolbarMenu === "game" ? null : "game");
            });
            gameMenu.addEventListener("click", (event) => {
                event.stopPropagation();
                const target = event.target instanceof Element ? event.target.closest("[data-game-variant]") : null;
                if (!target) {
                    return;
                }
                setGameVariant(target.dataset.gameVariant);
                setToolbarMenuOpen(null);
                gameButton.focus();
            });
        }

        document.addEventListener("click", (event) => {
            if (!state.openToolbarMenu) {
                return;
            }
            const target = event.target;
            if (!(target instanceof Node)) {
                setToolbarMenuOpen(null);
                return;
            }
            const isInsideToolbarChoice = [countButton, countMenu, gameButton, gameMenu].some((element) => element && element.contains(target));
            if (!isInsideToolbarChoice) {
                setToolbarMenuOpen(null);
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && state.openToolbarMenu) {
                setToolbarMenuOpen(null);
            }
        });

        refreshToolbarControls();
    }

    function bindControls() {
        if (elements.calculate) {
            elements.calculate.disabled = true;
            elements.calculate.style.display = "none";
            elements.calculate.setAttribute("aria-hidden", "true");
            elements.calculate.tabIndex = -1;
        }
    }

    function clearAllSlots(options = {}) {
        const { keepResults = false } = options;
        const previousAuto = state.isAutoAdvancePaused;
        const previousDefer = state.deferProbabilityUpdate;

        state.isAutoAdvancePaused = true;
        if (!previousDefer) {
            cancelScheduledProbabilityUpdate();
        }
        state.deferProbabilityUpdate = true;
        state.slotByKey.forEach((slot) => clearSlot(slot, { suppressUpdate: true }));
        state.isAutoAdvancePaused = previousAuto;
        state.deferProbabilityUpdate = previousDefer;
        if (state.ggReader) {
            state.ggReader.potOverride = null;
        }

        setActiveSlot(null);
        showError("");
        if (!keepResults && elements.results) {
            elements.results.innerHTML = "";
        }

        if (!state.isAutoAdvancePaused) {
            ensureActiveSlot();
        }
        if (!state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
    }

    function dealRandom() {
        const playerSlots = getSlotsByType("player");
        const boardSlots = getSlotsByType("board");
        const allSlots = [...playerSlots, ...boardSlots];
        if (!allSlots.length) {
            return;
        }

        const previousAuto = state.isAutoAdvancePaused;
        const previousDefer = state.deferProbabilityUpdate;
        state.isAutoAdvancePaused = true;
        if (!previousDefer) {
            cancelScheduledProbabilityUpdate();
        }
        state.deferProbabilityUpdate = true;

        state.slotByKey.forEach((slot) => clearSlot(slot, { suppressUpdate: true }));
        setActiveSlot(null);

        const deckCopy = [...state.deck];
        shuffle(deckCopy);

        allSlots.forEach((slot, index) => {
            const card = deckCopy[index];
            if (card) {
                assignCardToSlot(card, slot);
            }
        });

        state.isAutoAdvancePaused = previousAuto;
        state.deferProbabilityUpdate = previousDefer;

        showError("");
        if (elements.results) {
            elements.results.innerHTML = "";
        }

        if (!state.isAutoAdvancePaused) {
            ensureActiveSlot();
        }
        if (!state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
    }

    function shuffle(array) {
        for (let i = array.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            [array[i], array[j]] = [array[j], array[i]];
        }
    }

    function getSlotsByType(type) {
        const slots = [];
        state.slotByKey.forEach((slot) => {
            if (slot.dataset.slotType !== type) {
                return;
            }
            if (type === "player") {
                if (!isSlotActiveForCurrentGame(slot)) {
                    return;
                }
            }
            slots.push(slot);
        });
        return slots.sort((a, b) => Number(a.dataset.order) - Number(b.dataset.order));
    }

    function collectPlayersData() {
        const players = [];
        const requiredHoleCards = getRequiredHoleCards();
        getEquityPlayerIndexes().forEach((playerIndex) => {
            const slots = getPlayerCardSlots(playerIndex).slice(0, requiredHoleCards);
            const cardIds = slots.map((slot) => slot?.dataset.cardId).filter(Boolean);
            const cards = cardIds.map((id) => getCardById(id));
            players.push({
                index: playerIndex,
                slots,
                cardIds,
                cards
            });
        });
        return players;
    }

    function getEquityPlayerIndexes() {
        const snapshot = state.ggReader && state.ggReader.lastSnapshot;
        const seats = Array.isArray(snapshot?.seats) ? snapshot.seats : [];
        if (state.ggReader?.running && seats.length) {
            const indexes = seats
                .filter((seat) => seat && seat.active !== false)
                .map((seat) => Number(seat.physicalSeatIndex))
                .filter((index) => Number.isInteger(index) && index >= 0 && index < state.playersCount)
                .sort((left, right) => left - right);
            if (indexes.length >= MIN_PLAYERS) {
                return indexes;
            }
        }
        return Array.from({ length: state.playersCount }, (_item, index) => index);
    }

    function collectBoardCards() {
        return getSlotsByType("board")
            .map((slot) => getCardById(slot.dataset.cardId))
            .filter(Boolean);
    }

    function handleCalculate() {
        updateWinProbabilities({ userInitiated: true });
    }

    function scheduleProbabilityUpdate() {
        if (state.mode !== "equity") {
            scheduleSolverUpdate();
            return;
        }
        if (state.deferProbabilityUpdate) {
            return;
        }
        const timerHost = typeof window !== "undefined" ? window : globalThis;
        if (probabilityUpdateTimer !== null) {
            timerHost.clearTimeout(probabilityUpdateTimer);
        }
        probabilityUpdateTimer = timerHost.setTimeout(() => {
            probabilityUpdateTimer = null;
            updateWinProbabilities();
        }, PROBABILITY_UPDATE_DELAY);
    }

    // Add immediate update for fast response
    function scheduleImmediateProbabilityUpdate() {
        if (state.mode !== "equity") {
            scheduleSolverUpdate({ immediate: true });
            return;
        }
        if (state.deferProbabilityUpdate) {
            return;
        }
        if (probabilityUpdateTimer !== null) {
            const timerHost = typeof window !== "undefined" ? window : globalThis;
            timerHost.clearTimeout(probabilityUpdateTimer);
        }
        const rafHost = typeof window !== "undefined" && typeof window.requestAnimationFrame === "function"
            ? window
            : null;
        if (rafHost) {
            rafHost.requestAnimationFrame(() => {
                updateWinProbabilities();
            });
        } else {
            updateWinProbabilities();
        }
    }

    function cancelScheduledProbabilityUpdate() {
        if (probabilityUpdateTimer !== null) {
            const timerHost = typeof window !== "undefined" ? window : globalThis;
            timerHost.clearTimeout(probabilityUpdateTimer);
            probabilityUpdateTimer = null;
        }
        cancelScheduledSolverUpdate();
    }


    function updateWinProbabilities(options = {}) {
        if (state.mode !== "equity") {
            return;
        }

        const { userInitiated = false } = options;

        const players = collectPlayersData();
        const boardCards = collectBoardCards();

        const usedCardIds = new Set();
        players.forEach((player) => {
            player.cards.forEach((card) => {
                usedCardIds.add(card.id);
            });
        });
        boardCards.forEach((card) => {
            usedCardIds.add(card.id);
        });

        const remainingCards = [];
        state.deck.forEach((card) => {
            if (!usedCardIds.has(card.id)) {
                remainingCards.push(card);
            }
        });

        const { shares, winCounts, tieCounts, simulations } = calculateWinShares(players, boardCards, remainingCards);

        clearProbabilityHighlights();

        if (!simulations) {
            players.forEach((player) => {
                updateProbabilityLabel(player.index, { win: PROBABILITY_PLACEHOLDER, tie: PROBABILITY_PLACEHOLDER });
            });
            if (elements.results) {
                elements.results.innerHTML = "";
            }
            if (userInitiated) {
                showError("\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d7\u05e9\u05d1 \u05d0\u05d7\u05d5\u05d6\u05d9\u05dd \u05e2\u05d1\u05d5\u05e8 \u05d4\u05d4\u05e8\u05db\u05d1 \u05d4\u05e0\u05d5\u05db\u05d7\u05d9. \u05d5\u05d3\u05d0\u05d5 \u05e9\u05d9\u05e9 \u05de\u05e1\u05e4\u05d9\u05e7 \u05e7\u05dc\u05e4\u05d9\u05dd \u05e4\u05e0\u05d5\u05d9\u05d9\u05dd.");
            }
            return;
        }

        showError("");

        const inverseSimulations = 1 / simulations;

        const probabilityData = players.map((_, index) => ({
            shareRatio: shares[index] * inverseSimulations,
            winRatio: winCounts[index] * inverseSimulations,
            tieRatio: tieCounts[index] * inverseSimulations
        }));

        let bestShare = 0;
        probabilityData.forEach(({ shareRatio }) => {
            if (shareRatio > bestShare) {
                bestShare = shareRatio;
            }
        });

        probabilityData.forEach(({ winRatio, tieRatio }, index) => {
            updateProbabilityLabel(players[index].index, {
                win: formatProbability(winRatio),
                tie: formatProbability(tieRatio)
            });
        });

        probabilityData.forEach(({ shareRatio }, index) => {
            if (shareRatio >= bestShare - HIGHLIGHT_EPSILON) {
                setProbabilityHighlight(players[index].index, true);
            }
        });

        const isBoardComplete = boardCards.length === 5;
        const requiredHoleCards = getRequiredHoleCards();
        const allPlayersComplete = players.every((player) => player.cards.length === requiredHoleCards);

        if (elements.results) {
            elements.results.innerHTML = "";
        }
        if (isBoardComplete && allPlayersComplete) {
            renderFinalResults(players, boardCards);
        }
    }

    // Cache for board evaluations to avoid recomputation
    const evaluationCache = new Map();
    const handScoreLengthByCategory = Object.freeze({
        8: 2,
        7: 3,
        6: 3,
        5: 6,
        4: 2,
        3: 4,
        2: 4,
        1: 5,
        0: 6
    });

    const handScoreScratch = (() => ({
        rankCounts: new Uint8Array(13),
        suitCounts: new Uint8Array(4),
        ranks: new Uint8Array(5)
    }))();

    const bestHandScoreScratch = (() => ({
        combo: new Array(5)
    }))();

    const scoreOnlyPoolScratch = (() => ({
        pool: new Array(7)
    }))();

    const bestHandSelectionScratch = (() => ({
        pool: new Array(7),
        indices: new Uint8Array(5)
    }))();

    function encodeHandScore(category, v1 = 0, v2 = 0, v3 = 0, v4 = 0, v5 = 0) {
        return (category << 20) | (v1 << 16) | (v2 << 12) | (v3 << 8) | (v4 << 4) | v5;
    }

    function decodeHandScore(encoded) {
        if (typeof encoded !== 'number' || encoded < 0) {
            return [];
        }
        const category = (encoded >>> 20) & 0xF;
        const length = handScoreLengthByCategory[category] ?? 6;
        const values = new Array(length);
        values[0] = category;
        if (length > 1) values[1] = (encoded >>> 16) & 0xF;
        if (length > 2) values[2] = (encoded >>> 12) & 0xF;
        if (length > 3) values[3] = (encoded >>> 8) & 0xF;
        if (length > 4) values[4] = (encoded >>> 4) & 0xF;
        if (length > 5) values[5] = encoded & 0xF;
        return values;
    }

    function sortRanksDescending(buffer) {
        for (let i = 1; i < buffer.length; i += 1) {
            const value = buffer[i];
            let j = i - 1;
            while (j >= 0 && buffer[j] < value) {
                buffer[j + 1] = buffer[j];
                j -= 1;
            }
            buffer[j + 1] = value;
        }
    }

    function detectStraightFromSorted(buffer, rankCounts) {
        let consecutive = 1;
        for (let i = 1; i < buffer.length; i += 1) {
            const current = buffer[i];
            const previous = buffer[i - 1];
            if (current === previous - 1) {
                consecutive += 1;
                if (consecutive >= 5) {
                    return buffer[i - 4];
                }
            } else if (current !== previous) {
                consecutive = 1;
            }
        }

        if (rankCounts[12] && rankCounts[3] && rankCounts[2] && rankCounts[1] && rankCounts[0]) {
            return 3;
        }

        return -1;
    }

    function computeHandScore(cards, scratch = handScoreScratch) {
        const { rankCounts, suitCounts, ranks } = scratch;
        rankCounts.fill(0);
        suitCounts.fill(0);

        for (let i = 0; i < 5; i += 1) {
            const card = cards[i];
            if (!card) {
                return -1;
            }
            const rank = card.rankValue;
            let suitIndex = card.suitIndex;
            if (suitIndex === undefined) {
                suitIndex = getSuitIndex(card.suit.id);
                card.suitIndex = suitIndex;
            }
            rankCounts[rank] += 1;
            suitCounts[suitIndex] += 1;
            ranks[i] = rank;
        }

        sortRanksDescending(ranks);

        const isFlush = suitCounts[0] === 5 || suitCounts[1] === 5 || suitCounts[2] === 5 || suitCounts[3] === 5;
        const straightHigh = detectStraightFromSorted(ranks, rankCounts);
        const isStraight = straightHigh !== -1;

        let fourKind = -1;
        let threeKind = -1;
        let pairOne = -1;
        let pairTwo = -1;
        const singles = [];

        for (let rank = 12; rank >= 0; rank -= 1) {
            const count = rankCounts[rank];
            if (count === 4) {
                fourKind = rank;
            } else if (count === 3) {
                if (threeKind === -1) {
                    threeKind = rank;
                }
            } else if (count === 2) {
                if (pairOne === -1) {
                    pairOne = rank;
                } else {
                    pairTwo = rank;
                }
            } else if (count === 1) {
                singles.push(rank);
            }
        }

        if (isStraight && isFlush) {
            return encodeHandScore(8, straightHigh);
        }

        if (fourKind !== -1) {
            const kicker = singles.length ? singles[0] : 0;
            return encodeHandScore(7, fourKind, kicker);
        }

        if (threeKind !== -1 && (pairOne !== -1 || pairTwo !== -1)) {
            const pairRank = pairOne !== -1 ? pairOne : pairTwo;
            return encodeHandScore(6, threeKind, pairRank);
        }

        if (isFlush) {
            return encodeHandScore(5, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4]);
        }

        if (isStraight) {
            return encodeHandScore(4, straightHigh);
        }

        if (threeKind !== -1) {
            const kickerOne = singles[0] ?? 0;
            const kickerTwo = singles[1] ?? 0;
            return encodeHandScore(3, threeKind, kickerOne, kickerTwo);
        }

        if (pairOne !== -1 && pairTwo !== -1) {
            const kicker = singles[0] ?? 0;
            return encodeHandScore(2, pairOne, pairTwo, kicker);
        }

        if (pairOne !== -1) {
            const kickerOne = singles[0] ?? 0;
            const kickerTwo = singles[1] ?? 0;
            const kickerThree = singles[2] ?? 0;
            return encodeHandScore(1, pairOne, kickerOne, kickerTwo, kickerThree);
        }

        return encodeHandScore(0, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4]);
    }

    function fillCardPool(holeCards, boardCards, pool) {
        let length = 0;
        if (holeCards) {
            for (let i = 0; i < holeCards.length; i += 1) {
                const card = holeCards[i];
                if (card) {
                    pool[length++] = card;
                }
            }
        }
        if (boardCards) {
            for (let i = 0; i < boardCards.length; i += 1) {
                const card = boardCards[i];
                if (card) {
                    pool[length++] = card;
                }
            }
        }
        return length;
    }

    function bestHandScoreFromPool(pool, poolLength, scratch = bestHandScoreScratch, outIndices) {
        if (poolLength < 5) {
            return -1;
        }

        const combo = scratch.combo;
        let bestScore = -1;

        for (let a = 0; a < poolLength - 4; a += 1) {
            combo[0] = pool[a];
            for (let b = a + 1; b < poolLength - 3; b += 1) {
                combo[1] = pool[b];
                for (let c = b + 1; c < poolLength - 2; c += 1) {
                    combo[2] = pool[c];
                    for (let d = c + 1; d < poolLength - 1; d += 1) {
                        combo[3] = pool[d];
                        for (let e = d + 1; e < poolLength; e += 1) {
                            combo[4] = pool[e];
                            const score = computeHandScore(combo);
                            if (score > bestScore) {
                                bestScore = score;
                                if (outIndices) {
                                    outIndices[0] = a;
                                    outIndices[1] = b;
                                    outIndices[2] = c;
                                    outIndices[3] = d;
                                    outIndices[4] = e;
                                }
                            }
                        }
                    }
                }
            }
        }

        return bestScore;
    }

    function bestOmahaScoreForCards(holeCards, boardCards) {
        if (!holeCards || !boardCards || holeCards.length < 2 || boardCards.length < 3) {
            return -1;
        }

        const combo = bestHandScoreScratch.combo;
        let bestScore = -1;

        for (let h1 = 0; h1 < holeCards.length - 1; h1 += 1) {
            combo[0] = holeCards[h1];
            for (let h2 = h1 + 1; h2 < holeCards.length; h2 += 1) {
                combo[1] = holeCards[h2];
                for (let b1 = 0; b1 < boardCards.length - 2; b1 += 1) {
                    combo[2] = boardCards[b1];
                    for (let b2 = b1 + 1; b2 < boardCards.length - 1; b2 += 1) {
                        combo[3] = boardCards[b2];
                        for (let b3 = b2 + 1; b3 < boardCards.length; b3 += 1) {
                            combo[4] = boardCards[b3];
                            const score = computeHandScore(combo);
                            if (score > bestScore) {
                                bestScore = score;
                            }
                        }
                    }
                }
            }
        }

        return bestScore;
    }

    function bestScoreForCards(holeCards, boardCards) {
        if (isOmahaVariant()) {
            return bestOmahaScoreForCards(holeCards, boardCards);
        }
        const pool = scoreOnlyPoolScratch.pool;
        const poolLength = fillCardPool(holeCards, boardCards, pool);
        return bestHandScoreFromPool(pool, poolLength);
    }

    function calculateWinShares(players, boardCards, remainingCards) {
        const drawsNeeded = 5 - boardCards.length;
        const requiredHoleCards = getRequiredHoleCards();
        const enumerationLimit = getActiveEnumerationLimit();
        const simulationLimit = getActiveSimulationLimit();
        const shares = new Array(players.length).fill(0);
        const winCounts = new Array(players.length).fill(0);
        const tieCounts = new Array(players.length).fill(0);
        let simulations = 0;

        if (drawsNeeded < 0) {
            return { shares, winCounts, tieCounts, simulations };
        }

        const missingHoleCounts = players.map((player) => Math.max(0, requiredHoleCards - player.cards.length));
        const totalMissingHoleCards = missingHoleCounts.reduce((total, value) => total + value, 0);

        if (remainingCards.length < drawsNeeded + totalMissingHoleCards) {
            return { shares, winCounts, tieCounts, simulations: 0 };
        }

        if (totalMissingHoleCards === 0) {
            const playerKey = players
                .map((player) => player.cards.map((card) => card.id).sort().join(""))
                .join("|");

            const evaluateBoard = (board) => {
                const boardKey = board.map((card) => card.id).sort().join("");
                const cacheKey = getActiveGameVariant().id + '|' + playerKey + '|' + boardKey;
                let cachedResult = evaluationCache.get(cacheKey);

                if (!cachedResult) {
                    let bestScore = -1;
                    const winners = [];

                    for (let i = 0; i < players.length; i += 1) {
                        const score = bestScoreForCards(players[i].cards, board);

                        if (score > bestScore) {
                            bestScore = score;
                            winners.length = 0;
                            winners.push(i);
                        } else if (score === bestScore) {
                            winners.push(i);
                        }
                    }

                    cachedResult = { winners, bestScore };

                    if (evaluationCache.size < 10000) {
                        evaluationCache.set(cacheKey, cachedResult);
                    }
                }

                const winnerCount = cachedResult.winners.length;

                if (winnerCount === 1) {
                    winCounts[cachedResult.winners[0]] += 1;
                } else if (winnerCount > 1) {
                    cachedResult.winners.forEach((index) => {
                        tieCounts[index] += 1;
                    });
                }

                const share = winnerCount ? 1 / winnerCount : 0;
                cachedResult.winners.forEach((index) => {
                    shares[index] += share;
                });

                simulations += 1;
            };

            if (drawsNeeded === 0) {
                evaluateBoard(boardCards);
                return { shares, winCounts, tieCounts, simulations };
            }

            if (remainingCards.length < drawsNeeded) {
                return { shares, winCounts, tieCounts, simulations: 0 };
            }

            const totalCombos = combinationCount(remainingCards.length, drawsNeeded);
            const boardBuffer = [...boardCards];

            if (totalCombos && totalCombos <= enumerationLimit) {
                forEachCombinationFast(remainingCards, drawsNeeded, (combo) => {
                    boardBuffer.length = boardCards.length;
                    boardBuffer.push(...combo);
                    evaluateBoard(boardBuffer);
                });
            } else {
                const drawBuffer = new Array(drawsNeeded);
                const remainingLength = remainingCards.length;
                const tempIndices = new Uint8Array(remainingLength);

                for (let i = 0; i < remainingLength; i += 1) {
                    tempIndices[i] = i;
                }

                for (let iter = 0; iter < simulationLimit; iter += 1) {
                    for (let i = 0; i < drawsNeeded; i += 1) {
                        const j = i + Math.floor(Math.random() * (remainingLength - i));
                        const temp = tempIndices[i];
                        tempIndices[i] = tempIndices[j];
                        tempIndices[j] = temp;
                        drawBuffer[i] = remainingCards[tempIndices[i]];
                    }

                    boardBuffer.length = boardCards.length;
                    boardBuffer.push(...drawBuffer);
                    evaluateBoard(boardBuffer);
                }
            }

            return { shares, winCounts, tieCounts, simulations };
        }

        const cardsNeededPerSimulation = totalMissingHoleCards + drawsNeeded;
        const remainingLength = remainingCards.length;
        const tempIndices = new Uint16Array(remainingLength);

        for (let i = 0; i < remainingLength; i += 1) {
            tempIndices[i] = i;
        }

        const drawBuffer = new Array(cardsNeededPerSimulation);
        const playerHands = players.map(() => new Array(requiredHoleCards));
        const boardBaseLength = boardCards.length;
        const boardBuffer = new Array(boardBaseLength + drawsNeeded);

        for (let i = 0; i < boardBaseLength; i += 1) {
            boardBuffer[i] = boardCards[i];
        }

        const iterations = isOmahaVariant() ? Math.min(simulationLimit, 12000) : simulationLimit;

        for (let iter = 0; iter < iterations; iter += 1) {
            for (let i = 0; i < cardsNeededPerSimulation; i += 1) {
                const j = i + Math.floor(Math.random() * (remainingLength - i));
                const temp = tempIndices[i];
                tempIndices[i] = tempIndices[j];
                tempIndices[j] = temp;
                drawBuffer[i] = remainingCards[tempIndices[i]];
            }

            let drawIndex = 0;

            for (let p = 0; p < players.length; p += 1) {
                const baseCards = players[p].cards;
                const missing = missingHoleCounts[p];
                const handBuffer = playerHands[p];
                const baseLength = baseCards.length;

                handBuffer.length = baseLength + missing;

                for (let b = 0; b < baseLength; b += 1) {
                    handBuffer[b] = baseCards[b];
                }

                for (let m = 0; m < missing; m += 1) {
                    handBuffer[baseLength + m] = drawBuffer[drawIndex++];
                }
            }

            boardBuffer.length = boardBaseLength + drawsNeeded;

            for (let b = 0; b < drawsNeeded; b += 1) {
                boardBuffer[boardBaseLength + b] = drawBuffer[drawIndex++];
            }

            let bestScore = -1;
            const winners = [];

            for (let p = 0; p < players.length; p += 1) {
                const score = bestScoreForCards(playerHands[p], boardBuffer);

                if (score > bestScore) {
                    bestScore = score;
                    winners.length = 0;
                    winners.push(p);
                } else if (score === bestScore) {
                    winners.push(p);
                }
            }

            const winnerCount = winners.length;

            if (winnerCount === 1) {
                winCounts[winners[0]] += 1;
            } else if (winnerCount > 1) {
                winners.forEach((index) => {
                    tieCounts[index] += 1;
                });
            }

            const share = winnerCount ? 1 / winnerCount : 0;
            winners.forEach((index) => {
                shares[index] += share;
            });

            simulations += 1;
        }

        return { shares, winCounts, tieCounts, simulations };
    }

    function isGgLiveReaderActive() {
        return Boolean(state.ggReader && state.ggReader.running);
    }

    function getActiveEnumerationLimit() {
        return isGgLiveReaderActive() ? GG_READER_LIVE_ENUMERATION_LIMIT : ENUMERATION_LIMIT;
    }

    function getActiveSimulationLimit() {
        return isGgLiveReaderActive() ? GG_READER_LIVE_PREFLOP_SIMULATIONS : PREFLOP_SIMULATIONS;
    }

    // Optimized combination generator that avoids recursive calls
    function forEachCombinationFast(pool, choose, callback) {
        if (choose === 0) {
            callback([]);
            return;
        }

        const indices = new Array(choose);
        const combo = new Array(choose);

        // Initialize first combination
        for (let i = 0; i < choose; i++) {
            indices[i] = i;
            combo[i] = pool[i];
        }

        callback(combo);

        // Generate next combinations
        while (true) {
            let i = choose - 1;

            // Find rightmost index that can be incremented
            while (i >= 0 && indices[i] >= pool.length - choose + i) {
                i--;
            }

            if (i < 0) break; // No more combinations

            // Increment this index and reset all following indices
            indices[i]++;
            for (let j = i + 1; j < choose; j++) {
                indices[j] = indices[j - 1] + 1;
            }

            // Update combo array
            for (let j = i; j < choose; j++) {
                combo[j] = pool[indices[j]];
            }

            callback(combo);
        }
    }

    function combinationCount(n, k) {
        if (k < 0 || k > n) {
            return 0;
        }
        const m = Math.min(k, n - k);
        let result = 1;
        for (let i = 1; i <= m; i += 1) {
            result = (result * (n - m + i)) / i;
        }
        return Math.round(result);
    }

    function forEachCombination(pool, choose, callback) {
        if (choose === 0) {
            callback([]);
            return;
        }
        const combo = new Array(choose);
        const walk = (start, depth) => {
            if (depth === choose) {
                callback(combo);
                return;
            }
            for (let i = start; i <= pool.length - (choose - depth); i += 1) {
                combo[depth] = pool[i];
                walk(i + 1, depth + 1);
            }
        };
        walk(0, 0);
    }

    function drawRandomCombination(pool, choose, target, scratch) {
        target.length = 0;
        if (choose <= 0) {
            return;
        }

        // Use Fisher-Yates shuffle for much faster sampling
        const poolCopy = pool.slice();
        for (let i = 0; i < choose && i < poolCopy.length; i++) {
            const j = i + Math.floor(Math.random() * (poolCopy.length - i));
            [poolCopy[i], poolCopy[j]] = [poolCopy[j], poolCopy[i]];
            target.push(poolCopy[i]);
        }
    }

    function updateProbabilityLabel(index, values) {
        const display = state.probabilityDisplays[index];
        if (!display) {
            return;
        }
        const tieText = values && typeof values.tie !== "undefined" ? values.tie : PROBABILITY_PLACEHOLDER;
        const winText = values && typeof values.win !== "undefined" ? values.win : PROBABILITY_PLACEHOLDER;
        if (display.tie) {
            display.tie.textContent = `${TIE_LABEL}: ${tieText}`;
        }
        if (display.win) {
            display.win.textContent = `${WIN_LABEL}: ${winText}`;
        }
    }

    function setProbabilityHighlight(index, isActive) {
        const display = state.probabilityDisplays[index];
        if (display && display.container) {
            display.container.classList.toggle("is-leading", Boolean(isActive));
        }
    }

    function clearProbabilityHighlights() {
        state.probabilityDisplays.forEach((display) => {
            display?.container?.classList.remove("is-leading");
        });
    }

    function formatProbability(value) {
        if (!Number.isFinite(value) || value <= 0) {
            return "0.0%";
        }
        if (value >= 0.9995) {
            return "100%";
        }
        const percentage = value * 100;
        return `${percentage.toFixed(1)}%`;
    }

    function renderFinalResults(players, boardCards) {
        if (!elements.results) {
            return;
        }
        const boardLine = document.createElement("div");
        boardLine.className = "meta";
        boardLine.textContent = `\u05e7\u05dc\u05e4\u05d9\u05dd \u05de\u05e9\u05d5\u05ea\u05e4\u05d9\u05dd: ${formatCardList(boardCards)}`;
        elements.results.appendChild(boardLine);

        const playerResults = players.map((player) => {
            const evaluation = bestHandForPlayer(player.cards, boardCards);
            return {
                ...player,
                evaluation
            };
        });

        let bestScore = null;
        playerResults.forEach((result) => {
            if (!bestScore || compareScores(result.evaluation.score, bestScore) > 0) {
                bestScore = result.evaluation.score;
            }
        });

        const winners = playerResults.filter((result) => compareScores(result.evaluation.score, bestScore) === 0);

        const table = document.createElement("table");
        table.innerHTML = `
            <thead>
                <tr>
                    <th>\u05e9\u05d7\u05e7\u05df</th>
                    <th>\u05d9\u05d3</th>
                    <th>\u05ea\u05d9\u05d0\u05d5\u05e8</th>
                </tr>
            </thead>
        `;

        const tbody = document.createElement("tbody");
        playerResults.forEach((result) => {
            const row = document.createElement("tr");
            if (compareScores(result.evaluation.score, bestScore) === 0) {
                row.classList.add("highlight");
            }
            row.innerHTML = `
                <td>\u05e9\u05d7\u05e7\u05df ${result.index + 1}</td>
                <td>${formatCardList(result.cards)}</td>
                <td>${describeHand(result.evaluation)}</td>
            `;
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        elements.results.appendChild(table);

        const footer = document.createElement("div");
        footer.className = "meta";
        footer.textContent = winners.length === 1
            ? `\u05d4\u05de\u05e0\u05e6\u05d7 \u05d4\u05d5\u05d0 \u05e9\u05d7\u05e7\u05df ${winners[0].index + 1}.`
            : `\u05d4\u05ea\u05d9\u05e7\u05d5 \u05d1\u05d9\u05df \u05d4\u05e9\u05d7\u05e7\u05e0\u05d9\u05dd ${winners.map((winner) => winner.index + 1).join(", ")}.`;
        elements.results.appendChild(footer);
    }

    function bestOmahaHandForPlayer(holeCards, boardCards) {
        if (!holeCards || !boardCards || holeCards.length < 2 || boardCards.length < 3) {
            return null;
        }

        const combo = bestHandScoreScratch.combo;
        let bestScore = -1;
        let bestCards = null;

        for (let h1 = 0; h1 < holeCards.length - 1; h1 += 1) {
            combo[0] = holeCards[h1];
            for (let h2 = h1 + 1; h2 < holeCards.length; h2 += 1) {
                combo[1] = holeCards[h2];
                for (let b1 = 0; b1 < boardCards.length - 2; b1 += 1) {
                    combo[2] = boardCards[b1];
                    for (let b2 = b1 + 1; b2 < boardCards.length - 1; b2 += 1) {
                        combo[3] = boardCards[b2];
                        for (let b3 = b2 + 1; b3 < boardCards.length; b3 += 1) {
                            combo[4] = boardCards[b3];
                            const score = computeHandScore(combo);
                            if (score > bestScore) {
                                bestScore = score;
                                bestCards = [combo[0], combo[1], combo[2], combo[3], combo[4]];
                            }
                        }
                    }
                }
            }
        }

        if (!bestCards) {
            return null;
        }

        const evaluation = evaluateFiveCards(bestCards);
        evaluation.score = decodeHandScore(bestScore);
        evaluation.scoreValue = bestScore;
        evaluation.cards = bestCards;
        return evaluation;
    }

    function bestHandForPlayer(holeCards, boardCards) {
        if (isOmahaVariant()) {
            return bestOmahaHandForPlayer(holeCards, boardCards);
        }
        const selectionScratch = bestHandSelectionScratch;
        const pool = selectionScratch.pool;
        const poolLength = fillCardPool(holeCards, boardCards, pool);

        if (poolLength < 5) {
            return null;
        }

        const indices = selectionScratch.indices;
        const bestScore = bestHandScoreFromPool(pool, poolLength, bestHandScoreScratch, indices);

        if (bestScore < 0) {
            return null;
        }

        const bestCards = [
            pool[indices[0]],
            pool[indices[1]],
            pool[indices[2]],
            pool[indices[3]],
            pool[indices[4]]
        ];

        const evaluation = evaluateFiveCards(bestCards);
        evaluation.score = decodeHandScore(bestScore);
        evaluation.scoreValue = bestScore;
        evaluation.cards = bestCards;
        return evaluation;
    }

    // Optimized fast evaluation that avoids object creation
    function evaluateFiveCardsFast(cards) {
        const rankCounts = new Int8Array(13);
        const suitCounts = new Int8Array(4);
        const values = new Int8Array(5);

        // Count ranks and suits, store values
        for (let i = 0; i < 5; i++) {
            const card = cards[i];
            rankCounts[card.rankValue] += 1;
            let suitIndex = card.suitIndex;
            if (suitIndex === undefined) {
                suitIndex = getSuitIndex(card.suit.id);
                card.suitIndex = suitIndex;
            }
            suitCounts[suitIndex] += 1;
            values[i] = card.rankValue;
        }

        // Sort values descending for easier processing
        sortRanksDescending(values);

        const isFlush = suitCounts[0] === 5 || suitCounts[1] === 5 || suitCounts[2] === 5 || suitCounts[3] === 5;
        const straightHigh = detectStraightFast(values);
        const isStraight = straightHigh !== -1;

        // Find rank patterns
        let fourKind = -1, threeKind = -1, pairs = [];
        for (let i = 12; i >= 0; i--) {
            const count = rankCounts[i];
            if (count === 4) fourKind = i;
            else if (count === 3) threeKind = i;
            else if (count === 2) pairs.push(i);
        }

        // Build score array based on hand type
        if (isStraight && isFlush) {
            return { score: [8, straightHigh], category: 8, cards };
        }
        if (fourKind !== -1) {
            const kicker = values.find(v => v !== fourKind);
            return { score: [7, fourKind, kicker], category: 7, cards };
        }
        if (threeKind !== -1 && pairs.length > 0) {
            return { score: [6, threeKind, pairs[0]], category: 6, cards };
        }
        if (isFlush) {
            return { score: [5, ...values], category: 5, cards };
        }
        if (isStraight) {
            return { score: [4, straightHigh], category: 4, cards };
        }
        if (threeKind !== -1) {
            const kickers = values.filter(v => v !== threeKind);
            return { score: [3, threeKind, ...kickers], category: 3, cards };
        }
        if (pairs.length >= 2) {
            const kicker = values.find(v => v !== pairs[0] && v !== pairs[1]);
            return { score: [2, pairs[0], pairs[1], kicker], category: 2, cards };
        }
        if (pairs.length === 1) {
            const kickers = values.filter(v => v !== pairs[0]);
            return { score: [1, pairs[0], ...kickers], category: 1, cards };
        }
        return { score: [0, ...values], category: 0, cards };
    }

    function getSuitIndex(suitId) {
        switch(suitId) {
            case 'S': return 0;
            case 'H': return 1;
            case 'D': return 2;
            case 'C': return 3;
            default: return 0;
        }
    }

    function detectStraightFast(sortedValues) {
        // Check standard straights
        let consecutive = 1;
        for (let i = 1; i < 5; i++) {
            if (sortedValues[i] === sortedValues[i-1] - 1) {
                consecutive++;
            } else if (sortedValues[i] !== sortedValues[i-1]) {
                consecutive = 1;
            }
        }
        if (consecutive >= 5) {
            return sortedValues[0];
        }

        // Check wheel (A,5,4,3,2)
        if (sortedValues[0] === 12 && sortedValues[1] === 3 &&
            sortedValues[2] === 2 && sortedValues[3] === 1 && sortedValues[4] === 0) {
            return 3; // 5-high straight
        }

        return -1;
    }

    function compareScoresFast(a, b) {
        const aIsNumber = typeof a === 'number';
        const bIsNumber = typeof b === 'number';

        if (aIsNumber && bIsNumber) {
            if (a === b) {
                return 0;
            }
            return a > b ? 1 : -1;
        }

        const left = aIsNumber ? decodeHandScore(a) : a;
        const right = bIsNumber ? decodeHandScore(b) : b;
        const len = Math.min(left.length, right.length);
        for (let i = 0; i < len; i += 1) {
            if (left[i] > right[i]) {
                return 1;
            }
            if (left[i] < right[i]) {
                return -1;
            }
        }
        return left.length - right.length;
    }

    function evaluateFiveCards(cards) {
        const counts = new Map();
        const suitsCount = new Map();
        cards.forEach((card) => {
            counts.set(card.rankValue, (counts.get(card.rankValue) || 0) + 1);
            suitsCount.set(card.suit.id, (suitsCount.get(card.suit.id) || 0) + 1);
        });

        const uniqueValues = [...counts.keys()].sort((a, b) => b - a);
        const isFlush = suitsCount.size === 1;
        const straightHigh = detectStraight([...new Set(cards.map((card) => card.rankValue))].sort((a, b) => b - a));
        const isStraight = straightHigh !== null;

        const groups = [...counts.entries()].sort((a, b) => {
            const countDiff = b[1] - a[1];
            if (countDiff !== 0) {
                return countDiff;
            }
            return b[0] - a[0];
        });

        if (isStraight && isFlush) {
            return {
                category: 8,
                score: [8, straightHigh],
                detail: { high: straightHigh, isRoyal: straightHigh === rankValue.get("A") },
                cards
            };
        }

        if (groups[0][1] === 4) {
            const fourRank = groups[0][0];
            const kicker = groups[1][0];
            return {
                category: 7,
                score: [7, fourRank, kicker],
                detail: { four: fourRank, kicker },
                cards
            };
        }

        if (groups[0][1] === 3 && groups[1] && groups[1][1] === 2) {
            const tripleRank = groups[0][0];
            const pairRank = groups[1][0];
            return {
                category: 6,
                score: [6, tripleRank, pairRank],
                detail: { triple: tripleRank, pair: pairRank },
                cards
            };
        }

        if (isFlush) {
            const sorted = cards
                .map((card) => card.rankValue)
                .sort((a, b) => b - a);
            return {
                category: 5,
                score: [5, ...sorted],
                detail: { ranks: sorted },
                cards
            };
        }

        if (isStraight) {
            return {
                category: 4,
                score: [4, straightHigh],
                detail: { high: straightHigh },
                cards
            };
        }

        if (groups[0][1] === 3) {
            const tripleRank = groups[0][0];
            const kickers = groups
                .slice(1)
                .map((group) => group[0])
                .sort((a, b) => b - a);
            return {
                category: 3,
                score: [3, tripleRank, ...kickers],
                detail: { triple: tripleRank, kickers },
                cards
            };
        }

        if (groups[0][1] === 2 && groups[1] && groups[1][1] === 2) {
            const pairOne = groups[0][0];
            const pairTwo = groups[1][0];
            const kicker = groups.length > 2 ? groups[2][0] : -1;
            const highPair = Math.max(pairOne, pairTwo);
            const lowPair = Math.min(pairOne, pairTwo);
            return {
                category: 2,
                score: [2, highPair, lowPair, kicker],
                detail: { highPair, lowPair, kicker },
                cards
            };
        }

        if (groups[0][1] === 2) {
            const pairRank = groups[0][0];
            const kickers = groups
                .slice(1)
                .map((group) => group[0])
                .sort((a, b) => b - a);
            return {
                category: 1,
                score: [1, pairRank, ...kickers],
                detail: { pair: pairRank, kickers },
                cards
            };
        }

        const highCards = uniqueValues;
        return {
            category: 0,
            score: [0, ...highCards],
            detail: { ranks: highCards },
            cards
        };
    }

    function detectStraight(values) {
        if (values.length < 5) {
            return null;
        }

        let bestHigh = null;
        let run = 1;
        for (let i = 1; i < values.length; i += 1) {
            if (values[i] === values[i - 1] - 1) {
                run += 1;
                if (run >= 5) {
                    const high = values[i - 4];
                    if (bestHigh === null || high > bestHigh) {
                        bestHigh = high;
                    }
                }
            } else {
                run = 1;
            }
        }

        const hasWheel = values.includes(rankValue.get("A"))
            && values.includes(rankValue.get("5"))
            && values.includes(rankValue.get("4"))
            && values.includes(rankValue.get("3"))
            && values.includes(rankValue.get("2"));

        if (hasWheel) {
            bestHigh = Math.max(bestHigh ?? -1, rankValue.get("5"));
        }

        return bestHigh;
    }

    function compareScores(a, b) {
        const length = Math.max(a.length, b.length);
        for (let i = 0; i < length; i += 1) {
            const av = a[i] ?? -1;
            const bv = b[i] ?? -1;
            if (av > bv) {
                return 1;
            }
            if (av < bv) {
                return -1;
            }
        }
        return 0;
    }

    function describeHand(evaluation) {
        const nameFor = (value) => rankByValue.get(value)?.name ?? "";
        switch (evaluation.category) {
            case 8:
                return evaluation.detail.isRoyal
                    ? "\u05e1\u05d8\u05e8\u05d9\u05d9\u05d8 \u05e4\u05dc\u05d0\u05e9 \u05dc\u05e8\u05d5\u05d9\u05d0\u05dc"
                    : `\u05e1\u05d8\u05e8\u05d9\u05d9\u05d8 \u05e4\u05dc\u05d0\u05e9 \u05e2\u05d3 ${nameFor(evaluation.detail.high)}`;
            case 7:
                return `\u05e8\u05d1\u05d9\u05e2\u05d9\u05d4 \u05e9\u05dc ${nameFor(evaluation.detail.four)}`;
            case 6:
                return `\u05e4\u05d5\u05dc \u05d4\u05d0\u05d5\u05e1: ${nameFor(evaluation.detail.triple)} \u05e2\u05dc ${nameFor(evaluation.detail.pair)}`;
            case 5:
                return `\u05e4\u05dc\u05d0\u05e9, \u05d4\u05e7\u05dc\u05e3 \u05d4\u05d2\u05d1\u05d5\u05d4 ${nameFor(evaluation.detail.ranks[0])}`;
            case 4:
                return evaluation.detail.high === rankValue.get("5")
                    ? "\u05e8\u05e6\u05e3 \u05de\u05d5\u05e9\u05e4\u05dc (\u05d0\u05e1 \u05e2\u05d3 \u05d7\u05de\u05e9)"
                    : `\u05e8\u05e6\u05e3 \u05e2\u05d3 ${nameFor(evaluation.detail.high)}`;
            case 3:
                return `\u05e9\u05dc\u05d9\u05e9\u05d9\u05d4 \u05e9\u05dc ${nameFor(evaluation.detail.triple)}`;
            case 2:
                return `\u05e9\u05e0\u05d9 \u05d6\u05d5\u05d2\u05d5\u05ea: ${nameFor(evaluation.detail.highPair)} \u05d5-${nameFor(evaluation.detail.lowPair)}`;
            case 1:
                return `\u05d6\u05d5\u05d2 \u05e9\u05dc ${nameFor(evaluation.detail.pair)}`;
            default:
                return `\u05e7\u05dc\u05e3 \u05d2\u05d1\u05d5\u05d4 ${nameFor(evaluation.detail.ranks[0])}`;
        }
    }

    function setMode(nextMode) {
        const normalized = nextMode === "solver" ? "solver" : "equity";
        if (state.mode === normalized) {
            return;
        }
        if (normalized === "solver") {
            if (isOmahaVariant()) {
                showError("\u05e1\u05d5\u05dc\u05d1\u05e8 GTO \u05e0\u05ea\u05de\u05da \u05db\u05e8\u05d2\u05e2 \u05d1\u05d8\u05e7\u05e1\u05e1 \u05d4\u05d5\u05dc\u05d3\u05dd \u05d1\u05dc\u05d1\u05d3.");
                return;
            }
            cancelScheduledProbabilityUpdate();
            state.mode = "solver";
            state.isSolverPanelOpen = true;
            if (state.playersCount !== MIN_PLAYERS) {
                setPlayersCount(MIN_PLAYERS);
            }
            updateModeUI();
            scheduleSolverUpdate({ immediate: true });
        } else {
            cancelScheduledSolverUpdate();
            state.mode = "equity";
            updateModeUI();
            scheduleImmediateProbabilityUpdate();
        }

        state.activeView = "equity";
        updateActiveView();
    }

    function bindModeControls() {
        if (!elements.modeToggle) {
            return;
        }
        elements.modeToggle.addEventListener("click", () => {
            const targetView = state.mode === "equity" ? "solver" : "equity";
            setMode(targetView);
        });
    }

    function bindToolbarActions() {
        const buttons = Array.from(document.querySelectorAll("[data-toolbar-action]"));
        buttons.forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) {
                return;
            }
            button.addEventListener("click", () => {
                const action = button.dataset.toolbarAction;
                if (!action) {
                    return;
                }
                if (action === "read-gg-table") {
                    return;
                }
                const result = performSettingsMenuAction(action);
                if (result && result.handled) {
                    refreshSettingsMenu();
                }
            });
        });
    }

    function bindGgReaderControls() {
        populateGgMonitorOptions();

        if (elements.readGgTable) {
            elements.readGgTable.addEventListener("click", (event) => {
                event.preventDefault();
                toggleGgTableReader();
            });
        }

        if (elements.ggReaderMonitor) {
            elements.ggReaderMonitor.value = String(getGgMonitorIndex());
            elements.ggReaderMonitor.addEventListener("change", () => {
                const selected = Number(elements.ggReaderMonitor.value);
                if (Number.isInteger(selected) && selected > 0) {
                    localStorage.setItem("ggMonitorIndex", String(selected));
                    setGgReaderStatus("idle", `מסך GG נבחר: ${selected}`);
                }
            });
        }

        if (elements.ggReaderStop) {
            elements.ggReaderStop.addEventListener("click", () => {
                stopGgTableReader();
            });
        }

        if (elements.ggReaderHistoryToggle) {
            elements.ggReaderHistoryToggle.addEventListener("click", () => {
                state.ggReader.isHistoryOpen = !state.ggReader.isHistoryOpen;
                renderGgReaderHistory();
            });
        }

        if (elements.ggReaderHistoryDownload) {
            elements.ggReaderHistoryDownload.addEventListener("click", downloadGgReaderHistory);
        }

        if (elements.ggReaderRoiOverlay) {
            elements.ggReaderRoiOverlay.addEventListener("click", () => fetchGgReaderDebugArtifact("roi-overlay"));
        }

        if (elements.ggReaderFieldCrops) {
            elements.ggReaderFieldCrops.addEventListener("click", () => fetchGgReaderDebugArtifact("field-crops"));
        }
    }

    async function populateGgMonitorOptions() {
        if (!elements.ggReaderMonitor) {
            return;
        }
        try {
            const response = await fetch(`${GG_READER_API_BASE}/api/gg-reader/monitors`);
            if (!response.ok) {
                throw new Error(`monitors failed: ${response.status}`);
            }
            const monitors = await response.json();
            if (!Array.isArray(monitors) || !monitors.length) {
                return;
            }

            const selected = getGgMonitorIndex();
            elements.ggReaderMonitor.innerHTML = "";
            monitors.forEach((monitor) => {
                const option = document.createElement("option");
                option.value = String(monitor.index);
                option.textContent = `${monitor.index} (${monitor.width}×${monitor.height})`;
                elements.ggReaderMonitor.appendChild(option);
            });

            const hasSelected = monitors.some((monitor) => Number(monitor.index) === selected);
            elements.ggReaderMonitor.value = String(hasSelected ? selected : Number(monitors[0].index));
            if (!hasSelected) {
                localStorage.setItem("ggMonitorIndex", elements.ggReaderMonitor.value);
                setGgReaderStatus("idle", `Monitor ${selected} לא נמצא, משתמש במסך ${elements.ggReaderMonitor.value}`);
            }
        } catch (error) {
            state.ggReader.errors.push(String(error && error.message ? error.message : error));
        }
    }

    function getGgMonitorIndex() {
        const fromQuery = getPositiveIntegerQueryParam("ggMonitor");
        if (fromQuery !== null) {
            localStorage.setItem("ggMonitorIndex", String(fromQuery));
            return fromQuery;
        }

        const fromStorage = Number.parseInt(localStorage.getItem("ggMonitorIndex") || "", 10);
        if (Number.isInteger(fromStorage) && fromStorage > 0) {
            return fromStorage;
        }

        return 2;
    }

    function getPositiveIntegerQueryParam(name) {
        try {
            const value = new URLSearchParams(window.location.search).get(name);
            if (value === null) {
                return null;
            }
            const parsed = Number.parseInt(value, 10);
            return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
        } catch (error) {
            return null;
        }
    }

    function toggleGgTableReader() {
        if (state.ggReader.running) {
            stopGgTableReader();
            return;
        }
        startGgTableReader();
    }

    async function startGgTableReader() {
        setGgReaderStatus("connecting", "מתחבר לקורא GG...");
        showError("מתחבר לקורא GG מקומי...");

        if (isGgMockMode()) {
            try {
                const snapshot = await loadGgMockSnapshot();
                applyGgSnapshot(snapshot, { source: "mock" });
                setGgReaderStatus("mock", "GG mock נטען");
                showError("נטען snapshot לדוגמה של GG.");
            } catch (error) {
                setGgReaderStatus("error", "שגיאה בטעינת GG mock");
                showError("לא ניתן לטעון snapshot לדוגמה של GG.");
                state.ggReader.errors.push(String(error && error.message ? error.message : error));
            }
            return;
        }

        let timeoutId = null;
        let streamPromise = null;
        let backendStarted = false;
        const useBrowserCapture = shouldUseBrowserGgCapture();
        try {
            if (useBrowserCapture) {
                setGgReaderStatus("connecting", "בחר את חלון NLH 2-4 של GG...");
                showError("בחר בחלון GG בחלון השיתוף של הדפדפן. אם בוחרים מסך מלא, ודא ש-GG גלוי.");
                streamPromise = requestGgDisplayMedia();
            }

            const monitorIndex = getGgMonitorIndex();
            const controller = new AbortController();
            timeoutId = window.setTimeout(() => controller.abort(), 2500);
            const response = await fetch(`${GG_READER_API_BASE}/api/gg-reader/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                signal: controller.signal,
                body: JSON.stringify({
                    monitorIndex,
                    fps: GG_READER_BROWSER_FPS,
                    profile: "ggclub_9max",
                    captureMode: useBrowserCapture ? "browser" : "window"
                })
            });

            if (!response.ok) {
                throw new Error(`GG reader start failed: ${response.status}`);
            }

            state.ggReader.running = true;
            backendStarted = true;
            try {
                const startStatus = await response.json();
                if (startStatus && Number.isInteger(Number(startStatus.monitorIndex))) {
                    localStorage.setItem("ggMonitorIndex", String(startStatus.monitorIndex));
                    if (elements.ggReaderMonitor) {
                        elements.ggReaderMonitor.value = String(startStatus.monitorIndex);
                    }
                    if (startStatus.message && startStatus.message !== "running") {
                        setGgReaderStatus("connecting", startStatus.message);
                    }
                }
            } catch (error) {
                state.ggReader.errors.push(String(error && error.message ? error.message : error));
            }
            if (useBrowserCapture) {
                const stream = await streamPromise;
                await startGgBrowserCapture(stream);
            } else {
                connectGgReaderSocket();
            }
        } catch (error) {
            state.ggReader.running = false;
            if (streamPromise) {
                streamPromise.then(stopGgMediaStream).catch(() => {});
            }
            if (error && (error.name === "NotAllowedError" || error.name === "AbortError")) {
                setGgReaderStatus("idle", "שיתוף GG בוטל");
                showError("שיתוף המסך בוטל. לחץ שוב ובחר את חלון GG.");
            } else if (backendStarted && useBrowserCapture) {
                setGgReaderStatus("error", "שיתוף GG לא זמין");
                showError("הדפדפן לא הצליח להתחיל שיתוף מסך. לחץ שוב ובחר את חלון GG או פתח עם ?ggNative=1 לניסיון צילום מקומי.");
            } else {
                setGgReaderStatus("error", "שרת GG לא פעיל");
                showError("שרת GG המקומי לא פועל. הפעל את backend על פורט 8787 או פתח עם ?ggMock=1 לבדיקה.");
            }
            state.ggReader.errors.push(String(error && error.message ? error.message : error));
        } finally {
            if (timeoutId !== null) {
                window.clearTimeout(timeoutId);
            }
        }
    }

    async function stopGgTableReader() {
        const connection = state.ggReader.connection;
        state.ggReader.running = false;
        state.ggReader.connection = null;
        stopGgBrowserCapture();
        if (connection && connection.readyState <= WebSocket.OPEN) {
            connection.close();
        }

        try {
            await fetch(`${GG_READER_API_BASE}/api/gg-reader/stop`, { method: "POST" });
        } catch (error) {
            state.ggReader.errors.push(String(error && error.message ? error.message : error));
        }

        setGgReaderStatus("idle", "GG מנותק");
        showError("קריאת GG הופסקה.");
    }

    function shouldUseBrowserGgCapture() {
        try {
            const params = new URLSearchParams(window.location.search);
            if (params.get("ggBrowser") === "1") {
                return Boolean(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
            }
            if (params.get("ggNative") === "1" || params.get("ggBrowser") === "0") {
                return false;
            }
        } catch (error) {
            return false;
        }
        return false;
    }

    function requestGgDisplayMedia() {
        return navigator.mediaDevices.getDisplayMedia({
            audio: false,
            video: {
                frameRate: { ideal: GG_READER_BROWSER_FPS, max: 5 },
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });
    }

    async function startGgBrowserCapture(stream) {
        stopGgBrowserCapture();
        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;

        state.ggReader.browserStream = stream;
        state.ggReader.browserVideo = video;
        state.ggReader.browserCanvas = state.ggReader.browserCanvas || document.createElement("canvas");

        const endedHandler = () => {
            if (state.ggReader.running) {
                stopGgTableReader();
            }
        };
        stream.getTracks().forEach((track) => track.addEventListener("ended", endedHandler, { once: true }));

        await video.play();
        if (!video.videoWidth || !video.videoHeight) {
            await new Promise((resolve) => {
                video.addEventListener("loadedmetadata", resolve, { once: true });
            });
        }
        state.ggReader.browserCrop = await getGgBrowserCaptureCrop(video).catch(() => null);

        state.ggReader.running = true;
        setGgReaderStatus("running", "קורא GG מהחלון שבחרת...");
        showError("קורא את שולחן GG מהשיתוף לפחות פעמיים בשנייה.");
        startGgRenderLoop();
        state.ggReader.browserFrameNextAt = performance.now();
        scheduleNextGgBrowserFrame(0);
    }

    function stopGgBrowserCapture() {
        if (state.ggReader.browserFrameTimer) {
            window.clearTimeout(state.ggReader.browserFrameTimer);
        }
        state.ggReader.browserFrameTimer = null;
        state.ggReader.browserFrameInFlight = false;
        state.ggReader.browserFrameInFlightCount = 0;
        state.ggReader.browserFrameInFlightStartedAt = 0;
        state.ggReader.browserFrameInFlightStartedAts = [];
        state.ggReader.browserFrameNextAt = 0;
        state.ggReader.browserCrop = null;
        state.ggReader.frameTimes = [];
        state.ggReader.captureTimes = [];
        state.ggReader.responseTimes = [];
        state.ggReader.renderTimes = [];
        state.ggReader.actualFps = 0;
        state.ggReader.captureFps = 0;
        state.ggReader.parseFps = 0;
        state.ggReader.renderFps = 0;
        state.ggReader.failedReads = 0;
        state.ggReader.lastFrameMs = null;
        state.ggReader.lastParseMs = null;
        stopGgRenderLoop();
        if (state.ggReader.browserVideo) {
            state.ggReader.browserVideo.pause();
            state.ggReader.browserVideo.srcObject = null;
        }
        state.ggReader.browserVideo = null;
        if (state.ggReader.browserStream) {
            stopGgMediaStream(state.ggReader.browserStream);
        }
        state.ggReader.browserStream = null;
    }

    function stopGgMediaStream(stream) {
        if (!stream || typeof stream.getTracks !== "function") {
            return;
        }
        stream.getTracks().forEach((track) => track.stop());
    }

    async function getGgBrowserCaptureCrop(video) {
        const [windowsResponse, monitorsResponse] = await Promise.all([
            fetch(`${GG_READER_API_BASE}/api/gg-reader/windows`),
            fetch(`${GG_READER_API_BASE}/api/gg-reader/monitors`)
        ]);
        if (!windowsResponse.ok || !monitorsResponse.ok) {
            return null;
        }
        const windows = await windowsResponse.json();
        const monitors = await monitorsResponse.json();
        const ggWindow = Array.isArray(windows) ? windows[0] : null;
        if (!ggWindow || !Array.isArray(monitors) || !monitors.length) {
            return null;
        }

        const videoWidth = Number(video.videoWidth) || 0;
        const videoHeight = Number(video.videoHeight) || 0;
        const windowWidth = Number(ggWindow.width) || 0;
        const windowHeight = Number(ggWindow.height) || 0;
        if (!videoWidth || !videoHeight || !windowWidth || !windowHeight) {
            return null;
        }
        if (videoWidth <= windowWidth * 1.35 && videoHeight <= windowHeight * 1.35) {
            return null;
        }

        const monitor = monitors.find((item) => {
            const left = Number(item.left) || 0;
            const top = Number(item.top) || 0;
            const width = Number(item.width) || 0;
            const height = Number(item.height) || 0;
            return Number(ggWindow.left) >= left
                && Number(ggWindow.left) < left + width
                && Number(ggWindow.top) >= top
                && Number(ggWindow.top) < top + height;
        }) || monitors[0];
        const scaleX = videoWidth / Math.max(1, Number(monitor.width) || videoWidth);
        const scaleY = videoHeight / Math.max(1, Number(monitor.height) || videoHeight);
        const left = Math.max(0, Math.round((Number(ggWindow.left) - Number(monitor.left || 0)) * scaleX));
        const top = Math.max(0, Math.round((Number(ggWindow.top) - Number(monitor.top || 0)) * scaleY));
        const width = Math.min(videoWidth - left, Math.round(windowWidth * scaleX));
        const height = Math.min(videoHeight - top, Math.round(windowHeight * scaleY));
        if (width < 320 || height < 240) {
            return null;
        }
        return { left, top, width, height };
    }

    function scheduleNextGgBrowserFrame(delayMs = GG_READER_BROWSER_FRAME_INTERVAL_MS) {
        if (!state.ggReader.running) {
            return;
        }
        if (state.ggReader.browserFrameTimer) {
            window.clearTimeout(state.ggReader.browserFrameTimer);
        }
        state.ggReader.browserFrameTimer = window.setTimeout(
            captureGgBrowserFrame,
            Math.max(0, Number(delayMs) || 0)
        );
    }

    async function captureGgBrowserFrame() {
        const video = state.ggReader.browserVideo;
        const canvas = state.ggReader.browserCanvas;
        const crop = state.ggReader.browserCrop;
        const inFlightCount = Number(state.ggReader.browserFrameInFlightCount) || 0;
        if (!state.ggReader.running || !video || !canvas || inFlightCount >= GG_READER_MAX_IN_FLIGHT_FRAMES) {
            if (state.ggReader.running && inFlightCount >= GG_READER_MAX_IN_FLIGHT_FRAMES) {
                state.ggReader.droppedFrames += 1;
                scheduleNextGgBrowserFrame(GG_READER_BROWSER_FRAME_INTERVAL_MS);
            }
            return;
        }
        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth || !video.videoHeight) {
            scheduleNextGgBrowserFrame(50);
            return;
        }

        const frameStartedAt = performance.now();
        beginGgBrowserFrameRequest(frameStartedAt);
        let timeoutId = null;
        let nextFrameScheduled = false;
        try {
            const sourceWidth = crop ? crop.width : video.videoWidth;
            const sourceHeight = crop ? crop.height : video.videoHeight;
            const scale = Math.min(1, GG_READER_BROWSER_MAX_FRAME_WIDTH / Math.max(1, sourceWidth));
            const targetWidth = Math.max(1, Math.round(sourceWidth * scale));
            const targetHeight = Math.max(1, Math.round(sourceHeight * scale));
            canvas.width = targetWidth;
            canvas.height = targetHeight;
            const context = canvas.getContext("2d", { willReadFrequently: true });
            if (!context) {
                throw new Error("Canvas context is not available");
            }
            if (crop) {
                context.drawImage(video, crop.left, crop.top, crop.width, crop.height, 0, 0, targetWidth, targetHeight);
            } else {
                context.drawImage(video, 0, 0, targetWidth, targetHeight);
            }
            const encodeStartedAt = performance.now();
            const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", GG_READER_BROWSER_JPEG_QUALITY));
            if (!blob) {
                throw new Error("Browser frame encoding failed");
            }
            state.ggReader.lastEncodeMs = performance.now() - encodeStartedAt;
            state.ggReader.lastImageBytes = Number(blob.size) || 0;
            const sentSeq = state.ggReader.browserFrameSeq + 1;
            state.ggReader.browserFrameSeq = sentSeq;
            recordGgCaptureSent(frameStartedAt);
            if (state.ggReader.running) {
                const nextFrameAt = frameStartedAt + GG_READER_BROWSER_FRAME_INTERVAL_MS;
                state.ggReader.browserFrameNextAt = nextFrameAt;
                scheduleNextGgBrowserFrame(nextFrameAt - performance.now());
                nextFrameScheduled = true;
            }

            const controller = new AbortController();
            timeoutId = window.setTimeout(() => controller.abort(), 2200);
            const response = await fetch(`${GG_READER_API_BASE}/api/gg-reader/parse-frame?seq=${encodeURIComponent(String(sentSeq))}`, {
                method: "POST",
                headers: {
                    "Content-Type": blob.type || "image/jpeg",
                    "X-GG-Frame-Seq": String(sentSeq)
                },
                body: blob,
                signal: controller.signal
            });
            if (!response.ok) {
                throw new Error(`GG frame parse failed: ${response.status}`);
            }
            const payload = await response.json();
            const responseAt = performance.now();
            state.ggReader.lastInFlightMs = responseAt - frameStartedAt;
            state.ggReader.lastResponseAt = responseAt;
            recordGgParseResponse(responseAt);
            handleGgReaderSocketPayload(payload, { sentSeq, source: "browser-response" });
        } catch (error) {
            state.ggReader.lastInFlightMs = performance.now() - frameStartedAt;
            setGgReaderStatus("warning", "פריים GG לא נקרא");
            state.ggReader.errors.push(String(error && error.message ? error.message : error));
            saveGgHistoryEvent({
                type: "warning",
                message: "פריים GG לא נקרא מהשיתוף"
            });
        } finally {
            if (timeoutId !== null) {
                window.clearTimeout(timeoutId);
            }
            endGgBrowserFrameRequest(frameStartedAt);
            if (state.ggReader.running && !nextFrameScheduled) {
                const nextFrameAt = frameStartedAt + GG_READER_BROWSER_FRAME_INTERVAL_MS;
                state.ggReader.browserFrameNextAt = nextFrameAt;
                scheduleNextGgBrowserFrame(nextFrameAt - performance.now());
            }
        }
    }

    function beginGgBrowserFrameRequest(startedAt) {
        const starts = state.ggReader.browserFrameInFlightStartedAts || [];
        starts.push(startedAt);
        state.ggReader.browserFrameInFlightStartedAts = starts;
        state.ggReader.browserFrameInFlightCount = starts.length;
        state.ggReader.browserFrameInFlight = starts.length > 0;
        state.ggReader.browserFrameInFlightStartedAt = starts.length ? Math.min(...starts) : 0;
    }

    function endGgBrowserFrameRequest(startedAt) {
        const starts = (state.ggReader.browserFrameInFlightStartedAts || [])
            .filter((value) => Math.abs(Number(value) - Number(startedAt)) > 0.01);
        state.ggReader.browserFrameInFlightStartedAts = starts;
        state.ggReader.browserFrameInFlightCount = starts.length;
        state.ggReader.browserFrameInFlight = starts.length > 0;
        state.ggReader.browserFrameInFlightStartedAt = starts.length ? Math.min(...starts) : 0;
    }

    function recordGgRateSample(samplesKey, fpsKey, now, maxFps = Infinity) {
        const cutoff = now - 3000;
        const samples = state.ggReader[samplesKey] || [];
        samples.push(now);
        while (samples.length && samples[0] < cutoff) {
            samples.shift();
        }
        state.ggReader[samplesKey] = samples;
        const spanSeconds = samples.length > 1
            ? Math.max(0.25, (samples[samples.length - 1] - samples[0]) / 1000)
            : 1;
        const fps = samples.length > 1 ? (samples.length - 1) / spanSeconds : samples.length;
        state.ggReader[fpsKey] = Number.isFinite(maxFps) ? Math.min(maxFps, fps) : fps;
    }

    function recordGgCaptureSent(now) {
        recordGgRateSample("captureTimes", "captureFps", now, GG_READER_BROWSER_FPS);
    }

    function recordGgParseResponse(now) {
        recordGgRateSample("responseTimes", "parseFps", now, Infinity);
        state.ggReader.actualFps = Math.min(GG_READER_BROWSER_FPS, state.ggReader.parseFps || 0);
    }

    function recordGgFrameTiming(now) {
        recordGgRateSample("frameTimes", "actualFps", now, GG_READER_BROWSER_FPS);
        recordGgParseResponse(now);
    }

    function recordGgRenderTiming(now) {
        recordGgRateSample("renderTimes", "renderFps", now, Infinity);
    }

    function connectGgReaderSocket() {
        if (state.ggReader.connection) {
            state.ggReader.connection.close();
        }

        const socket = new WebSocket(GG_READER_WS_URL);
        state.ggReader.connection = socket;

        socket.addEventListener("open", () => {
            state.ggReader.running = true;
            setGgReaderStatus("running", "קורא GG...");
            showError("קורא שולחן GG מחלון ClubGG האמיתי בלבד.");
            startGgRenderLoop();
        });

        socket.addEventListener("message", (event) => {
            try {
                const payload = JSON.parse(event.data);
                handleGgReaderSocketPayload(payload);
            } catch (error) {
                saveGgHistoryEvent({
                    type: "warning",
                    message: "פריים GG לא נקרא כ-JSON תקין"
                });
                state.ggReader.errors.push(String(error && error.message ? error.message : error));
            }
        });

        socket.addEventListener("close", () => {
            if (state.ggReader.running) {
                state.ggReader.running = false;
                stopGgRenderLoop();
                setGgReaderStatus("error", "חיבור GG נסגר");
                showError("חיבור GG נסגר. בדוק שה-backend עדיין רץ.");
            }
        });

        socket.addEventListener("error", () => {
            state.ggReader.running = false;
            stopGgRenderLoop();
            setGgReaderStatus("error", "שגיאת GG");
            showError("שגיאה בחיבור WebSocket לקורא GG.");
        });
    }

    function handleGgReaderSocketPayload(payload, options = {}) {
        if (!payload) {
            return;
        }
        const payloadSeq = getGgPayloadFrameSeq(payload, options);
        if (Number.isFinite(payloadSeq) && payloadSeq < state.ggReader.latestSnapshotSeq) {
            state.ggReader.staleResponsesIgnored += 1;
            renderGgReaderStatus();
            return;
        }
        const serverReceivedAt = Number(payload.serverReceivedAt || 0);
        if (
            Number.isFinite(serverReceivedAt)
            && serverReceivedAt > 0
            && Number(state.ggReader.latestServerReceivedAt || 0) > 0
            && serverReceivedAt < Number(state.ggReader.latestServerReceivedAt || 0)
        ) {
            state.ggReader.staleResponsesIgnored += 1;
            renderGgReaderStatus();
            return;
        }
        updateGgReaderRuntimeMetrics(payload);

        if (payload.type === "status") {
            const previousStatusText = state.ggReader.lastStatusText;
            if (state.ggReader.running && ["warning", "error", "waiting"].includes(String(payload.status || ""))) {
                state.ggReader.failedReads += 1;
            }
            setGgReaderStatus(payload.status || "waiting", payload.message || "ממתין ל-GG...");
            if (payload.message && payload.status !== "waiting") {
                showError(payload.message);
            }
            if (payload.clearTable) {
                clearGgImportedSnapshot();
            }
            if (payload.fatal) {
                state.ggReader.running = false;
                const connection = state.ggReader.connection;
                state.ggReader.connection = null;
                stopGgRenderLoop();
                if (connection && connection.readyState <= WebSocket.OPEN) {
                    connection.close();
                }
                fetch(`${GG_READER_API_BASE}/api/gg-reader/stop`, { method: "POST" }).catch(() => {});
                renderGgReaderStatus();
            }
            if (payload.status !== "waiting" || previousStatusText !== payload.message) {
                saveGgHistoryEvent({
                    type: payload.status === "warning" ? "warning" : "reader_status",
                    message: payload.message || "סטטוס GG עודכן"
                });
            }
            return;
        }

        if (payload.captureSource !== "browser") {
            recordGgFrameTiming(performance.now());
        }
        storeLatestGgSnapshot(payload, { seq: payloadSeq });
    }

    function updateGgReaderRuntimeMetrics(payload) {
        const frameMs = Number(payload.frameMs);
        if (Number.isFinite(frameMs)) {
            state.ggReader.lastFrameMs = frameMs;
        }
        const decodeMs = Number(payload.decodeMs);
        if (Number.isFinite(decodeMs)) {
            state.ggReader.lastDecodeMs = decodeMs;
        }
        const cropMs = Number(payload.cropMs);
        if (Number.isFinite(cropMs)) {
            state.ggReader.lastCropMs = cropMs;
        }
        const parseMs = Number(payload.parseMs || payload.readerParseMs);
        if (Number.isFinite(parseMs)) {
            state.ggReader.lastParseMs = parseMs;
        }
        const readerParseMs = Number(payload.readerParseMs);
        if (Number.isFinite(readerParseMs)) {
            state.ggReader.lastReaderParseMs = readerParseMs;
        }
        const frameBytes = Number(payload.frameBytes);
        if (Number.isFinite(frameBytes) && frameBytes >= 0) {
            state.ggReader.lastFrameBytes = frameBytes;
        }
        const readerFps = Number(payload.actualReaderFps);
        if (Number.isFinite(readerFps) && readerFps > 0) {
            state.ggReader.actualFps = Math.min(GG_READER_BROWSER_FPS, readerFps);
        }
    }

    function getGgPayloadFrameSeq(payload, options = {}) {
        const rawSeq = payload?.frameSeq ?? payload?.seq ?? options.sentSeq;
        const seq = Number(rawSeq);
        return Number.isFinite(seq) && seq > 0 ? seq : null;
    }

    function storeLatestGgSnapshot(payload, options = {}) {
        if (!payload || payload.source !== "ggclub") {
            saveGgHistoryEvent({
                type: "warning",
                message: "Snapshot GG נדחה: מקור לא תקין"
            });
            return false;
        }

        const seq = Number.isFinite(options.seq)
            ? Number(options.seq)
            : state.ggReader.latestSnapshotSeq + 1;
        if (seq < state.ggReader.latestSnapshotSeq) {
            state.ggReader.staleResponsesIgnored += 1;
            renderGgReaderStatus();
            return false;
        }
        if (
            state.ggReader.latestSnapshot
            && state.ggReader.latestSnapshotSeq !== state.ggReader.lastRenderedSnapshotSeq
            && seq > state.ggReader.latestSnapshotSeq
        ) {
            state.ggReader.droppedFrames += 1;
        }

        payload.frameSeq = seq;
        const serverReceivedAt = Number(payload.serverReceivedAt || 0);
        if (Number.isFinite(serverReceivedAt) && serverReceivedAt > 0) {
            state.ggReader.latestServerReceivedAt = Math.max(
                Number(state.ggReader.latestServerReceivedAt || 0),
                serverReceivedAt
            );
        }
        state.ggReader.latestSnapshot = payload;
        state.ggReader.latestSnapshotSeq = seq;
        state.ggReader.lastSnapshotReceivedAt = performance.now();
        renderGgReaderStatus();
        return true;
    }

    function startGgRenderLoop() {
        stopGgRenderLoop();
        state.ggReader.renderTimer = window.setInterval(runGgRenderTick, GG_READER_RENDER_INTERVAL_MS);
    }

    function stopGgRenderLoop() {
        if (state.ggReader.renderTimer) {
            window.clearInterval(state.ggReader.renderTimer);
        }
        state.ggReader.renderTimer = null;
    }

    function runGgRenderTick() {
        const snapshot = state.ggReader.latestSnapshot;
        if (
            snapshot
            && state.ggReader.latestSnapshotSeq !== state.ggReader.lastRenderedSnapshotSeq
        ) {
            const started = performance.now();
            const applied = applyGgSnapshot(snapshot, {
                suppressProbability: true,
                source: "render-loop"
            });
            state.ggReader.lastApplySnapshotMs = performance.now() - started;
            if (applied) {
                state.ggReader.lastRenderedSnapshotSeq = state.ggReader.latestSnapshotSeq;
                state.ggReader.lastRenderAt = performance.now();
                recordGgRenderTiming(state.ggReader.lastRenderAt);
                scheduleProbabilityUpdateThrottled(state.ggReader.lastSnapshot || snapshot);
            }
        }
        renderGgReaderStatus();
        logGgReaderPipelineMetrics();
    }

    function scheduleProbabilityUpdateThrottled(snapshot) {
        const signature = buildGgProbabilitySnapshotSignature(snapshot);
        if (!signature || signature === state.ggReader.lastProbabilitySnapshotSignature) {
            return;
        }
        const now = performance.now();
        if (now - Number(state.ggReader.lastProbabilityUpdateAt || 0) < GG_READER_PROBABILITY_THROTTLE_MS) {
            return;
        }
        state.ggReader.lastProbabilityUpdateAt = now;
        const run = () => runProbabilityUpdateMeasured(snapshot, signature);
        if (typeof window.requestIdleCallback === "function") {
            window.requestIdleCallback(run, { timeout: 1000 });
        } else {
            window.setTimeout(run, 0);
        }
    }

    function runProbabilityUpdateMeasured(snapshot, signature) {
        const latestSignature = buildGgProbabilitySnapshotSignature(state.ggReader.lastSnapshot || state.ggReader.latestSnapshot);
        if (!snapshot || signature !== buildGgProbabilitySnapshotSignature(snapshot) || signature !== latestSignature) {
            return;
        }
        const started = performance.now();
        try {
            if (state.mode === "equity") {
                updateWinProbabilities();
            } else if (state.mode === "solver") {
                updateSolverRecommendations();
            }
            state.ggReader.lastProbabilitySnapshotSignature = signature;
        } finally {
            state.ggReader.lastProbabilityMs = performance.now() - started;
            renderGgReaderStatus();
        }
    }

    function buildGgProbabilitySnapshotSignature(snapshot) {
        if (!snapshot) {
            return "";
        }
        const cardSignature = (card) => {
            if (!card) {
                return "";
            }
            if (card.hidden || card.visible === false) {
                return card.display ? `hidden:${card.display}` : "hidden";
            }
            return getGgCardId(card);
        };
        const boardSignature = (Array.isArray(snapshot.board) ? snapshot.board : [])
            .map(cardSignature)
            .join(",");
        const seatsSignature = (Array.isArray(snapshot.seats) ? snapshot.seats : [])
            .map((seat) => {
                const seatIndex = Number(seat?.physicalSeatIndex);
                const cards = (Array.isArray(seat?.holeCards) ? seat.holeCards : [])
                    .map(cardSignature)
                    .join(",");
                return `${Number.isFinite(seatIndex) ? seatIndex : ""}:${seat?.active !== false ? 1 : 0}:${seat?.status || ""}:${cards}`;
            })
            .join("|");
        return `${boardSignature}#${seatsSignature}`;
    }

    function logGgReaderPipelineMetrics() {
        if (!state.ggReader.running || typeof console === "undefined" || typeof console.debug !== "function") {
            return;
        }
        const now = performance.now();
        if (now - Number(state.ggReader.lastPipelineLogAt || 0) < GG_READER_STATUS_LOG_INTERVAL_MS) {
            return;
        }
        state.ggReader.lastPipelineLogAt = now;
        const lastRenderAgeMs = state.ggReader.lastRenderAt ? now - state.ggReader.lastRenderAt : null;
        const lastSnapshotAgeMs = state.ggReader.lastSnapshotReceivedAt ? now - state.ggReader.lastSnapshotReceivedAt : null;
        const inFlightMs = state.ggReader.browserFrameInFlight && state.ggReader.browserFrameInFlightStartedAt
            ? now - state.ggReader.browserFrameInFlightStartedAt
            : state.ggReader.lastInFlightMs;
        console.debug("[GG Reader Pipeline]", {
            captureSentPerSec: Number(state.ggReader.captureFps || 0).toFixed(2),
            responsesPerSec: Number(state.ggReader.parseFps || state.ggReader.actualFps || 0).toFixed(2),
            renderFps: Number(state.ggReader.renderFps || 0).toFixed(2),
            latestSnapshotSeq: state.ggReader.latestSnapshotSeq,
            lastRenderedSnapshotSeq: state.ggReader.lastRenderedSnapshotSeq,
            lastRenderAgeMs: Number.isFinite(lastRenderAgeMs) ? Math.round(lastRenderAgeMs) : null,
            lastSnapshotAgeMs: Number.isFinite(lastSnapshotAgeMs) ? Math.round(lastSnapshotAgeMs) : null,
            browserFrameInFlight: state.ggReader.browserFrameInFlight,
            browserFrameInFlightCount: state.ggReader.browserFrameInFlightCount || 0,
            inFlightMs: Number.isFinite(inFlightMs) ? Math.round(inFlightMs) : null,
            lastParseMs: state.ggReader.lastParseMs,
            probabilityMs: Math.round(Number(state.ggReader.lastProbabilityMs) || 0),
            imageBytes: state.ggReader.lastImageBytes,
            frameBytes: state.ggReader.lastFrameBytes,
            droppedFrames: state.ggReader.droppedFrames,
            staleResponsesIgnored: state.ggReader.staleResponsesIgnored,
            backendDecodeMs: state.ggReader.lastDecodeMs,
            backendCropMs: state.ggReader.lastCropMs,
            backendFrameMs: state.ggReader.lastFrameMs
        });
    }

    function isGgMockMode() {
        try {
            return new URLSearchParams(window.location.search).get("ggMock") === "1";
        } catch (error) {
            return false;
        }
    }

    async function loadGgMockSnapshot() {
        const response = await fetch(GG_READER_MOCK_URL, { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`Mock snapshot failed: ${response.status}`);
        }
        return response.json();
    }

    function applyGgSnapshot(snapshot, options = {}) {
        if (!snapshot || snapshot.source !== "ggclub") {
            saveGgHistoryEvent({
                type: "warning",
                message: "Snapshot GG נדחה: מקור לא תקין"
            });
            return false;
        }

        const duplicate = findDuplicateVisibleGgCard(snapshot);
        if (duplicate) {
            saveGgHistoryEvent({
                type: "warning",
                message: `Snapshot GG נדחה: הקלף ${duplicate} הופיע פעמיים`
            });
            setGgReaderStatus("warning", "פריים GG נדחה");
            showError(`פריים GG נדחה: הקלף ${duplicate} הופיע פעמיים.`);
            return false;
        }

        if (!shouldApplyGgSnapshot(snapshot)) {
            setGgReaderStatus("waiting", "ממתין לאימות GG...");
            return false;
        }

        const normalizedSnapshot = normalizeGgSnapshotForUi(snapshot);
        const previousSnapshot = state.ggReader.lastSnapshot;
        const seats = Array.isArray(normalizedSnapshot.seats) ? normalizedSnapshot.seats : [];
        const board = Array.isArray(normalizedSnapshot.board) ? normalizedSnapshot.board : [];
        const tableSeatCount = Math.max(
            MIN_PLAYERS,
            Math.min(
                MAX_PLAYERS,
                Number(normalizedSnapshot.tableSeatCount)
                    || seats.length
                    || Number(normalizedSnapshot.activePlayerCount)
                    || MIN_PLAYERS
            )
        );

        const previousDefer = state.deferProbabilityUpdate;
        state.deferProbabilityUpdate = true;
        setPlayersCount(tableSeatCount);

        clearGgInactiveUiSeats(tableSeatCount);
        state.ggReader.potOverride = sanitizeEconomyValue(Number(normalizedSnapshot.pot) || 0);
        applyGgBoardSnapshot(board);
        seats.forEach((seat) => applyGgSeatSnapshot(seat));

        const dealerIndex = Number(normalizedSnapshot.dealerSeatIndex);
        if (Number.isInteger(dealerIndex) && dealerIndex >= 0 && dealerIndex < MAX_PLAYERS) {
            setDealerSeatIndex(dealerIndex);
        }
        applyGgPositionLabels(normalizedSnapshot);

        state.ggReader.lastSnapshot = normalizedSnapshot;
        syncPlayerEconomyInputs();
        updateTablePotDisplay();
        updateSeatStates();
        applyGgPositionLabels(normalizedSnapshot);
        ensureActiveSlot("player");
        state.deferProbabilityUpdate = previousDefer;
        if (!options.suppressProbability) {
            scheduleGgProbabilityUpdate(normalizedSnapshot);
        }
        if (options.source !== "mock") {
            setGgReaderStatus("running", "קורא GG...");
        }
        renderGgReaderStatus();
        renderGgReaderDebugPanel();
        recordGgSnapshotDiff(previousSnapshot, normalizedSnapshot, options);
        return true;
    }

    function scheduleGgProbabilityUpdate(snapshot = state.ggReader.lastSnapshot) {
        scheduleProbabilityUpdateThrottled(snapshot);
    }

    function normalizeGgSnapshotForUi(snapshot) {
        const rawSeats = Array.isArray(snapshot.seats) ? snapshot.seats : [];
        const seats = rawSeats
            .filter((seat) => seat && Number.isInteger(Number(seat.physicalSeatIndex)))
            .sort((left, right) => Number(left.physicalSeatIndex) - Number(right.physicalSeatIndex));

        if (!seats.length) {
            return {
                ...snapshot,
                seats: [],
                tableSeatCount: 0,
                activePlayerCount: 0
            };
        }

        const normalizedSeats = seats.slice(0, MAX_PLAYERS).map((seat) => {
            const physicalIndex = Number(seat.physicalSeatIndex);
            return {
                ...seat,
                sourcePhysicalSeatIndex: physicalIndex,
                physicalSeatIndex: physicalIndex,
                active: seat.active !== false
            };
        });

        const activePlayerCount = normalizedSeats.filter((seat) => seat.active !== false).length;
        const maxPhysicalIndex = normalizedSeats.reduce((maxIndex, seat) => Math.max(maxIndex, Number(seat.physicalSeatIndex)), -1);
        return {
            ...snapshot,
            seats: normalizedSeats,
            dealerSeatIndex: Number.isInteger(Number(snapshot.dealerSeatIndex)) ? Number(snapshot.dealerSeatIndex) : 0,
            heroSeatIndex: snapshot.heroSeatIndex === null || snapshot.heroSeatIndex === undefined
                ? null
                : Number(snapshot.heroSeatIndex),
            tableSeatCount: Math.max(activePlayerCount, maxPhysicalIndex + 1),
            activePlayerCount
        };
    }

    function clearGgInactiveUiSeats(activeSeatCount) {
        for (let index = activeSeatCount; index < MAX_PLAYERS; index += 1) {
            clearPlayerSlots(index, { suppressUpdate: true });
            state.playerEconomy[index] = createDefaultEconomy();
            const seat = state.seats[index];
            if (seat) {
                seat.classList.remove("seat--gg-empty", "seat--gg-hero", "seat--gg-folded");
            }
            const meta = state.seatMeta[index];
            if (meta && meta.nameEl) {
                meta.nameEl.textContent = `שחקן ${index + 1}`;
            }
            if (meta && meta.positionEl) {
                meta.positionEl.textContent = "";
                meta.label?.classList.remove("has-position");
            }
            updateGgSeatActionDisplay(index, null);
            updateSeatBetDisplay(index);
        }
    }

    function clearGgImportedSnapshot() {
        if (!state.ggReader.lastSnapshot && state.ggReader.potOverride === null) {
            return;
        }

        const previousDefer = state.deferProbabilityUpdate;
        state.deferProbabilityUpdate = true;
        state.ggReader.lastSnapshot = null;
        state.ggReader.latestSnapshot = null;
        state.ggReader.latestSnapshotSeq = 0;
        state.ggReader.latestServerReceivedAt = 0;
        state.ggReader.lastRenderedSnapshotSeq = 0;
        state.ggReader.pendingSnapshot = null;
        state.ggReader.potOverride = null;
        state.ggReader.lastProbabilitySnapshotSignature = "";

        state.slotByKey.forEach((slot) => clearSlot(slot, { suppressUpdate: true }));
        for (let index = 0; index < MAX_PLAYERS; index += 1) {
            state.playerEconomy[index] = createDefaultEconomy();
            const seat = state.seats[index];
            if (seat) {
                seat.classList.remove("seat--gg-empty", "seat--gg-hero", "seat--gg-folded");
            }
            const meta = state.seatMeta[index];
            if (meta && meta.nameEl) {
                meta.nameEl.textContent = `שחקן ${index + 1}`;
            }
            updateGgSeatActionDisplay(index, null);
            updateSeatBetDisplay(index);
        }

        state.deferProbabilityUpdate = previousDefer;
        syncPlayerEconomyInputs();
        updateTablePotDisplay();
        ensureActiveSlot("player");
        scheduleImmediateProbabilityUpdate();
    }

    function applyGgBoardSnapshot(board) {
        getSlotsByType("board").forEach((slot, index) => {
            const cardSnapshot = board[index];
            applyGgCardSnapshotToSlot(cardSnapshot, slot);
        });
    }

    function applyGgSeatSnapshot(seatSnapshot) {
        if (!seatSnapshot || !Number.isInteger(Number(seatSnapshot.physicalSeatIndex))) {
            return;
        }

        const index = Number(seatSnapshot.physicalSeatIndex);
        if (index < 0 || index >= MAX_PLAYERS) {
            return;
        }

        const seatEl = state.seats[index];
        const meta = state.seatMeta[index];
        const isActive = seatSnapshot.active !== false;
        const isFolded = seatSnapshot.status === "folded" || seatSnapshot.action === "fold";
        if (seatEl) {
            seatEl.classList.toggle("seat--gg-empty", !isActive);
            seatEl.classList.toggle("seat--gg-hero", Boolean(seatSnapshot.isHero));
            seatEl.classList.toggle("seat--gg-folded", Boolean(isFolded));
        }
        if (meta && meta.nameEl) {
            meta.nameEl.textContent = isActive && seatSnapshot.name
                ? String(seatSnapshot.name)
                : (isActive ? `שחקן ${index + 1}` : "Take Seat");
        }

        const economy = ensurePlayerEconomy(index);
        if (isActive) {
            const hasStackConfidence = Object.prototype.hasOwnProperty.call(seatSnapshot, "stackConfidence");
            const stackConfidence = seatSnapshot.stackConfidence ?? seatSnapshot.confidence;
            if (shouldApplyGgField(stackConfidence, seatSnapshot.stack)) {
                economy.stack = sanitizeEconomyValue(Number(seatSnapshot.stack) || 0);
            } else if (hasStackConfidence && Number(stackConfidence) === 0 && Number(seatSnapshot.stack || 0) === 0) {
                economy.stack = 0;
            }
            const hasBetConfidence = Object.prototype.hasOwnProperty.call(seatSnapshot, "betConfidence");
            const betConfidence = seatSnapshot.betConfidence ?? seatSnapshot.confidence;
            if (shouldApplyGgField(betConfidence, seatSnapshot.currentBet)) {
                economy.pendingBet = 0;
                economy.committedBet = sanitizeEconomyValue(Number(seatSnapshot.currentBet) || Number(seatSnapshot.committed) || 0);
            } else if (hasBetConfidence && Number(betConfidence) === 0 && Number(seatSnapshot.currentBet || 0) === 0) {
                economy.pendingBet = 0;
                economy.committedBet = 0;
            }
        } else {
            economy.stack = 0;
            economy.pendingBet = 0;
            economy.committedBet = 0;
        }

        getPlayerCardSlots(index).forEach((slot, cardIndex) => {
            const cardSnapshot = Array.isArray(seatSnapshot.holeCards)
                ? seatSnapshot.holeCards[cardIndex]
                : null;
            applyGgCardSnapshotToSlot(isActive && !isFolded ? cardSnapshot : null, slot);
        });

        updateGgSeatActionDisplay(index, seatSnapshot);
        updateSeatBetDisplay(index);
    }

    function updateGgSeatActionDisplay(index, seatSnapshot) {
        const meta = state.seatMeta[index];
        if (!meta || !meta.actionDisplay) {
            return;
        }
        const display = meta.actionDisplay;
        const action = seatSnapshot && seatSnapshot.active !== false
            ? String(seatSnapshot.action || "none")
            : "none";
        if (!action || action === "none") {
            display.hidden = true;
            display.textContent = "";
            display.setAttribute("aria-hidden", "true");
            display.className = "seat-live-action";
            return;
        }

        const amount = Number(seatSnapshot.actionAmount || seatSnapshot.currentBet || 0);
        const label = getGgActionLabel(action);
        display.textContent = amount > 0 && ["bet", "raise", "call", "all-in"].includes(action)
            ? `${label} ${formatChipAmount(amount)} BB`
            : label;
        display.hidden = false;
        display.setAttribute("aria-hidden", "false");
        display.className = `seat-live-action seat-live-action--${action.replace(/[^a-z-]/g, "")}`;
    }

    function getGgActionLabel(action) {
        const labels = {
            check: "צ'ק",
            call: "קול",
            bet: "הימור",
            raise: "רייז",
            fold: "פולד",
            "all-in": "אול אין",
            waiting: "ממתין"
        };
        return labels[action] || action;
    }

    function applyGgCardSnapshotToSlot(cardSnapshot, slot) {
        if (!slot) {
            return;
        }

        if (!cardSnapshot) {
            clearSlot(slot, { suppressUpdate: true });
            return;
        }

        const confidence = Number(cardSnapshot.confidence ?? 1);
        if (Number.isFinite(confidence) && confidence < GG_READER_CONFIDENCE_MIN) {
            return;
        }

        if (cardSnapshot.hidden) {
            markSlotHidden(slot, { display: cardSnapshot.display || "X", lock: true });
            return;
        }

        const cardId = getGgCardId(cardSnapshot);
        const card = cardId ? getCardById(cardId) : null;
        if (!card) {
            clearSlot(slot, { suppressUpdate: true });
            return;
        }

        clearHiddenMarker(slot);
        assignCardToSlot(card, slot, { lock: true, suppressUpdate: true });
    }

    function getGgCardId(cardSnapshot) {
        if (!cardSnapshot || !cardSnapshot.rank || !cardSnapshot.suit) {
            return "";
        }
        const rank = String(cardSnapshot.rank).trim().toUpperCase();
        const suit = normalizeGgSuit(cardSnapshot.suit);
        return rank && suit ? `${rank}${suit}` : "";
    }

    function normalizeGgSuit(suit) {
        const value = String(suit || "").trim().toUpperCase();
        const map = {
            S: "S",
            SPADE: "S",
            SPADES: "S",
            "♠": "S",
            H: "H",
            HEART: "H",
            HEARTS: "H",
            "♥": "H",
            D: "D",
            DIAMOND: "D",
            DIAMONDS: "D",
            "♦": "D",
            C: "C",
            CLUB: "C",
            CLUBS: "C",
            "♣": "C"
        };
        return map[value] || "";
    }

    function findDuplicateVisibleGgCard(snapshot) {
        const visibleCards = [];
        const collect = (card) => {
            if (!card || card.hidden || card.visible === false) {
                return;
            }
            const cardId = getGgCardId(card);
            if (cardId) {
                visibleCards.push(cardId);
            }
        };

        (Array.isArray(snapshot.board) ? snapshot.board : []).forEach(collect);
        (Array.isArray(snapshot.seats) ? snapshot.seats : []).forEach((seat) => {
            (Array.isArray(seat.holeCards) ? seat.holeCards : []).forEach(collect);
        });

        const seen = new Set();
        return visibleCards.find((cardId) => {
            if (seen.has(cardId)) {
                return true;
            }
            seen.add(cardId);
            return false;
        }) || "";
    }

    function shouldApplyGgField(confidence, value) {
        if (value === undefined || value === null || value === "") {
            return false;
        }
        const normalizedConfidence = Number(confidence ?? 1);
        return !Number.isFinite(normalizedConfidence) || normalizedConfidence >= GG_READER_CONFIDENCE_MIN;
    }

    function shouldApplyGgSnapshot(snapshot) {
        const confidence = Number(snapshot.confidence ?? 1);
        if (isFastGgReaderSnapshot(snapshot) && confidence >= GG_READER_CONFIDENCE_MIN) {
            state.ggReader.pendingSnapshot = null;
            return true;
        }
        if (!Number.isFinite(confidence) || confidence >= GG_READER_CONFIDENCE_DIRECT) {
            state.ggReader.pendingSnapshot = null;
            return true;
        }
        if (confidence < GG_READER_CONFIDENCE_MIN) {
            state.ggReader.pendingSnapshot = null;
            return false;
        }

        const signature = buildGgSnapshotSignature(snapshot);
        if (state.ggReader.pendingSnapshot === signature) {
            state.ggReader.pendingSnapshot = null;
            return true;
        }
        state.ggReader.pendingSnapshot = signature;
        return false;
    }

    function isFastGgReaderSnapshot(snapshot) {
        return snapshot
            && (
                snapshot.reader === "fast_roi"
                || snapshot.metrics?.reader === "fast_roi"
                || String(snapshot.profile || snapshot.metrics?.profile || "").startsWith("clubgg_")
            );
    }

    function buildGgSnapshotSignature(snapshot) {
        const seatPart = (Array.isArray(snapshot.seats) ? snapshot.seats : []).map((seat) => [
            seat.physicalSeatIndex,
            seat.active,
            seat.name,
            seat.stack,
            seat.currentBet,
            seat.position,
            seat.action,
            seat.status,
            (Array.isArray(seat.holeCards) ? seat.holeCards : []).map((card) => card.hidden ? "X" : getGgCardId(card)).join("/")
        ].join(":")).join("|");
        const boardPart = (Array.isArray(snapshot.board) ? snapshot.board : []).map(getGgCardId).join("/");
        return `${snapshot.street || "unknown"}|${snapshot.pot}|${snapshot.dealerSeatIndex}|${boardPart}|${seatPart}`;
    }

    function applyGgPositionLabels(snapshot) {
        const activeSeats = (Array.isArray(snapshot.seats) ? snapshot.seats : [])
            .filter((seat) => seat && seat.active !== false && Number.isInteger(Number(seat.physicalSeatIndex)))
            .map((seat) => Number(seat.physicalSeatIndex))
            .filter((index) => index >= 0 && index < MAX_PLAYERS)
            .sort((a, b) => a - b);

        if (!activeSeats.length) {
            updateSeatPositionLabels();
            return;
        }

        const dealerIndex = activeSeats.includes(Number(snapshot.dealerSeatIndex))
            ? Number(snapshot.dealerSeatIndex)
            : activeSeats[0];
        const dealerOrderIndex = activeSeats.indexOf(dealerIndex);
        const positions = getPositionSequence(activeSeats.length);

        state.seatMeta.forEach((meta, index) => {
            if (!meta || !meta.positionEl) {
                return;
            }
            const activeOrderIndex = activeSeats.indexOf(index);
            if (activeOrderIndex < 0) {
                meta.positionEl.textContent = "";
                meta.label?.classList.remove("has-position");
                return;
            }
            const relativeIndex = (activeOrderIndex - dealerOrderIndex + activeSeats.length) % activeSeats.length;
            const positionName = positions[relativeIndex] || "";
            meta.positionEl.textContent = positionName ? `(${positionName})` : "";
            meta.label?.classList.toggle("has-position", Boolean(positionName));
        });
        placeDealerButton();
    }

    function recordGgSnapshotDiff(previousSnapshot, snapshot, options = {}) {
        if (Array.isArray(snapshot.events) && snapshot.events.length) {
            snapshot.events.forEach((event) => {
                saveGgHistoryEvent({
                    type: event.type || "event",
                    message: event.message || "אירוע GG",
                    source: options.source || "gg"
                });
            });
            return;
        }
        if (!previousSnapshot) {
            saveGgHistoryEvent({
                type: "hand_started",
                message: "Snapshot ראשון נקלט מ-GG",
                source: options.source || "gg"
            });
            return;
        }

        if ((previousSnapshot.street || "unknown") !== (snapshot.street || "unknown")) {
            saveGgHistoryEvent({
                type: "street_changed",
                message: `רחוב השתנה ל-${snapshot.street || "unknown"}`
            });
        }
        if (Number(previousSnapshot.pot) !== Number(snapshot.pot)) {
            saveGgHistoryEvent({
                type: "pot_changed",
                message: `קופה: ${formatChipAmount(Number(snapshot.pot) || 0)}`
            });
        }
        if (Number(previousSnapshot.dealerSeatIndex) !== Number(snapshot.dealerSeatIndex)) {
            saveGgHistoryEvent({
                type: "dealer_changed",
                message: `דילר עבר לשחקן ${Number(snapshot.dealerSeatIndex) + 1}`
            });
        }

        const previousBoard = new Set((Array.isArray(previousSnapshot.board) ? previousSnapshot.board : []).map(getGgCardId).filter(Boolean));
        (Array.isArray(snapshot.board) ? snapshot.board : []).forEach((card) => {
            const cardId = getGgCardId(card);
            if (cardId && !previousBoard.has(cardId)) {
                saveGgHistoryEvent({
                    type: "board_card_added",
                    message: `קלף board נוסף: ${cardId}`
                });
            }
        });

        const previousSeats = new Map((Array.isArray(previousSnapshot.seats) ? previousSnapshot.seats : [])
            .map((seat) => [Number(seat.physicalSeatIndex), seat]));
        (Array.isArray(snapshot.seats) ? snapshot.seats : []).forEach((seat) => {
            const index = Number(seat.physicalSeatIndex);
            const previous = previousSeats.get(index);
            if (!previous && seat.active !== false) {
                saveGgHistoryEvent({ type: "player_joined", message: `${seat.name || `שחקן ${index + 1}`} נכנס` });
                return;
            }
            if (previous && previous.active !== false && seat.active === false) {
                saveGgHistoryEvent({ type: "player_left", message: `${previous.name || `שחקן ${index + 1}`} יצא` });
            }
            if (previous && Number(previous.currentBet) !== Number(seat.currentBet)) {
                saveGgHistoryEvent({
                    type: "bet_changed",
                    message: `${seat.name || `שחקן ${index + 1}`}: הימור ${formatChipAmount(Number(seat.currentBet) || 0)}`
                });
            }
            if (previous && previous.action !== seat.action && seat.action && seat.action !== "none") {
                saveGgHistoryEvent({
                    type: "player_action",
                    message: `${seat.name || `שחקן ${index + 1}`}: ${getGgActionLabel(seat.action)}`
                });
            }
            if (previous && previous.status !== seat.status && seat.status === "folded") {
                saveGgHistoryEvent({
                    type: "player_folded",
                    message: `${seat.name || `שחקן ${index + 1}`}: פולד`
                });
            }
        });
    }

    function saveGgHistoryEvent(event) {
        const entry = {
            time: new Date().toISOString(),
            type: event.type || "event",
            message: event.message || "",
            source: event.source || "gg"
        };
        state.ggReader.history.unshift(entry);
        if (state.ggReader.history.length > GG_READER_HISTORY_LIMIT) {
            state.ggReader.history.length = GG_READER_HISTORY_LIMIT;
        }
        renderGgReaderHistory();
    }

    function setGgReaderStatus(status, message) {
        state.ggReader.status = status;
        state.ggReader.lastStatusText = message;
        renderGgReaderStatus();
    }

    function renderGgReaderStatus() {
        if (elements.ggReaderStatus) {
            elements.ggReaderStatus.dataset.status = state.ggReader.status || "idle";
        }
        if (elements.ggReaderStatusText) {
            const parts = [state.ggReader.lastStatusText || "GG מנותק"];
            if (state.ggReader.running) {
                const now = performance.now();
                const inFlightMs = state.ggReader.browserFrameInFlight && state.ggReader.browserFrameInFlightStartedAt
                    ? now - state.ggReader.browserFrameInFlightStartedAt
                    : state.ggReader.lastInFlightMs;
                const lastRenderAgeMs = state.ggReader.lastRenderAt ? now - state.ggReader.lastRenderAt : null;
                const lastSnapshotAgeMs = state.ggReader.lastSnapshotReceivedAt ? now - state.ggReader.lastSnapshotReceivedAt : null;
                parts.push(`cap ${formatGgFps(state.ggReader.captureFps)}/${GG_READER_BROWSER_FPS}`);
                parts.push(`parse ${formatGgFps(state.ggReader.parseFps || state.ggReader.actualFps)}`);
                parts.push(`render ${formatGgFps(state.ggReader.renderFps)}`);
                parts.push(`snapAge ${formatGgMs(lastSnapshotAgeMs)}`);
                parts.push(`renderAge ${formatGgMs(lastRenderAgeMs)}`);
                parts.push(`flight ${state.ggReader.browserFrameInFlightCount || 0}/${GG_READER_MAX_IN_FLIGHT_FRAMES} ${formatGgMs(inFlightMs)}`);
                parts.push(`img ${formatGgBytes(state.ggReader.lastImageBytes || state.ggReader.lastFrameBytes)}`);
                parts.push(`drop ${state.ggReader.droppedFrames || 0}`);
                parts.push(`stale ${state.ggReader.staleResponsesIgnored || 0}`);
                parts.push(`apply ${formatGgMs(state.ggReader.lastApplySnapshotMs)}`);
                parts.push(`prob ${formatGgMs(state.ggReader.lastProbabilityMs)}`);
                parts.push(`be ${formatGgMs(state.ggReader.lastDecodeMs)}/${formatGgMs(state.ggReader.lastCropMs)}/${formatGgMs(state.ggReader.lastParseMs)}`);
            }
            const activeCount = Number(state.ggReader.lastSnapshot?.activePlayerCount);
            if (Number.isInteger(activeCount) && activeCount > 0) {
                parts.push(`${activeCount} שחקנים`);
            }
            elements.ggReaderStatusText.textContent = parts.join(" · ");
        }
        if (elements.ggReaderConfidence) {
            const confidence = Number(state.ggReader.lastSnapshot?.confidence);
            elements.ggReaderConfidence.textContent = Number.isFinite(confidence)
                ? `${Math.round(confidence * 100)}%`
                : "";
        }
        if (elements.ggReaderStop) {
            elements.ggReaderStop.hidden = !state.ggReader.running;
        }
        if (elements.readGgTable) {
            elements.readGgTable.textContent = state.ggReader.running ? "קורא GG..." : "קרא שולחן GG";
            elements.readGgTable.classList.toggle("is-active", state.ggReader.running);
        }
        renderGgReaderDebugPanel();
    }

    function renderGgReaderDebugPanel() {
        if (!elements.ggReaderDebug) {
            return;
        }
        const snapshot = state.ggReader.lastSnapshot || state.ggReader.latestSnapshot;
        const shouldShow = Boolean(snapshot || state.ggReader.running || state.ggReader.errors.length);
        elements.ggReaderDebug.hidden = !shouldShow;
        elements.ggReaderDebug.setAttribute("aria-hidden", shouldShow ? "false" : "true");
        if (!shouldShow) {
            return;
        }

        renderGgReaderTableInfo(snapshot);
        renderGgReaderSeatRows(snapshot);
    }

    function renderGgReaderTableInfo(snapshot) {
        if (!elements.ggReaderTableInfo) {
            return;
        }
        elements.ggReaderTableInfo.innerHTML = "";
        const metrics = snapshot || {};
        const seats = Array.isArray(snapshot?.seats) ? snapshot.seats : [];
        const activeSeats = seats.filter((seat) => seat && seat.active !== false);
        const board = Array.isArray(snapshot?.board) ? snapshot.board : [];
        const visibleBets = activeSeats.reduce((total, seat) => total + (Number(seat.currentBet) || 0), 0);
        const detectedPot = Number(snapshot?.pot);
        const warnings = [];
        if (Number.isFinite(detectedPot) && detectedPot > 0 && visibleBets > 0) {
            const mismatch = Math.abs(detectedPot - visibleBets);
            if (mismatch > Math.max(0.5, detectedPot * 0.25)) {
                warnings.push(`pot/bets ${formatChipAmount(detectedPot)} vs ${formatChipAmount(visibleBets)}`);
            }
        }
        const cropWarnings = getGgMetric(metrics, "cropWarnings");
        if (Array.isArray(cropWarnings)) {
            warnings.push(...cropWarnings.filter(Boolean).slice(0, 3));
        }
        const ocrPending = getGgMetric(metrics, "ocrPending");
        const tableSeatCount = Number(snapshot?.tableSeatCount) || seats.length || 0;
        const lastCaptureAt = Number(state.ggReader.latestServerReceivedAt || snapshot?.serverReceivedAt || snapshot?.timestamp || 0);

        const items = [
            ["street", snapshot?.street || "unknown"],
            ["pot", Number.isFinite(detectedPot) ? `${formatChipAmount(detectedPot)} BB` : "unknown"],
            ["visible bets", `${formatChipAmount(visibleBets)} BB`],
            ["board", board.length ? board.map(formatGgCardSnapshot).join(" ") : "-"],
            ["dealer", Number.isInteger(Number(snapshot?.dealerSeatIndex)) ? `seat ${Number(snapshot.dealerSeatIndex)}` : "-"],
            ["seats", tableSeatCount ? `${activeSeats.length}/${tableSeatCount}` : "-"],
            ["capture", `${formatGgFps(state.ggReader.captureFps)}`],
            ["read", `${formatGgFps(state.ggReader.parseFps || state.ggReader.actualFps)}`],
            ["render", `${formatGgFps(state.ggReader.renderFps)}`],
            ["last capture", lastCaptureAt ? new Date(lastCaptureAt).toLocaleTimeString() : "-"],
            ["latency", formatGgMs(state.ggReader.lastFrameMs || state.ggReader.lastInFlightMs)],
            ["OCR", ocrPending === undefined || ocrPending === null ? "-" : `${ocrPending} pending`],
            ["confidence", formatGgConfidence(snapshot?.confidence)],
            ["dropped", String(state.ggReader.droppedFrames || 0)],
            ["failed", String(state.ggReader.failedReads || 0)],
            ["warnings", warnings.length ? warnings.join(" | ") : "-"]
        ];

        items.forEach(([label, value]) => appendGgInfoPill(elements.ggReaderTableInfo, label, value));
    }

    function renderGgReaderSeatRows(snapshot) {
        if (!elements.ggReaderSeats) {
            return;
        }
        elements.ggReaderSeats.innerHTML = "";
        const seats = Array.isArray(snapshot?.seats) ? snapshot.seats.slice() : [];
        seats.sort((left, right) => Number(left.physicalSeatIndex) - Number(right.physicalSeatIndex));
        if (!seats.length) {
            const empty = document.createElement("div");
            empty.className = "gg-reader-seat-row gg-reader-seat-row--empty";
            empty.textContent = state.ggReader.running ? "waiting for seats" : "no snapshot";
            elements.ggReaderSeats.appendChild(empty);
            return;
        }
        const fragment = document.createDocumentFragment();
        seats.forEach((seat) => {
            const row = document.createElement("article");
            row.className = "gg-reader-seat-row";
            row.classList.toggle("is-empty", seat.active === false);
            row.classList.toggle("is-dealer", Boolean(seat.isDealer));

            const title = document.createElement("div");
            title.className = "gg-reader-seat-row__title";
            const seatIndex = Number(seat.physicalSeatIndex);
            title.textContent = `Seat ${Number.isInteger(seatIndex) ? seatIndex : "?"}`;
            if (seat.isDealer) {
                const dealer = document.createElement("span");
                dealer.className = "gg-reader-seat-row__dealer";
                dealer.textContent = "D";
                title.appendChild(dealer);
            }

            const status = document.createElement("div");
            status.className = "gg-reader-seat-row__status";
            status.textContent = seat.active === false ? "empty / Take Seat" : (seat.status || "occupied");

            const fields = document.createElement("div");
            fields.className = "gg-reader-seat-row__fields";
            appendGgSeatField(fields, "name", seat.active === false ? "Take Seat" : (seat.name || "unknown"), seat.nameConfidence);
            appendGgSeatField(fields, "stack", seat.active === false ? "-" : formatNullableBb(seat.stack), seat.stackConfidence);
            appendGgSeatField(fields, "bet", seat.active === false ? "-" : formatNullableBb(seat.currentBet), seat.betConfidence);
            appendGgSeatField(fields, "cards", formatGgSeatCards(seat), getGgSeatCardsConfidence(seat));
            appendGgSeatField(fields, "pos", seat.position || "-", seat.confidence);
            appendGgSeatField(fields, "conf", formatGgConfidence(seat.confidence), seat.confidence);

            row.append(title, status, fields);
            fragment.appendChild(row);
        });
        elements.ggReaderSeats.appendChild(fragment);
    }

    function appendGgInfoPill(parent, label, value) {
        const item = document.createElement("div");
        item.className = "gg-reader-info-pill";
        const labelEl = document.createElement("span");
        labelEl.className = "gg-reader-info-pill__label";
        labelEl.textContent = label;
        const valueEl = document.createElement("strong");
        valueEl.textContent = value;
        item.append(labelEl, valueEl);
        parent.appendChild(item);
    }

    function appendGgSeatField(parent, label, value, confidence) {
        const item = document.createElement("div");
        item.className = "gg-reader-seat-field";
        const labelEl = document.createElement("span");
        labelEl.textContent = label;
        const valueEl = document.createElement("strong");
        valueEl.textContent = value;
        const confidenceEl = document.createElement("em");
        confidenceEl.textContent = formatGgConfidence(confidence);
        item.append(labelEl, valueEl, confidenceEl);
        parent.appendChild(item);
    }

    function formatNullableBb(value) {
        const amount = Number(value);
        return Number.isFinite(amount) && amount > 0 ? `${formatChipAmount(amount)} BB` : "-";
    }

    function formatGgSeatCards(seat) {
        const cards = Array.isArray(seat?.holeCards) ? seat.holeCards : [];
        if (!cards.length) {
            return seat?.active === false ? "-" : "unknown";
        }
        return cards.map(formatGgCardSnapshot).join(" ");
    }

    function formatGgCardSnapshot(card) {
        if (!card) {
            return "-";
        }
        if (card.hidden || card.visible === false) {
            return card.display || "X";
        }
        const id = getGgCardId(card);
        return id || "unknown";
    }

    function getGgSeatCardsConfidence(seat) {
        const cards = Array.isArray(seat?.holeCards) ? seat.holeCards : [];
        if (!cards.length) {
            return 0;
        }
        const values = cards.map((card) => Number(card.confidence)).filter(Number.isFinite);
        return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0;
    }

    function formatGgConfidence(value) {
        const confidence = Number(value);
        return Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : "-";
    }

    function getGgMetric(snapshot, key) {
        if (!snapshot || !key) {
            return undefined;
        }
        if (Object.prototype.hasOwnProperty.call(snapshot, key)) {
            return snapshot[key];
        }
        if (snapshot.metrics && Object.prototype.hasOwnProperty.call(snapshot.metrics, key)) {
            return snapshot.metrics[key];
        }
        return undefined;
    }

    async function fetchGgReaderDebugArtifact(kind) {
        if (!elements.ggReaderDebugOutput) {
            return;
        }
        const endpoint = kind === "field-crops" ? "field-crops" : "roi-overlay";
        elements.ggReaderDebugOutput.textContent = "loading...";
        try {
            const response = await fetch(`${GG_READER_API_BASE}/api/gg-reader/debug/${endpoint}`, { cache: "no-store" });
            if (!response.ok) {
                throw new Error(`debug ${endpoint} failed: ${response.status}`);
            }
            const data = await response.json();
            if (endpoint === "field-crops") {
                elements.ggReaderDebugOutput.textContent = [
                    `field crops: ${data.path || "-"}`,
                    `profile: ${data.profile || "-"}`,
                    `fields: ${data.fieldCount ?? "-"}`,
                    `crop: ${data.croppedFramePath || "-"}`
                ].join("\n");
            } else {
                elements.ggReaderDebugOutput.textContent = [
                    `roi overlay: ${data.path || "-"}`,
                    `profile: ${data.profile || "-"}`,
                    `crop: ${data.croppedFramePath || "-"}`
                ].join("\n");
            }
        } catch (error) {
            elements.ggReaderDebugOutput.textContent = String(error && error.message ? error.message : error);
            state.ggReader.errors.push(elements.ggReaderDebugOutput.textContent);
            renderGgReaderStatus();
        }
    }

    function formatGgFps(value) {
        const fps = Number(value);
        return Number.isFinite(fps) && fps > 0 ? `${fps.toFixed(1)}fps` : "0.0fps";
    }

    function formatGgMs(value) {
        const ms = Number(value);
        return Number.isFinite(ms) && ms >= 0 ? `${Math.round(ms)}ms` : "-";
    }

    function formatGgBytes(value) {
        const bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes <= 0) {
            return "-";
        }
        if (bytes >= 1024 * 1024) {
            return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
        }
        return `${Math.round(bytes / 1024)}KB`;
    }

    function renderGgReaderHistory() {
        if (elements.ggReaderHistory) {
            elements.ggReaderHistory.hidden = !state.ggReader.isHistoryOpen;
            elements.ggReaderHistory.setAttribute("aria-hidden", state.ggReader.isHistoryOpen ? "false" : "true");
        }
        if (!elements.ggReaderHistoryList) {
            return;
        }
        elements.ggReaderHistoryList.innerHTML = "";
        state.ggReader.history.slice(0, 20).forEach((entry) => {
            const item = document.createElement("li");
            item.textContent = `${new Date(entry.time).toLocaleTimeString("he-IL")} · ${entry.message}`;
            elements.ggReaderHistoryList.appendChild(item);
        });
    }

    function downloadGgReaderHistory() {
        const blob = new Blob([JSON.stringify(state.ggReader.history, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "gg-reader-history.json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    function bindMenuNavigation() {
        if (!elements.appMenu) {
            return;
        }

        const buttons = Array.from(elements.appMenu.querySelectorAll('[data-menu-view]'));

        if (!buttons.length) {
            return;
        }

        elements.menuButtons = buttons;

        buttons.forEach((button) => {
            button.addEventListener('click', () => {
                const targetView = normalizeViewName(button.dataset.menuView);
                setActiveView(targetView);
            });
        });
    }

    function bindSettingsMenu() {
        if (!elements.settingsToggle || !elements.settingsMenu) {
            return;
        }

        const menu = elements.settingsMenu;
        const toggle = elements.settingsToggle;

        toggle.addEventListener('click', (event) => {
            event.stopPropagation();
            setSettingsMenuOpen(!state.isSettingsMenuOpen);
        });

        menu.addEventListener('click', (event) => {
            event.stopPropagation();
            const target = event.target;
            if (!target || !(target instanceof Element)) {
                return;
            }
            const actionTarget = target.closest('[data-setting-action]');
            if (!actionTarget) {
                return;
            }
            const action = actionTarget.dataset.settingAction;
            if (!action) {
                return;
            }
            const result = performSettingsMenuAction(action);
            if (result && result.handled) {
                if (result.shouldClose !== false) {
                    setSettingsMenuOpen(false);
                    if (elements.settingsToggle && typeof elements.settingsToggle.focus === 'function') {
                        elements.settingsToggle.focus();
                    }
                } else {
                    refreshSettingsMenu();
                }
            }
        });

        document.addEventListener('click', (event) => {
            if (!state.isSettingsMenuOpen) {
                return;
            }
            const target = event.target;
            if (!target || !(target instanceof Node)) {
                setSettingsMenuOpen(false);
                return;
            }
            if (target === toggle || menu.contains(target)) {
                return;
            }
            setSettingsMenuOpen(false);
        });

        document.addEventListener('keydown', (event) => {
            if (!state.isSettingsMenuOpen) {
                return;
            }
            if (event.key === 'Escape' || event.key === 'Esc') {
                setSettingsMenuOpen(false);
                if (typeof toggle.focus === 'function') {
                    toggle.focus();
                }
            }
        });

        setSettingsMenuOpen(false);
    }


    function setSettingsMenuOpen(open) {
        state.isSettingsMenuOpen = Boolean(open);

        if (!elements.settingsMenu || !elements.settingsToggle) {
            return;
        }

        const shouldOpen = state.isSettingsMenuOpen;
        elements.settingsMenu.classList.toggle('is-open', shouldOpen);
        elements.settingsMenu.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
        elements.settingsToggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    }

    function refreshSettingsMenu() {
        if (!elements.settingsMenu) {
            return;
        }

        const autoItem = elements.settingsMenu.querySelector('[data-setting-action="toggle-auto-advance"]');
        const autoIndicator = elements.settingsMenu.querySelector('[data-setting-indicator="auto-advance"]');
        if (autoIndicator) {
            const isActive = !state.isAutoAdvancePaused;
            autoIndicator.textContent = isActive ? "\u05e4\u05e2\u05d9\u05dc" : "\u05de\u05d5\u05e9\u05d4\u05d4";
            if (autoItem) {
                autoItem.setAttribute('aria-checked', isActive ? 'true' : 'false');
            }
        }

        const probabilitiesItem = elements.settingsMenu.querySelector('[data-setting-action="toggle-seat-probabilities"]');
        const probabilitiesIndicator = elements.settingsMenu.querySelector('[data-setting-indicator="seat-probabilities"]');
        if (probabilitiesIndicator) {
            const isVisible = state.showSeatProbabilities;
            probabilitiesIndicator.textContent = isVisible ? "\u05de\u05d5\u05e6\u05d2" : "\u05de\u05d5\u05e1\u05ea\u05e8";
            if (probabilitiesItem) {
                probabilitiesItem.setAttribute('aria-checked', isVisible ? 'true' : 'false');
            }
        }

        const countDisplay = elements.settingsPlayerCount;
        if (countDisplay) {
            countDisplay.textContent = String(state.playersCount);
        }
        const decrementBtn = elements.settingsMenu.querySelector('[data-setting-action="decrement-players"]');
        const incrementBtn = elements.settingsMenu.querySelector('[data-setting-action="increment-players"]');
        if (decrementBtn) {
            decrementBtn.disabled = state.playersCount <= MIN_PLAYERS;
        }
        if (incrementBtn) {
            incrementBtn.disabled = state.playersCount >= MAX_PLAYERS;
        }
    }


    function performSettingsMenuAction(action) {
        switch (action) {
            case 'toggle-auto-advance':
                toggleAutoAdvanceSetting();
                refreshSettingsMenu();
                return { handled: true, shouldClose: true };
            case 'toggle-seat-probabilities':
                setSeatProbabilitiesVisible(!state.showSeatProbabilities);
                refreshSettingsMenu();
                return { handled: true, shouldClose: true };
            case 'increment-players':
                setPlayersCount(state.playersCount + 1);
                refreshSettingsMenu();
                return { handled: true, shouldClose: false };
            case 'decrement-players':
                setPlayersCount(state.playersCount - 1);
                refreshSettingsMenu();
                return { handled: true, shouldClose: false };
            case 'deal-random':
                dealRandom();
                return { handled: true, shouldClose: true };
            case 'clear-all':
                clearAllSlots();
                return { handled: true, shouldClose: true };
            case 'read-gg-table':
                toggleGgTableReader();
                return { handled: true, shouldClose: true };
            case 'quick-reset':
                setPlayersCount(DEFAULT_PLAYERS);
                clearAllSlots();
                refreshSettingsMenu();
                return { handled: true, shouldClose: true };
            case 'live-game':
                document.dispatchEvent(new CustomEvent('app:settings-live-game'));
                return { handled: true, shouldClose: true };
            case 'reset-table':
                resetTableState();
                refreshSettingsMenu();
                return { handled: true, shouldClose: true };
            default:
                return { handled: false, shouldClose: true };
        }
    }


    function toggleAutoAdvanceSetting() {
        state.isAutoAdvancePaused = !state.isAutoAdvancePaused;
        if (!state.isAutoAdvancePaused) {
            ensureActiveSlot();
        }
    }

    function setSeatProbabilitiesVisible(visible) {
        state.showSeatProbabilities = Boolean(visible);
        if (elements.appShell) {
            elements.appShell.classList.toggle('settings--hide-seat-probabilities', !state.showSeatProbabilities);
        }
    }

    function resetTableState() {
        setPlayersCount(DEFAULT_PLAYERS);
        clearAllSlots();
        initializePlayerEconomy();
        state.isAutoAdvancePaused = false;
        setSeatProbabilitiesVisible(true);
        setDealerSeatIndex(0);
        ensureActiveSlot();
    }





    function openDeckOverlay(slot) {
        if (!elements.deckOverlay || !slot) {
            return;
        }

        const overlay = elements.deckOverlay;
        overlay.hidden = false;
        overlay.classList.add("is-open");
        positionDeckOverlay(slot);
        requestAnimationFrame(() => {
            if (!elements.deckOverlay || elements.deckOverlay.hidden || state.activeSlot !== slot) {
                return;
            }
            positionDeckOverlay(slot);
        });
    }

    function closeDeckOverlay() {
        if (!elements.deckOverlay) {
            return;
        }

        const overlay = elements.deckOverlay;
        overlay.classList.remove("is-open");
        overlay.removeAttribute("data-placement");
        overlay.style.removeProperty("--deck-overlay-anchor");
        overlay.style.left = "";
        overlay.style.top = "";
        overlay.hidden = true;
    }

    function positionDeckOverlay(slot) {
        if (!elements.deckOverlay || !slot || elements.deckOverlay.hidden) {
            return;
        }

        const overlay = elements.deckOverlay;
        const rect = slot.getBoundingClientRect();
        const overlayRect = overlay.getBoundingClientRect();
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
        const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
        const padding = 16;

        if (viewportWidth <= 720) {
            overlay.dataset.placement = "mobile";
            overlay.style.removeProperty("--deck-overlay-anchor");
            overlay.style.left = "";
            overlay.style.top = "";
            return;
        }

        const overlayWidth = overlayRect.width || overlay.scrollWidth || 0;
        const overlayHeight = overlayRect.height || overlay.scrollHeight || 0;

        let left = window.scrollX + rect.left + (rect.width / 2) - overlayWidth / 2;
        const minLeft = window.scrollX + padding;
        const maxLeft = window.scrollX + viewportWidth - overlayWidth - padding;
        if (minLeft <= maxLeft) {
            if (left < minLeft) {
                left = minLeft;
            } else if (left > maxLeft) {
                left = maxLeft;
            }
        } else {
            left = window.scrollX + Math.max(rect.left, padding);
        }

        const anchorCenter = window.scrollX + rect.left + (rect.width / 2);
        const rawAnchor = anchorCenter - left;
        const constrainedAnchor = Math.max(24, Math.min(rawAnchor, overlayWidth - 24));
        overlay.style.setProperty("--deck-overlay-anchor", `${constrainedAnchor}px`);

        let top = window.scrollY + rect.bottom + 12;
        let placement = "below";
        const viewportBottom = window.scrollY + viewportHeight - padding;
        if (top + overlayHeight > viewportBottom && rect.top > overlayHeight + padding) {
            top = window.scrollY + rect.top - overlayHeight - 12;
            placement = "above";
        }

        overlay.dataset.placement = placement;
        overlay.style.left = `${left}px`;
        overlay.style.top = `${top}px`;
    }

    function bindDeckOverlay() {
        if (!elements.deckOverlay) {
            return;
        }

        if (elements.deckOverlayClose) {
            elements.deckOverlayClose.addEventListener("click", () => {
                setActiveSlot(null);
            });
        }

        const handleViewportChange = () => {
            if (!state.activeSlot || elements.deckOverlay.hidden) {
                return;
            }
            positionDeckOverlay(state.activeSlot);
        };

        window.addEventListener("resize", handleViewportChange, { passive: true });
        window.addEventListener("scroll", handleViewportChange, { passive: true });

        document.addEventListener("click", (event) => {
            if (!state.activeSlot || elements.deckOverlay.hidden) {
                return;
            }
            const target = event.target;
            if (!target || !(target instanceof Node)) {
                return;
            }
            if (state.activeSlot.contains(target) || elements.deckOverlay.contains(target)) {
                return;
            }
            setActiveSlot(null);
        });
    }





    // Live game controls and state management
    function bindLiveGameControls() {
        if (!elements.liveGamePanel) {
            return;
        }
        const {
            liveGameExit,
            liveActionFold,
            liveActionCheck,
            liveActionRaise,
            liveActionRaiseOptions,
            liveActionNext
        } = elements;

        if (liveGameExit) {
            liveGameExit.addEventListener("click", finishLiveGameSession);
        }
        if (liveActionFold) {
            liveActionFold.addEventListener("click", () => handleLiveHeroAction("fold"));
        }
        if (liveActionCheck) {
            liveActionCheck.addEventListener("click", () => handleLiveHeroAction("check"));
        }
        if (liveActionRaise) {
            liveActionRaise.addEventListener("click", () => handleLiveHeroAction("raise"));
        }
        if (liveActionRaiseOptions) {
            liveActionRaiseOptions.addEventListener("click", handleLiveRaiseOptionsClick);
        }
        if (liveActionNext) {
            liveActionNext.addEventListener("click", () => {
                if (!state.liveGame) {
                    return;
                }
                if (state.liveGame.handActive) {
                    return;
                }
                updateLiveGameStatus("פותחים יד חדשה...");
                startLiveGameHand();
            });
        }
        disableLiveActionButtons(true);
    }

    function handleLiveRaiseOptionsClick(event) {
        const live = state.liveGame;
        if (!live || !live.handActive) {
            return;
        }
        const target = event.target;
        if (!target || !(target instanceof HTMLElement)) {
            return;
        }
        const button = target.closest('button[data-raise-value]');
        if (!button || button.disabled) {
            return;
        }
        const value = Number.parseFloat(button.dataset.raiseValue || '');
        if (!Number.isFinite(value) || value <= 0) {
            return;
        }
        live.raiseSelection = String(value);
        refreshLiveRaiseOptionSelection();
        updateLiveRaiseButtonState();
    }

    function refreshLiveRaiseOptionSelection() {
        const live = state.liveGame;
        const container = elements.liveActionRaiseOptions;
        if (!live || !container) {
            return;
        }
        const selected = live.raiseSelection ? Number.parseFloat(live.raiseSelection) : NaN;
        container.querySelectorAll('button[data-raise-value]').forEach((button) => {
            const amount = Number.parseFloat(button.dataset.raiseValue || '');
            if (Number.isFinite(selected) && Number.isFinite(amount) && Math.abs(amount - selected) < 1e-6) {
                button.classList.add('is-selected');
            } else {
                button.classList.remove('is-selected');
            }
        });
    }

    function setLiveRaiseOptionsDisabled(disabled) {
        const container = elements.liveActionRaiseOptions;
        if (!container) {
            return;
        }
        container.querySelectorAll('button[data-raise-value]').forEach((button) => {
            button.disabled = disabled;
        });
        if (disabled) {
            container.setAttribute('aria-disabled', 'true');
        } else {
            container.removeAttribute('aria-disabled');
        }
    }

    function handleLiveGameStartRequest() {
        if (isOmahaVariant()) {
            showError("\u05de\u05e9\u05d7\u05e7 \u05d7\u05d9 \u05e0\u05ea\u05de\u05da \u05db\u05e8\u05d2\u05e2 \u05d1\u05d8\u05e7\u05e1\u05e1 \u05d4\u05d5\u05dc\u05d3\u05dd \u05d1\u05dc\u05d1\u05d3.");
            return;
        }
        if (state.liveGame && state.liveGame.active) {
            updateLiveGameStatus("מתחיל יד חדשה...");
            startLiveGameHand();
            return;
        }
        startLiveGameSession();
    }

    function startLiveGameSession() {
        cancelScheduledProbabilityUpdate();
        const live = state.liveGame || createInitialLiveGameState();
        state.liveGame = live;
        if (!live.players || live.players.length < 2) {
            live.players = [
                { index: 0, name: "Hero", stack: DEFAULT_PLAYER_STACK, bet: 0, cards: [], revealed: true },
                { index: 1, name: "Solver", stack: DEFAULT_PLAYER_STACK, bet: 0, cards: [], revealed: false }
            ];
        } else {
            live.players.forEach((player) => {
                player.bet = 0;
            });
        }
        live.active = true;
        live.handActive = false;
        live.stage = "idle";
        live.awaitingHero = false;
        live.log = [];
        live.villainProfile = state.solverSettings.opponentProfile;
        live.lastAnalysis = null;
        state.deferProbabilityUpdate = true;
        state.isAutoAdvancePaused = true;
        if (state.playersCount !== MIN_PLAYERS) {
            setPlayersCount(MIN_PLAYERS);
            refreshSettingsMenu();
        }
        showLiveGamePanel(true);
        clearLiveGameLog();
        updateLiveGameStatus("מתכוננים ליד חדשה...");
        showLiveNextButton(false);
        startLiveGameHand();
    }

    function startLiveGameHand() {
        const live = state.liveGame;
        if (!live || !elements.liveGamePanel) {
            return;
        }

        live.handActive = true;
        live.stage = "preflop";
        live.awaitingHero = false;
        live.boardCards = [];
        live.boardIndex = 0;
        live.pot = 0;
        live.currentBet = 0;
        live.log = [];
        live.lastAnalysis = null;

        const hero = live.players[0];
        const villain = live.players[1];

        hero.bet = 0;
        villain.bet = 0;

        showLiveNextButton(false);

        const playerSlots = getSlotsByType("player");
        playerSlots.forEach((slot) => {
            clearSlot(slot, { suppressUpdate: true });
        });
        getSlotsByType("board").forEach((slot) => {
            clearSlot(slot, { suppressUpdate: true });
        });

        live.deck = state.deck.slice();
        shuffle(live.deck);

        const heroSlots = [
            state.slotByKey.get("player-0-0"),
            state.slotByKey.get("player-0-1")
        ].filter(Boolean);
        const villainSlots = [
            state.slotByKey.get("player-1-0"),
            state.slotByKey.get("player-1-1")
        ].filter(Boolean);

        const heroCards = [live.deck.shift(), live.deck.shift()].filter(Boolean);
        const villainCards = [live.deck.shift(), live.deck.shift()].filter(Boolean);

        if (heroSlots[0] && heroCards[0]) {
            assignCardToSlot(heroCards[0], heroSlots[0], { lock: true, suppressUpdate: true });
        }
        if (heroSlots[1] && heroCards[1]) {
            assignCardToSlot(heroCards[1], heroSlots[1], { lock: true, suppressUpdate: true });
        }
        if (villainSlots[0] && villainCards[0]) {
            assignCardToSlot(villainCards[0], villainSlots[0], { lock: true, suppressUpdate: true, hidden: true });
        }
        if (villainSlots[1] && villainCards[1]) {
            assignCardToSlot(villainCards[1], villainSlots[1], { lock: true, suppressUpdate: true, hidden: true });
        }

        hero.cards = heroCards;
        villain.cards = villainCards;

        updateLivePotDisplay();
        clearLiveGameLog();
        appendLiveGameLog("היד נפתחה מול הסולבר.");
        updateLiveCheckButtonLabel(false);
        disableLiveActionButtons(false);
        setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });

        const analysis = analyzeLiveGameContext();
        applyLiveAnalysisFeedback(analysis);
        live.awaitingHero = true;
    }

    function updateLivePotDisplay() {
        if (!elements.tablePot) {
            return;
        }
        const live = state.liveGame;
        const amount = live ? live.pot : 0;
        elements.tablePot.textContent = `${TABLE_POT_LABEL}: ${formatChipAmount(amount)}`;
        updateLiveRaiseOptions();
    }

    function updateLiveRaiseOptions() {
        const container = elements.liveActionRaiseOptions;
        if (!container) {
            return;
        }
        const optionsDisabled = container.getAttribute("aria-disabled") === "true";
        container.innerHTML = '';
        container.hidden = true;
        container.setAttribute("aria-hidden", "true");
        const live = state.liveGame;
        if (!live || !live.handActive) {
            if (live) {
                live.raiseSelection = null;
            }
            updateLiveRaiseButtonState();
            return;
        }
        const options = buildLiveRaiseOptionData(live);
        if (!options.length) {
            live.raiseSelection = null;
            updateLiveRaiseButtonState();
            return;
        }
        const previous = live.raiseSelection ? Number.parseFloat(live.raiseSelection) : NaN;
        let applied = false;
        options.forEach((option) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'live-game__raise-option';
            button.dataset.raiseValue = String(option.amount);
            button.textContent = option.label;
            container.appendChild(button);
            if (!applied && Number.isFinite(previous) && Math.abs(previous - option.amount) < 1e-6) {
                applied = true;
            }
        });
        if (applied && Number.isFinite(previous)) {
            live.raiseSelection = String(previous);
        } else {
            live.raiseSelection = String(options[0].amount);
        }
        container.hidden = false;
        setLiveRaiseOptionsDisabled(optionsDisabled);
        container.setAttribute("aria-hidden", "false");
        refreshLiveRaiseOptionSelection();
        updateLiveRaiseButtonState();
    }

    function buildLiveRaiseOptionData(live) {
        const hero = live.players[0];
        const villain = live.players[1];
        if (!hero || hero.stack <= 0) {
            return [];
        }
        const options = [];
        const seen = new Set();
        const totalPot = live.pot + (villain && villain.bet ? villain.bet : 0) + (hero.bet || 0);
        const baseline = totalPot > 0 ? totalPot : DEFAULT_BIG_BLIND * 2;
        const effectiveStack = villain ? Math.max(0, Math.min(hero.stack, villain.stack)) : hero.stack;
        LIVE_RAISE_PRESETS.forEach((preset) => {
            let amount;
            if (preset.type === 'all-in') {
                amount = hero.stack;
            } else {
                amount = baseline * preset.factor;
            }
            if (live.currentBet > 0) {
                const minRaise = Math.max(live.currentBet * 2, live.currentBet + DEFAULT_SMALL_BLIND);
                amount = Math.max(amount, minRaise);
            } else {
                amount = Math.max(amount, DEFAULT_BIG_BLIND);
            }
            if (effectiveStack > 0) {
                amount = Math.min(amount, effectiveStack);
            }
            amount = Math.min(amount, hero.stack);
            amount = Math.round(amount * 100) / 100;
            if (amount <= 0) {
                return;
            }
            const key = amount.toFixed(2);
            if (seen.has(key)) {
                return;
            }
            seen.add(key);
            const label = `${preset.descriptor} - ${formatChipAmount(amount)} BB`;
            options.push({ value: key, amount, label });
        });
        options.sort((a, b) => a.amount - b.amount);
        return options;
    }
    function showLiveGamePanel(visible) {
        if (!elements.liveGamePanel) {
            return;
        }
        elements.liveGamePanel.hidden = !visible;
        elements.liveGamePanel.setAttribute("aria-hidden", visible ? "false" : "true");
    }

    function updateLiveGameStatus(message) {
        if (!elements.liveGameStatus) {
            return;
        }
        elements.liveGameStatus.textContent = message || "";
    }

    function clearLiveGameLog() {
        if (!elements.liveGameLog) {
            return;
        }
        elements.liveGameLog.innerHTML = "";
    }

    function appendLiveGameLog(message) {
        if (!elements.liveGameLog) {
            return;
        }
        const log = elements.liveGameLog;
        const entry = document.createElement("div");
        entry.className = "live-game__log-entry";
        const textSpan = document.createElement("span");
        textSpan.textContent = message;
        const timeStamp = document.createElement("time");
        const now = new Date();
        timeStamp.dateTime = now.toISOString();
        timeStamp.textContent = now.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        entry.append(textSpan, timeStamp);
        log.appendChild(entry);
        while (log.childElementCount > 40) {
            log.removeChild(log.firstChild);
        }
        log.scrollTop = log.scrollHeight;
    }

    function disableLiveActionButtons(disabled) {
        const buttons = [
            elements.liveActionFold,
            elements.liveActionCheck,
            elements.liveActionRaise
        ];
        buttons.forEach((button) => {
            if (button) {
                button.disabled = disabled;
            }
        });
        setLiveRaiseOptionsDisabled(disabled);
        if (!disabled) {
            updateLiveRaiseButtonState();
        }
    }

    function setLiveActionAvailability(options = {}) {
        const { allowFold = true, allowCheck = true, allowBets = true } = options;
        if (elements.liveActionFold) {
            elements.liveActionFold.disabled = !allowFold;
        }
        if (elements.liveActionCheck) {
            elements.liveActionCheck.disabled = !allowCheck;
        }
        setLiveRaiseOptionsDisabled(!allowBets);
        updateLiveRaiseButtonState({ allowRaise: allowBets });
    }


    function updateLiveRaiseButtonState(options = {}) {
        const { allowRaise } = options;
        const raiseButton = elements.liveActionRaise;
        if (!raiseButton) {
            return;
        }
        if (typeof allowRaise === "boolean" && !allowRaise) {
            raiseButton.disabled = true;
            return;
        }
        raiseButton.disabled = !hasValidRaiseSelection();
    }

    function hasValidRaiseSelection() {
        const live = state.liveGame;
        if (!live || !live.handActive) {
            return false;
        }
        const selection = live.raiseSelection ? Number.parseFloat(live.raiseSelection) : NaN;
        if (!Number.isFinite(selection) || selection <= 0) {
            return false;
        }
        const hero = live.players && live.players[0];
        if (!hero || hero.stack <= 0) {
            return false;
        }
        return true;
    }
    function updateLiveCheckButtonLabel(facingBet, amount = 0) {
        if (!elements.liveActionCheck) {
            return;
        }
        if (facingBet) {
            elements.liveActionCheck.textContent = `קול ${formatChipAmount(amount)} BB`;
        } else {
            elements.liveActionCheck.textContent = "צ'ק / קול";
        }
    }

    function showLiveNextButton(visible, label = "יד חדשה") {
        if (!elements.liveActionNext) {
            return;
        }
        elements.liveActionNext.hidden = !visible;
        elements.liveActionNext.setAttribute("aria-hidden", visible ? "false" : "true");
        elements.liveActionNext.textContent = label;
    }

    function getLiveBetAmount(factor) {
        const live = state.liveGame;
        if (!live) {
            return DEFAULT_BIG_BLIND;
        }
        const hero = live.players[0];
        const villain = live.players[1];
        const effective = Math.max(0, Math.min(hero.stack, villain.stack));
        const baseline = live.pot > 0 ? live.pot : DEFAULT_BIG_BLIND * 2;
        const raw = Math.min(effective || baseline, baseline * factor);
        const normalized = Math.max(DEFAULT_SMALL_BLIND, raw);
        return Math.round(normalized * 100) / 100;
    }

    function analyzeLiveGameContext() {
        const live = state.liveGame;
        if (!live) {
            return null;
        }
        const hero = live.players[0];
        const board = live.boardCards.slice();
        const available = buildAvailableVillainCards(hero.cards, board);
        const analysis = getSolverAnalysis({
            heroCards: hero.cards,
            boardCards: board,
            availableVillainCards: available,
            settings: state.solverSettings,
            includeIntegrations: false
        });
        if (analysis && analysis.ok) {
            live.lastAnalysis = analysis;
        }
        return analysis;
    }

    function applyLiveAnalysisFeedback(analysis) {
        if (!analysis || !analysis.ok) {
            updateLiveGameStatus("אין המלצה זמינה כרגע. שחקו לפי האינסטינקט.");
            return;
        }
        const data = analysis.data;
        const heroCardsText = formatCardList(data.heroCards);
        const boardText = data.boardCards && data.boardCards.length ? formatCardList(data.boardCards) : "";
        const equityText = formatSolverPercent(data.heroEquity);
        const recommendation = data.recommendation ? data.recommendation.label : "אין המלצה זמינה";
        const statusParts = [];
        statusParts.push(`הקלפים שלך: ${heroCardsText}`);
        if (boardText) {
            statusParts.push(`לוח: ${boardText}`);
        }
        statusParts.push(`Equity משוער: ${equityText}`);
        statusParts.push(`המלצת הסולבר: ${recommendation}`);
        updateLiveGameStatus(statusParts.join(" | "));
    }

    function buildAvailableVillainCards(heroCards, boardCards) {
        const excluded = new Set();
        (heroCards || []).forEach((card) => excluded.add(card.id));
        (boardCards || []).forEach((card) => excluded.add(card.id));
        const available = [];
        state.deck.forEach((card) => {
            if (!excluded.has(card.id)) {
                available.push(card);
            }
        });
        return available;
    }

    function dealLiveBoardCards(count) {
        const live = state.liveGame;
        if (!live) {
            return;
        }
        const boardSlots = getSlotsByType("board");
        for (let i = 0; i < count; i += 1) {
            const slot = boardSlots[live.boardIndex + i];
            const card = live.deck.shift();
            if (!slot || !card) {
                continue;
            }
            live.boardCards.push(card);
            assignCardToSlot(card, slot, { lock: true, suppressUpdate: true });
        }
        live.boardIndex += count;
    }

    function advanceLiveGameStage() {
        const live = state.liveGame;
        if (!live || !live.handActive) {
            return;
        }
        live.awaitingHero = false;
        switch (live.stage) {
            case "preflop":
                dealLiveBoardCards(3);
                live.stage = "flop";
                appendLiveGameLog(`הפלופ: ${formatCardList(live.boardCards.slice(0, 3))}.`);
                break;
            case "flop":
                dealLiveBoardCards(1);
                live.stage = "turn";
                appendLiveGameLog(`הטרן: ${formatCardList(live.boardCards.slice(0, 4))}.`);
                break;
            case "turn":
                dealLiveBoardCards(1);
                live.stage = "river";
                appendLiveGameLog(`הריבר: ${formatCardList(live.boardCards)}.`);
                break;
            case "river":
                resolveLiveShowdown();
                return;
            default:
                return;
        }
        const analysis = analyzeLiveGameContext();
        applyLiveAnalysisFeedback(analysis);
        updateLiveCheckButtonLabel(false);
        disableLiveActionButtons(false);
        setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });
        live.awaitingHero = true;
    }

    function handleLiveHeroAction(action) {
        const live = state.liveGame;
        if (!live || !live.handActive || !live.awaitingHero) {
            return;
        }
        switch (action) {
            case "fold":
                disableLiveActionButtons(true);
                processLiveHeroFold();
                return;
            case "check":
                disableLiveActionButtons(true);
                if (live.currentBet > 0) {
                    handleLiveHeroCall();
                } else {
                    processLiveHeroCheck();
                }
                return;
            case "raise": {
                const amount = getSelectedRaiseAmount();
                if (!amount) {
                    disableLiveActionButtons(false);
                    updateLiveRaiseButtonState();
                    return;
                }
                if (state.liveGame) {
                }
                disableLiveActionButtons(true);
                processLiveHeroBet(amount);
                return;
            }
            default:
                return;
        }
    }

    function getSelectedRaiseAmount() {
        const live = state.liveGame;
        if (!live || !live.raiseSelection) {
            return 0;
        }
        const amount = Number.parseFloat(live.raiseSelection);
        if (!Number.isFinite(amount) || amount <= 0) {
            return 0;
        }
        const hero = live.players && live.players[0];
        if (!hero) {
            return amount;
        }
        const heroStack = Math.max(0, hero.stack);
        return heroStack > 0 ? Math.min(amount, heroStack) : 0;
    }
    function processLiveHeroFold() {
        appendLiveGameLog("אתה מקפל את היד.");
        endLiveGameHand({
            winnerIndex: 1,
            message: "קיפלת את היד והסולבר זכה בקופה."
        });
    }

    function processLiveHeroCheck() {
        const live = state.liveGame;
        appendLiveGameLog("אתה בוחר בצ'ק.");
        const villainBet = villainActAfterCheck();
        if (!villainBet) {
            disableLiveActionButtons(false);
            setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });
            updateLiveCheckButtonLabel(false);
            live.awaitingHero = true;
            advanceLiveGameStage();
        }
    }

    function processLiveHeroBet(amount) {
        const live = state.liveGame;
        if (!live) {
            return;
        }
        const hero = live.players[0];
        const villain = live.players[1];
        if (!hero || hero.stack <= 0) {
            disableLiveActionButtons(false);
            updateLiveRaiseButtonState();
            return;
        }
        const normalized = Math.max(DEFAULT_SMALL_BLIND, Math.round(amount * 100) / 100);
        const heroContribution = Math.min(hero.stack, normalized);
        if (heroContribution <= 0) {
            disableLiveActionButtons(false);
            updateLiveRaiseButtonState();
            return;
        }
        hero.stack -= heroContribution;
        hero.bet = (hero.bet || 0) + heroContribution;
        live.pot += heroContribution;
        live.currentBet = Math.max(live.currentBet || 0, hero.bet);
        updateLivePotDisplay();
        updateLiveRaiseOptions();
        appendLiveGameLog(`\u05d4\u05d2\u05d9\u05d1\u05d5\u05e8 \u05de\u05e2\u05dc\u05d4 \u05dc${formatChipAmount(live.currentBet)} BB.`);

        const analysis = analyzeLiveGameContext();
        const callFrequency = analysis && analysis.ok ? clampProbability(analysis.data.callFrequency || 0.5) : 0.5;
        const villainCalls = Math.random() < callFrequency;
        if (!villainCalls || !villain || villain.stack <= 0) {
            appendLiveGameLog("\u05d4\u05d9\u05e8\u05d9\u05d1 \u05de\u05e7\u05e4\u05dc.");
            endLiveGameHand({
                winnerIndex: 0,
                message: "\u05d4\u05d9\u05e8\u05d9\u05d1 \u05de\u05e7\u05e4\u05dc \u05d5\u05d4\u05d2\u05d9\u05d1\u05d5\u05e8 \u05d6\u05db\u05d4 \u05d0\u05ea \u05d4\u05e7\u05d5\u05e4\u05d4."
            });
            return;
        }

        const previousVillainBet = villain.bet || 0;
        const toCall = Math.max(0, live.currentBet - previousVillainBet);
        const villainContribution = Math.min(villain.stack, toCall);
        villain.stack -= villainContribution;
        villain.bet = previousVillainBet + villainContribution;
        live.pot += villainContribution;
        updateLivePotDisplay();
        appendLiveGameLog(`\u05d4\u05d9\u05e8\u05d9\u05d1 \u05de\u05e9\u05d5\u05d5\u05d4 ${formatChipAmount(villainContribution)} BB.`);

        hero.bet = 0;
        villain.bet = 0;
        live.currentBet = 0;
        updateLiveRaiseOptions();
        advanceLiveGameStage();
    }
    function villainActAfterCheck() {
        const live = state.liveGame;
        const villain = live.players[1];
        const analysis = analyzeLiveGameContext();
        let betChance = 0.35;
        if (analysis && analysis.ok) {
            const meta = analysis.meta || {};
            if (meta.solverOutput && typeof meta.solverOutput.villainBetAfterCheckFrequency === "number") {
                betChance = clampProbability(meta.solverOutput.villainBetAfterCheckFrequency);
            } else {
                const heroBetFrequency = clampProbability(analysis.data.heroBetFrequency || 0.5);
                betChance = Math.max(0.15, Math.min(0.85, 1 - heroBetFrequency));
            }
        }
        if (villain.stack <= 0) {
            betChance = 0;
        }
        const willBet = Math.random() < betChance;
        if (!willBet) {
            appendLiveGameLog("הסולבר בוחר בצ'ק.");
            disableLiveActionButtons(false);
            setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });
            updateLiveCheckButtonLabel(false);
            return false;
        }
        const betAmount = Math.min(villain.stack, getLiveBetAmount(0.75));
        if (betAmount <= 0) {
            appendLiveGameLog("הסולבר בוחר בצ'ק.");
            disableLiveActionButtons(false);
            setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });
            updateLiveCheckButtonLabel(false);
            return false;
        }
        villain.stack -= betAmount;
        villain.bet = betAmount;
        live.pot += betAmount;
        live.currentBet = betAmount;
        updateLivePotDisplay();
        appendLiveGameLog(`הסולבר מהמר ${formatChipAmount(betAmount)} BB.`);
        disableLiveActionButtons(false);
        setLiveActionAvailability({ allowFold: true, allowCheck: true, allowBets: true });
        updateLiveCheckButtonLabel(true, betAmount);
        live.awaitingHero = true;
        return true;
    }

    function handleLiveHeroCall() {
        const live = state.liveGame;
        if (!live) {
            return;
        }
        const hero = live.players[0];
        const villain = live.players[1];
        const callAmount = Math.min(hero.stack, live.currentBet);
        hero.stack -= callAmount;
        hero.bet = callAmount;
        live.pot += callAmount;
        updateLivePotDisplay();
        appendLiveGameLog(`אתה משלם ${formatChipAmount(callAmount)} BB.`);
        hero.bet = 0;
        villain.bet = 0;
        live.currentBet = 0;
        advanceLiveGameStage();
    }

    function resolveLiveShowdown() {
        const live = state.liveGame;
        const hero = live.players[0];
        const villain = live.players[1];
        const board = live.boardCards.slice();
        const heroEval = bestHandForPlayer(hero.cards, board);
        const villainEval = bestHandForPlayer(villain.cards, board);
        revealLivePlayerCards(villain);
        let message;
        let split = false;
        let winnerIndex = 0;
        if (heroEval && villainEval) {
            const cmp = compareScores(heroEval.score, villainEval.score);
            if (cmp > 0) {
                message = `ניצחת עם ${describeHand(heroEval)}.`;
                appendLiveGameLog(`הסולבר מציג ${describeHand(villainEval)}.`);
                winnerIndex = 0;
            } else if (cmp < 0) {
                message = `הסולבר ניצח עם ${describeHand(villainEval)}.`;
                appendLiveGameLog(`אתה מציג ${describeHand(heroEval)}.`);
                winnerIndex = 1;
            } else {
                message = "היד הסתיימה בתיקו והקופה חולקה.";
                appendLiveGameLog(`שני הצדדים: ${describeHand(heroEval)}.`);
                split = true;
            }
        } else {
            message = "היד הסתיימה.";
            winnerIndex = 0;
        }
        endLiveGameHand({
            winnerIndex,
            message,
            revealVillain: true,
            split
        });
    }

    function revealLivePlayerCards(player) {
        if (!player || !Array.isArray(player.cards)) {
            return;
        }
        const firstSlot = state.slotByKey.get(`player-${player.index}-0`);
        const secondSlot = state.slotByKey.get(`player-${player.index}-1`);
        if (firstSlot && player.cards[0]) {
            assignCardToSlot(player.cards[0], firstSlot, { lock: true, suppressUpdate: true, hidden: false });
        }
        if (secondSlot && player.cards[1]) {
            assignCardToSlot(player.cards[1], secondSlot, { lock: true, suppressUpdate: true, hidden: false });
        }
    }

    function endLiveGameHand(options = {}) {
        const live = state.liveGame;
        if (!live) {
            return;
        }
        const {
            winnerIndex = 0,
            message = "",
            revealVillain = false,
            split = false
        } = options;
        const hero = live.players[0];
        const villain = live.players[1];
        if (revealVillain) {
            revealLivePlayerCards(villain);
        }
        if (split) {
            const half = Math.round((live.pot / 2) * 100) / 100;
            hero.stack += half;
            villain.stack += live.pot - half;
        } else if (winnerIndex === 1) {
            villain.stack += live.pot;
        } else {
            hero.stack += live.pot;
        }
        live.pot = 0;
        updateLivePotDisplay();
        if (message) {
            appendLiveGameLog(message);
            updateLiveGameStatus(message);
        }
        disableLiveActionButtons(true);
        showLiveNextButton(true, "יד חדשה");
        live.handActive = false;
        live.awaitingHero = false;
    }

    function finishLiveGameSession() {
        const live = state.liveGame;
        if (live) {
            live.active = false;
            live.handActive = false;
        }
        showLiveGamePanel(false);
        showLiveNextButton(false);
        disableLiveActionButtons(true);
        updateLiveGameStatus("");
        clearLiveGameLog();
        clearAllSlots({ keepResults: false });
        state.liveGame = createInitialLiveGameState();
        state.deferProbabilityUpdate = false;
        state.isAutoAdvancePaused = false;
        scheduleImmediateProbabilityUpdate();
        updateTablePotDisplay();
        refreshSettingsMenu();
        showError("");
    }

    function normalizeViewName() {
        return "equity";
    }

    function setActiveView(nextView = "equity") {
        const normalized = normalizeViewName(nextView);
        if (normalized === "solver") {
            setMode("solver");
            return;
        }
        if (state.mode !== "equity") {
            setMode("equity");
            return;
        }
        if (state.activeView !== "equity") {
            state.activeView = "equity";
        }
        updateActiveView();
    }

    function updateActiveView() {
        if (Array.isArray(elements.menuButtons)) {
            elements.menuButtons.forEach((button) => {
                const isActive = normalizeViewName(button.dataset.menuView) === "equity";
                button.classList.toggle("is-active", isActive);
                button.setAttribute("aria-pressed", isActive ? "true" : "false");
            });
        }

        if (elements.calculatorView) {
            elements.calculatorView.hidden = false;
            elements.calculatorView.setAttribute("aria-hidden", "false");
        }

        if (elements.statisticsView) {
            elements.statisticsView.hidden = true;
            elements.statisticsView.setAttribute("aria-hidden", "true");
        }
    }
    function bindSolverControls() {
        if (!elements.solverControls) {
            return;
        }

        const attachNumberHandler = (input, key, options = {}) => {
            if (!input) {
                return;
            }
            const { min = -Infinity, max = Infinity, step = 1 } = options;
            input.addEventListener("change", () => {
                const raw = Number.parseFloat(input.value);
                if (!Number.isFinite(raw)) {
                    input.value = state.solverSettings[key];
                    return;
                }
                let clamped = Math.max(min, Math.min(max, raw));
                if (key === "iterations") {
                    clamped = Math.round(clamped / step) * step;
                }
                input.value = clamped;
                updateSolverSetting(key, clamped);
            });
        };

        attachNumberHandler(elements.solverPotSize, "potSize", { min: 0, max: 10000, step: 0.5 });
        attachNumberHandler(elements.solverEffectiveStack, "effectiveStack", { min: 0, max: 10000, step: 0.5 });
        attachNumberHandler(elements.solverBetSize, "betSizePercent", { min: 1, max: 400, step: 1 });
        attachNumberHandler(elements.solverIterations, "iterations", { min: 1000, max: 200000, step: 1000 });

        if (elements.solverOpponentProfile) {
            elements.solverOpponentProfile.addEventListener("change", () => {
                updateSolverSetting("opponentProfile", elements.solverOpponentProfile.value);
            });
        }

        elements.solverRun?.addEventListener("click", () => {
            scheduleSolverUpdate({ immediate: true });
        });

        elements.solverReset?.addEventListener("click", () => {
            resetSolverSettings();
        });
    }

    function bindSolverPanelToggle() {
        if (!elements.solverSettingsToggle || !elements.solverControls) {
            return;
        }

        elements.solverSettingsToggle.addEventListener("click", () => {
            setSolverPanelOpen(!state.isSolverPanelOpen);
        });

        document.addEventListener("click", (event) => {
            if (!state.isSolverPanelOpen || state.mode !== "solver") {
                return;
            }
            const floatingToggleVisible = !elements.solverSettingsToggle.hidden
                && window.getComputedStyle(elements.solverSettingsToggle).display !== "none"
                && window.getComputedStyle(elements.solverSettingsToggle).visibility !== "hidden";
            if (!floatingToggleVisible) {
                return;
            }
            const target = event.target;
            if (!target || !(target instanceof Node)) {
                return;
            }
            if (elements.solverControls.contains(target) || elements.solverSettingsToggle.contains(target)) {
                return;
            }
            setSolverPanelOpen(false);
        });

        document.addEventListener("keydown", (event) => {
            if (!state.isSolverPanelOpen || state.mode !== "solver") {
                return;
            }
            const floatingToggleVisible = !elements.solverSettingsToggle.hidden
                && window.getComputedStyle(elements.solverSettingsToggle).display !== "none"
                && window.getComputedStyle(elements.solverSettingsToggle).visibility !== "hidden";
            if (!floatingToggleVisible) {
                return;
            }
            if (event.key === "Escape" || event.key === "Esc") {
                setSolverPanelOpen(false);
                if (typeof elements.solverSettingsToggle.focus === "function") {
                    elements.solverSettingsToggle.focus();
                }
            }
        });
    }

    function setSolverPanelOpen(open) {
        if (!elements.solverControls || !elements.solverSettingsToggle) {
            state.isSolverPanelOpen = false;
            return;
        }

        const shouldOpen = Boolean(open) && state.mode === "solver" && !elements.solverControls.hidden;
        state.isSolverPanelOpen = shouldOpen;

        elements.solverControls.classList.toggle("is-open", shouldOpen);
        elements.solverControls.setAttribute("aria-hidden", shouldOpen ? "false" : "true");

        if (typeof elements.solverControls.toggleAttribute === "function") {
            elements.solverControls.toggleAttribute("inert", !shouldOpen);
        } else if (!shouldOpen) {
            elements.solverControls.setAttribute("inert", "");
        } else {
            elements.solverControls.removeAttribute("inert");
        }

        elements.solverSettingsToggle.classList.toggle("is-active", shouldOpen);
        elements.solverSettingsToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");

        if (shouldOpen) {
            const focusTarget = elements.solverControls.querySelector("input, select");
            if (focusTarget && typeof focusTarget.focus === "function") {
                setTimeout(() => {
                    focusTarget.focus({ preventScroll: true });
                }, 0);
            }
        }
    }

    function syncSolverInputs() {
        if (elements.solverPotSize) {
            elements.solverPotSize.value = state.solverSettings.potSize;
        }
        if (elements.solverEffectiveStack) {
            elements.solverEffectiveStack.value = state.solverSettings.effectiveStack;
        }
        if (elements.solverBetSize) {
            elements.solverBetSize.value = state.solverSettings.betSizePercent;
        }
        if (elements.solverOpponentProfile) {
            elements.solverOpponentProfile.value = state.solverSettings.opponentProfile;
        }
        if (elements.solverIterations) {
            elements.solverIterations.value = state.solverSettings.iterations;
        }
    }

    function resetSolverSettings() {
        state.solverSettings = { ...DEFAULT_SOLVER_SETTINGS };
        syncSolverInputs();
        scheduleSolverUpdate({ immediate: true });
    }

    function updateSolverSetting(key, value) {
        if (!Object.prototype.hasOwnProperty.call(state.solverSettings, key)) {
            return;
        }
        let normalized = value;
        if (key === "opponentProfile") {
            normalized = SOLVER_PROFILES.has(String(value)) ? String(value) : DEFAULT_SOLVER_SETTINGS.opponentProfile;
        } else {
            const numeric = Number(value);
            if (!Number.isFinite(numeric)) {
                return;
            }
            switch (key) {
                case "betSizePercent":
                    normalized = Math.max(1, Math.min(400, numeric));
                    break;
                case "iterations":
                    normalized = Math.max(1000, Math.round(numeric / 1000) * 1000);
                    break;
                default:
                    normalized = Math.max(0, numeric);
                    break;
            }
        }
        if (state.solverSettings[key] === normalized) {
            return;
        }
        state.solverSettings[key] = normalized;
        syncSolverInputs();
        scheduleSolverUpdate();
    }

    function updateModeUI() {
        const isSolver = state.mode === "solver";
        const isTexas = getActiveGameVariant().id === GAME_VARIANTS.texas.id;
        if (elements.modeToggle) {
            elements.modeToggle.disabled = !isTexas;
            elements.modeToggle.setAttribute("aria-pressed", isSolver ? "true" : "false");
            elements.modeToggle.textContent = isSolver ? "\u05d7\u05d6\u05e8\u05d4 \u05dc\u05de\u05d7\u05e9\u05d1\u05d5\u05df \u05d4\u05e1\u05ea\u05d1\u05e8\u05d5\u05d9\u05d5\u05ea" : "\u05e2\u05d1\u05d5\u05e8 \u05dc\u05e1\u05d5\u05dc\u05d1\u05e8 GTO";
            elements.modeToggle.title = isTexas ? "" : "\u05d4\u05e1\u05d5\u05dc\u05d1\u05e8 \u05e0\u05ea\u05de\u05da \u05db\u05e8\u05d2\u05e2 \u05d1\u05d8\u05e7\u05e1\u05e1 \u05d4\u05d5\u05dc\u05d3\u05dd.";
        }
        if (elements.liveGame) {
            elements.liveGame.disabled = !isTexas;
            elements.liveGame.title = isTexas ? "" : "\u05de\u05e9\u05d7\u05e7 \u05d7\u05d9 \u05e0\u05ea\u05de\u05da \u05db\u05e8\u05d2\u05e2 \u05d1\u05d8\u05e7\u05e1\u05e1 \u05d4\u05d5\u05dc\u05d3\u05dd.";
        }
        if (elements.controls) {
            elements.controls.classList.toggle("is-solver-mode", isSolver);
        }
        if (elements.solverSettingsToggle) {
            elements.solverSettingsToggle.hidden = !isSolver;
            elements.solverSettingsToggle.setAttribute("aria-hidden", isSolver ? "false" : "true");
        }
        if (elements.solverControls) {
            elements.solverControls.hidden = !isSolver;
        }
        if (isSolver) {
            setSolverPanelOpen(true);
        } else {
            setSolverPanelOpen(false);
        }
        if (elements.solverResults) {
            elements.solverResults.hidden = !isSolver;
            elements.solverResults.setAttribute("aria-hidden", isSolver ? "false" : "true");
            if (isSolver && !elements.solverResults.classList.contains("has-data")) {
                renderSolverPlaceholder();
            }
        }
        if (elements.results) {
            elements.results.hidden = isSolver;
            elements.results.setAttribute("aria-hidden", isSolver ? "true" : "false");
        }
    }

    function scheduleSolverUpdate(options = {}) {
        if (state.mode !== "solver") {
            return;
        }
        const { immediate = false, delay = PROBABILITY_UPDATE_DELAY } = options;
        const timerHost = typeof window !== "undefined" ? window : globalThis;
        if (solverUpdateTimer !== null) {
            timerHost.clearTimeout(solverUpdateTimer);
            solverUpdateTimer = null;
        }
        if (immediate) {
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(() => {
                    updateSolverRecommendations();
                });
            } else {
                updateSolverRecommendations();
            }
            return;
        }
        solverUpdateTimer = timerHost.setTimeout(() => {
            solverUpdateTimer = null;
            updateSolverRecommendations();
        }, delay);
    }

    function cancelScheduledSolverUpdate() {
        if (solverUpdateTimer !== null) {
            const timerHost = typeof window !== "undefined" ? window : globalThis;
            timerHost.clearTimeout(solverUpdateTimer);
            solverUpdateTimer = null;
        }
    }

    

    

        

    function getSolverAnalysis(options = {}) {
        const {
            heroCards,
            boardCards,
            settings = state.solverSettings,
            availableVillainCards = null,
            includeIntegrations = true
        } = options || {};
        if (!Array.isArray(heroCards) || heroCards.length !== 2) {
            return { ok: false, reason: "hero-cards", message: SOLVER_MESSAGES.heroCardsRequired };
        }
        if (!Array.isArray(boardCards) || boardCards.length > 5) {
            return { ok: false, reason: "board-length", message: SOLVER_MESSAGES.boardTooLong };
        }
        const assignedIds = new Set();
        heroCards.forEach((card) => {
            if (card && card.id) {
                assignedIds.add(card.id);
            }
        });
        boardCards.forEach((card) => {
            if (card && card.id) {
                assignedIds.add(card.id);
            }
        });
        let villainCandidates;
        if (Array.isArray(availableVillainCards)) {
            villainCandidates = availableVillainCards.filter((card) => card && card.id && !assignedIds.has(card.id));
        } else {
            state.cardAssignments.forEach((slot, cardId) => {
                assignedIds.add(cardId);
            });
            villainCandidates = [];
            state.deck.forEach((card) => {
                if (!assignedIds.has(card.id)) {
                    villainCandidates.push(card);
                }
            });
        }
        if (villainCandidates.length < 2) {
            return { ok: false, reason: "villain-deck", message: SOLVER_MESSAGES.insufficientDeck };
        }
        const profile = SOLVER_PROFILES.has(settings.opponentProfile)
            ? settings.opponentProfile
            : DEFAULT_SOLVER_SETTINGS.opponentProfile;
        const villainRange = buildVillainRange(villainCandidates, profile);
        if (!villainRange.combos.length || villainRange.totalWeight <= 0) {
            return { ok: false, reason: "villain-range", message: SOLVER_MESSAGES.rangeUnavailable };
        }
        const iterationsSetting = Number(settings.iterations) || 1000;
        const iterations = Math.max(villainRange.combos.length, Math.max(1000, iterationsSetting));
        const simulation = simulateRangeMatchup(heroCards, boardCards, villainRange, iterations);
        if (!simulation.samples) {
            return { ok: false, reason: "simulation", message: SOLVER_MESSAGES.simulationFailed };
        }
        const heroEquity = (simulation.heroWins + simulation.heroTies * 0.5) / simulation.samples;
        const potSize = Math.max(0, Number(settings.potSize) || 0);
        const effectiveStack = Math.max(0, Number(settings.effectiveStack) || 0);
        const betPercent = Math.max(1, Number(settings.betSizePercent) || 0) / 100;
        const proposedBet = potSize > 0 ? potSize * betPercent : betPercent;
        const betAmount = Math.min(effectiveStack, proposedBet);
        if (betAmount <= 0) {
            return { ok: false, reason: "bet-size", message: SOLVER_MESSAGES.betParametersMissing };
        }
        const totalWeight = villainRange.totalWeight;
        const solverNamespace = typeof window !== "undefined" ? window.AlphaPoker : globalThis.AlphaPoker;
        const solverRegistry = solverNamespace && solverNamespace.Solvers && typeof solverNamespace.Solvers.solveAll === "function"
            ? solverNamespace.Solvers
            : null;
        let solverOutput = null;
        let integrationSummaries = [];
        if (solverRegistry) {
            try {
                const aggregated = solverRegistry.solveAll({
                    hero: { cards: heroCards, equity: heroEquity },
                    board: boardCards,
                    villainRange,
                    potSize,
                    betSize: betAmount,
                    stackSize: effectiveStack,
                    iterations,
                    simulation,
                    metadata: { profile, boardStage: boardCards.length }
                });
                if (aggregated && aggregated.primary && aggregated.primary.summary) {
                    solverOutput = aggregated.primary.summary;
                }
                if (includeIntegrations && aggregated && Array.isArray(aggregated.results)) {
                    integrationSummaries = aggregated.results
                        .map((entry) => ({
                            id: entry.id,
                            label: entry.label,
                            ok: entry.ok,
                            origin: entry.origin || "",
                            version: entry.version || "",
                            priority: entry.priority || 0,
                            summary: entry.summary || null,
                            detail: entry.detail || null,
                            diagnostics: entry.diagnostics || null,
                            error: entry.error ? String(entry.error) : null
                        }))
                        .sort((a, b) => b.priority - a.priority);
                }
            } catch (error) {
                console.warn("[AlphaPoker] Solver registry failure", error);
            }
        }
        if (!solverOutput && solverNamespace && solverNamespace.SingleStreetCFR && typeof solverNamespace.SingleStreetCFR.solve === "function") {
            try {
                solverOutput = solverNamespace.SingleStreetCFR.solve({
                    combos: villainRange.combos,
                    totalWeight,
                    potSize,
                    betSize: betAmount,
                    stackSize: effectiveStack,
                    iterations
                });
                if (includeIntegrations && solverOutput && integrationSummaries.length === 0) {
                    integrationSummaries.push({
                        id: "singleStreetCfr",
                        label: "CFR חד רחובי",
                        ok: true,
                        origin: "ליבת AlphaPoker",
                        version: "לא זמין",
                        priority: 0,
                        summary: solverOutput,
                        detail: null,
                        diagnostics: { iterations },
                        error: null
                    });
                }
            } catch (error) {
                console.warn("[AlphaPoker] CFR solver failure", error);
            }
        }
        const meta = {
            villainRange,
            simulation,
            heroEquity,
            iterations,
            profile,
            solverOutput
        };
        if (!solverOutput) {
            const callThreshold = betAmount > 0 ? betAmount / ((potSize + betAmount) || 1) : 1;
            const mdf = betAmount > 0 ? potSize / ((potSize + betAmount) || 1) : 0;
            const sortedCombos = villainRange.combos.slice().sort((a, b) => a.heroEquity - b.heroEquity);
            const targetCallWeight = totalWeight * mdf;
            let callWeight = 0;
            let callEVSum = 0;
            const callDetails = [];
            for (let i = 0; i < sortedCombos.length && callWeight < targetCallWeight - 1e-7; i += 1) {
                const combo = sortedCombos[i];
                if (combo.weight <= 0) {
                    continue;
                }
                const remaining = targetCallWeight - callWeight;
                const usedWeight = Math.min(combo.weight, remaining);
                if (usedWeight <= 0) {
                    continue;
                }
                const portion = usedWeight / combo.weight;
                callWeight += usedWeight;
                const heroEq = clampProbability(combo.heroEquity);
                const callEV = heroEq * (potSize + betAmount) - (1 - heroEq) * betAmount;
                callEVSum += usedWeight * callEV;
                if (callDetails.length < 8) {
                    callDetails.push({
                        cards: combo.cards,
                        heroEquity: heroEq,
                        villainEquity: clampProbability(1 - heroEq),
                        portion,
                        weightShare: combo.weight / totalWeight
                    });
                }
            }
            const callFrequency = totalWeight > 0 ? callWeight / totalWeight : 0;
            const foldFrequency = Math.max(0, 1 - callFrequency);
            const foldEV = foldFrequency * potSize;
            const callEV = totalWeight > 0 ? callEVSum / totalWeight : 0;
            const evBet = foldEV + callEV;
            const evCheck = heroEquity * potSize;
            const betAdvantage = evBet - evCheck;
            const optimalBluffRatio = betAmount > 0 ? betAmount / ((potSize + betAmount) || 1) : 0;
            let valueWeight = 0;
            let bluffWeight = 0;
            villainRange.combos.forEach((combo) => {
                if (combo.weight <= 0) {
                    return;
                }
                if (combo.heroEquity >= callThreshold) {
                    valueWeight += combo.weight;
                } else {
                    bluffWeight += combo.weight;
                }
            });
            const bluffCapacity = valueWeight * optimalBluffRatio;
            const bluffCoverage = bluffCapacity > 0 ? Math.max(0, Math.min(1.5, bluffWeight / bluffCapacity)) : 0;
            const confidence = Math.max(0.1, Math.min(0.99, Math.sqrt(simulation.samples) / Math.sqrt(iterations * 1.5)));
            const rawRecommendation = describeHeroAction(heroEquity, callThreshold, betAdvantage);
            const recommendation = betAmount > 0
                ? {
                    label: `${rawRecommendation.label} ${betAmount.toFixed(2)} BB (${formatSolverPercent(betPercent)})`,
                    detail: rawRecommendation.detail
                }
                : rawRecommendation;
            const heroBetFrequency = clampProbability(betAdvantage > 0 ? 0.7 : 0.35);
            const heroCheckFrequency = clampProbability(1 - heroBetFrequency);
            const heroCallFrequency = clampProbability(callFrequency);
            const data = {
                heroCards,
                boardCards,
                heroEquity,
                evBet,
                evCheck,
                betAdvantage,
                betAmount,
                betPercent,
                potSize,
                effectiveStack,
                callThreshold,
                mdf,
                callFrequency,
                foldFrequency,
                optimalBluffRatio,
                bluffCoverage,
                valueWeight,
                bluffWeight,
                callDetails,
                heroBetFrequency,
                heroCheckFrequency,
                heroCallFrequency,
                villainBetAfterCheckFrequency: null,
                iterations: simulation.samples,
                combosCount: villainRange.combos.length,
                confidence,
                profile,
                boardStage: boardCards.length,
                recommendation,
                integrations: includeIntegrations ? integrationSummaries : []
            };
            return { ok: true, data, meta };
        }
        const callFrequency = clampProbability(solverOutput.villainCallFrequency);
        const foldFrequency = clampProbability(solverOutput.villainFoldFrequency);
        const evBet = Number.isFinite(solverOutput.evBet) ? solverOutput.evBet : 0;
        const evCheck = Number.isFinite(solverOutput.evCheck) ? solverOutput.evCheck : heroEquity * potSize;
        const betAdvantage = evBet - evCheck;
        const callThreshold = clampProbability(solverOutput.callThreshold);
        const mdf = callFrequency;
        const optimalBluffRatio = betAmount > 0 ? betAmount / ((potSize + betAmount) || 1) : 0;
        const valueWeight = Math.max(0, solverOutput.callWeight || 0);
        const bluffWeight = Math.max(0, solverOutput.bluffWeight || 0);
        const bluffCapacity = valueWeight * optimalBluffRatio;
        const bluffCoverage = bluffCapacity > 0 ? Math.max(0, Math.min(1.5, bluffWeight / bluffCapacity)) : 0;
        const baseConfidence = Math.max(0.1, Math.min(0.99, Math.sqrt(simulation.samples) / Math.sqrt(iterations * 1.5)));
        const regretPenalty = Math.max(0, (solverOutput.avgRootRegret || 0) + (solverOutput.avgCallRegret || 0));
        const regretScore = 1 / (1 + regretPenalty);
        const confidence = Math.max(0.1, Math.min(0.99, baseConfidence * regretScore));
        const heroBetFrequency = clampProbability(solverOutput.heroStrategy && typeof solverOutput.heroStrategy.bet === "number" ? solverOutput.heroStrategy.bet : 0.5);
        const heroCheckFrequency = clampProbability(solverOutput.heroStrategy && typeof solverOutput.heroStrategy.check === "number"
            ? solverOutput.heroStrategy.check
            : (1 - heroBetFrequency));
        const heroCallFrequency = clampProbability(solverOutput.heroCallStrategy && typeof solverOutput.heroCallStrategy.call === "number"
            ? solverOutput.heroCallStrategy.call
            : 1);
        const villainBetAfterCheckFrequency = solverOutput.villainBetAfterCheckFrequency !== undefined
            ? clampProbability(solverOutput.villainBetAfterCheckFrequency)
            : null;
        const rawRecommendation = describeHeroAction(heroEquity, callThreshold, betAdvantage);
        const mixDetail = `${formatSolverPercent(heroBetFrequency)} הימור / ${formatSolverPercent(heroCheckFrequency)} צ'ק`;
        const responseDetail = `${formatSolverPercent(heroCallFrequency)} קול מול ההימור`;
        const recommendationDetail = `${rawRecommendation.detail} | ${mixDetail} | ${responseDetail}`;
        const recommendation = betAmount > 0
            ? {
                label: `${rawRecommendation.label} ${betAmount.toFixed(2)} BB (${formatSolverPercent(betPercent)})`,
                detail: recommendationDetail
            }
            : { label: rawRecommendation.label, detail: recommendationDetail };
        const callDetails = (Array.isArray(solverOutput.callDetails) ? solverOutput.callDetails : [])
            .filter((item) => item && item.callProbability > 1e-3)
            .slice(0, 8)
            .map((item) => ({
                cards: item.cards,
                heroEquity: clampProbability(item.heroEquity),
                villainEquity: clampProbability(1 - item.heroEquity),
                portion: clampProbability(item.callProbability),
                weightShare: item.weightShare
            }));
        if (!callDetails.length && Array.isArray(solverOutput.callDetails) && solverOutput.callDetails.length) {
            const top = solverOutput.callDetails[0];
            callDetails.push({
                cards: top.cards,
                heroEquity: clampProbability(top.heroEquity),
                villainEquity: clampProbability(1 - top.heroEquity),
                portion: clampProbability(top.callProbability),
                weightShare: top.weightShare
            });
        }
        const data = {
            heroCards,
            boardCards,
            heroEquity,
            evBet,
            evCheck,
            betAdvantage,
            betAmount,
            betPercent,
            potSize,
            effectiveStack,
            callThreshold,
            mdf,
            callFrequency,
            foldFrequency,
            optimalBluffRatio,
            bluffCoverage,
            valueWeight,
            bluffWeight,
            callDetails,
            heroBetFrequency,
            heroCheckFrequency,
            heroCallFrequency,
            villainBetAfterCheckFrequency,
            iterations: Math.round(iterations + simulation.samples),
            combosCount: villainRange.combos.length,
            confidence,
            profile,
            boardStage: boardCards.length,
            recommendation,
            integrations: includeIntegrations ? integrationSummaries : []
        };
        return { ok: true, data, meta };
    }
    function updateSolverRecommendations() {
        if (state.mode !== "solver") {
            return;
        }
        if (!elements.solverResults) {
            return;
        }
        const players = collectPlayersData();
        const hero = players[0];
        if (!hero || hero.cards.length !== 2) {
            state.lastSolverAnalysis = null;
            renderSolverPlaceholder(SOLVER_MESSAGES.heroCardsRequired);
            return;
        }
        const boardCards = collectBoardCards();
        const analysis = getSolverAnalysis({ heroCards: hero.cards, boardCards });
        if (!analysis.ok) {
            state.lastSolverAnalysis = null;
            renderSolverPlaceholder(analysis.message || SOLVER_MESSAGES.default);
            return;
        }
        state.lastSolverAnalysis = analysis;
        renderSolverResults(analysis.data);
    }
function renderSolverPlaceholder(message = SOLVER_MESSAGES.default) {
        if (!elements.solverResults) {
            return;
        }
        elements.solverResults.classList.remove("has-data");
        elements.solverResults.innerHTML = '';
        const wrapper = document.createElement("div");
        wrapper.className = "solver-placeholder";
        const paragraph = document.createElement("p");
        paragraph.textContent = message;
        wrapper.appendChild(paragraph);
        elements.solverResults.appendChild(wrapper);
    }

    function renderSolverResults(data) {
        if (!elements.solverResults) {
            return;
        }
        elements.solverResults.innerHTML = '';
        elements.solverResults.classList.add("has-data");

        const summary = document.createElement("section");
        summary.className = "solver-summary";
        summary.innerHTML = `
            <div class="solver-chip">
                <span class="solver-chip-label">\u05d4\u05d9\u05d3 \u05e9\u05dc\u05da</span>
                <span class="solver-chip-value">${formatCardList(data.heroCards)}</span>
            </div>
            <div class="solver-chip">
                <span class="solver-chip-label">\u05e7\u05dc\u05e4\u05d9 \u05e7\u05d4\u05d9\u05dc\u05d4</span>
                <span class="solver-chip-value">${formatCardList(data.boardCards)}</span>
            </div>
            <div class="solver-chip emphasis">
                <span class="solver-chip-label">\u05d4\u05de\u05dc\u05e6\u05ea GTO</span>
                <span class="solver-chip-value">${data.recommendation.label}</span>
                <span class="solver-chip-hint">${data.recommendation.detail}</span>
            </div>
            <div class="solver-chip">
                <span class="solver-chip-label">\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea EV</span>
                <span class="solver-chip-value">${formatSolverEV(data.evBet)} \u05de\u05d5\u05dc ${formatSolverEV(data.evCheck)}</span>
                <span class="solver-chip-hint">\u0394 ${formatSolverEV(data.betAdvantage)}</span>
            </div>
        `;

        const metrics = document.createElement("section");
        metrics.className = "solver-metrics";
        metrics.appendChild(createMetricRow("\u05d4\u05e1\u05ea\u05d1\u05e8\u05d5\u05ea \u05d6\u05db\u05d9\u05d9\u05d4 \u05de\u05d5\u05dc \u05d4\u05d8\u05d5\u05d5\u05d7", formatSolverPercent(data.heroEquity)));
        metrics.appendChild(createMetricRow("\u05e1\u05e3 \u05e7\u05e8\u05d9\u05d0\u05d4 (Pot Odds)", formatSolverPercent(data.callThreshold)));
        metrics.appendChild(createMetricRow("MDF \u05e0\u05d3\u05e8\u05e9", formatSolverPercent(data.mdf)));
        metrics.appendChild(createMetricRow("\u05ea\u05d3\u05d9\u05e8\u05d5\u05ea \u05e7\u05e8\u05d9\u05d0\u05d4 \u05de\u05e9\u05d5\u05e2\u05e8\u05ea", formatSolverPercent(data.callFrequency)));
        metrics.appendChild(createMetricRow("\u05d4\u05e6\u05e2\u05ea \u05d2\u05d5\u05d3\u05dc \u05d4\u05d9\u05de\u05d5\u05e8", `${formatSolverEV(data.betAmount)} (${formatSolverPercent(data.betPercent)})`));
        metrics.appendChild(createMetricRow("\u05db\u05d9\u05e1\u05d5\u05d9 \u05d1\u05dc\u05d5\u05e4\u05d9\u05dd \u05dc\u05e2\u05d5\u05de\u05ea \u05e2\u05e8\u05da", `${formatSolverPercent(data.bluffCoverage)} / ${formatSolverPercent(data.optimalBluffRatio)}`, "ביצוע בפועל / ערך אופטימלי"));
        metrics.appendChild(createMetricRow("\u05e8\u05de\u05ea \u05d1\u05d9\u05d8\u05d7\u05d5\u05df", formatSolverPercent(data.confidence)));
        metrics.appendChild(createMetricRow("\u05de\u05d5\u05e4\u05e2\u05d9\u05dd \u05de\u05d3\u05d5\u05de\u05d9\u05dd", data.iterations.toLocaleString("he-IL")));

        const defense = document.createElement("section");
        defense.className = "solver-defense";
        const defenseTitle = document.createElement("h3");
        defenseTitle.textContent = "\u05d8\u05d5\u05d5\u05d7 \u05d4\u05d2\u05e0\u05d4 \u05d9\u05e8\u05d9\u05d1 (MDF)";
        defense.appendChild(defenseTitle);
        const defenseList = document.createElement("ul");
        defenseList.className = "solver-defense-list";
        data.callDetails.forEach((item) => {
            const li = document.createElement("li");
            li.className = "solver-defense-item";
            li.innerHTML = `
                <span class="combo">${formatCardList(item.cards)}</span>
                <span class="equity">${formatSolverPercent(item.villainEquity)}</span>
                <span class="portion">${formatSolverPercent(item.portion)}</span>
            `;
            defenseList.appendChild(li);
        });
        if (!data.callDetails.length) {
            const li = document.createElement("li");
            li.className = "solver-defense-item muted";
            li.textContent = SOLVER_MESSAGES.villainMustFold;
            defenseList.appendChild(li);
        }
        defense.appendChild(defenseList);

        elements.solverResults.append(summary, metrics, defense);
        if (Array.isArray(data.integrations) && data.integrations.length) {
            const integrationsSection = document.createElement("section");
            integrationsSection.className = "solver-integrations";
            const integrationsTitle = document.createElement("h3");
            integrationsTitle.textContent = "\u05de\u05e0\u05d5\u05e2\u05d9 \u05e0\u05d9\u05ea\u05d5\u05d7 \u05e0\u05d5\u05e1\u05e4\u05d9\u05dd";
            integrationsSection.appendChild(integrationsTitle);
            const integrationsList = document.createElement("div");
            integrationsList.className = "solver-integrations-list";
            data.integrations.forEach((entry) => {
                integrationsList.appendChild(renderIntegrationCard(entry));
            });
            integrationsSection.appendChild(integrationsList);
            elements.solverResults.appendChild(integrationsSection);
        }
    }

    function createMetricRow(label, value, hint) {
        const row = document.createElement("div");
        row.className = "solver-metric";
        const labelEl = document.createElement("span");
        labelEl.className = "solver-metric-label";
        labelEl.textContent = label;
        row.appendChild(labelEl);
        const valueEl = document.createElement("span");
        valueEl.className = "solver-metric-value";
        valueEl.textContent = value;
        row.appendChild(valueEl);
        if (hint) {
            const hintEl = document.createElement("span");
            hintEl.className = "solver-metric-hint";
            hintEl.textContent = hint;
            row.appendChild(hintEl);
        }
        return row;
    }

    function renderIntegrationCard(entry) {
        const card = document.createElement("article");
        card.className = "solver-integration-card";
        card.classList.add(entry && entry.ok ? "state-ok" : "state-error");

        const header = document.createElement("header");
        header.className = "solver-integration-header";
        const title = document.createElement("span");
        title.className = "solver-integration-title";
        title.textContent = entry && entry.label ? entry.label : (entry && entry.id ? entry.id : "סולבר");
        header.appendChild(title);
        if (entry && entry.version) {
            const meta = document.createElement("span");
            meta.className = "solver-integration-meta";
            meta.textContent = `v${entry.version}`;
            header.appendChild(meta);
        }
        if (entry && entry.origin) {
            const origin = document.createElement("span");
            origin.className = "solver-integration-origin";
            origin.textContent = entry.origin;
            header.appendChild(origin);
        }
        const status = document.createElement("span");
        status.className = "solver-integration-status";
        status.textContent = entry && entry.ok ? "\u05e4\u05e2\u05d9\u05dc" : "\u05e9\u05d2\u05d9\u05d0\u05d4";
        header.appendChild(status);
        card.appendChild(header);

        const body = document.createElement("div");
        body.className = "solver-integration-body";
        let populated = false;
        if (entry && entry.summary) {
            const summary = entry.summary;
            if (summary.heroStrategy) {
                const betFreq = formatSolverPercent(summary.heroStrategy.bet || 0);
                const checkFreq = formatSolverPercent(summary.heroStrategy.check || (1 - (summary.heroStrategy.bet || 0)));
                appendIntegrationRow(body, "\u05de\u05d9\u05e7\u05e1 \u05d4\u05d9\u05de\u05d5\u05e8", `${betFreq} / ${checkFreq}`);
                populated = true;
            }
            if (summary.heroCallStrategy) {
                const foldFreq = formatSolverPercent(summary.heroCallStrategy.fold || 0);
                const callFreq = formatSolverPercent(summary.heroCallStrategy.call || 0);
                appendIntegrationRow(body, "\u05de\u05e2\u05e8\u05da \u05e0\u05d2\u05d3", `${callFreq} \u05e7\u05d5\u05dc / ${foldFreq} \u05e4\u05dc\u05d3`);
                populated = true;
            }
            if (summary.villainCallFrequency !== undefined) {
                appendIntegrationRow(body, "MDF \u05d9\u05e8\u05d9\u05d1", formatSolverPercent(summary.villainCallFrequency));
                populated = true;
            }
            if (summary.villainBetAfterCheckFrequency !== undefined) {
                appendIntegrationRow(body, "\u05d9\u05e8\u05d9\u05d1 \u05de\u05e0\u05d9\u05e1 \u05d0\u05d7\u05e8\u05d9 \u05e6\u05e7", formatSolverPercent(summary.villainBetAfterCheckFrequency));
                populated = true;
            }
            if (Number.isFinite(summary.evBet) && Number.isFinite(summary.evCheck)) {
                appendIntegrationRow(body, "ערך צפוי (EV)", `${formatSolverEV(summary.evBet)} / ${formatSolverEV(summary.evCheck)}`);
                populated = true;
            }
            if (summary.callThreshold !== undefined) {
                appendIntegrationRow(body, "\u05e1\u05e3 \u05e7\u05e8\u05d9\u05d0\u05d4", formatSolverPercent(summary.callThreshold));
                populated = true;
            }
        }
        if (!populated && entry && entry.detail && entry.detail.metrics) {
            const metrics = entry.detail.metrics;
            appendIntegrationRow(body, "אקוויטי ממוצע", formatSolverPercent(metrics.weightedEquity || 0));
            appendIntegrationRow(body, "ערך צפוי של ההימור (EV)", formatSolverEV(metrics.weightedEvBet || 0));
            appendIntegrationRow(body, "ערך צפוי לאחר צ׳ק (EV)", formatSolverEV(metrics.weightedEvCheck || 0));
            populated = true;
        }
        if (!populated && entry && entry.error) {
            const error = document.createElement("p");
            error.className = "solver-integration-error";
            error.textContent = entry.error;
            body.appendChild(error);
            populated = true;
        }
        if (!populated) {
            const placeholder = document.createElement("p");
            placeholder.className = "solver-integration-empty";
            placeholder.textContent = entry && entry.ok ? "\u05d0\u05d9\u05df \u05e1\u05d9\u05db\u05d5\u05dd \u05dc\u05d4\u05e6\u05d9\u05d2" : "\u05dc\u05d0 \u05d4\u05ea\u05e7\u05d1\u05dc \u05de\u05e1\u05e4\u05e8";
            body.appendChild(placeholder);
        }
        if (entry && entry.diagnostics) {
            const diagnostics = Object.entries(entry.diagnostics)
                .filter(([, value]) => value !== null && value !== undefined)
                .slice(0, 4);
            if (diagnostics.length) {
                const diagList = document.createElement("ul");
                diagList.className = "solver-integration-diagnostics";
                diagnostics.forEach(([key, value]) => {
                    const item = document.createElement("li");
                    item.textContent = `${key}: ${value}`;
                    diagList.appendChild(item);
                });
                body.appendChild(diagList);
            }
        }
        card.appendChild(body);
        return card;
    }

    function appendIntegrationRow(container, label, value) {
        const row = document.createElement("div");
        row.className = "solver-integration-row";
        const labelEl = document.createElement("span");
        labelEl.className = "solver-integration-row-label";
        labelEl.textContent = label;
        const valueEl = document.createElement("span");
        valueEl.className = "solver-integration-row-value";
        valueEl.textContent = value;
        row.append(labelEl, valueEl);
        container.appendChild(row);
    }

    function buildVillainRange(cards, profile) {
        const combos = [];
        let totalWeight = 0;
        for (let i = 0; i < cards.length - 1; i += 1) {
            for (let j = i + 1; j < cards.length; j += 1) {
                const cardA = cards[i];
                const cardB = cards[j];
                const weight = computeComboWeight(cardA, cardB, profile);
                if (weight <= 0) {
                    continue;
                }
                totalWeight += weight;
                combos.push({
                    cards: [cardA, cardB],
                    weight,
                    cumulative: totalWeight,
                    heroWins: 0,
                    heroTies: 0,
                    samples: 0,
                    heroEquity: 0
                });
            }
        }
        return { combos, totalWeight };
    }

    function computeComboWeight(cardA, cardB, profile) {
        const high = Math.max(cardA.rankValue, cardB.rankValue);
        const low = Math.min(cardA.rankValue, cardB.rankValue);
        const gap = Math.abs(cardA.rankValue - cardB.rankValue) - 1;
        const pair = cardA.rankValue === cardB.rankValue;
        const suited = cardA.suit.id === cardB.suit.id;
        const connected = Math.abs(cardA.rankValue - cardB.rankValue) === 1;
        switch (profile) {
            case "tight":
                return 0.3 + (high + low) / 20 + (pair ? 1.1 : 0) + (suited ? 0.2 : 0);
            case "loose":
                return 0.8 + (14 - Math.max(0, gap)) / 18 + (suited ? 0.5 : 0) + (pair ? 0.7 : 0);
            case "aggressive":
                return 0.9 + (connected ? 0.7 : 0) + (suited ? 0.5 : 0) + (pair ? 0.9 : 0) + (gap <= 2 ? 0.3 : 0);
            default:
                return 1 + (pair ? 0.6 : 0) + (suited ? 0.25 : 0) + Math.max(0, high - 7) / 12;
        }
    }

    function pickWeightedCombo(combos, totalWeight, target) {
        if (!combos.length) {
            return null;
        }
        if (!Number.isFinite(totalWeight) || totalWeight <= 0) {
            return combos[0];
        }
        let low = 0;
        let high = combos.length - 1;
        while (low <= high) {
            const mid = low + Math.floor((high - low) / 2);
            const current = combos[mid];
            if (target <= current.cumulative) {
                if (mid === 0 || target > combos[mid - 1].cumulative) {
                    return current;
                }
                high = mid - 1;
            } else {
                low = mid + 1;
            }
        }
        return combos[combos.length - 1];
    }

    function simulateRangeMatchup(heroCards, boardCards, villainRange, iterations) {
        const heroIds = new Set(heroCards.map((card) => card.id));
        const boardIds = new Set(boardCards.map((card) => card.id));
        const basePool = [];
        state.deck.forEach((card) => {
            if (!heroIds.has(card.id) && !boardIds.has(card.id)) {
                basePool.push(card);
            }
        });
        const drawsNeeded = Math.max(0, 5 - boardCards.length);
        const boardBaseLength = boardCards.length;
        const boardBuffer = new Array(boardBaseLength + drawsNeeded);
        for (let i = 0; i < boardBaseLength; i += 1) {
            boardBuffer[i] = boardCards[i];
        }
        const scratchPool = new Array(basePool.length);
        let heroWins = 0;
        let heroTies = 0;
        let samples = 0;
        villainRange.combos.forEach((combo) => {
            combo.heroWins = 0;
            combo.heroTies = 0;
            combo.samples = 0;
        });
        const combos = villainRange.combos;
        const totalWeight = villainRange.totalWeight;
        const totalIterations = Math.max(iterations, combos.length);
        const ensured = Math.min(combos.length, totalIterations);
        for (let i = 0; i < ensured; i += 1) {
            simulateCombo(combos[i]);
        }
        for (let iter = ensured; iter < totalIterations; iter += 1) {
            const r = Math.random() * totalWeight;
            const combo = pickWeightedCombo(combos, totalWeight, r);
            if (combo) {
                simulateCombo(combo);
            }
        }
        combos.forEach((combo) => {
            if (combo.samples > 0) {
                combo.heroEquity = (combo.heroWins + combo.heroTies * 0.5) / combo.samples;
            } else {
                combo.heroEquity = samples > 0 ? (heroWins + heroTies * 0.5) / samples : 0.5;
            }
        });
        return { heroWins, heroTies, samples, drawsNeeded, boardLength: boardBaseLength };

        function simulateCombo(combo) {
            const poolSize = populateScratch(combo);
            if (poolSize < drawsNeeded) {
                return;
            }
            if (drawsNeeded > 0) {
                for (let d = 0; d < drawsNeeded; d += 1) {
                    const j = d + Math.floor(Math.random() * (poolSize - d));
                    const temp = scratchPool[d];
                    scratchPool[d] = scratchPool[j];
                    scratchPool[j] = temp;
                    boardBuffer[boardBaseLength + d] = scratchPool[d];
                }
                boardBuffer.length = boardBaseLength + drawsNeeded;
            } else {
                boardBuffer.length = boardBaseLength;
            }
            const heroScore = bestScoreForCards(heroCards, boardBuffer);
            const villainScore = bestScoreForCards(combo.cards, boardBuffer);
            const cmp = heroScore === villainScore ? 0 : (heroScore > villainScore ? 1 : -1);
            samples += 1;
            combo.samples += 1;
            if (cmp > 0) {
                heroWins += 1;
                combo.heroWins += 1;
            } else if (cmp === 0) {
                heroTies += 1;
                combo.heroTies += 1;
            }
        }

        function populateScratch(combo) {
            const firstId = combo.cards[0].id;
            const secondId = combo.cards[1].id;
            let length = 0;
            for (let i = 0; i < basePool.length; i += 1) {
                const card = basePool[i];
                if (card.id === firstId || card.id === secondId) {
                    continue;
                }
                scratchPool[length] = card;
                length += 1;
            }
            return length;
        }
    }

        function describeHeroAction(heroEquity, callThreshold, advantage) {
        const delta = advantage;
        let label;
        let detail;
        if (delta > 0.02) {
            label = "\u05d4\u05d9\u05de\u05d5\u05e8";
            detail = heroEquity >= callThreshold + 0.05 ? "\u05d4\u05d9\u05de\u05d5\u05e8 \u05e2\u05e8\u05da \u05d8\u05d4\u05d5\u05e8" : "\u05d4\u05d9\u05de\u05d5\u05e8 \u05de\u05e9\u05d5\u05dc\u05d1 / \u05d7\u05e6\u05d9 \u05e2\u05e8\u05da";
        } else if (delta < -0.02) {
            label = "\u05d1\u05d3\u05d9\u05e7\u05d4";
            detail = heroEquity <= callThreshold - 0.05 ? "\u05e6'\u05e7 \u05dc\u05e9\u05de\u05d9\u05e8\u05ea \u05d8\u05d5\u05d5\u05d7" : "\u05e6'\u05e7-\u05d1\u05e7 \u05de\u05d0\u05d5\u05d6\u05df";
        } else {
            label = "\u05d0\u05d9\u05d6\u05d5\u05df";
            detail = "\u05de\u05d9\u05e7\u05e1 \u05e9\u05d5\u05d5\u05d4 \u05d1\u05d9\u05df \u05e6'\u05e7 \u05dc\u05d4\u05d9\u05de\u05d5\u05e8";
        }
        return { label, detail };
    }

    function formatSolverPercent(value, decimals = 1) {
        const ratio = clampProbability(value);
        return `${(ratio * 100).toFixed(decimals)}%`;
    }

    function formatSolverEV(value) {
        if (!Number.isFinite(value)) {
            return "0 BB";
        }
        const rounded = Math.abs(value) < 0.005 ? 0 : value;
        return `${rounded >= 0 ? "+" : ""}${rounded.toFixed(2)} BB`;
    }

    function clampProbability(value) {
        if (!Number.isFinite(value)) {
            return 0;
        }
        return Math.max(0, Math.min(1, value));
    }

    function formatCard(card) {
        if (!card) {
            return "-";
        }
        return `${card.rank.label}${card.suit.symbol}`;
    }

    function formatCardList(cards) {
        if (!cards || !cards.length) {
            return "-";
        }
        return cards.map((card) => formatCard(card)).join(" ");
    }

    function setupResultsLayoutObserver() {
        if (!elements.results || !elements.calculatorLayout) {
            return;
        }

        const applyLayoutState = () => {
            const ariaHidden = elements.results.getAttribute("aria-hidden");
            const isHidden = elements.results.hidden || ariaHidden === "true";
            const hasContent = elements.results.childElementCount > 0;
            elements.calculatorLayout.classList.toggle(
                "calculator-layout--with-results",
                !isHidden && hasContent
            );
        };

        applyLayoutState();

        if (state.resultsObserver) {
            state.resultsObserver.disconnect();
        }

        state.resultsObserver = new MutationObserver(() => {
            applyLayoutState();
        });

        state.resultsObserver.observe(elements.results, {
            childList: true,
            subtree: false,
            attributes: true,
            attributeFilter: ["hidden", "aria-hidden"]
        });
    }

    function getCardById(id) {
        return id ? state.cardById.get(id) : null;
    }
})();















