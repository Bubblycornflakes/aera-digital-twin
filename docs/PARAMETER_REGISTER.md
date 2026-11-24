# Parameter register · 0.1
Reference inputs below are fixed for reproduction. Source is the author's own reference assumptions for a typical UK works of 150,000 population equivalent. Ranges in brackets indicate sensitivity assumptions, not confidence intervals.

|Quantity / symbol|Reference and unit|Evidence and purpose|
|---|---|---|
|Population P|150,000 PE|§4.1 representative works|
|Specific flow q; intensity I|0.225 m³/PE/d; 0.64 kWh/m³|§4.1 T2, derive flow and electricity|
|Price p; grid g|£0.25/kWh; 0.13096 kgCO₂e/kWh|§4.1 T2, 2026 reference cost and location-based Scope 2|
|Aeration and pump shares|0.55 [0.45–0.65]; 0.12|§§4.1, 5, allocate site use|
|Aeration and pump savings|0.20; 0.15|§4.5 assumed demand reduction|
|Nitrogen load; returned fraction|0.011 kg N/PE/d; 0.18 [0.15–0.25]|§4.8 return-liquor mass balance|
|Oxygen stoichiometry; marginal electricity|4.57 kg O₂/kg N; 2.03 kWh/kg N|§4.8 nitrification and annual central case|

Dynamic inputs below are illustrative engineering choices unless a source is cited. A single value in the fixed column indicates a model constant. Bounds are the implemented API limits.

|Symbol / purpose|Default and unit|Configurable range or fixed convention|
|---|---|---|
|V / mixed volume|2000 m³|500–8000 m³|
|Q / basin flow|351.5625 m³/h mean|fixed 1/4 flow allocation; nominal residence 5.69 h|
|Din; Nin / inlet|0.5 mg O₂/L; 22 mg N/L mean|fixed|
|D0; N0 / initial|2 mg O₂/L; 2 mg N/L|fixed|
|rmax / maximum oxidation|6 mg N/L/h|fixed; lumped biomass|
|KN; KO; KH / half saturation|1 mg N/L; 0.5 and 0.25 mg O₂/L|fixed|
|H / organic demand|9 mg O₂/L/h|fixed before load and DO adjustment|
|kLa_max; Csat|12/h clean water; 9.1 mg O₂/L|fixed reference temperature|
|alpha; beta|0.70; 0.93|0.4–0.9; 0.90–0.95 (§2.2 ranges; defaults illustrative)|
|P(u) / blower|12+118 u^1.4 kW when running|fixed; off draws zero|
|Kp; Ki; Kd|0.12; 0.8; 0|0–2, 0–5, 0–0.1; fractional command per mg/L, per mg/L·h integral, and per (mg/L)/h derivative respectively|
|Target; controller bias|2 mg O₂/L; 0.4 fraction|target 0.5–5; bias fixed|
|Noise SD; sensor bias|0; 0 mg O₂/L|0–0.5; −1 to +1|
|Seed; horizon; interval|42; 24 h; 60 s|nonnegative integer; 1–72 h; fixed|
|Storm; liquor|off; off|switch independently; see engineering model for timings, strengths and mixing rules|
