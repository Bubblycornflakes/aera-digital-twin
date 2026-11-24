"""A fast stand-in for the BSM1 simulation so benchmark logic can be tested in milliseconds."""
from aera import benchmark as bench

def fake_evaluate(params, scenario, mode="fast", use_cache=True):
    p = bench.clip_params(params)
    energy = 3700 + 600 * (p["so_ref"] - 2) - 0.8 * (360 - p["kla_max"]) + 2.0 * abs(p["k_do"] - 25)
    stress = 1.0 + 0.5 * (scenario.noise_scale > 1) + 0.3 * abs(scenario.do_bias) + 0.4 * (scenario.return_liquor_kg > 0)
    lack = max(0.0, 2.0 - p["so_ref"])
    share = dict(total_n=min(1, 0.18 * stress + 0.3 * lack), total_cod=0.0, snh=min(1, 0.17 * stress + 0.3 * lack),
                 tss=0.0, bod5=0.0)
    return dict(aeration_energy_kwh_d=energy, eqi=6100.0 + 200 * lack, share_over_limit=share,
                low_do_share=max(0.0, 1.0 - p["so_ref"]) * 0.2, average={}, p95={}, seconds=0.0,
                trajectory=dict(day=[7 + i / 12 for i in range(84)], so5=[p["so_ref"]] * 84, kla5=[130.0] * 84,
                                snh5=[1.0] * 84))
