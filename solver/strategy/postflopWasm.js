(function (global) {
    const root = typeof global !== "undefined" ? global : globalThis;
    const namespace = root.AlphaPoker || (root.AlphaPoker = Object.create(null));
    const registry = namespace.Solvers && typeof namespace.Solvers.register === "function" ? namespace.Solvers : null;

    function clampProbability(value) {
        if (!Number.isFinite(value)) {
            return 0;
        }
        return Math.max(0, Math.min(1, value));
    }

    function clampFinite(value, fallback = 0) {
        return Number.isFinite(value) ? value : fallback;
    }

    function computeCallUtility(equity, potSize, betSize) {
        const eq = clampProbability(equity);
        if (betSize <= 0) {
            return eq * potSize;
        }
        return eq * (potSize + 2 * betSize) - betSize;
    }

    function computeMoments(entries) {
        if (!entries.length) {
            return {
                mean: 0,
                variance: 0,
                stdev: 0,
                min: 0,
                max: 0,
                quantiles: {}
            };
        }
        let totalWeight = 0;
        let mean = 0;
        for (let i = 0; i < entries.length; i += 1) {
            const { value, weight } = entries[i];
            totalWeight += weight;
            mean += value * weight;
        }
        mean /= (totalWeight || 1);
        let variance = 0;
        for (let i = 0; i < entries.length; i += 1) {
            const { value, weight } = entries[i];
            const diff = value - mean;
            variance += diff * diff * weight;
        }
        variance /= (totalWeight || 1);
        const stdev = Math.sqrt(Math.max(0, variance));
        const sorted = entries.slice().sort((a, b) => a.value - b.value);
        const quantiles = {};
        const marks = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1];
        for (let i = 0; i < marks.length; i += 1) {
            const q = marks[i];
            const target = q * (totalWeight || 1);
            let acc = 0;
            let value = sorted[sorted.length - 1].value;
            for (let j = 0; j < sorted.length; j += 1) {
                acc += sorted[j].weight;
                if (acc >= target) {
                    value = sorted[j].value;
                    break;
                }
            }
            quantiles[q] = value;
        }
        return {
            mean,
            variance,
            stdev,
            min: sorted[0].value,
            max: sorted[sorted.length - 1].value,
            quantiles
        };
    }

    function buildHistogram(entries, binCount) {
        if (!entries.length) {
            return [];
        }
        const min = entries.reduce((m, item) => Math.min(m, item.value), entries[0].value);
        const max = entries.reduce((m, item) => Math.max(m, item.value), entries[0].value);
        const range = Math.max(1e-9, max - min);
        const bins = new Array(binCount).fill(null).map(() => ({ weight: 0, midpoint: 0 }));
        for (let i = 0; i < entries.length; i += 1) {
            const { value, weight } = entries[i];
            const ratio = (value - min) / range;
            let index = Math.floor(ratio * binCount);
            if (index >= binCount) {
                index = binCount - 1;
            }
            bins[index].weight += weight;
        }
        const totalWeight = bins.reduce((sum, bin) => sum + bin.weight, 0) || 1;
        for (let i = 0; i < bins.length; i += 1) {
            const midpoint = min + (i + 0.5) * (range / binCount);
            bins[i].midpoint = midpoint;
            bins[i].probability = bins[i].weight / totalWeight;
        }
        return bins;
    }

    function solveWasmStyleReport(context) {
        if (!context || !context.villainRange || !context.villainRange.combos || !context.villainRange.combos.length) {
            return null;
        }
        const combos = context.villainRange.combos;
        const potSize = Math.max(0, Number(context.potSize) || 0);
        const betSize = Math.max(0, Number(context.betSize) || 0);
        const stackSize = Math.max(0, Number(context.stackSize) || 0);
        const totalWeight = context.villainRange.totalWeight || 1;

        const analysis = [];
        let meanEquityNumerator = 0;
        let meanEvBetNumerator = 0;
        let meanEvCheckNumerator = 0;
        let meanRatioNumerator = 0;
        for (let i = 0; i < combos.length; i += 1) {
            const combo = combos[i];
            const weight = Number(combo.weight) || 0;
            if (weight <= 0) {
                continue;
            }
            const equity = clampProbability(Number(combo.heroEquity) || 0.5);
            const evBet = computeCallUtility(equity, potSize, betSize);
            const evCheck = equity * potSize;
            const ratioBase = equity * (potSize + 2 * betSize) || 0;
            const efficiency = ratioBase > 0 ? evBet / ratioBase : (evBet >= 0 ? Infinity : -Infinity);
            analysis.push({
                cards: combo.cards,
                weight,
                equity,
                evBet,
                evCheck,
                efficiency
            });
            meanEquityNumerator += equity * weight;
            meanEvBetNumerator += evBet * weight;
            meanEvCheckNumerator += evCheck * weight;
            meanRatioNumerator += clampFinite(efficiency, 0) * weight;
        }
        if (!analysis.length) {
            return null;
        }
        const weightedEquity = meanEquityNumerator / totalWeight;
        const weightedEvBet = meanEvBetNumerator / totalWeight;
        const weightedEvCheck = meanEvCheckNumerator / totalWeight;
        const weightedEfficiency = meanRatioNumerator / totalWeight;

        const equityMoments = computeMoments(analysis.map((item) => ({ value: item.equity, weight: item.weight })));
        const evBetMoments = computeMoments(analysis.map((item) => ({ value: item.evBet, weight: item.weight })));
        const efficiencyMoments = computeMoments(analysis.map((item) => ({ value: clampFinite(item.efficiency, 0), weight: item.weight })));
        const histogram = buildHistogram(analysis.map((item) => ({ value: item.equity, weight: item.weight })), 12);

        analysis.sort((a, b) => a.equity - b.equity);
        const trimmed = analysis.slice(0, Math.min(analysis.length, 200)).map((item) => ({
            cards: item.cards,
            equity: item.equity,
            evBet: item.evBet,
            evCheck: item.evCheck,
            efficiency: clampFinite(item.efficiency, 0),
            weightShare: item.weight / totalWeight
        }));

        return {
            metrics: {
                weightedEquity,
                weightedEvBet,
                weightedEvCheck,
                weightedEfficiency,
                equityMoments,
                evBetMoments,
                efficiencyMoments
            },
            histogram,
            report: trimmed,
            parameters: {
                potSize,
                betSize,
                stackSize,
                combos: analysis.length
            }
        };
    }

    const solverApi = {
        buildReport: solveWasmStyleReport
    };

    if (registry) {
        registry.register({
            id: "postflopWasm",
            label: "WASM Postflop Analytics",
            description: "Aggregated equity diagnostics inspired by wasm-postflop GameManager reports.",
            priority: 5,
            version: "0.1.0",
            origin: "Adapted from b-inary/wasm-postflop",
            solve(context) {
                const detail = solveWasmStyleReport(context);
                if (!detail) {
                    return { ok: false, diagnostics: { reason: "postflopWasm: invalid context" } };
                }
                return {
                    ok: true,
                    summary: null,
                    detail,
                    diagnostics: {
                        combos: detail.parameters.combos,
                        histogramBins: detail.histogram.length
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.PostflopWasm = solverApi;
})(typeof window !== "undefined" ? window : globalThis);
