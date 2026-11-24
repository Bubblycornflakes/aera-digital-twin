# AeroBench design (v2, for approval)

Status: implemented, with the deviations listed in section 14. The current behaviour is documented in `AEROBENCH.md`; this file records the reasoning and the decisions.

## 1. Question the benchmark answers
Can an LLM agent, given a fixed budget of simulation trials, tune an activated sludge aeration controller so that effluent limits are met on disturbances it has never seen, using less aeration energy than a conventional controller? Success is judged on held-out scenarios, feasibility before energy.

## 2. What is wrong with v1
- It runs on the two-state educational basin, which has no clarifier, no recycles and one ammonia state.
- Its ammonia limit (8 mg N/L mean) was chosen by me so the reference controller fails. It is not from a standard.
- Its scenarios and plant variants are invented, not taken from BSM1 or a standard.
- Search baselines were run on a plant where the feasible region is narrow and set by the toy model, so the results say little.
Kept from v1: the Inspect AI task structure, the trial budget, the held-out scoring path, the search baselines and their tests.

## 3. Plant
Use the verified BSM1 plant already in the repo (`aera/asm1.py`, `aera/bsm1.py`): five reactors (two anoxic, three aerobic), internal recycle, return sludge and a ten-layer Takacs settler, fixed 15 degrees Celsius. Verified only for constant influent and open loop.

Measured on this machine: one simulated day with a feedback DO controller (15 minute control interval, restarted solver per interval) takes about 2.8 s. A 14 day run is about 20 s.

Missing and needed:
1. Dynamic influent: dry, rain and storm weather (`influent_files/*.ascii`, 14 days each). Now on disk (see section 13), not committed.
2. The BSM1 default closed loop, implemented in Python: a PI on reactor 5 DO acting on kLa5, and a PI on reactor 2 nitrate acting on the internal recycle flow. The repo plant currently holds the internal recycle constant, so it must be made a variable input. Sensor and actuator dynamics are needed too (section 13).
3. Effluent quality and aeration energy indices (section 6).
4. Optional ammonia-based outer loop (section 5).

## 4. Scenarios
Follow the BSM1 protocol (confirmed in the archive description): 100 days of closed loop stabilisation with constant influent, then the 14 day weather file, scoring days 7 to 14. Noise on measurements is used with the dynamic files.

| Set | Scenario |
| --- | --- |
| Training (visible to agent) | dry weather |
| Held out | rain; storm; dry weather with a return liquor pulse (15 to 25% of daily nitrogen over 6 hours, a typical digestate range); dry weather with DO sensor noise, +0.3 mg/L bias and 5 minute delay; rain with return liquor pulse and sensor fault together |

Plant variants (to stop the agent learning one plant): perturb oxygen transfer (alpha) and nitrifier growth rate by fixed seeded factors, so each sample is a slightly different plant. Held-out scenarios use plant seeds the agent never sees.

Contamination risk: BSM1 is public and a model may recall default controller settings. Held-out scenarios, plant perturbations and sensor faults reduce this, but results should not be read as zero-shot reasoning. State this in the README.

## 5. Agent action space
Stage 1 (v2 core): DO setpoint, Kp, Ki, controller sample time, kLa upper limit, each with documented bounds.
Stage 2 (extension, only after stage 1 works): ammonia-based setpoint cascade (published full-scale studies report about 16 to 20% savings from ammonia-based control, for example Rieger, Jones, Dold and Bott).

The agent never sees held-out results and cannot change plant parameters. Tools: `run_trial` (training scenario, returns metrics and a downsampled trajectory), `submit_gains` once. Budget: 40 trials, shared with all baselines.

## 6. Metrics and constraints
Constraints, confirmed from `perf_plant.m` in the archive: effluent total nitrogen 18, total COD 100, ammonium 4, suspended solids 30, BOD5 10 g/m3. The standard counts the share of time each limit is exceeded. Plus one author-chosen constraint: true DO below 0.5 mg/L for no more than 1% of the time (nitrous oxide risk).

The published BSM1 default closed loop itself violates two limits on dry weather (days 7 to 14): total nitrogen 18.3% of the time and ammonium 17.1% of the time. So a fixed "5% of time" rule, as first proposed, would make the standard reference infeasible. Revised feasibility rule: on each scenario, the share of time over each limit must be no worse than the BSM1 default controller's share on that same scenario (non-inferiority), plus the DO rule. A limit the default never violates must stay unviolated. This needs your approval (section 11).

Energy, primary: the updated BSM1 aeration energy index, the sum over reactors of SOSAT x volume x kLa divided by 1.8 x 1000, in kWh per day (archive `perf_plant.m`). Published value for the default controller on dry weather: 3,698 kWh/day (original version 7,241). Secondary: the equipment-based blower power model in `process_playback.py`, labelled illustrative. Also report the effluent quality index (published 6,123 kg pollution units per day, updated weights), pumping energy (published 241 kWh/day on BSM2 factors) and sludge production for context.

Cost and carbon: use the placeholder values already in `model.py` (0.25 pounds per kWh, 0.13096 kgCO2e per kWh) only to convert simulated energy. Published figures often assume about 20% aeration saving from DO control; the benchmark can show what the simulator gives, labelled simulated and unverified. `OPTIMISATION_ARCHITECTURE.md` forbids facility savings claims without independent verification, and this stays true.

## 7. Scoring and baselines
Per sample: feasible (yes or no on all held-out scenarios), aeration energy, effluent quality index, trials used. Headline: feasibility rate, then mean energy among feasible runs, with confidence intervals over at least five seeds or epochs.

Baselines with the same 40 trial budget: BSM1 default PI, a Ziegler-Nichols style tuning from a relay or step test (not implemented in v1), random search, differential evolution. Plus an oracle: differential evolution with a large budget, to give a regret measure.

## 8. Cost of running
Training trials are 14 day dry runs, about 20 s each: roughly 13 minutes of simulation per agent run for 40 trials. Held-out scoring is five scenarios, about 2 minutes. Several plant seeds and five epochs per model gives a few hours per model on one machine, so a first pass should use 3 plant seeds and 3 epochs. Local `qwen3:8b` is a plumbing test only.

## 9. Validation gates before any result is published
1. Reproduce BSM1 closed-loop reference outputs for the default controller from the archive within the documented tolerance, for the dry weather file.
2. Mass balance and non-negativity tests on the dynamic runs, same standard as the existing open-loop tests.
3. Determinism: identical seeds give identical trajectories.
4. Mock-model Inspect tests as now (scoring uses held-out only, budget enforced, no submission scores zero).
5. README states non-goals: no real plant calibration, fixed temperature, no claim about any facility.

## 10. UI
Add an Agent trials page next to Controller trials: replay each trial's trajectory in the 3D viewport (the process mode selector already exists), a table of trials with feasibility and energy, and a leaderboard of agents and baselines. The 3D scene stays illustrative; the credibility comes from sections 3 and 9.

## 11. Decisions needed from the user
1. Download the BSM1 archive: done on 2026-11-24 with your approval (section 13).
2. Primary energy metric: BSM1 aeration energy index (recommended) or the illustrative blower model.
3. Scope of the first release: stage 1 only (recommended), or include the ammonia cascade.
4. Feasibility rule: non-inferiority to the BSM1 default controller per limit (recommended, section 6) or a fixed percentage of time.
5. Which models to evaluate, and whether you will provide an API key (I will not search your files for one).

## 14. Deviations from this design (2026-11-25)
- Plant variants are three fixed, named plants (oxygen transfer and nitrifier activity scaled) that the tuner can see during training. They are not seeded unseen perturbations. The unseen part is the scenarios, not the plant.
- Held-out scenarios use the sensor noise file rotated by 3 days, so none reuses the training noise. The two dry weather scenarios still share the dry influent file with training.
- Confidence intervals: a 95% Wilson interval on the feasible share is reported. No interval is reported for energy, and the "at least five seeds" target was not met (three seeds for stochastic tuners).
- The oracle baseline (differential evolution with a large budget) was not implemented.
- Ziegler-Nichols uses the reaction curve rule from one step test, charged as 3 trials.
- Stage 2 (ammonia cascade) was implemented with an ideal ammonium sensor.
- The Agent trials page shows charts and tables, not a 3D replay.
- Integrity is cooperative: the Inspect task exposes only `run_trial` and `submit_gains`, but a Python tuner runs in the scorer's process and is trusted. Leaderboard entries from tuners you did not run yourself are self-reported.
- The standard start state, the solver modes and the model version are part of the results cache key, because the start state is a hidden input to every result.

## 13. Archive audit (2026-11-24)
Downloaded `BSM1_R2019b.zip` (14,054,207 bytes) from the IWA task group GitHub release. SHA256 matches the register: f0ed19ed214e562317c719f9d0ec93cdb45d4db3feea642c67101afc9f191f06. Extracted to `data/bsm1_extracted/` (gitignored; the register says to check the distribution terms, in `Documents/BSM1_agreement_LU.pdf`, before repackaging, which I have not done). No archive script was executed. I read `perf_plant.m`, `reginit.m`, `sensorinit.m`, the description PDF and the closed loop dynamic results.

Confirmed defaults for the reference controller:
- DO loop: setpoint 2 mg/L in reactor 5, PI with K = 25 per day per (g/m3), integral time 0.002 d (2.88 min), anti-windup time 0.001 d, kLa5 offset 144 per day, maximum kLa5 360 per day, actuator T90 4 minutes. The description text says 0 to 10 per hour; the 2019 release sets 360 per day. Use the code value and note the difference.
- DO sensor: class A, range 0 to 10, T90 1 minute, noise standard deviation 0.025 times range (0.25 g/m3), predefined noise file, sampled once a minute.
- Nitrate loop: setpoint 1 mg N/L in reactor 2, K = 10000, integral time 0.025 d, manipulating the internal recycle up to 5 times the influent flow; nitrate sensor class B0, T90 10 minutes.
- Published closed loop dry weather results (days 7 to 14) for the acceptance test in section 9: aeration energy 3,698 kWh/d (updated), EQI 6,123 (updated), average effluent ammonium 2.54 and total nitrogen 16.92 g/m3, total nitrogen limit exceeded 18.3% of the time, ammonium 17.1%.

Mapping to what the agent tunes: DO setpoint, K and integral time (the doc's earlier "Kp, Ki" become K and Ti), and the kLa5 upper limit. The derivative term does not exist in the benchmark controller, so `kd` is dropped.

## 12. Build order
1. Load the dynamic influent files from the extracted archive (done: archive downloaded and verified).
2. Closed-loop DO controller and indices; reproduce BSM1 reference closed-loop outputs.
3. Scenario and plant perturbation definitions, with tests.
4. Rebuild the Inspect task and baselines on the new plant, including Ziegler-Nichols.
5. Run baselines, then local model plumbing test, then real models.
6. Agent trials UI page.
7. README, results, limits.
Each step ends with passing tests and a commit before the next starts.
