"""AeroBench for Inspect AI: can an LLM tune the BSM1 reactor 5 DO controller from simulation trials?

Run:  inspect eval aerobench_task.py --model <provider/model>
The agent sees one training scenario (dry weather) and a trial budget. Its submission is scored on held-out
scenarios: rain, storm, a return liquor ammonia pulse and DO sensor faults, on three plant variants.
"""
import asyncio
import json
from inspect_ai import Task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState, generate, solver, system_message, use_tools
from inspect_ai.tool import tool
from inspect_ai.util import store
from . import benchmark as bench

TRIAL_BUDGET = 40

def _describe():
    lines = [f"  {k}: from {lo} to {hi}, BSM1 default {bench.DEFAULT[k]}" for k, (lo, hi) in bench.BOUNDS.items()]
    return "\n".join(lines)

# No curly braces here: Inspect treats them as template fields in a system message.
PROMPT = f"""You tune the dissolved oxygen (DO) controller of the BSM1 activated sludge benchmark plant.
The controller is a PI loop on the last aerated reactor that sets its oxygen transfer coefficient.
Parameters you choose, with allowed ranges:
{_describe()}
so_ref is the DO setpoint in g/m3, k_do the proportional gain, ti_do the integral time in days, kla_max the actuator limit in 1/d.
Goal: minimise aeration energy (kWh/d) while staying feasible. Feasible means that for each effluent limit
(total nitrogen, total COD, ammonium, suspended solids, BOD5) the share of time over the limit is no worse than
the BSM1 default controller's share on the same scenario plus {bench.TOLERANCE * 100:g} percentage points, and true DO
is below 0.5 g/m3 for at most 1% of the time. Feasibility comes before energy.
Use run_trial to test settings on the training scenario (dry weather). You have {TRIAL_BUDGET} trials. Each trial
returns aeration energy, effluent quality, limit exceedance, feasibility and a coarse trajectory.
Your submission is scored on different, unseen scenarios (other weather, an ammonia pulse from sludge liquor,
noisy or biased sensors) on plants that differ in oxygen transfer and nitrifier activity. Prefer robust settings.
Always act by calling a tool. Call submit_gains exactly once when done."""

NUDGE = "Continue. Call run_trial to test settings, or submit_gains to finish."

def plant_for(state):
    return bench.PLANTS[state.metadata["plant"]]

_LOCKS = {}

def environment(plant):
    """An Environment over this sample's stored trial history (so the budget persists between tool calls)."""
    return bench.Environment(plant, TRIAL_BUDGET, history=list(store().get("history", [])))

def sample_lock():
    """One lock per sample: a model may emit several run_trial calls in a single message."""
    return _LOCKS.setdefault(id(store()), asyncio.Lock())

def brief(trial):
    t = trial["trajectory"]
    keep = slice(None, None, 3)                    # every 6 h
    return dict(params=trial["params"], aeration_energy_kwh_d=trial["aeration_energy_kwh_d"], eqi=trial["eqi"],
                share_over_limit=trial["share_over_limit"], low_do_share=trial["low_do_share"],
                feasible=trial["feasible"], failures=trial["failures"], default=trial["reference"],
                trajectory=dict(day=t["day"][keep], so5=t["so5"][keep], kla5=t["kla5"][keep], snh5=t["snh5"][keep]),
                trials_left=trial["trials_left"])

@tool
def run_trial():
    async def execute(so_ref: float, k_do: float, ti_do: float, kla_max: float) -> str:
        """Test controller settings on the training scenario (dry weather).

        Args:
            so_ref: DO setpoint, g/m3, 0.5 to 5.
            k_do: proportional gain, 1/d per g/m3, 1 to 500.
            ti_do: integral time, days, 0.0005 to 0.02.
            kla_max: actuator upper limit, 1/d, 120 to 360.
        """
        async with sample_lock():
            env = environment(bench.PLANTS[store().get("plant")])
            try:
                trial = await asyncio.to_thread(env.trial, dict(so_ref=so_ref, k_do=k_do, ti_do=ti_do, kla_max=kla_max))
            except bench.BudgetExceeded:
                return "Trial budget exhausted. Call submit_gains now."
            except ValueError as error:
                return f"Invalid parameters, no trial used: {error}"
            store().set("history", env.history_list())
        return json.dumps(brief(trial))
    return execute

@tool
def submit_gains():
    async def execute(so_ref: float, k_do: float, ti_do: float, kla_max: float) -> str:
        """Submit final controller settings. Call once.

        Args:
            so_ref: DO setpoint, g/m3.
            k_do: proportional gain, 1/d per g/m3.
            ti_do: integral time, days.
            kla_max: actuator upper limit, 1/d.
        """
        params = dict(so_ref=so_ref, k_do=k_do, ti_do=ti_do, kla_max=kla_max)
        try:
            bench.clip_params(params)
        except ValueError as error:
            return f"Invalid parameters, not submitted: {error}"
        store().set("submission", params)
        return "Submitted."
    return execute

@solver
def agent_loop(max_nudges=15):
    """generate() ends when the model replies without a tool call. Small models often do this after thinking, so
    re-prompt up to max_nudges times until a submission exists. The number of nudges is recorded in the store."""
    async def solve(state: TaskState, generate):
        nudges = 0
        while True:
            state = await generate(state)
            if store().get("submission") is not None or state.completed or nudges >= max_nudges:
                break
            nudges += 1
            state.messages.append(ChatMessageUser(content=NUDGE))
        store().set("nudges", nudges)
        return state
    return solve

@solver
def bind_plant():
    async def solve(state: TaskState, generate):
        store().set("plant", state.metadata["plant"])
        store().set("history", [])
        return state
    return solve

@scorer(metrics={"submitted": [mean()], "feasible": [mean()], "energy_kwh_day": [mean()], "saving_pct": [mean()],
                 "trials_used": [mean()], "nudges": [mean()]})
def held_out():
    async def run(state: TaskState, target: Target) -> Score:
        sub = store().get("submission")
        used = len(store().get("history", []))
        nudges = store().get("nudges", 0)
        if sub is None:
            return Score(value=dict(submitted=0, feasible=0, energy_kwh_day=0, saving_pct=0, trials_used=used, nudges=nudges),
                         explanation="no submission")
        result = await asyncio.to_thread(bench.score, plant_for(state), sub)
        return Score(value=dict(submitted=1, feasible=int(result["feasible"]), energy_kwh_day=result["aeration_energy_kwh_d"],
                                saving_pct=result["saving_pct"], trials_used=used, nudges=nudges),
                     answer=json.dumps(result["params"]),
                     explanation=json.dumps(dict(scenarios_failed=result["scenarios_failed"], failures=result["failures"])),
                     metadata=dict(score=result))
    return run

def aerobench():
    samples = [Sample(input="Tune the DO controller for this plant.", id=name, metadata=dict(plant=name))
               for name in bench.PLANTS]
    return Task(dataset=samples, solver=[bind_plant(), system_message(PROMPT), use_tools(run_trial(), submit_gains()), agent_loop()],
                scorer=held_out(), message_limit=3 * TRIAL_BUDGET + 10)
