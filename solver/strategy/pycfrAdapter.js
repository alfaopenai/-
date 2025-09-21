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

    function createInfoSet(actionCount) {
        return {
            regret: new Array(actionCount).fill(0),
            strategy: new Array(actionCount).fill(0),
            strategySum: new Array(actionCount).fill(0),
            visitWeight: 0
        };
    }

    function regretMatching(infoSet) {
        let positiveSum = 0;
        for (let i = 0; i < infoSet.regret.length; i += 1) {
            const positive = infoSet.regret[i] > 0 ? infoSet.regret[i] : 0;
            infoSet.strategy[i] = positive;
            positiveSum += positive;
        }
        if (positiveSum <= 1e-12) {
            const uniform = 1 / infoSet.strategy.length;
            for (let i = 0; i < infoSet.strategy.length; i += 1) {
                infoSet.strategy[i] = uniform;
            }
        } else {
            for (let i = 0; i < infoSet.strategy.length; i += 1) {
                infoSet.strategy[i] /= positiveSum;
            }
        }
        return infoSet.strategy;
    }

    function computeCallUtility(equity, potSize, betSize) {
        const eq = clampProbability(equity);
        if (betSize <= 0) {
            return eq * potSize;
        }
        return eq * (potSize + 2 * betSize) - betSize;
    }

    function sampleIterations(context, comboCount) {
        const base = Number(context && context.iterations) || 3000;
        const capped = Math.max(400, Math.min(base, 8000));
        if (comboCount <= 120) {
            return capped;
        }
        const scale = Math.sqrt(comboCount / 120);
        return Math.floor(capped / scale);
    }

    function buildComboDetails(totalWeight, analysis) {
        const summaries = [];
        for (let i = 0; i < analysis.length; i += 1) {
            const item = analysis[i];
            summaries.push({
                cards: item.cards,
                heroEquity: item.equity,
                callProbability: clampProbability(item.callProbability),
                weightShare: item.weight / (totalWeight || 1)
            });
        }
        summaries.sort((a, b) => b.callProbability - a.callProbability || b.heroEquity - a.heroEquity);
        return summaries;
    }

    function quantizeProbabilities(analysis, bucketCount) {
        if (!analysis.length) {
            return [];
        }
        const sorted = analysis.slice().sort((a, b) => a.equity - b.equity);
        const buckets = [];
        const target = Math.max(1, Math.floor(sorted.length / bucketCount));
        let currentWeight = 0;
        let currentEquitySum = 0;
        let currentCallSum = 0;
        let currentBetAfterCheckSum = 0;
        let items = 0;
        for (let i = 0; i < sorted.length; i += 1) {
            const item = sorted[i];
            currentWeight += item.weight;
            currentEquitySum += item.equity * item.weight;
            currentCallSum += item.callProbability * item.weight;
            currentBetAfterCheckSum += item.betAfterCheckProbability * item.weight;
            items += 1;
            if (items >= target && buckets.length < bucketCount - 1) {
                buckets.push({
                    weight: currentWeight,
                    averageEquity: currentEquitySum / (currentWeight || 1),
                    callProbability: currentCallSum / (currentWeight || 1),
                    betAfterCheckProbability: currentBetAfterCheckSum / (currentWeight || 1)
                });
                currentWeight = 0;
                currentEquitySum = 0;
                currentCallSum = 0;
                currentBetAfterCheckSum = 0;
                items = 0;
            }
        }
        if (currentWeight > 0 || !buckets.length) {
            buckets.push({
                weight: currentWeight,
                averageEquity: currentEquitySum / (currentWeight || 1),
                callProbability: currentCallSum / (currentWeight || 1),
                betAfterCheckProbability: currentBetAfterCheckSum / (currentWeight || 1)
            });
        }
        const totalWeight = buckets.reduce((sum, bucket) => sum + bucket.weight, 0) || 1;
        return buckets.map((bucket) => ({
            probability: bucket.weight / totalWeight,
            callProbability: clampProbability(bucket.callProbability),
            betAfterCheckProbability: clampProbability(bucket.betAfterCheckProbability),
            averageEquity: clampProbability(bucket.averageEquity)
        }));
    }

    function solvePycfrStyle(context) {
        if (!context || !context.villainRange || !context.villainRange.combos || !context.villainRange.combos.length) {
            return null;
        }
        const combos = context.villainRange.combos;
        const totalWeight = context.villainRange.totalWeight;
        if (!Number.isFinite(totalWeight) || totalWeight <= 0) {
            return null;
        }
        const potSize = Math.max(0, Number(context.potSize) || 0);
        const stackSize = Math.max(0, Number(context.stackSize) || 0);
        const heroBetSize = Math.max(0, Number(context.betSize) || 0);
        const villainBetSize = Math.max(0, Math.min(stackSize, potSize * 0.75 || heroBetSize || potSize));
        const iterations = sampleIterations(context, combos.length);

        const equities = new Array(combos.length);
        const weights = new Array(combos.length);
        for (let i = 0; i < combos.length; i += 1) {
            equities[i] = clampProbability(Number(combos[i].heroEquity) || 0.5);
            weights[i] = Number(combos[i].weight) || 0;
        }

        const heroRoot = createInfoSet(2); // bet, check
        const heroResponse = createInfoSet(2); // fold, call
        const villainVsBet = combos.map(() => createInfoSet(2));
        const villainDonk = combos.map(() => createInfoSet(2));

        let aggregateBetValue = 0;
        let aggregateCheckValue = 0;

        for (let iteration = 0; iteration < iterations; iteration += 1) {
            const heroStrategy = regretMatching(heroRoot);
            const betProb = heroStrategy[0];
            const checkProb = heroStrategy[1];

            for (let i = 0; i < combos.length; i += 1) {
                const weightShare = weights[i] / totalWeight;
                if (weightShare <= 0) {
                    continue;
                }
                const equity = equities[i];

                const vsBet = villainVsBet[i];
                const villainResponse = regretMatching(vsBet);
                const callUtility = computeCallUtility(equity, potSize, heroBetSize);
                const heroBetUtility = villainResponse[0] * potSize + villainResponse[1] * callUtility;
                const villainFoldUtility = -potSize;
                const villainCallUtility = -callUtility;
                const villainNodeValue = villainResponse[0] * villainFoldUtility + villainResponse[1] * villainCallUtility;
                vsBet.regret[0] += betProb * weightShare * (villainFoldUtility - villainNodeValue);
                vsBet.regret[1] += betProb * weightShare * (villainCallUtility - villainNodeValue);
                vsBet.visitWeight += betProb * weightShare;
                vsBet.strategySum[0] += betProb * weightShare * villainResponse[0];
                vsBet.strategySum[1] += betProb * weightShare * villainResponse[1];

                const vsDonk = villainDonk[i];
                const villainDonkStrategy = regretMatching(vsDonk);
                const heroResponseStrategy = regretMatching(heroResponse);
                const showdownUtility = equity * potSize;
                const donkCallUtility = computeCallUtility(equity, potSize, villainBetSize);
                const heroCallUtility = heroResponseStrategy[1] * donkCallUtility;
                const heroCheckUtility = villainDonkStrategy[0] * showdownUtility + villainDonkStrategy[1] * heroCallUtility;
                const villainCheckUtility = -showdownUtility;
                const villainBetUtility = -heroCallUtility;
                const villainDonkNodeValue = villainDonkStrategy[0] * villainCheckUtility + villainDonkStrategy[1] * villainBetUtility;
                vsDonk.regret[0] += checkProb * weightShare * (villainCheckUtility - villainDonkNodeValue);
                vsDonk.regret[1] += checkProb * weightShare * (villainBetUtility - villainDonkNodeValue);
                vsDonk.visitWeight += checkProb * weightShare;
                vsDonk.strategySum[0] += checkProb * weightShare * villainDonkStrategy[0];
                vsDonk.strategySum[1] += checkProb * weightShare * villainDonkStrategy[1];

                const heroResponseNodeValue = heroCallUtility;
                heroResponse.regret[0] += checkProb * villainDonkStrategy[1] * weightShare * (0 - heroResponseNodeValue);
                heroResponse.regret[1] += checkProb * villainDonkStrategy[1] * weightShare * (donkCallUtility - heroResponseNodeValue);
                heroResponse.visitWeight += checkProb * villainDonkStrategy[1] * weightShare;
                heroResponse.strategySum[0] += checkProb * villainDonkStrategy[1] * weightShare * heroResponseStrategy[0];
                heroResponse.strategySum[1] += checkProb * villainDonkStrategy[1] * weightShare * heroResponseStrategy[1];

                const nodeUtility = heroStrategy[0] * heroBetUtility + heroStrategy[1] * heroCheckUtility;
                heroRoot.regret[0] += weightShare * (heroBetUtility - nodeUtility);
                heroRoot.regret[1] += weightShare * (heroCheckUtility - nodeUtility);

                aggregateBetValue += weightShare * heroBetUtility;
                aggregateCheckValue += weightShare * heroCheckUtility;
            }

            heroRoot.strategySum[0] += heroStrategy[0];
            heroRoot.strategySum[1] += heroStrategy[1];
            heroRoot.visitWeight += 1;
        }

        const heroStrategyAvg = heroRoot.strategySum.map((value) => value / (heroRoot.visitWeight || 1));
        const heroBetFrequency = clampProbability(heroStrategyAvg[0]);
        const heroCheckFrequency = clampProbability(heroStrategyAvg[1]);
        const heroCallFrequency = heroResponse.visitWeight > 0
            ? clampProbability(heroResponse.strategySum[1] / heroResponse.visitWeight)
            : 1;

        let villainCallSum = 0;
        let villainCallVisit = 0;
        let villainBetAfterCheckSum = 0;
        let villainBetAfterCheckVisit = 0;
        const analysis = [];
        for (let i = 0; i < combos.length; i += 1) {
            const vsBet = villainVsBet[i];
            const vsDonk = villainDonk[i];
            const callProbability = vsBet.visitWeight > 0 ? vsBet.strategySum[1] / vsBet.visitWeight : 0.5;
            const betAfterCheckProbability = vsDonk.visitWeight > 0 ? vsDonk.strategySum[1] / vsDonk.visitWeight : 0.5;
            villainCallSum += vsBet.strategySum[1];
            villainCallVisit += vsBet.visitWeight;
            villainBetAfterCheckSum += vsDonk.strategySum[1];
            villainBetAfterCheckVisit += vsDonk.visitWeight;
            analysis.push({
                cards: combos[i].cards,
                equity: equities[i],
                weight: weights[i],
                callProbability,
                betAfterCheckProbability
            });
        }

        const villainCallFrequency = villainCallVisit > 0 ? clampProbability(villainCallSum / villainCallVisit) : 0.5;
        const villainFoldFrequency = clampProbability(1 - villainCallFrequency);
        const villainBetAfterCheckFrequency = villainBetAfterCheckVisit > 0
            ? clampProbability(villainBetAfterCheckSum / villainBetAfterCheckVisit)
            : 0.5;

        const bucketSummaries = quantizeProbabilities(analysis, Math.min(10, Math.max(4, Math.ceil(Math.sqrt(analysis.length)))));
        const callProbabilities = bucketSummaries.map((bucket) => bucket.callProbability);
        const betAfterCheckProbabilities = bucketSummaries.map((bucket) => bucket.betAfterCheckProbability);
        const callDetails = buildComboDetails(totalWeight, analysis).slice(0, Math.min(analysis.length, 120));

        const callWeight = callDetails.reduce((sum, item) => sum + item.weightShare * item.callProbability, 0);
        const bluffWeight = callDetails.reduce((sum, item) => sum + item.weightShare * (1 - item.callProbability), 0);
        const mixedCombos = callDetails.filter((item) => item.callProbability > 1e-3 && item.callProbability < 1 - 1e-3);
        const callThreshold = mixedCombos.length
            ? mixedCombos.reduce((sum, item) => sum + item.heroEquity * item.weightShare, 0) /
                mixedCombos.reduce((sum, item) => sum + item.weightShare, 0)
            : callProbabilities.reduce((sum, prob, idx) => sum + prob * bucketSummaries[idx].averageEquity * bucketSummaries[idx].probability, 0) /
                (callProbabilities.reduce((sum, prob, idx) => sum + prob * bucketSummaries[idx].probability, 0) || 1);

        const evBet = aggregateBetValue / (iterations || 1);
        const evCheck = aggregateCheckValue / (iterations || 1);
        const heroUtility = heroBetFrequency * evBet + heroCheckFrequency * evCheck;

        const avgRootRegret = heroRoot.regret.reduce((sum, value) => sum + Math.max(0, value), 0) / (iterations || 1);
        const avgCallRegret = heroResponse.regret.reduce((sum, value) => sum + Math.max(0, value), 0) / (iterations || 1);

        return {
            heroStrategy: {
                bet: heroBetFrequency,
                check: heroCheckFrequency
            },
            heroCallStrategy: {
                fold: clampProbability(1 - heroCallFrequency),
                call: heroCallFrequency
            },
            villainCallFrequency,
            villainFoldFrequency,
            villainBetAfterCheckFrequency,
            evBet,
            evCheck,
            heroUtility,
            callThreshold: clampProbability(callThreshold),
            callWeight,
            bluffWeight,
            callDetails,
            callProbabilities,
            betAfterCheckProbabilities,
            avgRootRegret,
            avgCallRegret,
            metadata: {
                iterations,
                villainBetSize,
                heroBetSize,
                bucketSummaries
            }
        };
    }

    const solverApi = {
        solveFromContext: solvePycfrStyle
    };

    if (registry) {
        registry.register({
            id: "pycfr",
            label: "PyCFR Monte Carlo",
            description: "Chance-sampled CFR derived from tansey/pycfr recursive solver.",
            priority: 20,
            version: "0.1.0",
            origin: "Adapted from tansey/pycfr",
            solve(context) {
                const summary = solvePycfrStyle(context);
                if (!summary) {
                    return { ok: false, diagnostics: { reason: "pycfr: invalid context" } };
                }
                return {
                    ok: true,
                    summary,
                    detail: summary.metadata,
                    diagnostics: {
                        iterations: summary.metadata.iterations,
                        bucketCount: summary.metadata.bucketSummaries.length
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.PyCFR = solverApi;
})(typeof window !== "undefined" ? window : globalThis);
