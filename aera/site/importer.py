"""Read a works' historian export (CSV) into a clean 15 minute table, and say exactly what was wrong with it.

Rules: raw data is never edited on disk; nothing is deleted silently (every removed value is counted and reported); clock
changes (BST) are handled; values are converted to the units the model uses (m3/d, mg/l, kW)."""
import re
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd
from . import config as cfg

STEP = pd.Timedelta("15min")
RANGES = {  # physical limits after unit conversion: (lowest, highest); values outside are treated as faulty
    "influent_nh4": (0.0, 500.0), "influent_cod": (0.0, 5000.0), "effluent_nh4": (0.0, 500.0), "effluent_tss": (0.0, 2000.0),
    "do_aerobic": (-0.2, 20.0), "blower_power": (0.0, 10_000.0), "temperature": (0.0, 45.0),
}

@dataclass
class SiteData:
    table: pd.DataFrame                  # 15 minute UTC index, one column per tag (model units)
    report: dict
    windows: list = field(default_factory=list)   # usable (start, end) periods of required data

NEVER_STUCK = {"temperature"}      # a slowly changing probe can legitimately repeat a value for hours
ISO = re.compile(r"^\s*\d{4}-\d{2}-\d{2}")
THOUSANDS = re.compile(r"^\s*-?\d{1,3}(,\d{3})+(\.\d+)?\s*$")

def _parse_time(series, conf, issues):
    """UK files are day first (31/10/2026). ISO files (2026-10-31) are year first and must not be read day first."""
    fmt = conf.data.timestamp_format or None
    first = next((x for x in series if isinstance(x, str) and x.strip()), "")
    kwargs = dict(format=fmt) if fmt else (dict(format="ISO8601") if ISO.match(first) else dict(dayfirst=True))
    if conf.data.timestamp_is_local:
        parsed = pd.to_datetime(series, errors="coerce", **kwargs)
        if getattr(parsed.dt, "tz", None) is not None:
            raise cfg.ConfigError("The timestamps carry a time zone offset (for example +01:00), but timestamp_is_local is true. Set timestamp_is_local = false.")
    else:
        parsed = pd.to_datetime(series, errors="coerce", utc=True, **kwargs)
    bad = int(parsed.isna().sum())
    if bad:
        issues.append(f"{bad} timestamp(s) could not be read and were dropped")
    return parsed

def _localise(index, conf, issues):
    """Turn site clock time into UTC. The autumn clock change repeats an hour, the spring one skips an hour."""
    tz = conf.site.timezone
    try:
        return index.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward").tz_convert("UTC"), "inferred"
    except Exception:                                   # the repeated hour could not be inferred (rows not in time order, or an hour is incomplete)
        local = index.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        lost = int(local.isna().sum())
        issues.append(f"{lost} timestamp(s) fall in the repeated autumn clock hour and could not be told apart (rows out of time order or the hour is incomplete), so they were dropped")
        return local.tz_convert("UTC"), "dropped"

def _fill_short_gaps(series, limit):
    """Interpolate a gap only if the whole gap is at most `limit` steps. A longer gap stays empty (no partial fills)."""
    if limit <= 0:
        return series
    missing = series.isna()
    run = (missing != missing.shift()).cumsum()
    length = missing.groupby(run).transform("size")
    return series.where(~(missing & (length <= limit)), series.interpolate(limit_area="inside"))

def load(config, config_dir=None):
    """Import the file named in the configuration. Returns SiteData."""
    config_dir = Path(config_dir or ".")
    path = Path(config.data.file)
    path = path if path.is_absolute() else config_dir / path
    try:
        raw = pd.read_csv(path, dtype=str, skipinitialspace=True, keep_default_na=False, na_values=[""])   # "N/A" stays text so it is reported
    except FileNotFoundError:
        raise cfg.ConfigError(f"Data file not found: {path}. Check [data] file in the configuration.") from None
    except Exception as error:
        raise cfg.ConfigError(f"Could not read {path.name} as CSV: {error}") from None
    raw.columns = [c.strip() for c in raw.columns]
    report = dict(file=path.name, rows_read=len(raw), tags={}, issues=[], notes=[])
    issues = report["issues"]
    if config.data.timestamp_column not in raw.columns:
        raise cfg.ConfigError(f"Timestamp column '{config.data.timestamp_column}' is not in the file. Columns found: {', '.join(raw.columns)}")
    missing = [t.column for t in config.data.tags.values() if t.column not in raw.columns]
    if missing:
        raise cfg.ConfigError(f"Column(s) {missing} named in [data.tags] are not in the file. Columns found: {', '.join(raw.columns)}")

    times = _parse_time(raw[config.data.timestamp_column], config, issues)
    keep = times.notna()
    raw, times = raw[keep].reset_index(drop=True), pd.DatetimeIndex(times[keep])
    if config.data.timestamp_is_local:
        local_repeats = int(pd.Series(raw[config.data.timestamp_column]).duplicated().sum())
        times, how = _localise(times, config, issues)
        if how == "inferred":
            true_dups = int(pd.DatetimeIndex(times).duplicated().sum())
            repeated = max(local_repeats - true_dups, 0)
            if repeated:
                report["notes"].append(f"{repeated} repeated local timestamp(s) were resolved as the autumn clock change (the hour that happens twice)")
        ok = times.notna()
        raw, times = raw[ok].reset_index(drop=True), times[ok]
    frame = pd.DataFrame(index=times)
    for name, tag in config.data.tags.items():
        cleaned = raw[tag.column].map(lambda x: x.replace(",", "") if isinstance(x, str) and THOUSANDS.match(x) else x)    # "1,250" is a thousand; "1,5" is left to be reported
        values = pd.to_numeric(cleaned, errors="coerce").to_numpy() * cfg.unit_factor(name, tag.unit)
        text_missing = int((raw[tag.column].str.strip().replace("", np.nan).notna() & np.isnan(values)).sum())
        frame[name] = values
        report["tags"][name] = dict(column=tag.column, unit_in=tag.unit, not_numeric=text_missing, out_of_range=0, flatline=0, filled=0)
    frame = frame.sort_index(kind="stable")

    dup = frame.index.duplicated(keep="first")
    if dup.any():
        issues.append(f"{int(dup.sum())} duplicate timestamp(s): the first row was kept, the others were dropped")
        frame = frame[~dup]
    if frame.empty:
        raise cfg.ConfigError("No rows with a readable timestamp were found.")

    gaps = pd.Series(frame.index).diff().dropna().dt.total_seconds() / 60
    cadence = float(gaps.median()) if len(gaps) else 15.0
    report["cadence_minutes"] = round(cadence, 2)
    if cadence > 15:
        report["notes"].append(f"The file has one row every {cadence:g} minutes; values between rows are interpolated to the model's 15 minute step")
    flat_n = max(int(round(config.data.flatline_hours * 60 / cadence)), 3)       # rows in a run, from the file's own time step
    for name in frame.columns:
        col, info = frame[name], report["tags"][name]
        if name in RANGES:
            lo, hi = RANGES[name]
            bad = (col < lo) | (col > hi)
        else:                                            # flow: negative or beyond 20x the design flow
            bad = (col < 0) | (col > 20 * config.site.design_flow_m3_d)
        info["out_of_range"] = int(bad.sum())
        frame.loc[bad, name] = np.nan
        runs = (frame[name].ne(frame[name].shift()) | frame[name].isna()).cumsum()
        size = frame[name].groupby(runs).transform("size")
        stuck = (size >= flat_n) & frame[name].notna() & (frame[name].abs() > 0) & (name not in config.data.flatline_exempt) & (name not in NEVER_STUCK)
        info["flatline"] = int(stuck.sum())
        frame.loc[stuck, name] = np.nan

    table = frame.resample(STEP).mean()
    limit = int(round(config.data.max_fill_hours * 4))
    for name in table.columns:
        before = table[name].isna()
        table[name] = _fill_short_gaps(table[name], limit)
        report["tags"][name]["filled"] = int((before & table[name].notna()).sum())
        valid = table[name].notna()
        report["tags"][name]["coverage_pct"] = round(100 * float(valid.mean()), 1)
        gap = (~valid).astype(int).groupby(valid.cumsum()).cumsum()
        longest = float(gap.max()) / 4
        report["tags"][name]["longest_gap_hours"] = round(longest, 2)
        if longest > 6:
            when = table.index[int(gap.to_numpy().argmax())].tz_convert(config.site.timezone).strftime("%d %b %H:%M")
            issues.append(f"{name}: longest gap after filling is {longest:g} hours (ending {when} local time)")
        report["tags"][name]["median"] = round(float(table[name].median()), 3) if valid.any() else None
    tz = config.site.timezone
    local = lambda ts: pd.Timestamp(ts).tz_convert(tz).strftime("%Y-%m-%d %H:%M")
    report.update(timezone=tz, start=local(table.index[0]), end=local(table.index[-1]),
                  days=round((table.index[-1] - table.index[0]).total_seconds() / 86400, 2), step_minutes=15, rows_after_resampling=len(table))

    flow = table["influent_flow"].median()
    ratio = flow / config.site.design_flow_m3_d if flow == flow else float("nan")
    report["flow_to_design_ratio"] = None if ratio != ratio else round(float(ratio), 2)
    if ratio == ratio and not 0.3 <= ratio <= 3.0:
        issues.append(f"Median influent flow is {ratio:.1f} times the design flow. Check the flow unit and design_flow_m3_d; a unit mistake here would invalidate everything downstream")
    for name, info in report["tags"].items():
        for key, text in (("not_numeric", "non-numeric value(s) ignored"), ("out_of_range", "value(s) outside the physical range removed"),
                          ("flatline", f"value(s) in a stuck sensor run of {config.data.flatline_hours:g} h or more removed")):
            if info[key]:
                issues.append(f"{name}: {info[key]} {text}")
    for name, info in report["tags"].items():
        if info["coverage_pct"] < 80:
            issues.append(f"{name}: only {info['coverage_pct']}% of the period has usable data")

    required = [n for n, (_, req, _) in cfg.TAGS.items() if req]
    ok = table[required].notna().all(axis=1)
    windows, start = [], None
    for ts, good in ok.items():
        if good and start is None:
            start = ts
        if not good and start is not None:
            windows.append((start, ts - STEP))
            start = None
    if start is not None:
        windows.append((start, table.index[-1]))
    usable = [(a, b) for a, b in windows if (b - a).total_seconds() / 86400 >= config.validation.min_days]
    report["windows"] = [dict(start=local(a), end=local(b), days=round((b - a).total_seconds() / 86400, 2)) for a, b in usable]
    if not usable:
        issues.append(f"No continuous period of at least {config.validation.min_days:g} days has both influent flow and ammonium, so nothing can be replayed")
    return SiteData(table=table, report=report, windows=usable)

def quality_markdown(report):
    """A plain-language summary of the data quality report."""
    out = [f"# Data quality: {report['file']}", "",
           f"{report['rows_read']} rows read, covering {report['days']} days ({report['start']} to {report['end']}, {report['timezone']} time), resampled to 15 minutes.", ""]
    out += ["| Tag | Column | Usable data | Removed or ignored | Gaps filled |", "| --- | --- | --- | --- | --- |"]
    for name, i in report["tags"].items():
        removed = i["not_numeric"] + i["out_of_range"] + i["flatline"]
        out.append(f"| {name} | {i['column']} | {i['coverage_pct']}% | {removed} | {i['filled']} |")
    out += ["", "## Things to look at", ""]
    out += [f"- {t}" for t in report["issues"] + report["notes"]] or ["- Nothing unusual found."]
    out += ["", "## Periods that can be replayed", ""]
    out += [f"- {w['start']} to {w['end']} ({w['days']} days, {report['timezone']} time)" for w in report["windows"]] or ["- None."]
    return "\n".join(out)
