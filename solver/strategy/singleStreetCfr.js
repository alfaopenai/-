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
            const value = infoSet.regret[i];
            const positive = value > 0 ? value : 0;
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

    function normalizePair(pair, fallback = [0.5, 0.5]) {
        const total = pair[0] + pair[1];
        if (total <= 1e-9) {
            return fallback.slice();
        }
        return [pair[0] / total, pair[1] / total];
    }

    function computeCallUtility(equity, potSize, betSize) {
        const eq = clampProbability(equity);
        if (betSize <= 0) {
            return eq * potSize;
        }
        return eq * (potSize + 2 * betSize) - betSize;
    }

    function bucketizeCombos(combos, totalWeight, maxBuckets) {
        const filtered = [];
        for (let i = 0; i < combos.length; i += 1) {
            const combo = combos[i];
            const weight = Number(combo.weight) || 0;
            if (weight <= 0) {
                continue;
            }
            const equity = clampProbability(combo.heroEquity);
            filtered.push({
                index: i,
                weight,
                equity,
                cards: combo.cards
            });
        }
        if (!filtered.length) {
            return [];
        }
        filtered.sort((a, b) => a.equity - b.equity);
        const targetBuckets = Math.max(4, Math.min(maxBuckets, Math.ceil(Math.sqrt(filtered.length))));
        const targetWeight = totalWeight / targetBuckets;
        const buckets = [];
        let current = {
            weight: 0,
            equityWeight: 0,
            combos: [],
            vsBet: createInfoSet(2),
            vsCheck: createInfoSet(2)
        };

        for (let i = 0; i < filtered.length; i += 1) {
            const item = filtered[i];
            if (current.weight >= targetWeight && buckets.length < targetBuckets - 1) {
                finalizeBucket(current);
                buckets.push(current);
                current = {
                    weight: 0,
                    equityWeight: 0,
                    combos: [],
                    vsBet: createInfoSet(2),
                    vsCheck: createInfoSet(2)
                };
            }
            current.weight += item.weight;
            current.equityWeight += item.equity * item.weight;
            current.combos.push(item);
        }
        finalizeBucket(current);
        buckets.push(current);
        const normalized = buckets.filter((bucket) => bucket.weight > 0);
        const normTotal = normalized.reduce((sum, bucket) => sum + bucket.weight, 0) || 1;
        normalized.forEach((bucket) => {
            bucket.probability = bucket.weight / normTotal;
            bucket.averageEquity = bucket.equityWeight / bucket.weight;
        });
        return normalized;
    }

    function finalizeBucket(bucket) {
        if (bucket.weight <= 0) {
            bucket.weight = 0;
            bucket.averageEquity = 0.5;
            bucket.probability = 0;
            return;
        }
        bucket.averageEquity = bucket.equityWeight / bucket.weight;
        bucket.probability = 0;
    }

    function evaluateProfile(potSize, betSize, buckets, heroRootStrategy, heroCallStrategy, callProbabilities, betAfterCheckProbabilities) {
        let betValue = 0;
        let checkValue = 0;
        let callFrequency = 0;
        let betFacingFrequency = 0;

        for (let i = 0; i < buckets.length; i += 1) {
            const bucket = buckets[i];
            const prob = bucket.probability;
            const callProb = callProbabilities[i];
            const betProb = betAfterCheckProbabilities[i];
            const callUtility = computeCallUtility(bucket.averageEquity, potSize, betSize);
            const showdownUtility = bucket.averageEquity * potSize;
            const heroCallUtility = heroCallStrategy[0] * 0 + heroCallStrategy[1] * callUtility;

            betValue += prob * (callProb * callUtility + (1 - callProb) * potSize);
            checkValue += prob * (betProb * heroCallUtility + (1 - betProb) * showdownUtility);
            callFrequency += prob * callProb;
            betFacingFrequency += prob * betProb;
        }

        const heroUtility = heroRootStrategy[0] * betValue + heroRootStrategy[1] * checkValue;
        return {
            betValue,
            checkValue,
            heroUtility,
            callFrequency,
            foldFrequency: Math.max(0, 1 - callFrequency),
            betFacingFrequency
        };
    }

    function buildDetails(totalWeight, buckets, callProbabilities) {
        const summaries = [];
        for (let i = 0; i < buckets.length; i += 1) {
            const bucket = buckets[i];
            const callProb = callProbabilities[i];
            for (let j = 0; j < bucket.combos.length; j += 1) {
                const combo = bucket.combos[j];
                summaries.push({
                    cards: combo.cards,
                    heroEquity: combo.equity,
                    callProbability: callProb,
                    weightShare: combo.weight / (totalWeight || 1)
                });
            }
        }
        summaries.sort((a, b) => b.callProbability - a.callProbability || b.heroEquity - a.heroEquity);
        return summaries;
    }

    function solveSingleStreet(params) {
        if (!params || !params.combos || !params.combos.length) {
            return null;
        }
        const potSize = Math.max(0, Number(params.potSize) || 0);
        const betSizeRaw = Math.max(0, Number(params.betSize) || 0);
        const effectiveStack = Math.max(0, Number(params.stackSize) || betSizeRaw);
        const betSize = Math.min(betSizeRaw, effectiveStack);
        if (betSize <= 0) {
            return null;
        }
        const totalWeight = Math.max(0, Number(params.totalWeight) || 0);
        if (totalWeight <= 0) {
            return null;
        }
        const iterations = Math.max(500, Math.min(200000, Math.floor(Number(params.iterations) || 0) || 5000));
        const buckets = bucketizeCombos(params.combos, totalWeight, 18);
        if (!buckets.length) {
            return null;
        }

        const heroRoot = createInfoSet(2);
        const heroCall = createInfoSet(2);

        let avgRootRegret = 0;
        let avgCallRegret = 0;

        for (let iter = 0; iter < iterations; iter += 1) {
            const heroStrategy = regretMatching(heroRoot);
            const heroCallStrategy = regretMatching(heroCall);
            let betValue = 0;
            let checkValue = 0;
            let sumBetProbability = 0;

            for (let b = 0; b < buckets.length; b += 1) {
                const bucket = buckets[b];
                const prob = bucket.probability;
                const vsBetStrategy = regretMatching(bucket.vsBet);
                const vsCheckStrategy = regretMatching(bucket.vsCheck);

                const callUtility = computeCallUtility(bucket.averageEquity, potSize, betSize);
                const showdownUtility = bucket.averageEquity * potSize;

                const heroBetUtility = vsBetStrategy[1] * callUtility + vsBetStrategy[0] * potSize;
                betValue += prob * heroBetUtility;

                const heroCallUtility = heroCallStrategy[1] * callUtility;
                const heroCheckUtility = vsCheckStrategy[0] * showdownUtility + vsCheckStrategy[1] * (heroCallStrategy[0] * 0 + heroCallUtility);
                checkValue += prob * heroCheckUtility;

                bucket.vsBet.visitWeight += heroStrategy[0] * prob;
                bucket.vsBet.strategySum[0] += heroStrategy[0] * prob * vsBetStrategy[0];
                bucket.vsBet.strategySum[1] += heroStrategy[0] * prob * vsBetStrategy[1];

                bucket.vsCheck.visitWeight += heroStrategy[1] * prob;
                bucket.vsCheck.strategySum[0] += heroStrategy[1] * prob * vsCheckStrategy[0];
                bucket.vsCheck.strategySum[1] += heroStrategy[1] * prob * vsCheckStrategy[1];

                const villainFoldUtility = -potSize;
                const villainCallUtility = -callUtility;
                const villainBetUtility = -(heroCallStrategy[0] * 0 + heroCallUtility);
                const villainCheckUtility = -showdownUtility;

                const villainVsBetValue = vsBetStrategy[0] * villainFoldUtility + vsBetStrategy[1] * villainCallUtility;
                bucket.vsBet.regret[0] += heroStrategy[0] * prob * (villainFoldUtility - villainVsBetValue);
                bucket.vsBet.regret[1] += heroStrategy[0] * prob * (villainCallUtility - villainVsBetValue);

                const villainVsCheckValue = vsCheckStrategy[0] * villainCheckUtility + vsCheckStrategy[1] * villainBetUtility;
                bucket.vsCheck.regret[0] += heroStrategy[1] * prob * (villainCheckUtility - villainVsCheckValue);
                bucket.vsCheck.regret[1] += heroStrategy[1] * prob * (villainBetUtility - villainVsCheckValue);

                const nodeCallUtility = heroCallStrategy[1] * callUtility;
                heroCall.regret[0] += prob * vsCheckStrategy[1] * (0 - nodeCallUtility);
                heroCall.regret[1] += prob * vsCheckStrategy[1] * (callUtility - nodeCallUtility);

                heroCall.strategySum[0] += heroStrategy[1] * prob * vsCheckStrategy[1] * heroCallStrategy[0];
                heroCall.strategySum[1] += heroStrategy[1] * prob * vsCheckStrategy[1] * heroCallStrategy[1];
                sumBetProbability += prob * vsCheckStrategy[1];
            }

            const nodeUtility = heroStrategy[0] * betValue + heroStrategy[1] * checkValue;
            heroRoot.regret[0] += betValue - nodeUtility;
            heroRoot.regret[1] += checkValue - nodeUtility;
            heroRoot.strategySum[0] += heroStrategy[0];
            heroRoot.strategySum[1] += heroStrategy[1];
            heroRoot.visitWeight += 1;
            heroCall.visitWeight += heroStrategy[1] * sumBetProbability;

            avgRootRegret += Math.max(0, heroRoot.regret[0]) + Math.max(0, heroRoot.regret[1]);
            avgCallRegret += Math.max(0, heroCall.regret[0]) + Math.max(0, heroCall.regret[1]);
        }

        const heroRootStrategy = normalizePair(heroRoot.strategySum, [0.5, 0.5]);
        const heroCallStrategy = heroCall.visitWeight > 0
            ? normalizePair(heroCall.strategySum.map((v) => v / heroCall.visitWeight), [0.0, 1.0])
            : [0.0, 1.0];

        const callProbabilities = buckets.map((bucket) => {
            if (bucket.vsBet.visitWeight > 0) {
                return bucket.vsBet.strategySum[1] / bucket.vsBet.visitWeight;
            }
            return regretMatching(bucket.vsBet)[1];
        });

        const betAfterCheckProbabilities = buckets.map((bucket) => {
            if (bucket.vsCheck.visitWeight > 0) {
                return bucket.vsCheck.strategySum[1] / bucket.vsCheck.visitWeight;
            }
            return regretMatching(bucket.vsCheck)[1];
        });

        const profile = evaluateProfile(potSize, betSize, buckets, heroRootStrategy, heroCallStrategy, callProbabilities, betAfterCheckProbabilities);
        const details = buildDetails(totalWeight, buckets, callProbabilities);
        const callWeight = details.reduce((sum, item) => sum + item.weightShare * item.callProbability, 0);
        const bluffWeight = details.reduce((sum, item) => sum + item.weightShare * (1 - item.callProbability), 0);
        const mixedCombos = details.filter((item) => item.callProbability > 1e-3 && item.callProbability < 1 - 1e-3);
        const callThreshold = mixedCombos.length
            ? mixedCombos.reduce((sum, item) => sum + item.heroEquity * item.weightShare, 0) /
                mixedCombos.reduce((sum, item) => sum + item.weightShare, 0)
            : callProbabilities.reduce((sum, prob, index) => sum + prob * buckets[index].averageEquity * buckets[index].probability, 0) /
                (callProbabilities.reduce((sum, prob, index) => sum + prob * buckets[index].probability, 0) || 1);

        return {
            heroStrategy: { bet: heroRootStrategy[0], check: heroRootStrategy[1] },
            heroCallStrategy: { fold: heroCallStrategy[0], call: heroCallStrategy[1] },
            villainCallFrequency: clampProbability(profile.callFrequency),
            villainFoldFrequency: clampProbability(profile.foldFrequency),
            villainBetAfterCheckFrequency: clampProbability(profile.betFacingFrequency),
            evBet: profile.betValue,
            evCheck: profile.checkValue,
            heroUtility: profile.heroUtility,
            callThreshold,
            callWeight,
            bluffWeight,
            callDetails: details,
            callProbabilities,
            betAfterCheckProbabilities,
            avgRootRegret: avgRootRegret / iterations,
            avgCallRegret: avgCallRegret / iterations
        };
    }

    const solverApi = {
        solve: solveSingleStreet,
        solveFromContext(context) {
            if (!context || !context.villainRange) {
                return null;
            }
            const { villainRange, potSize, betSize, stackSize, iterations } = context;
            return solveSingleStreet({
                combos: villainRange.combos,
                totalWeight: villainRange.totalWeight,
                potSize,
                betSize,
                stackSize,
                iterations
            });
        }
    };

    if (registry) {
        registry.register({
            id: "singleStreetCfr",
            label: "Single Street CFR",
            description: "Baseline single-street CFR with equity buckets; adapted from community solvers.",
            priority: 10,
            version: "1.1.0",
            origin: "AlphaPoker core module inspired by TexasSolver and PyCFR",
            solve(context) {
                const summary = solverApi.solveFromContext(context);
                if (!summary) {
                    return { ok: false, diagnostics: { reason: "invalid context" } };
                }
                return {
                    ok: true,
                    summary,
                    detail: {
                        callProbabilities: summary.callProbabilities,
                        betAfterCheckProbabilities: summary.betAfterCheckProbabilities,
                        buckets: summary.callDetails
                    },
                    diagnostics: {
                        iterations: context && context.iterations,
                        combos: context && context.villainRange ? context.villainRange.combos.length : 0
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.SingleStreetCFR = solverApi;
})(typeof window !== "undefined" ? window : globalThis);


