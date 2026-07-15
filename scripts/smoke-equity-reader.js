const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_PATH = path.resolve(__dirname, "..", "app.js");

function extractFunction(source, name) {
    const marker = `    function ${name}(`;
    const start = source.indexOf(marker);
    assert.notEqual(start, -1, `missing ${name} in app.js`);
    const nextFunction = source.indexOf("\n    function ", start + marker.length);
    assert.notEqual(nextFunction, -1, `could not delimit ${name} in app.js`);
    return source.slice(start, nextFunction);
}

function loadEquityReaderFunctions() {
    const source = fs.readFileSync(APP_PATH, "utf8");
    const names = [
        "isGgSeatEligibleForEquity",
        "getEquityPlayerIndexes",
        "clearNonParticipantProbabilityLabels",
        "formatProbability",
        "formatGgProbability",
        "getGgEquityBoardContext",
        "getGgRunCards",
        "getGgSnapshotBoardCollections",
        "getGgSnapshotRunouts",
        "getAcceptedGgDeckCard",
        "getGgMultiRunContext",
        "buildGgBoardCollectionsSignature",
        "getGgProbabilityCardSignature",
        "buildGgProbabilitySnapshotSignature",
        "buildGgSnapshotSignature",
        "normalizeGgSuit",
        "getGgCardId"
    ];
    const updates = [];
    const highlights = [];
    const state = {
        playersCount: 8,
        probabilityDisplays: Array.from({ length: 8 }, () => ({})),
        ggReader: { lastSnapshot: null }
    };
    const context = {
        GG_READER_CARD_CONFIDENCE_MIN: 0.6,
        PROBABILITY_PLACEHOLDER: "-",
        state,
        updateProbabilityLabel: (index, values) => updates.push({ index, values }),
        setProbabilityHighlight: (index, active) => highlights.push({ index, active }),
        getGgCardId: (card) => {
            if (!card || !card.rank || !card.suit) {
                return "";
            }
            return `${String(card.rank).trim().toUpperCase()}${String(card.suit).trim().toUpperCase()}`;
        },
        getCardById: (id) => {
            const suitId = id.slice(-1);
            const rankId = id.slice(0, -1);
            const symbols = { S: "♠", H: "♥", D: "♦", C: "♣" };
            return {
                id,
                rank: { id: rankId, label: rankId },
                suit: { id: suitId, symbol: symbols[suitId] }
            };
        }
    };
    const snippets = names.map((name) => extractFunction(source, name)).join("\n");
    vm.runInNewContext(`${snippets}\nglobalThis.__equityReaderHooks = { ${names.join(", ")} };`, context);
    return { hooks: context.__equityReaderHooks, state, updates, highlights, source };
}

function card(rank, suit, confidence = 0.95) {
    return { rank, suit, visible: true, hidden: false, confidence };
}

function runEquityReaderSmoke() {
    const { hooks, state, updates, highlights, source } = loadEquityReaderFunctions();

    state.ggReader.lastSnapshot = {
        seats: [
            { physicalSeatIndex: 0, active: true, status: "active", action: "all-in" },
            { physicalSeatIndex: 1, active: true, status: "active", action: "none" },
            { physicalSeatIndex: 2, active: true, status: "folded", action: "none" },
            { physicalSeatIndex: 3, active: true, status: "active", action: "fold" },
            { physicalSeatIndex: 4, active: true, status: "empty", action: "none" },
            { physicalSeatIndex: 5, active: true, status: "sitting-out", action: "none" },
            { physicalSeatIndex: 6, active: false, status: "active", action: "none" },
            { physicalSeatIndex: 7, active: true, inHand: false, status: "active", action: "none" }
        ]
    };
    assert.deepEqual(Array.from(hooks.getEquityPlayerIndexes()), [0, 1]);
    assert.equal(hooks.isGgSeatEligibleForEquity({ active: true, status: "sitting out" }), false);
    assert.equal(hooks.isGgSeatEligibleForEquity({ active: true, status: "unknown" }), true);
    assert.equal(
        hooks.isGgSeatEligibleForEquity({ active: true, inHand: true, status: "folded", action: "fold" }),
        true,
        "explicit inHand is authoritative when the backend provides it"
    );

    state.ggReader.lastSnapshot = null;
    state.playersCount = 4;
    assert.deepEqual(Array.from(hooks.getEquityPlayerIndexes()), [0, 1, 2, 3], "manual mode retains every configured player");

    state.probabilityDisplays = Array.from({ length: 4 }, () => ({}));
    hooks.clearNonParticipantProbabilityLabels(new Set([0, 2]));
    assert.deepEqual(JSON.parse(JSON.stringify(updates)), [
        { index: 1, values: { win: "-", tie: "-" } },
        { index: 3, values: { win: "-", tie: "-" } }
    ]);
    assert.deepEqual(JSON.parse(JSON.stringify(highlights)), [
        { index: 1, active: false },
        { index: 3, active: false }
    ]);
    assert.equal(hooks.formatProbability(1, 2), "100.00%");
    assert.equal(hooks.formatProbability(0.5, 2), "50.00%");
    assert.equal(hooks.formatProbability(0, 2), "0.00%");
    assert.equal(hooks.formatGgProbability(6 / 42, 2), "14.28%", "ClubGG live percentages are truncated");

    const baseSnapshot = {
        street: "flop",
        pot: 101.5,
        dealerSeatIndex: 2,
        board: [card("J", "C"), card("9", "S"), card("3", "H")],
        seats: [
            {
                physicalSeatIndex: 0,
                active: true,
                status: "active",
                action: "all-in",
                holeCards: [card("J", "D"), card("9", "D", 0.59)]
            },
            {
                physicalSeatIndex: 1,
                active: true,
                status: "active",
                action: "all-in",
                holeCards: [card("A", "H"), card("J", "H")]
            },
            { physicalSeatIndex: 2, active: true, status: "folded", action: "none", holeCards: [] }
        ]
    };
    const pendingSignature = hooks.buildGgProbabilitySnapshotSignature(baseSnapshot);
    const acceptedSnapshot = structuredClone(baseSnapshot);
    acceptedSnapshot.seats[0].holeCards[1].confidence = 0.95;
    const acceptedSignature = hooks.buildGgProbabilitySnapshotSignature(acceptedSnapshot);
    assert.notEqual(
        pendingSignature,
        acceptedSignature,
        "crossing the accepted-card confidence threshold must invalidate the probability signature"
    );
    assert.equal(
        acceptedSignature,
        hooks.buildGgProbabilitySnapshotSignature(structuredClone(acceptedSnapshot)),
        "stable accepted cards retain a stable signature"
    );

    const foldedSnapshot = structuredClone(acceptedSnapshot);
    foldedSnapshot.seats[1].action = "fold";
    assert.notEqual(
        acceptedSignature,
        hooks.buildGgProbabilitySnapshotSignature(foldedSnapshot),
        "a Fold action must invalidate the participant signature"
    );

    const multiRun = {
        ...acceptedSnapshot,
        sharedBoard: [card("J", "C"), card("9", "S"), card("3", "H")],
        runouts: [
            { index: 0, cards: [card("4", "C"), card("K", "C")], complete: true },
            { index: 1, cards: [card("Q", "S")], complete: false }
        ]
    };
    const multiRunProbabilitySignature = hooks.buildGgProbabilitySnapshotSignature(multiRun);
    const activeRunContext = hooks.getGgEquityBoardContext(multiRun);
    assert.deepEqual(
        Array.from(activeRunContext.boardCards, (item) => item.id),
        ["JC", "9S", "3H", "QS"],
        "the currently incomplete run is the board used for live equity"
    );
    assert.deepEqual(
        Array.from(activeRunContext.deadCards, (item) => item.id),
        ["4C", "KC"],
        "cards dealt on the completed first run are dead for the second run"
    );
    assert.equal(activeRunContext.activeRunIndex, 1);
    assert.equal(activeRunContext.completedBoards.length, 0);

    const completedSecondRun = structuredClone(multiRun);
    completedSecondRun.runouts[1].cards.push(card("A", "D"));
    completedSecondRun.runouts[1].complete = true;
    const completeRunContext = hooks.getGgEquityBoardContext(completedSecondRun);
    assert.deepEqual(
        Array.from(completeRunContext.completedBoards, (board) => Array.from(board, (item) => item.id)),
        [
            ["JC", "9S", "3H", "4C", "KC"],
            ["JC", "9S", "3H", "QS", "AD"]
        ],
        "both complete boards remain available for final split-pot equity"
    );
    assert.notEqual(
        multiRunProbabilitySignature,
        hooks.buildGgProbabilitySnapshotSignature(completedSecondRun),
        "optional runout cards must participate in probability signatures"
    );
    assert.notEqual(
        hooks.buildGgSnapshotSignature(multiRun),
        hooks.buildGgSnapshotSignature(completedSecondRun),
        "optional runout cards must participate in raw snapshot signatures"
    );

    assert.match(source, /clearNonParticipantProbabilityLabels\(new Set\(players\.map/);
    assert.match(source, /const probabilityFormatter = state\.ggReader\?\.lastSnapshot \? formatGgProbability : formatProbability/);
    assert.match(source, /const ggBoardContext = getGgEquityBoardContext/);
    assert.match(source, /const isFolded = isActive && !isGgSeatEligibleForEquity\(seatSnapshot\)/);
}

if (require.main === module) {
    try {
        runEquityReaderSmoke();
        console.log("equity-reader-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runEquityReaderSmoke };
