# Scientific reference register
* Henze M., Grady C.P.L. Jr, Gujer W., Marais G.v.R., Matsuo T. (1987), Activated Sludge Model No. 1, Scientific and Technical Report 1. Original attribution verified in Alex et al. §9; original monograph pages unavailable in this audit. Implemented edition is the documented BSM1 selection below.
* Alex J., Benedetti L., Copp J., Gernaey K.V., Jeppsson U., Nopens I., Pons M.N., Steyer J.P., Vanrolleghem P. (©2008), Benchmark Simulation Model no. 1, file Description_BSM1_20090101.pdf. Read §§2.2–2.4 (pp.4–11); §3 and §4 specify benchmark initialization and open-loop assessment. State definitions §2.2.1, eight process rates §2.2.2, conversions §2.2.3, fixed parameters §2.2.4, tank hydraulics §2.3.2. Approximately 15°C.
* Jeppsson U., Lund University (21 May 2009), Steady State Results for Openloop, Results/openloop_ss.pdf, “Input to AS” and “Reactor 1” through “Reactor 5”. Independent MATLAB/Simulink reference measurements **of a simulation**. Fixture transcribes those 78 numbers in native units.
* IWA task group [BSM1 release](https://github.com/wwtmodels/Benchmark-Simulation-Models/releases/tag/BSM1_vR2019b), archive BSM1_R2019b.zip SHA256 f0ed19ed214e562317c719f9d0ec93cdb45d4db3feea642c67101afc9f191f06. Read asm1.c and openloop/olasm1init.m for conventions and settings. Data include constant influent and 1,344 records each for dry, rain and storm influent, plus reference open/closed-loop outputs and ring-test workbook. Check distribution terms before repackaging. Only the numerical verification fixture is included.
* Author's reference assumptions: annual energy and return-load accounting for a typical UK works of 150,000 population equivalent. Its parameters apply to the educational scenario.
* ASM2d, ASM3 and WEF MOP 8: separate future references. No pages, coefficients or design values from those texts used here. No manufacturer data or operational measurements supplied.

|BSM1 quantity (§2.2.4 unless indicated)|Value|Unit|
|---|---|---|
|Aerobic max growth μH, μA; decay bH, bA|4, 0.5; 0.3, 0.05|1/day|
|KS; KOH, KOA|10; 0.2, 0.4|g COD/m³; g O₂/m³|
|KNO, KNH|0.5, 1|g N/m³|
|ηg, ηh|0.8, 0.8|dimensionless|
|ka|0.05|m³/(g biomass COD·day)|
|kh; KX|3; 0.1|g substrate COD/(g biomass COD·day); g/g|
|YH, YA|0.67, 0.24|g biomass COD/g substrate COD; g biomass COD/g N|
|fP; iXB, iXP|0.08; 0.08, 0.06|COD fraction; g N/g COD|
|N conversion factors (§2.2.3)|4.57; 2.86; 14|g O₂/g N oxidation; g COD-equivalent/g N reduction; g N/mol|
|Q; V; kLa; SOsat (open-loop init and results)|92230; 1000,1000,1333,1333,1333; 0,0,240,240,84; 8|m³/day; m³; /day; g O₂/m³|
