# Replay and nitrogen balance
Reproduced with engine 0.1.0, 24 h, 60 s PID sampling, RK45 rtol 1e-6 and atol 1e-8, D(0)=N(0)=2 mg/L as O₂ and N respectively. All runs used V=2000 m³, alpha=0.70, beta=0.93, target=2 mg O₂/L, Kp/Ki/Kd=0.12/0.8/0, noise=bias=0, seed=42.

|Storm|Return|Electricity (kWh)|Peak NH₄-N (mg/L)|
|---|---|---:|---:|
|Off|Off|1184.2233|6.9694|
|On|Off|1184.8488|6.9694|
|Off|On|1318.2528|22.7777|
|On|On|1303.7146|20.1958|

At 2 mg O₂/L the nitrification ceiling is 6×2/(0.5+2)=4.8 mg N/L/h. The six-hour sidestream delivers 74.25 kg N, equivalent to 6.1875 mg N/L/h gross addition to this basin. Mainstream inflow and mixed effluent export also enter the balance. Faster hydraulic export and dilution alter concentration under the storm. A DO-only controller cannot set biological capacity. The combined peak occurs at 15:00 with DO 2.004 mg/L. Rates and load allocation remain illustrative. Reproduce the combined case with python -m aera --storm --returns.
