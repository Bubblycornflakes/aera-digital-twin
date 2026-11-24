# Roadmap: what is built, what is next, what is deliberately not built

## Built
- Site data import with a quality report, UK clock-change handling, unit conversion and gap and stuck-sensor handling.
- Shadow mode replay on a scaled benchmark plant, with a validation gate, energy calibration, permit-style limit checks, energy, cost and carbon appraisal with ranges, a setpoint sweep, bounded advisory recommendations and a hash-chained audit log.
- A synthetic works to try it on, and a Site shadow page in the web app.
- Temperature: the model follows a recorded mixed liquor temperature (or an assumed constant) using typical literature coefficients, exact at the benchmark's 15 degrees. On a synthetic works that cools from 17.8 to 10.8 degrees it validates (ammonium NSE 0.99), where assuming 15 degrees does not (NSE -0.31). The coefficients are not calibrated to any works.
- A read-only watch folder (`python -m aera.site watch`): runs shadow mode on each new CSV export, once per distinct file, never touching the inbox.
- Calibration of nitrifier activity and oxygen transfer, with a held-out check, an identifiability test and refusal when the fit does not generalise (recovered the planted values on a synthetic works; never tried on real data).
- The AeroBench research benchmark (docs/AEROBENCH.md), with a private held-out set mechanism (commit-reveal).

## Next, in order of value
1. **Run it on one real works' data.** Nothing else matters as much. Expect the first result to be "not validated" and use it to learn what the model is missing.
2. **More calibration**: calibration of two multipliers (nitrifier activity, oxygen transfer) is built. Next: influent fractions, more kinetic parameters, and parameter uncertainty (confidence ranges) rather than a single best fit.
3. **Plant library**: a small set of typical UK layouts beyond the benchmark (trickling filter plus nitrifying stage, SBR, chemical phosphorus removal, digester return liquor).
4. **Better consents**: wording checked against real permits, sample-frequency handling for percentile and look-up table conditions, phosphorus.
5. **Benchmark credibility**: server-side scoring (the private held-out set with commit-reveal is built; no private leaderboard has been published yet).

## Deliberately not built
- **Live connections to SCADA or historians (OPC UA, MQTT).** A live link is where safety and cyber risk begins. Shadow mode works from exported files by design, and the watch folder gives scheduled, automatic runs without any plant connection. If a live link is ever added it should be read-only and reviewed by the operator's OT security team.
- **Any write path to a plant.** The tool is advisory only.

## Not verified
- UK regulatory details and funding programmes: not researched for 2026.
- The Docker image and the GitHub Pages workflow have never been run.
