const assert = require("node:assert/strict");
const {
    buildPositionAssignments,
    formatPositionLabel,
    getPositionSequence,
    normalizePosition
} = require("../poker-position-policy");

const EXPECTED_POSITIONS = Object.freeze({
    2: ["SB", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]
});

function positionMap(assignments) {
    return Object.fromEntries(assignments.map((assignment) => [
        assignment.physicalSeatIndex,
        assignment.position
    ]));
}

function runPositionPolicySmoke() {
    for (let playerCount = 2; playerCount <= 9; playerCount += 1) {
        assert.deepEqual(
            getPositionSequence(playerCount),
            EXPECTED_POSITIONS[playerCount],
            `${playerCount}-handed position sequence`
        );
    }
    assert.deepEqual(getPositionSequence(1), []);
    assert.deepEqual(getPositionSequence(10), []);

    const exactUserSeats = [
        { physicalSeatIndex: 0, active: true, position: "UTG" },
        { physicalSeatIndex: 3, active: true, position: "HJ" },
        { physicalSeatIndex: 4, active: true, position: "CO" },
        { physicalSeatIndex: 5, active: true, position: "BTN" },
        { physicalSeatIndex: 6, active: true, position: "SB" },
        { physicalSeatIndex: 7, active: true, position: "BB" }
    ];
    const expectedSparseMapping = {
        0: "UTG",
        3: "HJ",
        4: "CO",
        5: "BTN",
        6: "SB",
        7: "BB"
    };
    const explicitAssignments = buildPositionAssignments(exactUserSeats, 5);
    assert.deepEqual(positionMap(explicitAssignments), expectedSparseMapping);
    assert.ok(explicitAssignments.every((assignment) => assignment.source === "snapshot"));

    const explicitAssignmentsWithConflictingDealer = buildPositionAssignments(exactUserSeats, 4);
    assert.deepEqual(
        positionMap(explicitAssignmentsWithConflictingDealer),
        expectedSparseMapping,
        "validated snapshot positions take priority over recomputation"
    );

    const fallbackAssignments = buildPositionAssignments(
        exactUserSeats.map(({ position, ...seat }) => seat),
        5
    );
    assert.deepEqual(
        positionMap(fallbackAssignments),
        expectedSparseMapping,
        "sparse physical seats use the correct six-handed fallback"
    );
    assert.ok(fallbackAssignments.every((assignment) => assignment.source === "fallback"));

    assert.equal(normalizePosition(" button "), "BTN");
    assert.equal(normalizePosition("utg + 1"), "UTG+1");
    assert.equal(normalizePosition("invalid"), "");
    assert.equal(formatPositionLabel("BTN", 6), "דילר");
    assert.equal(formatPositionLabel("SB", 2), "דילר / סמול בליינד");
    assert.equal(formatPositionLabel("HJ", 6), "הייג'ק");
    assert.equal(formatPositionLabel("CO", 6), "קאט-אוף");
}

if (require.main === module) {
    try {
        runPositionPolicySmoke();
        console.log("position-policy-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runPositionPolicySmoke };
