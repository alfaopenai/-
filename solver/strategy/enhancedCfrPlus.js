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

    function createInfoSetPlus(actionCount) {
        return {
            cumulativeRegret: new Float32Array(actionCount),
            strategySum: new Float32Array(actionCount),
            currentStrategy: new Float32Array(actionCount),
            reachWeight: 0,
            lastUpdateIteration: 0
        };
    }

    function regretMatchingPlus(infoSet, iteration) {
        let positiveSum = 0;

        for (let i = 0; i < infoSet.cumulativeRegret.length; i += 1) {
            const regret = Math.max(0, infoSet.cumulativeRegret[i]);
            infoSet.currentStrategy[i] = regret;
            positiveSum += regret;
        }

        if (positiveSum <= 1e-12) {
            const uniform = 1 / infoSet.currentStrategy.length;
            for (let i = 0; i < infoSet.currentStrategy.length; i += 1) {
                infoSet.currentStrategy[i] = uniform;
            }
        } else {
            for (let i = 0; i < infoSet.currentStrategy.length; i += 1) {
                infoSet.currentStrategy[i] /= positiveSum;
            }
        }

        return infoSet.currentStrategy;
    }

    function updateCumulativeRegret(infoSet, regrets, iteration, reachProb) {
        for (let i = 0; i < regrets.length; i += 1) {
            infoSet.cumulativeRegret[i] = Math.max(
                infoSet.cumulativeRegret[i] + regrets[i] * reachProb,
                0
            );
        }
        infoSet.lastUpdateIteration = iteration;
    }

    function updateStrategySum(infoSet, strategy, iteration, reachProb) {
        for (let i = 0; i < strategy.length; i += 1) {
            infoSet.strategySum[i] += strategy[i] * reachProb;
        }
        infoSet.reachWeight += reachProb;
    }

    function getAverageStrategy(infoSet) {
        const avgStrategy = new Array(infoSet.strategySum.length);

        if (infoSet.reachWeight <= 1e-12) {
            const uniform = 1 / avgStrategy.length;
            for (let i = 0; i < avgStrategy.length; i += 1) {
                avgStrategy[i] = uniform;
            }
        } else {
            for (let i = 0; i < avgStrategy.length; i += 1) {
                avgStrategy[i] = infoSet.strategySum[i] / infoSet.reachWeight;
            }
        }

        return avgStrategy;
    }

    function computeCallUtility(equity, potSize, betSize) {
        const eq = clampProbability(equity);
        if (betSize <= 0) {
            return eq * potSize;
        }
        return eq * (potSize + 2 * betSize) - betSize;
    }

    function detectSuitIsomorphisms(board) {
        const suitCounts = [0, 0, 0, 0];
        const cardsSeen = new Set();

        for (const card of board) {
            if (typeof card === 'string' && card.length >= 2) {
                const suit = card.slice(-1);
                const suitIndex = ['c', 'd', 'h', 's'].indexOf(suit.toLowerCase());
                if (suitIndex >= 0) {
                    suitCounts[suitIndex]++;
                    cardsSeen.add(card);
                }
            }
        }

        const uniqueDistributions = new Map();
        suitCounts.forEach((count, index) => {
            if (!uniqueDistributions.has(count)) {
                uniqueDistributions.set(count, []);
            }
            uniqueDistributions.get(count).push(index);
        });

        const isomorphicGroups = [];
        for (const [count, suits] of uniqueDistributions) {
            if (suits.length > 1) {
                isomorphicGroups.push(suits);
            }
        }

        return isomorphicGroups;
    }

    function normalizeHandBySuit(hand, isomorphicGroups) {
        if (!isomorphicGroups.length || !hand || hand.length < 2) {
            return hand;
        }

        let normalizedHand = hand;
        for (const group of isomorphicGroups) {
            if (group.length > 1) {
                const suitMap = ['c', 'd', 'h', 's'];
                const targetSuit = suitMap[group[0]];

                for (let i = 1; i < group.length; i++) {
                    const sourceSuit = suitMap[group[i]];
                    normalizedHand = normalizedHand.replace(
                        new RegExp(sourceSuit, 'g'),
                        targetSuit
                    );
                }
            }
        }

        return normalizedHand;
    }

    function enhancedBucketization(combos, totalWeight, maxBuckets, bucketingStrategy = 'emd') {
        const filtered = [];

        for (let i = 0; i < combos.length; i += 1) {
            const combo = combos[i];
            const weight = Number(combo.weight) || 0;
            if (weight <= 0) continue;

            filtered.push({
                index: i,
                weight,
                equity: clampProbability(combo.heroEquity),
                cards: combo.cards,
                handStrength: combo.handStrength || combo.heroEquity,
                potential: combo.potential || 0
            });
        }

        if (!filtered.length) return [];

        switch (bucketingStrategy) {
            case 'emd':
                return emdBucketization(filtered, totalWeight, maxBuckets);
            case 'multidimensional':
                return multidimensionalBucketization(filtered, totalWeight, maxBuckets);
            default:
                return basicEquityBucketization(filtered, totalWeight, maxBuckets);
        }
    }

    function emdBucketization(filtered, totalWeight, maxBuckets) {
        filtered.sort((a, b) => a.equity - b.equity);

        const targetBuckets = Math.max(4, Math.min(maxBuckets, Math.ceil(Math.sqrt(filtered.length))));
        const targetWeight = totalWeight / targetBuckets;
        const buckets = [];

        let current = {
            weight: 0,
            equityWeight: 0,
            combos: [],
            villainInfoSets: new Map()
        };

        for (let i = 0; i < filtered.length; i += 1) {
            if (current.weight >= targetWeight && buckets.length < targetBuckets - 1) {
                finalizeBucket(current);
                buckets.push(current);
                current = {
                    weight: 0,
                    equityWeight: 0,
                    combos: [],
                    villainInfoSets: new Map()
                };
            }

            const item = filtered[i];
            current.weight += item.weight;
            current.equityWeight += item.equity * item.weight;
            current.combos.push(item);
        }

        finalizeBucket(current);
        buckets.push(current);

        return normalizeAndInitializeBuckets(buckets);
    }

    function multidimensionalBucketization(filtered, totalWeight, maxBuckets) {
        const strengthWeight = 0.7;
        const potentialWeight = 0.3;

        filtered.forEach(combo => {
            combo.compositeValue =
                strengthWeight * combo.handStrength +
                potentialWeight * combo.potential;
        });

        filtered.sort((a, b) => a.compositeValue - b.compositeValue);

        return emdBucketization(filtered, totalWeight, maxBuckets);
    }

    function basicEquityBucketization(filtered, totalWeight, maxBuckets) {
        return emdBucketization(filtered, totalWeight, maxBuckets);
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

    function normalizeAndInitializeBuckets(buckets) {
        const validBuckets = buckets.filter(b => b.weight > 0);
        const totalWeight = validBuckets.reduce((sum, b) => sum + b.weight, 0) || 1;

        validBuckets.forEach(bucket => {
            bucket.probability = bucket.weight / totalWeight;
            bucket.villainVsBet = new Map();
            bucket.villainVsCheck = new Map();
        });

        return validBuckets;
    }

    function calculateExploitability(buckets, heroStrategy, villainStrategies) {
        let totalExploitability = 0;

        buckets.forEach(bucket => {
            bucket.villainVsBet.forEach((infoSet) => {
                const avgStrategy = getAverageStrategy(infoSet);
                const bestResponse = computeBestResponse(avgStrategy, bucket);
                const currentUtility = computeUtility(avgStrategy, bucket);
                totalExploitability += (bestResponse - currentUtility) * bucket.probability;
            });
        });

        return totalExploitability;
    }

    function computeBestResponse(strategy, bucket) {
        const utilities = [];

        for (let i = 0; i < strategy.length; i++) {
            utilities.push(computeActionUtility(i, bucket));
        }

        return Math.max(...utilities);
    }

    function computeUtility(strategy, bucket) {
        let utility = 0;

        for (let i = 0; i < strategy.length; i++) {
            utility += strategy[i] * computeActionUtility(i, bucket);
        }

        return utility;
    }

    function computeActionUtility(action, bucket) {
        return bucket.averageEquity * (action === 0 ? 0 : 1);
    }

    function solveCfrPlus(context) {
        if (!context || !context.villainRange || !context.villainRange.combos?.length) {
            return null;
        }

        const totalWeight = context.villainRange.totalWeight;
        if (!Number.isFinite(totalWeight) || totalWeight <= 0) {
            return null;
        }

        const potSize = Math.max(0, Number(context.potSize) || 0);
        const stackSize = Math.max(0, Number(context.stackSize) || 0);
        const baseBet = Math.max(0, Number(context.betSize) || 0);
        const iterations = Math.max(1000, Math.min(100000, Number(context.iterations) || 15000));
        const exploitabilityThreshold = Number(context.exploitabilityThreshold) || 0.001;

        const isomorphicGroups = detectSuitIsomorphisms(context.board || []);
        const normalizedCombos = context.villainRange.combos.map(combo => ({
            ...combo,
            cards: normalizeHandBySuit(combo.cards, isomorphicGroups)
        }));

        const buckets = enhancedBucketization(
            normalizedCombos,
            totalWeight,
            Math.max(8, Math.ceil(Math.sqrt(normalizedCombos.length))),
            context.bucketingStrategy || 'emd'
        );

        if (!buckets.length) return null;

        const heroRoot = createInfoSetPlus(2);
        const actionSizes = [baseBet];
        let convergenceData = [];
        let exploitability = Infinity;

        for (let iteration = 1; iteration <= iterations && exploitability > exploitabilityThreshold; iteration++) {
            const heroStrategy = regretMatchingPlus(heroRoot, iteration);
            const branchUtilities = [0, 0];

            buckets.forEach(bucket => {
                const bucketProb = bucket.probability;

                if (!bucket.villainVsBet.has('bet')) {
                    bucket.villainVsBet.set('bet', createInfoSetPlus(2));
                }
                if (!bucket.villainVsCheck.has('check')) {
                    bucket.villainVsCheck.set('check', createInfoSetPlus(2));
                }

                const villainVsBetInfo = bucket.villainVsBet.get('bet');
                const villainVsCheckInfo = bucket.villainVsCheck.get('check');

                const villainBetStrategy = regretMatchingPlus(villainVsBetInfo, iteration);
                const villainCheckStrategy = regretMatchingPlus(villainVsCheckInfo, iteration);

                const callUtility = computeCallUtility(bucket.averageEquity, potSize, baseBet);
                const showdownUtility = bucket.averageEquity * potSize;

                const heroBetUtility = villainBetStrategy[0] * potSize + villainBetStrategy[1] * callUtility;
                const heroCheckUtility = villainCheckStrategy[0] * showdownUtility + villainCheckStrategy[1] * callUtility;

                branchUtilities[0] += bucketProb * heroBetUtility;
                branchUtilities[1] += bucketProb * heroCheckUtility;

                const heroReachProb = heroStrategy[0] * bucketProb;
                updateStrategySum(villainVsBetInfo, villainBetStrategy, iteration, heroReachProb);

                const villainBetRegrets = [
                    -potSize - heroBetUtility,
                    -callUtility - heroBetUtility
                ];
                updateCumulativeRegret(villainVsBetInfo, villainBetRegrets, iteration, heroReachProb);

                const heroCheckReachProb = heroStrategy[1] * bucketProb;
                updateStrategySum(villainVsCheckInfo, villainCheckStrategy, iteration, heroCheckReachProb);

                const villainCheckRegrets = [
                    -showdownUtility - heroCheckUtility,
                    -callUtility - heroCheckUtility
                ];
                updateCumulativeRegret(villainVsCheckInfo, villainCheckRegrets, iteration, heroCheckReachProb);
            });

            const nodeUtility = heroStrategy[0] * branchUtilities[0] + heroStrategy[1] * branchUtilities[1];
            const heroRegrets = [
                branchUtilities[0] - nodeUtility,
                branchUtilities[1] - nodeUtility
            ];

            updateCumulativeRegret(heroRoot, heroRegrets, iteration, 1.0);
            updateStrategySum(heroRoot, heroStrategy, iteration, 1.0);

            if (iteration % 1000 === 0) {
                exploitability = calculateExploitability(buckets, heroStrategy, {});
                convergenceData.push({
                    iteration,
                    exploitability,
                    avgRegret: heroRoot.cumulativeRegret.reduce((sum, r) => sum + Math.abs(r), 0) / heroRoot.cumulativeRegret.length
                });
            }
        }

        const finalHeroStrategy = getAverageStrategy(heroRoot);
        const callProbabilities = buckets.map(bucket => {
            const villainInfo = bucket.villainVsBet.get('bet');
            return villainInfo ? getAverageStrategy(villainInfo)[1] : 0.5;
        });

        const betAfterCheckProbabilities = buckets.map(bucket => {
            const villainInfo = bucket.villainVsCheck.get('check');
            return villainInfo ? getAverageStrategy(villainInfo)[1] : 0.5;
        });

        const details = buildDetailedResults(totalWeight, buckets, callProbabilities);

        return {
            heroStrategy: {
                bet: clampProbability(finalHeroStrategy[0]),
                check: clampProbability(finalHeroStrategy[1])
            },
            villainCallFrequency: callProbabilities.reduce((sum, p, i) => sum + p * buckets[i].probability, 0),
            villainFoldFrequency: 1 - callProbabilities.reduce((sum, p, i) => sum + p * buckets[i].probability, 0),
            villainBetAfterCheckFrequency: betAfterCheckProbabilities.reduce((sum, p, i) => sum + p * buckets[i].probability, 0),
            evBet: branchUtilities[0],
            evCheck: branchUtilities[1],
            heroUtility: finalHeroStrategy[0] * branchUtilities[0] + finalHeroStrategy[1] * branchUtilities[1],
            callDetails: details,
            callProbabilities,
            betAfterCheckProbabilities,
            exploitability,
            convergenceData,
            metadata: {
                iterations: convergenceData[convergenceData.length - 1]?.iteration || iterations,
                isomorphicGroups,
                bucketCount: buckets.length,
                finalExploitability: exploitability
            }
        };
    }

    function buildDetailedResults(totalWeight, buckets, callProbabilities) {
        const details = [];

        buckets.forEach((bucket, index) => {
            bucket.combos.forEach(combo => {
                details.push({
                    cards: combo.cards,
                    heroEquity: combo.equity,
                    callProbability: clampProbability(callProbabilities[index]),
                    weightShare: combo.weight / totalWeight
                });
            });
        });

        details.sort((a, b) => b.callProbability - a.callProbability || b.heroEquity - a.heroEquity);

        return details.slice(0, 200);
    }

    const solverApi = {
        solveFromContext: solveCfrPlus,
        detectIsomorphisms: detectSuitIsomorphisms,
        normalizeHand: normalizeHandBySuit
    };

    if (registry) {
        registry.register({
            id: "enhancedCfrPlus",
            label: "Enhanced CFR+ Solver",
            description: "Advanced CFR+ implementation with suit isomorphism detection, enhanced bucketing strategies, and exploitability-based convergence.",
            priority: 35,
            version: "1.0.0",
            origin: "Enhanced AlphaPoker CFR+ with TexasSolver optimizations",
            solve(context) {
                const summary = solveCfrPlus(context);
                if (!summary) {
                    return { ok: false, diagnostics: { reason: "enhancedCfrPlus: invalid context" } };
                }

                return {
                    ok: true,
                    summary,
                    detail: summary.metadata,
                    diagnostics: {
                        finalExploitability: summary.exploitability,
                        iterations: summary.metadata.iterations,
                        bucketCount: summary.metadata.bucketCount,
                        isomorphicGroups: summary.metadata.isomorphicGroups.length,
                        convergencePoints: summary.convergenceData.length
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.EnhancedCFRPlus = solverApi;
})(typeof window !== "undefined" ? window : globalThis);