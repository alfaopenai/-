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

    function almostEqual(a, b, epsilon = 1e-9) {
        return Math.abs(a - b) <= epsilon;
    }

    function pushUnique(target, value) {
        for (let i = 0; i < target.length; i += 1) {
            if (almostEqual(target[i], value)) {
                return;
            }
        }
        target.push(value);
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

    function deriveHeroBetSizes(potSize, stackSize, baseBetSize) {
        const pot = Math.max(0, Number(potSize) || 0);
        const stack = Math.max(0, Number(stackSize) || 0);
        const base = Math.max(0, Number(baseBetSize) || 0);
        const candidates = [];
        if (pot > 0) {
            pushUnique(candidates, pot * 0.5);
            pushUnique(candidates, pot * 0.75);
            pushUnique(candidates, pot);
        }
        if (base > 0) {
            pushUnique(candidates, base);
        }
        if (!candidates.length) {
            pushUnique(candidates, pot > 0 ? pot * 0.6 : 1);
        }
        const cap = stack > 0 ? stack : Math.max(...candidates);
        const normalized = [];
        for (let i = 0; i < candidates.length; i += 1) {
            const size = Math.max(0, Math.min(cap, candidates[i]));
            if (size > 0) {
                pushUnique(normalized, size);
            }
        }
        normalized.sort((a, b) => a - b);
        if (normalized.length > 2) {
            return [normalized[0], normalized[normalized.length - 1]];
        }
        return normalized;
    }

    function deriveVillainBetSizes(potSize, stackSize, heroSizes) {
        const pot = Math.max(0, Number(potSize) || 0);
        const stack = Math.max(0, Number(stackSize) || 0);
        const base = heroSizes.length ? heroSizes[heroSizes.length - 1] : pot;
        const candidates = [];
        if (pot > 0) {
            pushUnique(candidates, pot * 0.5);
            pushUnique(candidates, pot * 0.75);
        }
        if (base > 0) {
            pushUnique(candidates, base);
        }
        if (!candidates.length) {
            pushUnique(candidates, pot > 0 ? pot * 0.5 : 1);
        }
        const cap = stack > 0 ? stack : Math.max(...candidates);
        const normalized = [];
        for (let i = 0; i < candidates.length; i += 1) {
            const size = Math.max(0, Math.min(cap, candidates[i]));
            if (size > 0) {
                pushUnique(normalized, size);
            }
        }
        normalized.sort((a, b) => a - b);
        if (normalized.length > 2) {
            return [normalized[0], normalized[normalized.length - 1]];
        }
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

    function bucketizeCombos(combos, totalWeight, maxBuckets) {
        const filtered = [];
        for (let i = 0; i < combos.length; i += 1) {
            const combo = combos[i];
            const weight = Number(combo.weight) || 0;
            if (weight <= 0) {
                continue;
            }
            filtered.push({
                index: i,
                weight,
                equity: clampProbability(combo.heroEquity),
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
            villainVsBet: [],
            villainVsCheck: null,
            heroVsDonk: []
        };
        for (let i = 0; i < filtered.length; i += 1) {
            if (current.weight >= targetWeight && buckets.length < targetBuckets - 1) {
                finalizeBucket(current);
                buckets.push(current);
                current = {
                    weight: 0,
                    equityWeight: 0,
                    combos: [],
                    villainVsBet: [],
                    villainVsCheck: null,
                    heroVsDonk: []
                };
            }
            const item = filtered[i];
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
        });
        return normalized;
    }

    function buildDetails(totalWeight, buckets, callProbabilities) {
        const summaries = [];
        for (let i = 0; i < buckets.length; i += 1) {
            const bucket = buckets[i];
            const callProb = clampProbability(callProbabilities[i] || 0);
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

    function collectCallProbabilities(buckets) {
        const callProbabilities = [];
        for (let i = 0; i < buckets.length; i += 1) {
            const bucket = buckets[i];
            let visit = 0;
            let callSum = 0;
            for (let j = 0; j < bucket.villainVsBet.length; j += 1) {
                const info = bucket.villainVsBet[j];
                visit += info.visitWeight;
                callSum += info.strategySum[1];
            }
            if (visit > 0) {
                callProbabilities.push(callSum / visit);
            } else {
                callProbabilities.push(0.5);
            }
        }
        return callProbabilities;
    }

    function collectBetAfterCheckProbabilities(buckets) {
        const results = [];
        for (let i = 0; i < buckets.length; i += 1) {
            const info = buckets[i].villainVsCheck;
            if (info && info.visitWeight > 0) {
                let betSum = 0;
                for (let a = 1; a < info.strategySum.length; a += 1) {
                    betSum += info.strategySum[a];
                }
                results.push(betSum / info.visitWeight);
            } else {
                results.push(0.5);
            }
        }
        return results;
    }

    function solveTexasStyle(context) {
        if (!context || !context.villainRange || !context.villainRange.combos || !context.villainRange.combos.length) {
            return null;
        }
        const totalWeight = context.villainRange.totalWeight;
        if (!Number.isFinite(totalWeight) || totalWeight <= 0) {
            return null;
        }
        const potSize = Math.max(0, Number(context.potSize) || 0);
        const stackSize = Math.max(0, Number(context.stackSize) || 0);
        const baseBet = Math.max(0, Number(context.betSize) || 0);
        const iterations = Math.max(500, Math.min(50000, Number(context.iterations) || 8000));

        const heroBetSizes = deriveHeroBetSizes(potSize, stackSize, baseBet);
        if (!heroBetSizes.length) {
            return null;
        }
        const villainBetSizes = deriveVillainBetSizes(potSize, stackSize, heroBetSizes);
        const heroActionCount = heroBetSizes.length + 1; // +1 for check
        const maxBuckets = Math.max(6, Math.ceil(Math.sqrt(context.villainRange.combos.length)));
        const buckets = bucketizeCombos(context.villainRange.combos, totalWeight, maxBuckets);
        if (!buckets.length) {
            return null;
        }

        for (let i = 0; i < buckets.length; i += 1) {
            const bucket = buckets[i];
            bucket.villainVsBet = heroBetSizes.map(() => createInfoSet(2));
            bucket.villainVsCheck = createInfoSet(1 + villainBetSizes.length);
            bucket.heroVsDonk = villainBetSizes.map(() => createInfoSet(2));
        }

        const heroRoot = createInfoSet(heroActionCount);
        const aggregateActionTotals = new Array(heroActionCount).fill(0);
        let accumulatedUtility = 0;

        for (let iteration = 0; iteration < iterations; iteration += 1) {
            const heroStrategy = regretMatching(heroRoot);
            const checkIndex = heroActionCount - 1;
            const branchTotals = new Array(heroActionCount).fill(0);

            for (let b = 0; b < buckets.length; b += 1) {
                const bucket = buckets[b];
                const bucketProbability = bucket.probability;
                const branchValues = new Array(heroActionCount).fill(0);

                for (let a = 0; a < heroBetSizes.length; a += 1) {
                    const betSize = heroBetSizes[a];
                    const info = bucket.villainVsBet[a];
                    const villainStrategy = regretMatching(info);
                    const callUtility = computeCallUtility(bucket.averageEquity, potSize, betSize);
                    const foldUtility = potSize;
                    const heroBranchValue = villainStrategy[0] * foldUtility + villainStrategy[1] * callUtility;
                    branchValues[a] = heroBranchValue;

                    const villainFoldUtility = -foldUtility;
                    const villainCallUtility = -callUtility;
                    const villainNodeValue = villainStrategy[0] * villainFoldUtility + villainStrategy[1] * villainCallUtility;
                    info.regret[0] += heroStrategy[a] * bucketProbability * (villainFoldUtility - villainNodeValue);
                    info.regret[1] += heroStrategy[a] * bucketProbability * (villainCallUtility - villainNodeValue);
                    info.visitWeight += heroStrategy[a] * bucketProbability;
                    info.strategySum[0] += heroStrategy[a] * bucketProbability * villainStrategy[0];
                    info.strategySum[1] += heroStrategy[a] * bucketProbability * villainStrategy[1];
                }

                const infoCheck = bucket.villainVsCheck;
                const villainStrategyCheck = regretMatching(infoCheck);
                const villainUtilities = new Array(infoCheck.regret.length).fill(0);
                let heroCheckValue = 0;
                const showdownUtility = bucket.averageEquity * potSize;
                heroCheckValue += villainStrategyCheck[0] * showdownUtility;
                villainUtilities[0] = -showdownUtility;
                infoCheck.strategySum[0] += heroStrategy[checkIndex] * bucketProbability * villainStrategyCheck[0];
                infoCheck.visitWeight += heroStrategy[checkIndex] * bucketProbability;

                for (let v = 0; v < villainBetSizes.length; v += 1) {
                    const betInfoIndex = v + 1;
                    const betSize = villainBetSizes[v];
                    const heroResponse = bucket.heroVsDonk[v];
                    const heroResponseStrategy = regretMatching(heroResponse);
                    const callUtility = computeCallUtility(bucket.averageEquity, potSize, betSize);
                    const heroResponseValue = heroResponseStrategy[1] * callUtility;
                    heroCheckValue += villainStrategyCheck[betInfoIndex] * heroResponseValue;
                    villainUtilities[betInfoIndex] = -heroResponseValue;

                    const nodeValueHeroResponse = heroResponseValue;
                    heroResponse.regret[0] += heroStrategy[checkIndex] * villainStrategyCheck[betInfoIndex] * bucketProbability * (0 - nodeValueHeroResponse);
                    heroResponse.regret[1] += heroStrategy[checkIndex] * villainStrategyCheck[betInfoIndex] * bucketProbability * (callUtility - nodeValueHeroResponse);
                    heroResponse.visitWeight += heroStrategy[checkIndex] * villainStrategyCheck[betInfoIndex] * bucketProbability;
                    heroResponse.strategySum[0] += heroStrategy[checkIndex] * villainStrategyCheck[betInfoIndex] * bucketProbability * heroResponseStrategy[0];
                    heroResponse.strategySum[1] += heroStrategy[checkIndex] * villainStrategyCheck[betInfoIndex] * bucketProbability * heroResponseStrategy[1];
                    infoCheck.strategySum[betInfoIndex] += heroStrategy[checkIndex] * bucketProbability * villainStrategyCheck[betInfoIndex];
                }

                const villainNodeValueCheck = villainStrategyCheck.reduce((sum, value, idx) => sum + value * villainUtilities[idx], 0);
                for (let idx = 0; idx < infoCheck.regret.length; idx += 1) {
                    infoCheck.regret[idx] += heroStrategy[checkIndex] * bucketProbability * (villainUtilities[idx] - villainNodeValueCheck);
                }

                branchValues[checkIndex] = heroCheckValue;

                const nodeValue = heroStrategy.reduce((sum, value, idx) => sum + value * branchValues[idx], 0);
                accumulatedUtility += bucketProbability * nodeValue;
                for (let idx = 0; idx < heroActionCount; idx += 1) {
                    heroRoot.regret[idx] += bucketProbability * (branchValues[idx] - nodeValue);
                    branchTotals[idx] += branchValues[idx] * bucketProbability;
                }
            }

            for (let idx = 0; idx < heroActionCount; idx += 1) {
                aggregateActionTotals[idx] += branchTotals[idx];
                heroRoot.strategySum[idx] += heroStrategy[idx];
            }
            heroRoot.visitWeight += 1;
        }

        const heroStrategyAvg = heroRoot.strategySum.map((value) => value / (heroRoot.visitWeight || 1));
        const checkIndex = heroActionCount - 1;
        const heroBetFrequency = heroBetSizes.reduce((sum, _, idx) => sum + heroStrategyAvg[idx], 0);
        const heroCheckFrequency = clampProbability(heroStrategyAvg[checkIndex]);
        const heroBetBreakdown = heroBetSizes.map((size, idx) => ({
            size,
            frequency: clampProbability(heroStrategyAvg[idx])
        }));

        let heroCallVisits = 0;
        let heroCallSum = 0;
        for (let b = 0; b < buckets.length; b += 1) {
            const bucket = buckets[b];
            for (let v = 0; v < bucket.heroVsDonk.length; v += 1) {
                const info = bucket.heroVsDonk[v];
                heroCallVisits += info.visitWeight;
                heroCallSum += info.strategySum[1];
            }
        }
        const heroCallFrequency = heroCallVisits > 0 ? heroCallSum / heroCallVisits : 1;

        let villainCallVisit = 0;
        let villainCallSum = 0;
        for (let b = 0; b < buckets.length; b += 1) {
            const bucket = buckets[b];
            for (let a = 0; a < bucket.villainVsBet.length; a += 1) {
                const info = bucket.villainVsBet[a];
                villainCallVisit += info.visitWeight;
                villainCallSum += info.strategySum[1];
            }
        }
        const villainCallFrequency = villainCallVisit > 0 ? clampProbability(villainCallSum / villainCallVisit) : 0.5;
        const villainFoldFrequency = clampProbability(1 - villainCallFrequency);

        let betAfterCheckVisit = 0;
        let betAfterCheckSum = 0;
        for (let b = 0; b < buckets.length; b += 1) {
            const info = buckets[b].villainVsCheck;
            if (info) {
                betAfterCheckVisit += info.visitWeight;
                for (let idx = 1; idx < info.strategySum.length; idx += 1) {
                    betAfterCheckSum += info.strategySum[idx];
                }
            }
        }
        const villainBetAfterCheckFrequency = betAfterCheckVisit > 0
            ? clampProbability(betAfterCheckSum / betAfterCheckVisit)
            : 0.5;

        const actionAverages = aggregateActionTotals.map((total) => total / (iterations || 1));
        const evCheck = actionAverages[checkIndex] || 0;
        let evBet = 0;
        for (let i = 0; i < heroBetSizes.length; i += 1) {
            evBet += heroStrategyAvg[i] * actionAverages[i];
        }
        evBet = evBet / (heroBetFrequency || 1);
        const heroUtility = heroStrategyAvg.reduce((sum, freq, idx) => sum + freq * actionAverages[idx], 0);

        const callProbabilities = collectCallProbabilities(buckets);
        const betAfterCheckProbabilities = collectBetAfterCheckProbabilities(buckets);
        const details = buildDetails(totalWeight, buckets, callProbabilities);
        const callWeight = details.reduce((sum, item) => sum + item.weightShare * item.callProbability, 0);
        const bluffWeight = details.reduce((sum, item) => sum + item.weightShare * (1 - item.callProbability), 0);
        const mixedCombos = details.filter((item) => item.callProbability > 1e-3 && item.callProbability < 1 - 1e-3);
        const callThreshold = mixedCombos.length
            ? mixedCombos.reduce((sum, item) => sum + item.heroEquity * item.weightShare, 0) /
                mixedCombos.reduce((sum, item) => sum + item.weightShare, 0)
            : callProbabilities.reduce((sum, prob, index) => sum + prob * buckets[index].averageEquity * buckets[index].probability, 0) /
                (callProbabilities.reduce((sum, prob, index) => sum + prob * buckets[index].probability, 0) || 1);

        const avgRootRegret = heroRoot.regret.reduce((sum, value) => sum + Math.max(0, value), 0) / (iterations || 1);
        let responseRegret = 0;
        for (let b = 0; b < buckets.length; b += 1) {
            const bucket = buckets[b];
            for (let v = 0; v < bucket.heroVsDonk.length; v += 1) {
                const info = bucket.heroVsDonk[v];
                for (let i = 0; i < info.regret.length; i += 1) {
                    responseRegret += Math.max(0, info.regret[i]);
                }
            }
        }
        const avgCallRegret = responseRegret / ((iterations || 1) * Math.max(1, villainBetSizes.length));

        return {
            heroStrategy: {
                bet: clampProbability(heroBetFrequency),
                check: clampProbability(heroCheckFrequency),
                breakdown: heroBetBreakdown
            },
            heroCallStrategy: {
                fold: clampProbability(1 - heroCallFrequency),
                call: clampProbability(heroCallFrequency),
                breakdown: heroCallBreakdown
            },
            villainCallFrequency,
            villainFoldFrequency,
            villainBetAfterCheckFrequency,
            evBet: Number.isFinite(evBet) ? evBet : heroUtility,
            evCheck: Number.isFinite(evCheck) ? evCheck : heroUtility,
            heroUtility,
            callThreshold: clampProbability(callThreshold),
            callWeight,
            bluffWeight,
            callDetails: details,
            callProbabilities,
            betAfterCheckProbabilities,
            avgRootRegret,
            avgCallRegret,
            metadata: {
                heroBetSizes,
                villainBetSizes,
                heroCallBreakdown,
                buckets: buckets.map((bucket) => ({
                    probability: bucket.probability,
                    averageEquity: bucket.averageEquity,
                    weight: bucket.weight
                }))
            }
        };
    }

    const solverApi = {
        solveFromContext: solveTexasStyle
    };

    if (registry) {
        registry.register({
            id: "texasCfr",
            label: "TexasSolver CFR",
            description: "Multi-action single-street CFR inspired by TexasSolver game-tree configuration.",
            priority: 25,
            version: "0.1.0",
            origin: "Adapted from bupticybee/TexasSolver concepts",
            solve(context) {
                const summary = solveTexasStyle(context);
                if (!summary) {
                    return { ok: false, diagnostics: { reason: "texasCfr: invalid context" } };
                }
                return {
                    ok: true,
                    summary,
                    detail: summary.metadata,
                    diagnostics: {
                        heroBetOptions: summary.metadata.heroBetSizes.length,
                        villainBetOptions: summary.metadata.villainBetSizes.length
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.TexasCFR = solverApi;
})(typeof window !== "undefined" ? window : globalThis);

