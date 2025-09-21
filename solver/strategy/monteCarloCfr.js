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

    function createMCInfoSet(actionCount) {
        return {
            regretSum: new Float32Array(actionCount),
            strategySum: new Float32Array(actionCount),
            currentStrategy: new Float32Array(actionCount),
            sampleCount: 0,
            totalReachProb: 0
        };
    }

    function regretMatching(infoSet) {
        let positiveSum = 0;

        for (let i = 0; i < infoSet.regretSum.length; i += 1) {
            const regret = Math.max(0, infoSet.regretSum[i]);
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

    function getAverageStrategy(infoSet) {
        const avgStrategy = new Array(infoSet.strategySum.length);

        if (infoSet.totalReachProb <= 1e-12) {
            const uniform = 1 / avgStrategy.length;
            for (let i = 0; i < avgStrategy.length; i += 1) {
                avgStrategy[i] = uniform;
            }
        } else {
            for (let i = 0; i < avgStrategy.length; i += 1) {
                avgStrategy[i] = infoSet.strategySum[i] / infoSet.totalReachProb;
            }
        }

        return avgStrategy;
    }

    function weightedSample(probabilities) {
        const cumulative = [];
        let sum = 0;

        for (let i = 0; i < probabilities.length; i += 1) {
            sum += probabilities[i];
            cumulative[i] = sum;
        }

        if (sum <= 1e-12) {
            return Math.floor(Math.random() * probabilities.length);
        }

        const random = Math.random() * sum;
        for (let i = 0; i < cumulative.length; i += 1) {
            if (random <= cumulative[i]) {
                return i;
            }
        }

        return probabilities.length - 1;
    }

    function shuffleArray(array) {
        const shuffled = array.slice();
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        return shuffled;
    }

    function computeCallUtility(equity, potSize, betSize) {
        const eq = clampProbability(equity);
        if (betSize <= 0) {
            return eq * potSize;
        }
        return eq * (potSize + 2 * betSize) - betSize;
    }

    function sampleCombos(combos, sampleSize) {
        if (combos.length <= sampleSize) {
            return combos.slice();
        }

        const weights = combos.map(combo => Number(combo.weight) || 0);
        const totalWeight = weights.reduce((sum, w) => sum + w, 0);

        if (totalWeight <= 0) {
            return shuffleArray(combos).slice(0, sampleSize);
        }

        const probabilities = weights.map(w => w / totalWeight);
        const sampled = [];
        const sampledIndices = new Set();

        while (sampled.length < sampleSize && sampledIndices.size < combos.length) {
            const index = weightedSample(probabilities);
            if (!sampledIndices.has(index)) {
                sampledIndices.add(index);
                sampled.push({
                    ...combos[index],
                    sampleWeight: totalWeight / sampleSize
                });
            }
        }

        return sampled;
    }

    function chanceSamplingCFR(context, samplingStrategy = 'chance') {
        if (!context || !context.villainRange || !context.villainRange.combos?.length) {
            return null;
        }

        const combos = context.villainRange.combos;
        const totalWeight = context.villainRange.totalWeight;
        const potSize = Math.max(0, Number(context.potSize) || 0);
        const betSize = Math.max(0, Number(context.betSize) || 0);
        const iterations = Math.max(5000, Math.min(200000, Number(context.iterations) || 25000));
        const explorationRate = clampProbability(Number(context.exploration) || 0.1);

        const maxSampleSize = Math.max(50, Math.min(200, Math.floor(combos.length * 0.3)));
        const heroInfoSets = new Map();
        const villainInfoSets = new Map();

        let exploitabilityHistory = [];
        let cumulativeUtility = 0;

        for (let iteration = 1; iteration <= iterations; iteration++) {
            let sampledCombos;

            switch (samplingStrategy) {
                case 'outcome':
                    sampledCombos = sampleCombos(combos, Math.min(maxSampleSize, 20));
                    break;
                case 'external':
                    sampledCombos = sampleCombos(combos, Math.min(maxSampleSize, 100));
                    break;
                case 'chance':
                default:
                    sampledCombos = sampleCombos(combos, maxSampleSize);
                    break;
            }

            if (!sampledCombos.length) continue;

            if (!heroInfoSets.has('root')) {
                heroInfoSets.set('root', createMCInfoSet(2));
            }

            const heroRoot = heroInfoSets.get('root');
            const heroStrategy = regretMatching(heroRoot);

            let iterationUtility = 0;
            const actionUtilities = [0, 0];

            sampledCombos.forEach(combo => {
                const equity = clampProbability(Number(combo.heroEquity) || 0.5);
                const weight = Number(combo.sampleWeight) || 1;
                const weightShare = weight / totalWeight;

                const villainBetKey = `villain_bet_${Math.floor(equity * 10)}`;
                const villainCheckKey = `villain_check_${Math.floor(equity * 10)}`;

                if (!villainInfoSets.has(villainBetKey)) {
                    villainInfoSets.set(villainBetKey, createMCInfoSet(2));
                }
                if (!villainInfoSets.has(villainCheckKey)) {
                    villainInfoSets.set(villainCheckKey, createMCInfoSet(2));
                }

                const villainBetInfo = villainInfoSets.get(villainBetKey);
                const villainCheckInfo = villainInfoSets.get(villainCheckKey);

                let villainBetStrategy = regretMatching(villainBetInfo);
                let villainCheckStrategy = regretMatching(villainCheckInfo);

                if (samplingStrategy === 'outcome' && Math.random() < explorationRate) {
                    villainBetStrategy = villainBetStrategy.map(() => 1 / villainBetStrategy.length);
                    villainCheckStrategy = villainCheckStrategy.map(() => 1 / villainCheckStrategy.length);
                }

                const callUtility = computeCallUtility(equity, potSize, betSize);
                const showdownUtility = equity * potSize;

                const heroBetUtility = villainBetStrategy[0] * potSize + villainBetStrategy[1] * callUtility;
                const heroCheckUtility = villainCheckStrategy[0] * showdownUtility + villainCheckStrategy[1] * 0;

                actionUtilities[0] += weightShare * heroBetUtility;
                actionUtilities[1] += weightShare * heroCheckUtility;

                const heroReachProb = heroStrategy[0] * weightShare;
                const villainBetRegrets = [
                    -potSize - heroBetUtility,
                    -callUtility - heroBetUtility
                ];

                for (let i = 0; i < villainBetRegrets.length; i++) {
                    villainBetInfo.regretSum[i] += heroReachProb * villainBetRegrets[i];
                    villainBetInfo.strategySum[i] += heroReachProb * villainBetStrategy[i];
                }
                villainBetInfo.totalReachProb += heroReachProb;
                villainBetInfo.sampleCount++;

                const heroCheckReachProb = heroStrategy[1] * weightShare;
                const villainCheckRegrets = [
                    -showdownUtility - heroCheckUtility,
                    0 - heroCheckUtility
                ];

                for (let i = 0; i < villainCheckRegrets.length; i++) {
                    villainCheckInfo.regretSum[i] += heroCheckReachProb * villainCheckRegrets[i];
                    villainCheckInfo.strategySum[i] += heroCheckReachProb * villainCheckStrategy[i];
                }
                villainCheckInfo.totalReachProb += heroCheckReachProb;
                villainCheckInfo.sampleCount++;
            });

            const nodeUtility = heroStrategy[0] * actionUtilities[0] + heroStrategy[1] * actionUtilities[1];
            const heroRegrets = [
                actionUtilities[0] - nodeUtility,
                actionUtilities[1] - nodeUtility
            ];

            for (let i = 0; i < heroRegrets.length; i++) {
                heroRoot.regretSum[i] += heroRegrets[i];
                heroRoot.strategySum[i] += heroStrategy[i];
            }
            heroRoot.totalReachProb += 1.0;
            heroRoot.sampleCount++;

            iterationUtility = nodeUtility;
            cumulativeUtility += iterationUtility;

            if (iteration % 2500 === 0) {
                const avgRegret = Array.from(heroInfoSets.values())
                    .concat(Array.from(villainInfoSets.values()))
                    .reduce((sum, info) => {
                        return sum + info.regretSum.reduce((s, r) => s + Math.abs(r), 0);
                    }, 0) / (heroInfoSets.size + villainInfoSets.size);

                exploitabilityHistory.push({
                    iteration,
                    averageRegret: avgRegret,
                    cumulativeUtility: cumulativeUtility / iteration,
                    infoSets: heroInfoSets.size + villainInfoSets.size
                });
            }
        }

        const finalHeroStrategy = getAverageStrategy(heroInfoSets.get('root'));

        const callProbabilities = [];
        const betAfterCheckProbabilities = [];

        for (let i = 0; i < 10; i++) {
            const betKey = `villain_bet_${i}`;
            const checkKey = `villain_check_${i}`;

            const betInfo = villainInfoSets.get(betKey);
            const checkInfo = villainInfoSets.get(checkKey);

            callProbabilities.push(betInfo ? getAverageStrategy(betInfo)[1] : 0.5);
            betAfterCheckProbabilities.push(checkInfo ? getAverageStrategy(checkInfo)[1] : 0.3);
        }

        const overallCallFreq = callProbabilities.reduce((sum, p) => sum + p, 0) / callProbabilities.length;
        const overallBetAfterCheckFreq = betAfterCheckProbabilities.reduce((sum, p) => sum + p, 0) / betAfterCheckProbabilities.length;

        const details = buildMCDetails(combos, callProbabilities, totalWeight);

        return {
            heroStrategy: {
                bet: clampProbability(finalHeroStrategy[0]),
                check: clampProbability(finalHeroStrategy[1])
            },
            villainCallFrequency: clampProbability(overallCallFreq),
            villainFoldFrequency: clampProbability(1 - overallCallFreq),
            villainBetAfterCheckFrequency: clampProbability(overallBetAfterCheckFreq),
            evBet: actionUtilities[0],
            evCheck: actionUtilities[1],
            heroUtility: cumulativeUtility / iterations,
            callDetails: details,
            callProbabilities,
            betAfterCheckProbabilities,
            exploitabilityHistory,
            metadata: {
                iterations,
                samplingStrategy,
                maxSampleSize,
                totalInfoSets: heroInfoSets.size + villainInfoSets.size,
                explorationRate,
                convergenceData: exploitabilityHistory
            }
        };
    }

    function buildMCDetails(combos, callProbabilities, totalWeight) {
        const details = [];

        combos.slice(0, 150).forEach(combo => {
            const equity = clampProbability(Number(combo.heroEquity) || 0.5);
            const bucketIndex = Math.min(9, Math.floor(equity * 10));
            const callProb = callProbabilities[bucketIndex] || 0.5;

            details.push({
                cards: combo.cards,
                heroEquity: equity,
                callProbability: clampProbability(callProb),
                weightShare: Number(combo.weight || 0) / totalWeight
            });
        });

        details.sort((a, b) => b.callProbability - a.callProbability || b.heroEquity - a.heroEquity);

        return details;
    }

    const solverApi = {
        solveFromContext: (context) => chanceSamplingCFR(context, 'chance'),
        solveChanceSampling: (context) => chanceSamplingCFR(context, 'chance'),
        solveOutcomeSampling: (context) => chanceSamplingCFR(context, 'outcome'),
        solveExternalSampling: (context) => chanceSamplingCFR(context, 'external')
    };

    if (registry) {
        registry.register({
            id: "monteCarloCfr",
            label: "Monte Carlo CFR",
            description: "Advanced Monte Carlo CFR with multiple sampling strategies: chance sampling, outcome sampling, and external sampling for scalable poker solving.",
            priority: 30,
            version: "1.0.0",
            origin: "Enhanced AlphaPoker Monte Carlo CFR with sampling optimizations",
            solve(context) {
                const samplingStrategy = context.samplingStrategy || 'chance';
                let summary;

                switch (samplingStrategy) {
                    case 'outcome':
                        summary = solverApi.solveOutcomeSampling(context);
                        break;
                    case 'external':
                        summary = solverApi.solveExternalSampling(context);
                        break;
                    default:
                        summary = solverApi.solveChanceSampling(context);
                        break;
                }

                if (!summary) {
                    return { ok: false, diagnostics: { reason: `monteCarloCfr: invalid context for ${samplingStrategy} sampling` } };
                }

                return {
                    ok: true,
                    summary,
                    detail: summary.metadata,
                    diagnostics: {
                        samplingStrategy: summary.metadata.samplingStrategy,
                        iterations: summary.metadata.iterations,
                        totalInfoSets: summary.metadata.totalInfoSets,
                        maxSampleSize: summary.metadata.maxSampleSize,
                        convergencePoints: summary.metadata.convergenceData.length
                    }
                };
            },
            exports: solverApi
        });
    }

    namespace.MonteCarloCFR = solverApi;
})(typeof window !== "undefined" ? window : globalThis);