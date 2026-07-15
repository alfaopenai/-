async page => {
    const shown = (rank, suit) => ({ rank, suit, visible: true, hidden: false, confidence: 0.96 });
    const hidden = () => ({ visible: false, hidden: true, display: "X", confidence: 0.95 });
    const sharedBoard = [shown("J", "C"), shown("9", "S"), shown("3", "H")];
    const snapshot = {
        source: "ggclub",
        timestamp: Date.now(),
        tableType: "8max",
        handId: "equity-smoke-multirun",
        street: "showdown",
        pot: 101.5,
        dealerSeatIndex: 2,
        board: [...sharedBoard, shown("4", "C"), shown("K", "C")],
        sharedBoard,
        runouts: [
            [shown("4", "C"), shown("K", "C")],
            [shown("Q", "S")]
        ],
        seats: Array.from({ length: 8 }, (_item, index) => ({
            physicalSeatIndex: index,
            active: true,
            inHand: index < 2,
            name: `P${index}`,
            stack: index < 2 ? 0 : 100,
            currentBet: 0,
            status: index < 2 ? "active" : "folded",
            action: index < 2 ? "all-in" : "fold",
            holeCards: index === 0
                ? [shown("J", "D"), shown("9", "D")]
                : (index === 1 ? [shown("A", "H"), shown("J", "H")] : [hidden(), hidden()]),
            confidence: 0.95
        })),
        confidence: 0.95
    };

    await page.route("**/mock/gg_snapshot_example.json", async route => route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(snapshot)
    }));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator("#read-gg-table").click();
    await page.waitForFunction(() => {
        const labels = [...document.querySelectorAll(".seat .probability-win")].slice(0, 8);
        const rows = [...document.querySelectorAll("#gg-runout-boards .gg-runout-board")];
        return /85\.71%/.test(labels[0]?.textContent || "")
            && /14\.28%/.test(labels[1]?.textContent || "")
            && labels.slice(2).every(label => /:\s*-$/.test(label.textContent || ""))
            && rows.length === 2
            && rows.every(row => row.querySelectorAll(".gg-runout-card").length === 5)
            && document.querySelector("#board-cards")?.hidden === true;
    }, null, { timeout: 20000 });

    const result = {
        probabilities: await page.locator(".seat .probability-win").evaluateAll(
            elements => elements.slice(0, 8).map(element => element.textContent || "")
        ),
        rows: await page.locator("#gg-runout-boards .gg-runout-board").evaluateAll(rows => rows.map(row => ({
            label: row.querySelector(".gg-runout-board__label")?.textContent || "",
            cards: [...row.querySelectorAll(".gg-runout-card")].map(card => card.getAttribute("aria-label"))
        })))
    };
    await page.screenshot({ path: "output/playwright/equity-reader-multirun-smoke.png", fullPage: true });
    return result;
}
