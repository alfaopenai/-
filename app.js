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

    let probabilityUpdateTimer = null;

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
        deferProbabilityUpdate: false
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
        results: document.getElementById("results")
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
        ensureActiveSlot();
        scheduleImmediateProbabilityUpdate();
    }

    function buildDeck() {
        state.deck = [];
        state.cardById.clear();

        suits.forEach((suit) => {
            ranks.forEach((rank) => {
                const card = {
                    id: `${rank.id}${suit.id}`,
                    rank,
                    suit,
                    rankValue: rankValue.get(rank.id)
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
        probability.textContent = PROBABILITY_PLACEHOLDER;

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
        state.probabilityDisplays[index] = probability;
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
                display.textContent = "";
                display.classList.remove("is-leading");
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
        if (state.deferProbabilityUpdate) {
            return;
        }
        if (probabilityUpdateTimer !== null) {
            const timerHost = typeof window !== "undefined" ? window : globalThis;
            timerHost.clearTimeout(probabilityUpdateTimer);
        }
        // Use requestAnimationFrame for fastest visual update
        requestAnimationFrame(() => {
            updateWinProbabilities();
        });
    }

    function cancelScheduledProbabilityUpdate() {
        if (probabilityUpdateTimer !== null) {
            const timerHost = typeof window !== "undefined" ? window : globalThis;
            timerHost.clearTimeout(probabilityUpdateTimer);
            probabilityUpdateTimer = null;
        }
    }

    function updateWinProbabilities(options = {}) {
        const { userInitiated = false } = options;
        const players = collectPlayersData();
        if (!players.length) {
            clearProbabilityHighlights();
            return;
        }

        const boardCards = collectBoardCards();
        const hasAssignments = state.cardAssignments.size > 0;
        const showMessages = userInitiated || hasAssignments;

        for (let i = state.playersCount; i < state.probabilityDisplays.length; i += 1) {
            const display = state.probabilityDisplays[i];
            if (display) {
                display.textContent = "";
                display.classList.remove("is-leading");
            }
        }

        clearProbabilityHighlights();

        for (let i = 0; i < players.length; i += 1) {
            updateProbabilityLabel(players[i].index, PROBABILITY_PLACEHOLDER);
        }

        const incompletePlayers = players.filter((player) => player.cards.length !== 2);
        if (incompletePlayers.length) {
            if (showMessages) {
                showError("\u05d9\u05e9 \u05dc\u05d4\u05e9\u05dc\u05d9\u05dd \u05e9\u05e0\u05d9 \u05e7\u05dc\u05e4\u05d9\u05dd \u05dc\u05db\u05dc \u05e9\u05d7\u05e7\u05df \u05e4\u05e2\u05d9\u05dc.");
            } else {
                showError("");
            }
            if (elements.results) {
                elements.results.innerHTML = "";
            }
            return;
        }

        const boardLength = boardCards.length;
        if (boardLength !== 0 && boardLength !== 3 && boardLength !== 4 && boardLength !== 5) {
            if (showMessages) {
                showError("\u05d1\u05d7\u05e8\u05d5 0, 3, 4 \u05d0\u05d5 5 \u05e7\u05dc\u05e4\u05d9\u05dd \u05de\u05e9\u05d5\u05ea\u05e4\u05d9\u05dd \u05dc\u05d7\u05d9\u05e9\u05d5\u05d1.");
            } else {
                showError("");
            }
            if (elements.results) {
                elements.results.innerHTML = "";
            }
            return;
        }

        const remainingCards = state.deck.filter((card) => !state.cardAssignments.has(card.id));
        const { shares, simulations } = calculateWinShares(players, boardCards, remainingCards);

        if (!simulations) {
            if (elements.results) {
                elements.results.innerHTML = "";
            }
            return;
        }

        showError("");

        let maxShare = 0;
        shares.forEach((value) => {
            if (value > maxShare) {
                maxShare = value;
            }
        });

        for (let i = 0; i < players.length; i += 1) {
            const probability = Math.max(0, shares[i] / simulations);
            updateProbabilityLabel(players[i].index, formatProbability(probability));
            const shouldHighlight = maxShare > 0 && Math.abs(shares[i] - maxShare) <= HIGHLIGHT_EPSILON;
            setProbabilityHighlight(players[i].index, shouldHighlight);
        }

        if (boardLength === 5) {
            if (elements.results) {
                elements.results.innerHTML = "";
            }
            renderFinalResults(players, boardCards);
        } else if (elements.results) {
            elements.results.innerHTML = "";
        }
    }

    // Cache for board evaluations to avoid recomputation
    const evaluationCache = new Map();

    function calculateWinShares(players, boardCards, remainingCards) {
        const drawsNeeded = 5 - boardCards.length;
        const shares = new Array(players.length).fill(0);
        let simulations = 0;

        if (drawsNeeded < 0) {
            return { shares, simulations };
        }

        // Create cache key for this specific scenario
        const cacheKey = players.map(p => p.cards.map(c => c.id).sort().join('')).join('|') +
                        '|' + boardCards.map(c => c.id).join('');

        const evaluateBoard = (board) => {
            // Check cache first
            const boardKey = board.map(c => c.id).sort().join('');
            let cachedResult = evaluationCache.get(boardKey);

            if (!cachedResult) {
                let bestScore = null;
                let winners = [];

                for (let i = 0; i < players.length; i++) {
                    const evaluation = bestHandForPlayer(players[i].cards, board);
                    if (bestScore === null) {
                        bestScore = evaluation.score;
                        winners = [i];
                        continue;
                    }
                    const comparison = compareScoresFast(evaluation.score, bestScore);
                    if (comparison > 0) {
                        bestScore = evaluation.score;
                        winners = [i];
                    } else if (comparison === 0) {
                        winners.push(i);
                    }
                }

                cachedResult = { winners, bestScore };

                // Limit cache size to prevent memory issues
                if (evaluationCache.size < 10000) {
                    evaluationCache.set(boardKey, cachedResult);
                }
            }

            const share = cachedResult.winners.length ? 1 / cachedResult.winners.length : 0;
            cachedResult.winners.forEach((index) => {
                shares[index] += share;
            });
            simulations++;
        };

        if (drawsNeeded === 0) {
            evaluateBoard(boardCards);
            return { shares, simulations };
        }

        if (remainingCards.length < drawsNeeded) {
            return { shares, simulations: 0 };
        }

        const totalCombos = combinationCount(remainingCards.length, drawsNeeded);
        const boardBuffer = [...boardCards];

        if (totalCombos && totalCombos <= ENUMERATION_LIMIT) {
            // Use optimized combination generation
            forEachCombinationFast(remainingCards, drawsNeeded, (combo) => {
                boardBuffer.length = boardCards.length;
                boardBuffer.push(...combo);
                evaluateBoard(boardBuffer);
            });
        } else {
            // Optimized Monte Carlo with reduced array operations
            const drawBuffer = new Array(drawsNeeded);
            const remainingLength = remainingCards.length;

            // Pre-allocate arrays for better performance
            const tempIndices = new Uint8Array(remainingLength);
            for (let i = 0; i < remainingLength; i++) tempIndices[i] = i;

            for (let iter = 0; iter < PREFLOP_SIMULATIONS; iter++) {
                // Ultra-fast Fisher-Yates sampling
                for (let i = 0; i < drawsNeeded; i++) {
                    const j = i + Math.floor(Math.random() * (remainingLength - i));
                    [tempIndices[i], tempIndices[j]] = [tempIndices[j], tempIndices[i]];
                    drawBuffer[i] = remainingCards[tempIndices[i]];
                }

                boardBuffer.length = boardCards.length;
                boardBuffer.push(...drawBuffer);
                evaluateBoard(boardBuffer);
            }
        }

        return { shares, simulations };
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

    function updateProbabilityLabel(index, text) {
        const display = state.probabilityDisplays[index];
        if (display) {
            display.textContent = text;
        }
    }

    function setProbabilityHighlight(index, isActive) {
        const display = state.probabilityDisplays[index];
        if (display) {
            display.classList.toggle("is-leading", Boolean(isActive));
        }
    }

    function clearProbabilityHighlights() {
        state.probabilityDisplays.forEach((display) => {
            display?.classList.remove("is-leading");
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
        const allCards = [...holeCards, ...boardCards];
        let bestScore = null;
        let bestHand = null;

        // Fast combination generation using indices
        const n = allCards.length;
        for (let a = 0; a < n - 4; a++) {
            for (let b = a + 1; b < n - 3; b++) {
                for (let c = b + 1; c < n - 2; c++) {
                    for (let d = c + 1; d < n - 1; d++) {
                        for (let e = d + 1; e < n; e++) {
                            const combo = [allCards[a], allCards[b], allCards[c], allCards[d], allCards[e]];
                            const evaluation = evaluateFiveCardsFast(combo);
                            if (!bestScore || compareScoresFast(evaluation.score, bestScore) > 0) {
                                bestScore = evaluation.score;
                                bestHand = evaluation;
                            }
                        }
                    }
                }
            }
        }
        return bestHand;
    }

    // Optimized fast evaluation that avoids object creation
    function evaluateFiveCardsFast(cards) {
        const rankCounts = new Int8Array(13);
        const suitCounts = new Int8Array(4);
        const values = new Int8Array(5);

        // Count ranks and suits, store values
        for (let i = 0; i < 5; i++) {
            const card = cards[i];
            rankCounts[card.rankValue]++;
            suitCounts[getSuitIndex(card.suit.id)]++;
            values[i] = card.rankValue;
        }

        // Sort values descending for easier processing
        values.sort((a, b) => b - a);

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
        const len = Math.min(a.length, b.length);
        for (let i = 0; i < len; i++) {
            if (a[i] > b[i]) return 1;
            if (a[i] < b[i]) return -1;
        }
        return a.length - b.length;
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
