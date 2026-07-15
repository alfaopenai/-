async page => {
    let requestCount = 0;
    const shown = (rank, suit) => ({
        rank,
        suit,
        visible: true,
        hidden: false,
        confidence: 0.96
    });
    const hidden = () => ({
        visible: false,
        hidden: true,
        display: "X",
        confidence: 0.95
    });
    const extraHands = [
        [shown("2", "C"), shown("2", "S")],
        [shown("4", "H"), shown("4", "S")],
        [shown("5", "C"), shown("5", "H")],
        [shown("6", "C"), shown("6", "D")],
        [shown("8", "C"), shown("8", "D")],
        [shown("10", "C"), shown("10", "H")]
    ];
    const makeSnapshot = (filtered, tied = false) => ({
        source: "ggclub",
        timestamp: Date.now() + requestCount,
        tableType: "8max",
        handId: "equity-smoke",
        street: "river",
        pot: 100,
        dealerSeatIndex: 0,
        board: tied
            ? [shown("5", "D"), shown("6", "H"), shown("7", "S"), shown("8", "C"), shown("9", "D")]
            : [shown("10", "D"), shown("3", "D"), shown("7", "H"), shown("K", "S"), shown("7", "S")],
        seats: Array.from({ length: 8 }, (_item, index) => ({
            physicalSeatIndex: index,
            active: true,
            name: `P${index}`,
            stack: 100,
            currentBet: 0,
            status: filtered && index >= 2
                ? ([2, 3].includes(index)
                    ? "folded"
                    : (index === 4 ? "empty" : (index === 5 ? "sitting_out" : "active")))
                : "active",
            action: filtered && index >= 2 && [3, 6, 7].includes(index)
                ? "fold"
                : (index < 2 ? "all-in" : "none"),
            holeCards: index === 0
                ? [shown("K", "C"), shown("J", "C")]
                : (index === 1
                    ? [shown("A", "S"), shown("Q", "C")]
                    : (filtered ? [hidden(), hidden()] : extraHands[index - 2])),
            confidence: 0.95
        })),
        confidence: 0.95
    });

    await page.route("**/mock/gg_snapshot_example.json", async (route) => {
        requestCount += 1;
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(makeSnapshot(requestCount >= 2, requestCount >= 3))
        });
    });
    await page.reload({ waitUntil: "domcontentloaded" });

    const probabilityTexts = () => page.locator(".seat .probability-win").evaluateAll(
        (elements) => elements.slice(0, 8).map((element) => element.textContent || "")
    );

    await page.locator("#read-gg-table").click();
    await page.waitForFunction(() => {
        const labels = [...document.querySelectorAll(".seat .probability-win")].slice(0, 8);
        return labels.length === 8 && labels.every((label) => /%/.test(label.textContent || ""));
    }, null, { timeout: 20000 });
    const beforeFiltering = await probabilityTexts();

    await page.locator("#read-gg-table").click();
    await page.waitForFunction(() => {
        const labels = [...document.querySelectorAll(".seat .probability-win")].slice(0, 8);
        return labels.length === 8
            && labels.slice(0, 2).every((label) => /%/.test(label.textContent || ""))
            && labels.slice(2).every((label) => /:\s*-$/.test(label.textContent || ""));
    }, null, { timeout: 20000 });
    const afterFiltering = await probabilityTexts();

    if (!/100\.00%/.test(afterFiltering[0]) || !/0\.00%/.test(afterFiltering[1])) {
        throw new Error(`unexpected heads-up result: ${JSON.stringify(afterFiltering.slice(0, 2))}`);
    }
    await page.screenshot({
        path: "output/playwright/equity-reader-filter-smoke.png",
        fullPage: true
    });

    await page.locator("#read-gg-table").click();
    await page.waitForFunction(() => {
        const labels = [...document.querySelectorAll(".seat .probability-win")].slice(0, 8);
        return labels.length === 8
            && labels.slice(0, 2).every((label) => /50\.00%/.test(label.textContent || ""))
            && labels.slice(2).every((label) => /:\s*-$/.test(label.textContent || ""));
    }, null, { timeout: 20000 });
    const splitTie = await probabilityTexts();
    await page.screenshot({
        path: "output/playwright/equity-reader-split-tie-smoke.png",
        fullPage: true
    });

    return { requestCount, beforeFiltering, afterFiltering, splitTie };
}
