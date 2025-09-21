(function (global) {
    const root = typeof global !== "undefined" ? global : globalThis;
    const namespace = root.AlphaPoker || (root.AlphaPoker = Object.create(null));
    const registry = namespace.Solvers && typeof namespace.Solvers.register === "function" ? namespace.Solvers : null;

    function detectWorkerSupport() {
        if (typeof Worker === 'undefined') {
            return false;
        }

        try {
            const testWorker = new Worker(
                URL.createObjectURL(new Blob(['self.postMessage("test");'], { type: 'application/javascript' }))
            );
            testWorker.terminate();
            return true;
        } catch (error) {
            return false;
        }
    }

    function createSolverWorker() {
        const workerCode = `
            // Import existing solver implementations
            ${createWorkerSolverCode()}
        `;

        return new Worker(
            URL.createObjectURL(new Blob([workerCode], { type: 'application/javascript' }))
        );
    }

    function createWorkerSolverCode() {
        return `
            // Utility functions for worker thread
            function clampProbability(value) {
                if (!Number.isFinite(value)) return 0;
                return Math.max(0, Math.min(1, value));
            }

            function createInfoSet(actionCount) {
                return {
                    regret: new Float32Array(actionCount),
                    strategy: new Float32Array(actionCount),
                    strategySum: new Float32Array(actionCount),
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
                if (betSize <= 0) return eq * potSize;
                return eq * (potSize + 2 * betSize) - betSize;
            }

            function bucketizeCombos(combos, totalWeight, maxBuckets) {
                const filtered = [];
                for (let i = 0; i < combos.length; i += 1) {
                    const combo = combos[i];
                    const weight = Number(combo.weight) || 0;
                    if (weight <= 0) continue;

                    filtered.push({
                        index: i,
                        weight,
                        equity: clampProbability(combo.heroEquity),
                        cards: combo.cards
                    });
                }

                if (!filtered.length) return [];

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

                return buckets.filter(b => b.weight > 0).map(bucket => {
                    const totalBucketWeight = buckets.reduce((sum, b) => sum + b.weight, 0) || 1;
                    bucket.probability = bucket.weight / totalBucketWeight;
                    return bucket;
                });
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

            function workerSolveCFR(context, progressCallback) {
                const combos = context.villainRange.combos;
                const totalWeight = context.villainRange.totalWeight;
                const potSize = Math.max(0, Number(context.potSize) || 0);
                const betSize = Math.max(0, Number(context.betSize) || 0);
                const iterations = Math.max(1000, Math.min(150000, Number(context.iterations) || 20000));
                const progressInterval = Math.max(100, Math.floor(iterations / 100));

                const buckets = bucketizeCombos(combos, totalWeight, 12);
                if (!buckets.length) return null;

                const heroRoot = createInfoSet(2);
                const villainInfoSets = new Map();

                let cumulativeUtility = 0;
                let avgRegretSum = 0;

                for (let iteration = 1; iteration <= iterations; iteration++) {
                    const heroStrategy = regretMatching(heroRoot);
                    const branchUtilities = [0, 0];

                    buckets.forEach(bucket => {
                        const bucketProb = bucket.probability;

                        if (!villainInfoSets.has(\`bet_\${bucket.averageEquity.toFixed(2)}\`)) {
                            villainInfoSets.set(\`bet_\${bucket.averageEquity.toFixed(2)}\`, createInfoSet(2));
                        }
                        if (!villainInfoSets.has(\`check_\${bucket.averageEquity.toFixed(2)}\`)) {
                            villainInfoSets.set(\`check_\${bucket.averageEquity.toFixed(2)}\`, createInfoSet(2));
                        }

                        const villainBetInfo = villainInfoSets.get(\`bet_\${bucket.averageEquity.toFixed(2)}\`);
                        const villainCheckInfo = villainInfoSets.get(\`check_\${bucket.averageEquity.toFixed(2)}\`);

                        const villainBetStrategy = regretMatching(villainBetInfo);
                        const villainCheckStrategy = regretMatching(villainCheckInfo);

                        const callUtility = computeCallUtility(bucket.averageEquity, potSize, betSize);
                        const showdownUtility = bucket.averageEquity * potSize;

                        const heroBetUtility = villainBetStrategy[0] * potSize + villainBetStrategy[1] * callUtility;
                        const heroCheckUtility = villainCheckStrategy[0] * showdownUtility + villainCheckStrategy[1] * callUtility * 0.8;

                        branchUtilities[0] += bucketProb * heroBetUtility;
                        branchUtilities[1] += bucketProb * heroCheckUtility;

                        // Update villain strategies
                        const heroReachProb = heroStrategy[0] * bucketProb;
                        villainBetInfo.visitWeight += heroReachProb;
                        villainBetInfo.strategySum[0] += heroReachProb * villainBetStrategy[0];
                        villainBetInfo.strategySum[1] += heroReachProb * villainBetStrategy[1];

                        const villainBetRegrets = [
                            -potSize - heroBetUtility,
                            -callUtility - heroBetUtility
                        ];
                        villainBetInfo.regret[0] += heroReachProb * villainBetRegrets[0];
                        villainBetInfo.regret[1] += heroReachProb * villainBetRegrets[1];

                        const heroCheckReachProb = heroStrategy[1] * bucketProb;
                        villainCheckInfo.visitWeight += heroCheckReachProb;
                        villainCheckInfo.strategySum[0] += heroCheckReachProb * villainCheckStrategy[0];
                        villainCheckInfo.strategySum[1] += heroCheckReachProb * villainCheckStrategy[1];

                        const villainCheckRegrets = [
                            -showdownUtility - heroCheckUtility,
                            -callUtility * 0.8 - heroCheckUtility
                        ];
                        villainCheckInfo.regret[0] += heroCheckReachProb * villainCheckRegrets[0];
                        villainCheckInfo.regret[1] += heroCheckReachProb * villainCheckRegrets[1];
                    });

                    const nodeUtility = heroStrategy[0] * branchUtilities[0] + heroStrategy[1] * branchUtilities[1];
                    const heroRegrets = [
                        branchUtilities[0] - nodeUtility,
                        branchUtilities[1] - nodeUtility
                    ];

                    heroRoot.regret[0] += heroRegrets[0];
                    heroRoot.regret[1] += heroRegrets[1];
                    heroRoot.strategySum[0] += heroStrategy[0];
                    heroRoot.strategySum[1] += heroStrategy[1];
                    heroRoot.visitWeight += 1;

                    cumulativeUtility += nodeUtility;
                    avgRegretSum += Math.abs(heroRegrets[0]) + Math.abs(heroRegrets[1]);

                    // Progress reporting
                    if (iteration % progressInterval === 0 && progressCallback) {
                        const progress = {
                            iteration,
                            progress: iteration / iterations,
                            avgUtility: cumulativeUtility / iteration,
                            avgRegret: avgRegretSum / iteration,
                            infoSets: villainInfoSets.size + 1
                        };
                        progressCallback(progress);
                    }
                }

                // Generate final results
                const finalHeroStrategy = heroRoot.visitWeight > 0 ? [
                    heroRoot.strategySum[0] / heroRoot.visitWeight,
                    heroRoot.strategySum[1] / heroRoot.visitWeight
                ] : [0.5, 0.5];

                const callProbabilities = [];
                const betAfterCheckProbabilities = [];

                buckets.forEach(bucket => {
                    const betKey = \`bet_\${bucket.averageEquity.toFixed(2)}\`;
                    const checkKey = \`check_\${bucket.averageEquity.toFixed(2)}\`;

                    const betInfo = villainInfoSets.get(betKey);
                    const checkInfo = villainInfoSets.get(checkKey);

                    const betCallProb = betInfo && betInfo.visitWeight > 0 ?
                        betInfo.strategySum[1] / betInfo.visitWeight : 0.5;
                    const checkBetProb = checkInfo && checkInfo.visitWeight > 0 ?
                        checkInfo.strategySum[1] / checkInfo.visitWeight : 0.3;

                    callProbabilities.push(clampProbability(betCallProb));
                    betAfterCheckProbabilities.push(clampProbability(checkBetProb));
                });

                const details = buckets.flatMap((bucket, index) =>
                    bucket.combos.slice(0, Math.ceil(200 / buckets.length)).map(combo => ({
                        cards: combo.cards,
                        heroEquity: combo.equity,
                        callProbability: callProbabilities[index],
                        weightShare: combo.weight / totalWeight
                    }))
                ).sort((a, b) => b.callProbability - a.callProbability || b.heroEquity - a.heroEquity);

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
                    heroUtility: cumulativeUtility / iterations,
                    callDetails: details,
                    callProbabilities,
                    betAfterCheckProbabilities,
                    avgRegret: avgRegretSum / iterations,
                    metadata: {
                        iterations,
                        bucketCount: buckets.length,
                        infoSets: villainInfoSets.size + 1,
                        avgUtility: cumulativeUtility / iterations
                    }
                };
            }

            // Worker message handler
            self.addEventListener('message', function(e) {
                const { type, context, messageId } = e.data;

                if (type === 'solve') {
                    try {
                        const result = workerSolveCFR(context, (progress) => {
                            self.postMessage({
                                type: 'progress',
                                messageId,
                                progress
                            });
                        });

                        self.postMessage({
                            type: 'result',
                            messageId,
                            result
                        });
                    } catch (error) {
                        self.postMessage({
                            type: 'error',
                            messageId,
                            error: error.message
                        });
                    }
                } else if (type === 'terminate') {
                    self.close();
                }
            });
        `;
    }

    class WorkerSolverManager {
        constructor() {
            this.workers = [];
            this.activeJobs = new Map();
            this.maxWorkers = Math.min(navigator.hardwareConcurrency || 4, 8);
            this.jobCounter = 0;
            this.supportsWorkers = detectWorkerSupport();
        }

        async initializeWorkers() {
            if (!this.supportsWorkers) {
                throw new Error('Web Workers are not supported in this environment');
            }

            const workerPromises = [];
            for (let i = 0; i < this.maxWorkers; i++) {
                workerPromises.push(this.createWorker());
            }

            this.workers = await Promise.all(workerPromises);
        }

        async createWorker() {
            return new Promise((resolve, reject) => {
                try {
                    const worker = createSolverWorker();

                    worker.addEventListener('message', (e) => {
                        this.handleWorkerMessage(worker, e);
                    });

                    worker.addEventListener('error', (e) => {
                        console.error('Worker error:', e);
                        reject(e);
                    });

                    resolve(worker);
                } catch (error) {
                    reject(error);
                }
            });
        }

        handleWorkerMessage(worker, e) {
            const { type, messageId, result, progress, error } = e.data;
            const job = this.activeJobs.get(messageId);

            if (!job) return;

            switch (type) {
                case 'progress':
                    if (job.onProgress) {
                        job.onProgress(progress);
                    }
                    break;

                case 'result':
                    job.resolve(result);
                    this.activeJobs.delete(messageId);
                    this.releaseWorker(worker);
                    break;

                case 'error':
                    job.reject(new Error(error));
                    this.activeJobs.delete(messageId);
                    this.releaseWorker(worker);
                    break;
            }
        }

        async solve(context, onProgress = null) {
            if (!this.supportsWorkers) {
                throw new Error('Web Workers not supported');
            }

            if (this.workers.length === 0) {
                await this.initializeWorkers();
            }

            const worker = await this.getAvailableWorker();
            const messageId = ++this.jobCounter;

            return new Promise((resolve, reject) => {
                this.activeJobs.set(messageId, {
                    resolve,
                    reject,
                    onProgress,
                    worker
                });

                worker.postMessage({
                    type: 'solve',
                    context,
                    messageId
                });
            });
        }

        async getAvailableWorker() {
            return new Promise((resolve) => {
                const checkWorker = () => {
                    for (const worker of this.workers) {
                        if (!this.isWorkerBusy(worker)) {
                            resolve(worker);
                            return;
                        }
                    }

                    setTimeout(checkWorker, 50);
                };

                checkWorker();
            });
        }

        isWorkerBusy(worker) {
            for (const job of this.activeJobs.values()) {
                if (job.worker === worker) {
                    return true;
                }
            }
            return false;
        }

        releaseWorker(worker) {
            // Worker is automatically released when job completes
        }

        terminate() {
            this.workers.forEach(worker => {
                worker.postMessage({ type: 'terminate' });
                worker.terminate();
            });
            this.workers = [];
            this.activeJobs.clear();
        }
    }

    const workerManager = new WorkerSolverManager();

    async function solveWithWorkers(context, onProgress = null) {
        if (!context || !context.villainRange || !context.villainRange.combos?.length) {
            return null;
        }

        try {
            const result = await workerManager.solve(context, onProgress);
            return result;
        } catch (error) {
            console.error('Worker solver error:', error);
            return null;
        }
    }

    const solverApi = {
        solveFromContext: solveWithWorkers,
        supportsWorkers: () => workerManager.supportsWorkers,
        getWorkerCount: () => workerManager.maxWorkers,
        initializeWorkers: () => workerManager.initializeWorkers(),
        terminate: () => workerManager.terminate()
    };

    if (registry) {
        registry.register({
            id: "webWorkerSolver",
            label: "Web Worker CFR Solver",
            description: "High-performance CFR solver using Web Workers for non-blocking computation with real-time progress updates.",
            priority: 40,
            version: "1.0.0",
            origin: "AlphaPoker Web Worker implementation for performance optimization",
            solve(context) {
                return new Promise(async (resolve) => {
                    let progressData = null;

                    const summary = await solveWithWorkers(context, (progress) => {
                        progressData = progress;
                    });

                    if (!summary) {
                        resolve({ ok: false, diagnostics: { reason: "webWorkerSolver: invalid context or worker error" } });
                        return;
                    }

                    resolve({
                        ok: true,
                        summary,
                        detail: summary.metadata,
                        diagnostics: {
                            workerSupport: workerManager.supportsWorkers,
                            maxWorkers: workerManager.maxWorkers,
                            iterations: summary.metadata.iterations,
                            bucketCount: summary.metadata.bucketCount,
                            infoSets: summary.metadata.infoSets,
                            lastProgress: progressData
                        }
                    });
                });
            },
            exports: solverApi
        });
    }

    namespace.WebWorkerSolver = solverApi;
})(typeof window !== "undefined" ? window : globalThis);