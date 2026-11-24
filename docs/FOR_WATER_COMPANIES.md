# For water companies: what you would get from a pilot

This page is for an asset manager, process scientist or innovation lead deciding whether a small trial is worth doing.

## The offer in one paragraph

Give us (or run yourself) a few weeks of one works' existing data. You get a report that says, in plain English, whether a model of your works can be trusted, and if it can, what a different dissolved oxygen setpoint would do to energy, carbon, effluent ammonium and your permit limits. It never connects to your plant. The first output is often "the model does not fit your works yet", which is a useful and honest result.

## What exists today, and what does not

| Built and tested on synthetic data | Not yet built or not yet proven |
| --- | --- |
| Data import with a quality report (UK clock changes, units, gaps, stuck sensors) | Any run on real works data |
| Replay of your influent through a scaled benchmark plant | Calibration beyond two multipliers (influent fractions, more kinetic parameters, confidence ranges) |
| A validation gate against your recorded effluent ammonium, blower energy and DO, and calibration of two multipliers with a held-out check | Plants other than the benchmark layout (trickling filters, SBR, chemical phosphorus removal, sludge digestion) |
| Temperature-aware replay (recorded or assumed temperature) |
| Permit-style limit checks (absolute, percentile, annual mean, look-up table) | Fitting the temperature coefficients to a works (typical literature values are used) |
| Energy, cost and carbon with tariff and carbon-factor ranges (not model error) | Live connections (OPC UA, SCADA): deliberately not built. A read-only watch folder runs shadow mode on each CSV export instead |
| Bounded, advisory recommendations and a tamper-evident audit log | A hidden test set and server-side scoring for the benchmark |

## A pilot in four to six weeks

| Week | What happens | Output |
| --- | --- | --- |
| 1 | You export 3 or more weeks of data for one works. We run the data check together. | Data quality report; agree what is missing |
| 2 | Shadow mode: validate the model against your records | Validation verdict. If not validated, we agree whether calibration or a different model is needed |
| 3 | Calibrate if needed, then setpoint sweep and permit checks on validated data | The trade-off between energy, carbon and each permit limit |
| 4 | Review with the operators and process scientists | A decision: stop, calibrate further, or design a controlled on-site trial |
| 5 to 6 (optional) | A staged, supervised trial of the smallest recommended step | Measured result, compared with the prediction |

**Success** for the pilot is not "energy saved". It is a clear answer to: *can a model of this works be made trustworthy, and is there a setpoint change worth trialling?*

## Data and security

- All processing is local. The analysis code makes no network connections, so your data never leaves the machine it runs on. (The only network-facing code is a read-only web page for the report in the web app, which you do not need to run.)
- They read a file you give them, or files that appear in a folder you name (the watch folder, which is read only: it never changes, moves or deletes anything in it). They do not connect to SCADA, historians or any plant system, and cannot write a setting.
- Your original data file is never modified. Every removed or ignored value is counted in the quality report.
- Every import, replay and approval is written to a hash-chained audit log. It shows whether an entry was edited or deleted from the middle; removal of the last entries is only detectable if you keep the printed head hash elsewhere. It does not prove who produced it.
- The data is a flow, ammonium, DO and power time series. No personal data is needed.

## Governance

- Recommendations carry one of three states: *ready for operator review* (model validated on both effluent ammonium and blower energy, every check passed, and every permit limit relied on was itself checked against a recording), *research only*, or *rejected* (a check failed, including a limit that already exceeds being made worse, or controller settings outside the tested ranges).
- Setpoint changes larger than your configured step are split into stages, each to be reviewed.
- A named person records approval. The record is a note, not an actuation, and the tool refuses to record an approval of a report that is not ready (unless an override reason is given and logged).

## Honest limits

- The benchmark plant is generic. Your works is not. The validation gate exists because of this, and its pass marks were chosen by the author, not by a standard; you set your own.
- Permit shapes are configured from your own permit. The tool does not interpret regulation for you.
- Annual figures are extrapolations from the data window.
- Earlier AeroBench results (the research benchmark in this project) found that retuning PI settings on the benchmark plant did not beat the default controller under a strict "no worse on any limit" rule. Do not expect large savings from setpoint changes alone; the value is in finding out, safely, what your works can do.

## Before you use it

- **Licence:** MIT (see LICENSE): you may use, copy and modify it, with no warranty. The IWA BSM1 benchmark files it downloads have their own terms and are not redistributed.
- **Status:** research software built by one person, not independently reviewed. Treat results as research until a pilot validates them on your data.
- **Funding and procurement routes** (for example innovation funds): not researched for 2026; check current programmes.
