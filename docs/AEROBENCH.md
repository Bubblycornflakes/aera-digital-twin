# AeroBench

A benchmark of whether a tuner, including an LLM agent, can tune the dissolved oxygen (DO) controller of the BSM1 activated sludge plant from simulation trials, and whether its answer still works on scenarios it never saw. Design rationale and decisions: `AEROBENCH_DESIGN.md`. The plant is checked against the published BSM1 results in `BSM1_REPRODUCTION.md`.

## Task
The controller is a PI loop on the last aerated reactor that sets its oxygen transfer coefficient. The tuner chooses four numbers:

| Parameter | Meaning | Range | BSM1 default |
| --- | --- | --- | --- |
| `so_ref` | DO setpoint, g/m3 | 0.5 to 5 | 2 |
| `k_do` | proportional gain, 1/d per g/m3 | 1 to 500 | 25 |
| `ti_do` | integral time, d | 0.0005 to 0.02 | 0.002 |
| `kla_max` | actuator limit, 1/d | 120 to 360 | 360 |

Stage 2 (`--stage 2`) adds an ammonia cascade: setpoint = `so_ref` + `nh_gain` x (ammonium in the last reactor − `nh_ref`), using an ideal sensor.

A tuner gets 40 trials on the training scenario (BSM1 dry weather). Each trial returns aeration energy, effluent quality, the share of time over each effluent limit, feasibility and a coarse trajectory. It then submits one set of parameters.

## Scoring
Held-out scenarios, run on three plants (benchmark; fouled diffusers with 25% lower oxygen transfer; slow nitrifiers with 20% lower growth rate): rain weather, storm weather, dry weather with a 116 kg N return liquor pulse (20% of the daily nitrogen load, inside the typical 15 to 25% range), dry weather with sensor faults (double noise, +0.3 g/m3 bias, 5 times slower sensor), and rain with both a liquor pulse and a negative sensor bias.

Feasible means that, in every held-out scenario, the share of time over each of the five BSM1 effluent limits (total nitrogen 18, total COD 100, ammonium 4, suspended solids 30, BOD5 10 g/m3) is no worse than under the BSM1 default controller on the same scenario plus a tolerance of 0.5 percentage points, and true DO is below 0.5 g/m3 for at most 1% of the time. The default controller itself exceeds the nitrogen and ammonium limits for 11 to 27% of the time on the dry, rain and storm files, so a fixed percentage limit was not used. Energy (the updated BSM1 aeration energy index, kWh/d) is compared only after feasibility.

Reported per run: feasibility, which scenarios and limits failed and by how much, held-out aeration energy, and the saving against the default.

## Reference tuners (40 trials, 3 plants, 3 seeds for stochastic ones)
<!-- leaderboard-full:start -->
| Tuner | Runs | Feasible (95% interval) | Saving vs BSM1 default, feasible runs | Most common failures |
| --- | --- | --- | --- | --- |
| bsm1_default | 3 | 100% (44% to 100%) | 0.0% | none |
| llm_ollama_qwen3_8b | 3 | 33% (6% to 79%) | 0.0% | storm:snh (2), dry_return_liquor:snh (1), dry_sensor_fault:snh (1) |
| bayesian_optimisation | 9 | 22% (6% to 55%) | 0.07% | rain:total_n (5), rain_liquor_and_fault:snh (4), dry_sensor_fault:low_do (2) |
| bayesian_optimisation_stage2 | 3 | 0% (0% to 56%) | n/a | dry_sensor_fault:low_do (2), rain:total_n (2), dry_return_liquor:total_n (1) |
| differential_evolution | 9 | 0% (0% to 30%) | n/a | rain_liquor_and_fault:snh (6), dry_sensor_fault:snh (5), rain:total_n (5) |
| random_search | 9 | 0% (0% to 30%) | n/a | rain:total_n (7), dry_sensor_fault:low_do (4), dry_sensor_fault:snh (4) |
| random_search_stage2 | 3 | 0% (0% to 56%) | n/a | dry_sensor_fault:low_do (2), dry_sensor_fault:snh (1), rain:snh (1) |
| ziegler_nichols | 3 | 0% (0% to 56%) | n/a | dry_sensor_fault:snh (3), dry_sensor_fault:low_do (1), rain_liquor_and_fault:snh (1) |
<!-- leaderboard-full:end -->

A negative saving means the answer used more energy than the default.

What this shows, and what it does not:
- Tuning on the training scenario rarely generalises. Over the 30 stage 1 runs of the reference tuners (excluding the default) the most frequent failures were the sensor fault scenario (31 failed rules), rain with a pulse and a fault (23), rain (20), storm (14) and the dry weather pulse (10).
- No tuner found a feasible setting that saved energy. The two feasible Bayesian runs saved 0.16% and -0.01%; the local model's one feasible answer was essentially the BSM1 default (saving 0.0%). The default is hard to beat under this rule.
- Intervals are wide. With 3 to 9 runs per tuner, only the gap between the default (feasible by construction) and the other tuners is clear; the ranking among Bayesian optimisation, differential evolution, random search and the local model is not.
- The result depends on the tolerance (percentage points of time over a limit, beyond the default). Share of runs feasible as it grows:

<!-- sensitivity:start -->
| Tuner | 0 | 0.005 | 0.01 | 0.02 | 0.05 |
| --- | --- | --- | --- | --- | --- |
| bayesian_optimisation | 0% | 22% | 33% | 56% | 67% |
| bsm1_default | 100% | 100% | 100% | 100% | 100% |
| differential_evolution | 0% | 0% | 11% | 44% | 78% |
| llm_ollama_qwen3_8b | 33% | 33% | 67% | 67% | 100% |
| random_search | 0% | 0% | 0% | 33% | 44% |
| ziegler_nichols | 0% | 0% | 33% | 67% | 67% |
<!-- sensitivity:end -->

- The stage 2 rows have three runs each and no feasible run; that is not evidence about ammonia-based control in general.
- Ziegler-Nichols here is the reaction curve rule (Kc = 0.9 T / (K L), Ti = 3.33 L) from one open loop step test. It gives k_do about 130 and ti_do about 0.0043 d, against 25 and 0.002 for the default, and fails the sensor fault scenario on every plant.
- One small local model has been scored (`qwen3:8b` via Ollama, 3 runs, 1 epoch): it used 4 to 6 of 40 trials, needed 3 to 10 re-prompts per run (the harness nudges a model that stops without calling a tool, up to 15 times, and records the count), and its one feasible answer was essentially the BSM1 default. This is far too little to say anything about LLMs in general. Claude and GPT models have not been scored; that needs a provider API key (see below).

## Running
```
python scripts/fetch_bsm1.py                                  # downloads and checksums the IWA archive into data/
python -m aera.run_benchmark                                  # reference tuners, all plants (about an hour on 8 cores)
python -m aera.leaderboard                                    # results/leaderboard.json and a table
python -m aera.report results/report.html                     # standalone HTML report
inspect eval aerobench_task.py --model <provider/model>       # an LLM agent; hosted models need the provider API key in the environment
inspect eval aerobench_task.py --model ollama/qwen3:8b        # free, local, no key (needs Ollama and `pip install openai`)
python -m aera.import_inspect results/logs/*.eval             # add Inspect runs to the leaderboard
```
Solver modes: `fast` (rtol 1e-3, used for training trials, about 12 s per 14 day run) and `full` (rtol 1e-4, used for held-out scoring). Both reproduce the strict tolerance indices to within 0.05% on dry weather.

## Bring your own tuner
A tuner is a function `tuner(env) -> params`. `env.trial(params)` runs the training scenario; stop when `env.used` reaches `env.budget`. See `examples/hill_climber.py`, then:
```
python -m aera.run_benchmark --tuner examples.hill_climber:hill_climber --seeds 1
```
To add a result to the leaderboard, commit the new files in `results/runs/` and open a pull request.

## Private held-out set (commit-reveal)
The public held-out scenarios are in this repository, so anyone can tune against them. For a fair comparison the maintainer can score answers on a **private set** generated from a secret seed:

```
python -m aera.private_set generate --seed-file secret_seed.txt --out private_set.json     # publish the printed commitment; keep both files private
python -m aera.rescore --held-out private_set.json                                          # scores every stored answer; results go to results/private_runs/
python -m aera.leaderboard --runs results/private_runs --out results/private_leaderboard.json
python -m aera.private_set verify --seed-file secret_seed.txt --set private_set.json        # anyone, after the seed is revealed
```
A set has 6 scenarios (every weather file appears; a return liquor pulse, sensor faults with random size, bias and delay, and a rotated noise file) and 3 extra plants, all drawn from the public ranges in `aera/private_set.py`. The maintainer publishes only the SHA-256 commitment of the seed. After a scoring round the seed is revealed, so anyone can regenerate the set, check it matches the commitment, and reproduce the scores. Each result carries a label such as `private:ab12cd34:9f01ee`. Private results and files are git-ignored.

What this does and does not give you: the scenarios cannot be reconstructed before the reveal, and a tuner cannot overfit what it cannot see. But a Python tuner run on the same machine could read the file (see Integrity), the set is only as secret as the seed, and the ranges are public, so a tuner can be built to be robust to them, which is the point. No private results exist yet: this is the mechanism, not a published leaderboard.

## Integrity
A model run through the Inspect task can only call `run_trial` (training scenario, metered) and `submit_gains`; the held-out scenarios are not reachable. A Python tuner passed to `aera.run_benchmark` is different: it runs in the same process as the scorer and could import the scoring functions or change internal state, so it is trusted, not sandboxed. `Environment` makes the budget read-only and thread safe to prevent accidents, not cheating. Treat leaderboard entries you did not run yourself as self-reported. The results cache is keyed on the controller, scenario, solver mode and a fingerprint of the model version and standard start state, so results from an older model are never reused.

## Limits
- BSM1 at a fixed 15 degrees Celsius, not a calibrated plant. Nothing here is a facility saving estimate.
- BSM1 is public, so a language model may recall its default settings. The held-out scenarios, plant variants and sensor faults reduce this, but results are not zero-shot evidence.
- The feasibility tolerance, scenario set and plant variants were chosen by the author, not taken from a standard. The sensitivity table above shows the effect of the tolerance.
- The tuner sees the plant it is scored on. Two of the five held-out scenarios (the dry weather pulse and sensor fault) share the dry influent file with the training scenario; only the pulse or fault differs. All held-out scenarios use a rotated sensor noise file, so noise is not shared.
- Pumping and mixing energy and sludge production are not scored.
- The ideal ammonium sensor in stage 2 is a simplification.
