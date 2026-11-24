"""The site configuration file (TOML). One file describes a works: its data, its current control, its consents and costs.

Errors are written for a process engineer, not a programmer: each says which setting is wrong and what is allowed."""
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TEMP_UNITS = {"degC": 1.0}
FLOW_UNITS = {"m3/d": 1.0, "m3/h": 24.0, "l/s": 86.4, "Ml/d": 1000.0}          # to m3/d
CONC_UNITS = {"mg/l": 1.0, "g/m3": 1.0, "ug/l": 0.001}                           # to mg/l
POWER_UNITS = {"kW": 1.0, "W": 0.001, "MW": 1000.0}                              # to kW

TAGS = {  # name: (unit table, required, description)
    "influent_flow": (FLOW_UNITS, True, "Flow entering the biological treatment"),
    "influent_nh4": (CONC_UNITS, True, "Ammonium nitrogen entering the biological treatment, as N"),
    "influent_cod": (CONC_UNITS, False, "Total COD entering the biological treatment"),
    "effluent_nh4": (CONC_UNITS, False, "Ammonium nitrogen in the final effluent, as N (needed to validate the model)"),
    "temperature": (TEMP_UNITS, False, "Mixed liquor temperature (the model follows it; without it, site.temperature_c is used)"),
    "effluent_tss": (CONC_UNITS, False, "Suspended solids in the final effluent"),
    "do_aerobic": (CONC_UNITS, False, "Dissolved oxygen in the last aerated zone"),
    "blower_power": (POWER_UNITS, False, "Electrical power of the aeration blowers (needed to calibrate energy)"),
}

class ConfigError(Exception):
    """A configuration problem, with a message that says what to change."""

class Tag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1, description="Column name in the data file")
    unit: str

class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "My works"
    design_flow_m3_d: float = Field(gt=100, lt=2_000_000, description="Average dry weather flow, m3/d")
    timezone: str = "Europe/London"
    temperature_c: float = Field(15.0, ge=0, le=40, description="Mixed liquor temperature to assume when no temperature is recorded, Celsius")

    @model_validator(mode="after")
    def _known_timezone(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"time zone '{self.timezone}' is not known; use a name such as Europe/London") from None
        return self

class Data(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str
    timestamp_column: str = "Timestamp"
    timestamp_format: str = ""                 # empty: day first dates and ISO dates are recognised
    timestamp_is_local: bool = True            # True: clock time in site.timezone, False: UTC or carries an offset
    max_fill_hours: float = Field(2.0, ge=0, le=24, description="Gaps up to this long are filled by interpolation; longer gaps stay empty. 0 turns filling off")
    flatline_hours: float = Field(6.0, ge=1, le=72, description="A value that does not change for this long is treated as a stuck sensor")
    flatline_exempt: list[str] = Field(default_factory=list, description="Tags where a constant value is normal, for example a lab ammonium result held until the next sample")
    tags: dict[str, Tag]

class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    do_setpoint: float = Field(2.0, ge=0.3, le=6, description="Current DO setpoint, mg/l")
    k_do: float = Field(25.0, gt=0, description="Current proportional gain, 1/d per mg/l (BSM1 default 25)")
    ti_do: float = Field(0.002, gt=0, description="Current integral time, days (BSM1 default 0.002)")

class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    so_ref_min: float = 1.0
    so_ref_max: float = 3.0
    max_setpoint_step: float = Field(0.5, gt=0, description="Largest change in DO setpoint recommended in one step, mg/l")

class ConsentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    tag: Literal["effluent_nh4", "effluent_tss"]
    kind: Literal["absolute", "percentile", "annual_mean", "lut"]
    limit: float = Field(gt=0, description="The numeric limit, mg/l")
    percentile: float = Field(95.0, gt=50, lt=100)
    upper_tier: float | None = Field(None, gt=0, description="A limit that no sample may exceed")
    lut: list[tuple[int, int]] = Field(default_factory=list, description="(samples taken, failures allowed) pairs")
    sample_every_days: int = Field(1, ge=1, le=60, description="Take one sample every N days (regulatory sampling is usually sparser than daily)")

    @model_validator(mode="after")
    def _lut_needs_table(self):
        if self.kind == "lut" and not self.lut:
            raise ValueError("a look-up table consent needs lut = [[samples, failures allowed], ...] copied from your permit")
        return self

class Band(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    gbp_per_kwh: float = Field(ge=0)

class Tariff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flat_gbp_per_kwh: float = Field(0.25, ge=0)          # placeholder; replace with your contract price
    bands: list[Band] = Field(default_factory=list)       # optional time-of-day prices (clock hours, local time); hours not in a band use the flat price
    uncertainty_pct: float = Field(15.0, ge=0, le=100)

    @model_validator(mode="after")
    def _bands_make_sense(self):
        taken = []
        for b in self.bands:
            if b.end_hour <= b.start_hour:
                raise ValueError(f"tariff band {b.start_hour} to {b.end_hour} ends before it starts; split an overnight band into two, for example 22 to 24 and 0 to 6")
            for a in taken:
                if b.start_hour < a.end_hour and a.start_hour < b.end_hour:
                    raise ValueError(f"tariff bands {a.start_hour}-{a.end_hour} and {b.start_hour}-{b.end_hour} overlap")
            taken.append(b)
        return self

class Carbon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kg_co2e_per_kwh: float = Field(0.13096, ge=0)        # placeholder; replace with the current UK government factor
    uncertainty_pct: float = Field(15.0, ge=0, le=100)

class Validation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nse_min: float = Field(0.5, description="Smallest acceptable Nash-Sutcliffe efficiency")
    bias_max_pct: float = Field(20.0, gt=0, description="Largest acceptable mean bias, per cent")
    min_days: float = Field(7.0, gt=0, description="Shortest data window that can be replayed, days")
    do_mae_max: float = Field(0.3, gt=0, description="Largest acceptable mean absolute error of daily DO, mg/l. DO is held near its setpoint, so it is checked by level, not by Nash-Sutcliffe")
    min_days_compared: int = Field(7, ge=3, description="Fewest daily values an indicator needs before it can count")
    nh4_abs_bias_mg_l: float = Field(0.3, gt=0, description="Effluent ammonium bias this small (mg/l) passes even if it is a large per cent of a very low value")
    nh4_min_std: float = Field(0.15, gt=0, description="If recorded daily effluent ammonium varies less than this (mg/l, standard deviation) it cannot test the model")
    energy_factor_min: float = Field(0.5, gt=0, description="Smallest believable ratio of recorded blower energy to modelled aeration energy")
    energy_factor_max: float = Field(2.0, gt=0, description="Largest believable ratio of recorded blower energy to modelled aeration energy")

class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    train_fraction: float = Field(0.6, gt=0.3, lt=0.85, description="Share of the replayed days used to fit; the rest are held out to check the fit")
    min_improvement: float = Field(0.10, ge=0, lt=1, description="The fit is only used if it cuts the error on the held-out days by at least this share")
    flat_threshold: float = Field(0.02, gt=0, description="A parameter whose change barely moves the error cannot be identified from your data and is left at the benchmark value")

class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: Site
    data: Data
    control: Control = Control()
    guardrails: Guardrails = Guardrails()
    consent: list[ConsentSpec] = Field(default_factory=list)
    tariff: Tariff = Tariff()
    carbon: Carbon = Carbon()
    validation: Validation = Validation()
    calibration: Calibration = Calibration()

    @model_validator(mode="after")
    def _check_tags(self):
        problems = []
        for name, (units, required, _) in TAGS.items():
            tag = self.data.tags.get(name)
            if tag is None:
                if required:
                    problems.append(f"[data.tags.{name}] is required: {TAGS[name][2]}")
            elif tag.unit not in units:
                problems.append(f"[data.tags.{name}] unit '{tag.unit}' is not supported; use one of {', '.join(units)}")
        for name in self.data.flatline_exempt:
            if name not in TAGS:
                problems.append(f"flatline_exempt names '{name}', which is not a tag; allowed: {', '.join(TAGS)}")
        unknown = set(self.data.tags) - set(TAGS)
        if unknown:
            problems.append(f"unknown tag(s) {sorted(unknown)}; allowed: {', '.join(TAGS)}")
        for c in self.consent:
            if c.tag not in self.data.tags:
                problems.append(f"consent '{c.name}' uses {c.tag}, which is not listed under [data.tags]")
        if problems:
            raise ValueError("; ".join(problems))
        return self

def unit_factor(tag, unit):
    return TAGS[tag][0][unit]

def load(path):
    """Read and validate a site.toml. Raises ConfigError with a readable message."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"Cannot find {path}. Create one with: python -m aera.site init <folder>") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path.name} is not valid TOML: {error}") from None
    try:
        return SiteConfig.model_validate(raw)
    except ValidationError as error:
        lines = []
        for e in error.errors():
            where = ".".join(str(p) for p in e["loc"]) or "(file)"
            lines.append(f"  {where}: {e['msg']}")
        raise ConfigError(f"{path.name} has {len(lines)} problem(s):\n" + "\n".join(lines)) from None
