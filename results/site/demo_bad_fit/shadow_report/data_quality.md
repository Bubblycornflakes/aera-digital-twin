# Data quality: historian.csv

2018 rows read, covering 20.99 days (2026-10-14 00:00 to 2026-11-03 22:45, Europe/London time), resampled to 15 minutes.

| Tag | Column | Usable data | Removed or ignored | Gaps filled |
| --- | --- | --- | --- | --- |
| influent_flow | Q_in | 100.0% | 1 | 1 |
| influent_nh4 | NH4_in | 100.0% | 2 | 2 |
| influent_cod | COD_in | 100.0% | 0 | 0 |
| effluent_nh4 | NH4_out | 97.6% | 0 | 0 |
| do_aerobic | DO_5 | 98.4% | 32 | 0 |
| blower_power | Blower_kW | 100.0% | 1 | 1 |
| temperature | Temp_C | 100.0% | 0 | 0 |

## Things to look at

- 2 duplicate timestamp(s): the first row was kept, the others were dropped
- effluent_nh4: longest gap after filling is 12.25 hours (ending 19 Oct 14:30 local time)
- do_aerobic: longest gap after filling is 8 hours (ending 22 Oct 07:45 local time)
- influent_flow: 1 value(s) outside the physical range removed
- influent_nh4: 1 non-numeric value(s) ignored
- influent_nh4: 1 value(s) outside the physical range removed
- do_aerobic: 32 value(s) in a stuck sensor run of 6 h or more removed
- blower_power: 1 non-numeric value(s) ignored
- 4 repeated local timestamp(s) were resolved as the autumn clock change (the hour that happens twice)

## Periods that can be replayed

- 2026-10-14 00:00 to 2026-11-03 22:45 (20.99 days, Europe/London time)