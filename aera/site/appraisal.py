"""Energy, cost and carbon of a replay, with stated uncertainty. UK units: pounds and kg CO2e per kWh.

The defaults for price and carbon factor are placeholders and must be replaced with your contract price and the
current UK government conversion factor for the reporting year. Annual figures are an extrapolation of the window and are only
meaningful if the window is representative of the year (weather, season, load)."""
import numpy as np
import pandas as pd

def price_series(index, tariff, tz):
    """Pounds per kWh for each timestamp: time-of-day bands (local clock) where given, otherwise the flat price."""
    price = np.full(len(index), tariff.flat_gbp_per_kwh, dtype=float)
    if tariff.bands:
        hours = index.tz_convert(tz).hour
        for band in tariff.bands:
            price[(hours >= band.start_hour) & (hours < band.end_hour)] = band.gbp_per_kwh
    return price

def appraise(table, factor, config):
    """table: replay output (aeration_kwh_d on the replay index). factor: model-to-blower calibration (None if uncalibrated)."""
    k = 1.0 if factor is None else factor
    kwh = table["aeration_kwh_d"].to_numpy() * k / 96.0                              # kWh per 15 minute record
    days = len(table) / 96.0
    cost = float((kwh * price_series(table.index, config.tariff, config.site.timezone)).sum())
    carbon = float(kwh.sum() * config.carbon.kg_co2e_per_kwh / 1000.0)               # tonnes CO2e
    per_year = 365.0 / days
    t, c = config.tariff.uncertainty_pct / 100, config.carbon.uncertainty_pct / 100
    return dict(days=round(days, 1), calibrated=factor is not None, energy_kwh=round(float(kwh.sum()), 1),
                energy_kwh_per_day=round(float(kwh.sum() / days), 1), cost_gbp=round(cost, 2),
                cost_gbp_range=[round(cost * (1 - t), 2), round(cost * (1 + t), 2)], carbon_t=round(carbon, 3),
                carbon_t_range=[round(carbon * (1 - c), 3), round(carbon * (1 + c), 3)],
                annualised=dict(energy_kwh=round(float(kwh.sum() * per_year)), cost_gbp=round(cost * per_year),
                                carbon_t=round(carbon * per_year, 1), note="Extrapolated from the window; valid only if the window is typical of the year."))

def compare(base, cand):
    """Candidate minus baseline, as numbers and per cent. Negative means the candidate uses less."""
    def pct(a, b):
        return round(100 * (b - a) / a, 2) if a else None
    return dict(energy_kwh=round(cand["energy_kwh"] - base["energy_kwh"], 1), energy_pct=pct(base["energy_kwh"], cand["energy_kwh"]),
                cost_gbp=round(cand["cost_gbp"] - base["cost_gbp"], 2), carbon_t=round(cand["carbon_t"] - base["carbon_t"], 3))
