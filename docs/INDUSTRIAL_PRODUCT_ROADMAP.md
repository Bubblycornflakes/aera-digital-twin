# Industrial product roadmap and audit
Audit baseline: commit 7253844. The browser runs recorded Python experiments through FastAPI. Keep this path available for teaching, UI regression and reproducible control exercises.

|Subsystem|Established evidence|Gap and disposition|
|---|---|---|
|Two-state mixed tank|Balances, solver tolerance, nitrogen disturbance arithmetic and repeatability tested|Fixed nitrification capacity cannot represent biomass retention, organic fractions or denitrification. Freeze educational model.|
|Annual reference accounts|Reproduces annual throughput, end-use allocations, Scope 2 and S1 costs|These are scenario calculations. Never use them as measured calibration targets.|
|Control and energy|Minute PID, saturation and integrated kWh tested|Illustrative nonlinear power and oxygen transfer. Retain comparison UI; replace constitutive laws for facility studies.|
|Scene|WebGL geometry and labels use simulation playback|Illustrative scale, one lane, no asset survey or measured graphics performance.|
|Data and reporting|CLI JSON includes timestamp, settings, solver and seed|No historian importer, site records, persistent experiments or permissions.|
|New ASM1 kernel|Conditional open-loop comparison at five outlets; fixed BSM1 parameters|Reference-parameterised. Settler, return/waste feedback, dynamic influents and full-plant ring test remain gates.|

1. Biology and reactor verification (this checkpoint). Research interface is Python; production UI continues using the educational model.
2. Implement settler solids flux, flow split, RAS, internal recycle and WAS. Close water and solids balances before matching whole-plant constant influent and dry/rain/storm reference results.
3. Introduce read-only measured-data ingestion, schema versions and asset configuration. Gate access to calibration on quality and fractionation reports.
4. Introduce equipment duty curves and aeration physics; verify standard/actual flow, pressure, transfer and metered power independently.
5. Fit identifiable parameters; issue independent validation reports, then compare feasible controllers offline.
6. Release versioned project storage, audit trail, permissions, reports and deployment tests.

Existing NumPy/SciPy, FastAPI/Pydantic, pytest, React/Three and ECharts suffice for this checkpoint. Future persistence needs database migrations, site-scoped identity and immutable data storage. Evaluate optimisation libraries only after constraints and solver budgets are defined.
