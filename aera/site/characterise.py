"""Translate what a works measures (flow, ammonium, COD) into the 13 influent states of the ASM1 model.

This is the weakest link in any replay, so the assumptions are plain:
- COD is split into fractions in the same proportions as the BSM1 dry weather average, scaled to the measured COD.
  If no COD is measured it is assumed to scale with ammonium, in the BSM1 ratio.
- Ammonium is the measured value. Organic nitrogen scales with COD.
- Alkalinity is the BSM1 value (7 mol/m3).
- Oxygen, nitrate and active biomass in the influent are zero."""
import numpy as np
from .. import bsm1 as plant

COD_STATES = [0, 1, 2, 3, 4]      # SI, SS, XI, XS, XBH
BASE = plant.RAW
COD_REF = float(BASE[COD_STATES].sum())
NH4_REF = float(BASE[9])

def asm1_feed(nh4, cod=None):
    """nh4, cod: arrays in mg/l. Returns an (n, 13) array of influent concentrations."""
    nh4 = np.asarray(nh4, dtype=float)
    cod = nh4 / NH4_REF * COD_REF if cod is None else np.asarray(cod, dtype=float)
    feed = np.tile(BASE, (len(nh4), 1))
    f_cod = cod / COD_REF
    feed[:, COD_STATES] *= f_cod[:, None]
    feed[:, 9] = nh4
    feed[:, [10, 11]] *= f_cod[:, None]
    return feed

def total_cod(feed):
    return np.asarray(feed)[:, COD_STATES].sum(axis=1)
