(() => {
    const MIN_PLAYERS = 2;
    const MAX_PLAYERS = 9;
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

    let probabilityUpdateTimer = null;
    let solverUpdateTimer = null;

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
        playersCount: MIN_PLAYERS,
        seats: [],
        probabilityDisplays: [],
        isAutoAdvancePaused: false,
        deferProbabilityUpdate: false,
        mode: "equity",
        isSolverPanelOpen: false,
        solverSettings: { ...DEFAULT_SOLVER_SETTINGS }
    };

    const elements = {
        table: document.getElementById("table"),
        board: document.getElementById("board-cards"),
        deck: document.getElementById("deck"),
        addPlayer: document.getElementById("add-player"),
        removePlayer: document.getElementById("remove-player"),
        playerCountLabel: document.getElementById("player-count-label"),
        dealRandom: document.getElementById("deal-random"),
        clearAll: document.getElementById("clear-all"),
        calculate: document.getElementById("calculate"),
        reset: document.getElementById("reset"),
        errors: document.getElementById("errors"),
        results: document.getElementById("results"),
        controls: document.querySelector(".controls"),
        modeToggle: document.getElementById("mode-toggle"),
        solverControls: document.getElementById("solver-controls"),
        solverResults: document.getElementById("solver-results"),
        solverPotSize: document.getElementById("solver-pot-size"),
        solverEffectiveStack: document.getElementById("solver-effective-stack"),
        solverBetSize: document.getElementById("solver-bet-size"),
        solverOpponentProfile: document.getElementById("solver-opponent-profile"),
        solverIterations: document.getElementById("solver-iterations"),
        solverRun: document.getElementById("solver-run"),
        solverReset: document.getElementById("solver-reset"),
        solverSettingsToggle: document.getElementById("solver-settings-toggle")
    };

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        if (!elements.table || !elements.board || !elements.deck) {
            console.warn("Alpha Poker UI: missing core elements, aborting init.");
            return;
        }

        buildDeck();
        renderDeck();
        buildBoard();
        buildSeats();
        updateSeatStates();
        updatePlayerCountLabel();
        bindControls();
        bindModeControls();
        bindSolverControls();
        bindSolverPanelToggle();
        syncSolverInputs();
        updateModeUI();
        ensureActiveSlot();
        scheduleImmediateProbabilityUpdate();
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
            label.innerHTML = `<span class="suit-symbol${suit.color === "red" ? " red" : ""}">${suit.symbol}</span><span class="suit-name">${suit.name}</span>`;
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
                cardEl.className = `deck-card${card.suit.color === "red" ? " red" : ""}`;
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
        label.textContent = `\u05e9\u05d7\u05e7\u05df ${index + 1}`;

        const cardsRow = document.createElement("div");
        cardsRow.className = "card-row";

        for (let c = 0; c < 2; c += 1) {
            const slot = createCardSlot({
                key: `player-${index}-${c}`,
                placeholder: `\u05e7\u05dc\u05e3 ${c + 1}`,
                type: "player",
                order: index * 2 + c,
                playerIndex: index
            });
            cardsRow.appendChild(slot);
        }

        seat.append(probability, label, cardsRow);
        state.probabilityDisplays[index] = {
            container: probability,
            tie: tieLine,
            win: winLine
        };
        return seat;
    }

    function createCardSlot({ key, placeholder, type, order, playerIndex }) {
        const slot = document.createElement("div");
        slot.className = "card-slot";
        slot.dataset.slotKey = key;
        slot.dataset.slotType = type;
        slot.dataset.order = order;
        if (typeof playerIndex === "number") {
            slot.dataset.playerIndex = String(playerIndex);
        }
        slot.innerHTML = `
            <span class="card-placeholder">${placeholder}</span>
            <span class="card-value"><span class="rank"></span><span class="suit"></span></span>
        `;
        slot.addEventListener("click", () => handleSlotClick(slot));
        slot.addEventListener("dblclick", (event) => {
            event.preventDefault();
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
        if (Number(slot.dataset.playerIndex) >= state.playersCount) {
            return;
        }

        if (slot.dataset.cardId) {
            clearSlot(slot, { keepFocus: true });
            showError("");
            return;
        }

        if (state.activeSlot === slot) {
            setActiveSlot(null);
            showError("");
            return;
        }

        setActiveSlot(slot);
        showError("\u05d1\u05d7\u05e8\u05d5 \u05e7\u05dc\u05e3 \u05de\u05d4\u05d7\u05e4\u05d9\u05e1\u05d4 \u05dc\u05d4\u05e6\u05d1\u05ea\u05d5.");
    }

    function handleDeckCardClick(card) {
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
    function assignCardToSlot(card, slot) {
        if (!slot) {
            return;
        }

        if (slot.dataset.cardId === card.id) {
            advanceActiveSlot(slot);
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
        slot.classList.add("filled");

        const valueEl = slot.querySelector(".card-value");
        const rankEl = valueEl.querySelector(".rank");
        const suitEl = valueEl.querySelector(".suit");
        rankEl.textContent = card.rank.label;
        suitEl.textContent = card.suit.symbol;
        valueEl.classList.toggle("red", card.suit.color === "red");

        const deckButton = elements.deck.querySelector(`[data-card-id="${card.id}"]`);
        if (deckButton) {
            deckButton.classList.add("used");
        }

        state.cardAssignments.set(card.id, slot);

        if (!state.isAutoAdvancePaused) {
            advanceActiveSlot(slot);
        } else {
            setActiveSlot(null);
        }

        scheduleImmediateProbabilityUpdate();
        if (!state.deferProbabilityUpdate && state.mode === "equity") {
            updateWinProbabilities();
        }
    }

    function clearSlot(slot, options = {}) {
        if (!slot) {
            return;
        }

        const { keepFocus = false, suppressUpdate = false } = options;
        const cardId = slot.dataset.cardId;
        if (!cardId) {
            if (keepFocus) {
                setActiveSlot(slot);
            } else if (state.activeSlot === slot) {
                setActiveSlot(null);
                ensureActiveSlot();
            }
            return;
        }

        slot.classList.remove("filled");
        delete slot.dataset.cardId;

        const valueEl = slot.querySelector(".card-value");
        valueEl.classList.remove("red");
        valueEl.querySelector(".rank").textContent = "";
        valueEl.querySelector(".suit").textContent = "";

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

    function setActiveSlot(slot) {
        if (state.activeSlot === slot) {
            return;
        }

        if (state.activeSlot) {
            state.activeSlot.classList.remove("active");
        }

        state.activeSlot = slot;

        if (state.activeSlot) {
            state.activeSlot.classList.add("active");
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
            const isInactivePlayer = slot.dataset.slotType === "player" && Number(slot.dataset.playerIndex) >= state.playersCount;
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
            if (!isActive) {
                clearSlot(state.slotByKey.get(`player-${index}-0`), { suppressUpdate: true });
                clearSlot(state.slotByKey.get(`player-${index}-1`), { suppressUpdate: true });
            }
        });
        state.deferProbabilityUpdate = wasDeferred;
        if (!state.deferProbabilityUpdate) {
            scheduleImmediateProbabilityUpdate();
        }
        ensureActiveSlot("player");
    }

    function updatePlayerCountLabel() {
        if (elements.playerCountLabel) {
            elements.playerCountLabel.textContent = `${state.playersCount} \u05e9\u05d7\u05e7\u05e0\u05d9\u05dd`;
        }
    }

    function setPlayersCount(count) {
        const next = Math.min(MAX_PLAYERS, Math.max(MIN_PLAYERS, count));
        if (next === state.playersCount) {
            return;
        }

        for (let i = next; i < state.playersCount; i += 1) {
            clearSlot(state.slotByKey.get(`player-${i}-0`), { suppressUpdate: true });
            clearSlot(state.slotByKey.get(`player-${i}-1`), { suppressUpdate: true });
        }

        state.playersCount = next;
        updateSeatStates();
        updatePlayerCountLabel();
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

        scheduleImmediateProbabilityUpdate();
    }

    function bindControls() {
        elements.addPlayer?.addEventListener("click", () => setPlayersCount(state.playersCount + 1));
        elements.removePlayer?.addEventListener("click", () => setPlayersCount(state.playersCount - 1));
        elements.dealRandom?.addEventListener("click", () => dealRandom());
        elements.clearAll?.addEventListener("click", () => clearAllSlots());
        if (elements.calculate) {
            elements.calculate.disabled = true;
            elements.calculate.style.display = "none";
            elements.calculate.setAttribute("aria-hidden", "true");
            elements.calculate.tabIndex = -1;
        }
        elements.reset?.addEventListener("click", () => {
            setPlayersCount(MIN_PLAYERS);
            clearAllSlots();
        });
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
                const playerIndex = Number(slot.dataset.playerIndex);
                if (Number.isNaN(playerIndex) || playerIndex >= state.playersCount) {
                    return;
                }
            }
            slots.push(slot);
        });
        return slots.sort((a, b) => Number(a.dataset.order) - Number(b.dataset.order));
    }

    function collectPlayersData() {
        const players = [];
        for (let i = 0; i < state.playersCount; i += 1) {
            const slotA = state.slotByKey.get(`player-${i}-0`);
            const slotB = state.slotByKey.get(`player-${i}-1`);
            const cardIds = [slotA?.dataset.cardId, slotB?.dataset.cardId].filter(Boolean);
            const cards = cardIds.map((id) => getCardById(id));
            players.push({
                index: i,
                slots: [slotA, slotB],
                cardIds,
                cards
            });
        }
        return players;
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
            players.forEach((_, index) => {
                updateProbabilityLabel(index, { win: PROBABILITY_PLACEHOLDER, tie: PROBABILITY_PLACEHOLDER });
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
            updateProbabilityLabel(index, {
                win: formatProbability(winRatio),
                tie: formatProbability(tieRatio)
            });
        });

        probabilityData.forEach(({ shareRatio }, index) => {
            if (shareRatio >= bestShare - HIGHLIGHT_EPSILON) {
                setProbabilityHighlight(index, true);
            }
        });

        const isBoardComplete = boardCards.length === 5;
        const allPlayersComplete = players.every((player) => player.cards.length === 2);

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

    function bestScoreForCards(holeCards, boardCards) {
        const pool = scoreOnlyPoolScratch.pool;
        const poolLength = fillCardPool(holeCards, boardCards, pool);
        return bestHandScoreFromPool(pool, poolLength);
    }

    function calculateWinShares(players, boardCards, remainingCards) {
        const drawsNeeded = 5 - boardCards.length;
        const shares = new Array(players.length).fill(0);
        const winCounts = new Array(players.length).fill(0);
        const tieCounts = new Array(players.length).fill(0);
        let simulations = 0;

        if (drawsNeeded < 0) {
            return { shares, winCounts, tieCounts, simulations };
        }

        const missingHoleCounts = players.map((player) => Math.max(0, 2 - player.cards.length));
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
                const cacheKey = playerKey + '|' + boardKey;
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

            if (totalCombos && totalCombos <= ENUMERATION_LIMIT) {
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

                for (let iter = 0; iter < PREFLOP_SIMULATIONS; iter += 1) {
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
        const playerHands = players.map(() => new Array(2));
        const boardBaseLength = boardCards.length;
        const boardBuffer = new Array(boardBaseLength + drawsNeeded);

        for (let i = 0; i < boardBaseLength; i += 1) {
            boardBuffer[i] = boardCards[i];
        }

        const iterations = PREFLOP_SIMULATIONS;

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

    function bestHandForPlayer(holeCards, boardCards) {
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
            cancelScheduledProbabilityUpdate();
            state.mode = "solver";
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
    }

    function bindModeControls() {
        if (!elements.modeToggle) {
            return;
        }
        elements.modeToggle.addEventListener("click", () => {
            setMode(state.mode === "equity" ? "solver" : "equity");
        });
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
        if (elements.modeToggle) {
            elements.modeToggle.setAttribute("aria-pressed", isSolver ? "true" : "false");
            elements.modeToggle.textContent = isSolver ? "\u05d7\u05d6\u05e8\u05d4 \u05dc\u05de\u05d7\u05e9\u05d1\u05d5\u05df \u05d4\u05e1\u05ea\u05d1\u05e8\u05d5\u05d9\u05d5\u05ea" : "\u05e2\u05d1\u05d5\u05e8 \u05dc\u05e1\u05d5\u05dc\u05d1\u05e8 GTO";
        }
        if (elements.controls) {
            elements.controls.classList.toggle("is-solver-mode", isSolver);
        }
        if (elements.addPlayer) {
            elements.addPlayer.disabled = isSolver;
        }
        if (elements.removePlayer) {
            elements.removePlayer.disabled = isSolver;
        }
        if (elements.solverSettingsToggle) {
            elements.solverSettingsToggle.hidden = !isSolver;
            elements.solverSettingsToggle.setAttribute("aria-hidden", isSolver ? "false" : "true");
        }
        if (elements.solverControls) {
            elements.solverControls.hidden = !isSolver;
        }
        if (isSolver) {
            setSolverPanelOpen(state.isSolverPanelOpen);
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
            renderSolverPlaceholder(SOLVER_MESSAGES.heroCardsRequired);
            return;
        }
        const boardCards = collectBoardCards();
        if (boardCards.length > 5) {
            renderSolverPlaceholder(SOLVER_MESSAGES.boardTooLong);
            return;
        }
        const assignedIds = new Set();
        hero.cards.forEach((card) => assignedIds.add(card.id));
        boardCards.forEach((card) => assignedIds.add(card.id));
        state.cardAssignments.forEach((slot, cardId) => {
            assignedIds.add(cardId);
        });
        const availableForVillain = [];
        state.deck.forEach((card) => {
            if (!assignedIds.has(card.id)) {
                availableForVillain.push(card);
            }
        });
        if (availableForVillain.length < 2) {
            renderSolverPlaceholder(SOLVER_MESSAGES.insufficientDeck);
            return;
        }
        const profile = SOLVER_PROFILES.has(state.solverSettings.opponentProfile)
            ? state.solverSettings.opponentProfile
            : DEFAULT_SOLVER_SETTINGS.opponentProfile;
        const villainRange = buildVillainRange(availableForVillain, profile);
        if (!villainRange.combos.length || villainRange.totalWeight <= 0) {
            renderSolverPlaceholder(SOLVER_MESSAGES.rangeUnavailable);
            return;
        }
        const iterations = Math.max(villainRange.combos.length, Math.max(1000, Number(state.solverSettings.iterations) || 1000));
        const simulation = simulateRangeMatchup(hero.cards, boardCards, villainRange, iterations);
        if (!simulation.samples) {
            renderSolverPlaceholder(SOLVER_MESSAGES.simulationFailed);
            return;
        }
        const heroEquity = (simulation.heroWins + simulation.heroTies * 0.5) / simulation.samples;
        const potSize = Math.max(0, Number(state.solverSettings.potSize) || 0);
        const effectiveStack = Math.max(0, Number(state.solverSettings.effectiveStack) || 0);
        const betPercent = Math.max(1, Number(state.solverSettings.betSizePercent) || 0) / 100;
        const proposedBet = potSize > 0 ? potSize * betPercent : betPercent;
        const betAmount = Math.min(effectiveStack, proposedBet);
        if (betAmount <= 0) {
            renderSolverPlaceholder(SOLVER_MESSAGES.betParametersMissing);
            return;
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
                    hero: { cards: hero.cards, equity: heroEquity },
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
                if (aggregated && Array.isArray(aggregated.results)) {
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
                if (solverOutput && integrationSummaries.length === 0) {
                    integrationSummaries.push({
                        id: "singleStreetCfr",
                        label: "Single Street CFR",
                        ok: true,
                        origin: "AlphaPoker core",
                        version: "legacy",
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
            renderSolverResults({
                heroCards: hero.cards,
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
                iterations: simulation.samples,
                combosCount: villainRange.combos.length,
                confidence,
                profile,
                boardStage: boardCards.length,
                recommendation,
                integrations: integrationSummaries
            });
            return;
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
        const rawRecommendation = describeHeroAction(heroEquity, callThreshold, betAdvantage);
        const mixDetail = `${formatSolverPercent(heroBetFrequency)} \u05d4\u05d9\u05de\u05d5\u05e8 / ${formatSolverPercent(heroCheckFrequency)} \u05e6'\u05e7`;
        const responseDetail = `${formatSolverPercent(heroCallFrequency)} \u05e7\u05d5\u05dc \u05de\u05d5\u05dc \u05d4\u05d9\u05de\u05d5\u05e8`;
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
        renderSolverResults({
            heroCards: hero.cards,
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
            iterations: Math.round(iterations + simulation.samples),
            combosCount: villainRange.combos.length,
            confidence,
            profile,
            boardStage: boardCards.length,
            recommendation,
            integrations: integrationSummaries
        });
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
        metrics.appendChild(createMetricRow("\u05db\u05d9\u05e1\u05d5\u05d9 \u05d1\u05dc\u05d5\u05e4\u05d9\u05dd \u05dc\u05e2\u05d5\u05de\u05ea \u05e2\u05e8\u05da", `${formatSolverPercent(data.bluffCoverage)} / ${formatSolverPercent(data.optimalBluffRatio)}`, "Actual / Optimal"));
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
        title.textContent = entry && entry.label ? entry.label : (entry && entry.id ? entry.id : "Solver");
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
                appendIntegrationRow(body, "EV", `${formatSolverEV(summary.evBet)} / ${formatSolverEV(summary.evCheck)}`);
                populated = true;
            }
            if (summary.callThreshold !== undefined) {
                appendIntegrationRow(body, "\u05e1\u05e3 \u05e7\u05e8\u05d9\u05d0\u05d4", formatSolverPercent(summary.callThreshold));
                populated = true;
            }
        }
        if (!populated && entry && entry.detail && entry.detail.metrics) {
            const metrics = entry.detail.metrics;
            appendIntegrationRow(body, "Equity \u05de\u05de\u05d5\u05e6\u05e2", formatSolverPercent(metrics.weightedEquity || 0));
            appendIntegrationRow(body, "EV \u05d4\u05d9\u05de\u05d5\u05e8", formatSolverEV(metrics.weightedEvBet || 0));
            appendIntegrationRow(body, "EV \u05e6\u05e7", formatSolverEV(metrics.weightedEvCheck || 0));
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

    function getCardById(id) {
        return id ? state.cardById.get(id) : null;
    }
})();
















