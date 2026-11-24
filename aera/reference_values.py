"""Published BSM1 closed loop dry weather results, days 7 to 14.

Source: BSM1_R2019b, Results/closedloop_dyn.pdf (U. Jeppsson, Lund University, Matlab/Simulink, 2009).
"""
PUBLISHED = dict(
    aeration_energy_kwh_d=3698.3438,    # updated BSM1 index
    eqi=6123.0182,                      # updated weights
    snh_avg=2.5392, total_n_avg=16.9245, tss_avg=13.0038, cod_avg=48.2201, bod5_avg=2.7568,
    over_total_n=0.183036, over_snh=0.171131,
    p95_snh=7.3902, p95_total_n=20.2693,
    qintr_steady=16485.6074,            # m3/d, closed loop steady state with constant influent
)

# Same source, rain and storm weather files (days 7 to 14).
PUBLISHED_WEATHER = dict(
    rain=dict(aeration_energy_kwh_d=3671.3519, eqi=8184.7262, snh_avg=3.226, total_n_avg=14.7465, tss_avg=16.1768,
              over_total_n=0.110119, over_snh=0.270833, over_tss=0.0, p95_snh=8.0395, p95_total_n=19.1429),
    storm=dict(aeration_energy_kwh_d=3720.9174, eqi=7220.724, snh_avg=3.0622, total_n_avg=15.8676, tss_avg=15.2737,
               over_total_n=0.15625, over_snh=0.269345, over_tss=0.0029762, p95_snh=7.8033, p95_total_n=20.1257),
)
