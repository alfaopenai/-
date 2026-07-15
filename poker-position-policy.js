(function exposePokerPositionPolicy(root, factory) {
    const policy = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = policy;
    }
    if (root) {
        Object.defineProperty(root, "AlphaPokerPositionPolicy", {
            configurable: false,
            enumerable: false,
            writable: false,
            value: policy
        });
    }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    const POSITIONS_BY_PLAYER_COUNT = Object.freeze({
        2: Object.freeze(["SB", "BB"]),
        3: Object.freeze(["BTN", "SB", "BB"]),
        4: Object.freeze(["BTN", "SB", "BB", "CO"]),
        5: Object.freeze(["BTN", "SB", "BB", "UTG", "CO"]),
        6: Object.freeze(["BTN", "SB", "BB", "UTG", "HJ", "CO"]),
        7: Object.freeze(["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"]),
        8: Object.freeze(["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"]),
        9: Object.freeze(["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"])
    });

    const POSITION_ALIASES = Object.freeze({
        D: "BTN",
        DEALER: "BTN",
        BUTTON: "BTN",
        BTN: "BTN",
        "BTN/SB": "BTN/SB",
        "SB/BTN": "BTN/SB",
        SB: "SB",
        BB: "BB",
        UTG: "UTG",
        "UTG+1": "UTG+1",
        "UTG+2": "UTG+2",
        MP: "MP",
        LJ: "LJ",
        HJ: "HJ",
        CO: "CO"
    });

    const POSITION_LABELS = Object.freeze({
        BTN: "דילר",
        "BTN/SB": "דילר / סמול בליינד",
        SB: "סמול בליינד",
        BB: "ביג בליינד",
        UTG: "UTG",
        "UTG+1": "UTG+1",
        "UTG+2": "UTG+2",
        MP: "מידל פוזישן",
        LJ: "לואו ג'ק",
        HJ: "הייג'ק",
        CO: "קאט-אוף"
    });

    function getPositionSequence(playerCount) {
        const normalizedCount = Number(playerCount);
        const positions = POSITIONS_BY_PLAYER_COUNT[normalizedCount];
        return positions ? [...positions] : [];
    }

    function normalizePosition(position) {
        const normalized = String(position || "")
            .trim()
            .toUpperCase()
            .replace(/\s+/g, "");
        return POSITION_ALIASES[normalized] || "";
    }

    function formatPositionLabel(position, playerCount) {
        const normalized = normalizePosition(position);
        if (normalized === "SB" && Number(playerCount) === 2) {
            return POSITION_LABELS["BTN/SB"];
        }
        return POSITION_LABELS[normalized] || "";
    }

    function buildPositionAssignments(seats, dealerSeatIndex) {
        const seatByIndex = new Map();
        (Array.isArray(seats) ? seats : []).forEach((seat) => {
            const physicalSeatIndex = Number(seat?.physicalSeatIndex);
            if (
                seat
                && seat.active !== false
                && Number.isInteger(physicalSeatIndex)
                && physicalSeatIndex >= 0
                && physicalSeatIndex <= 8
            ) {
                seatByIndex.set(physicalSeatIndex, seat);
            }
        });
        const activeSeats = [...seatByIndex.entries()]
            .sort(([left], [right]) => left - right);
        const playerCount = activeSeats.length;
        const fallbackPositions = getPositionSequence(playerCount);
        if (!playerCount || !fallbackPositions.length) {
            return [];
        }

        const requestedDealer = Number(dealerSeatIndex);
        const activeIndexes = activeSeats.map(([physicalSeatIndex]) => physicalSeatIndex);
        const dealerIndex = activeIndexes.includes(requestedDealer)
            ? requestedDealer
            : activeIndexes[0];
        const dealerOrderIndex = activeIndexes.indexOf(dealerIndex);

        return activeSeats.map(([physicalSeatIndex, seat], activeOrderIndex) => {
            const relativeIndex = (activeOrderIndex - dealerOrderIndex + playerCount) % playerCount;
            const snapshotPosition = normalizePosition(seat.position);
            const position = snapshotPosition || fallbackPositions[relativeIndex] || "";
            return {
                physicalSeatIndex,
                position,
                label: formatPositionLabel(position, playerCount),
                source: snapshotPosition ? "snapshot" : "fallback"
            };
        });
    }

    return Object.freeze({
        POSITIONS_BY_PLAYER_COUNT,
        buildPositionAssignments,
        formatPositionLabel,
        getPositionSequence,
        normalizePosition
    });
}));
