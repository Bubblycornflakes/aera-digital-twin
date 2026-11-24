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
