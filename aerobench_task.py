"""Inspect entry point: inspect eval aerobench_task.py --model <provider/model>"""
from inspect_ai import task
from aera.aerobench import aerobench as build

@task
def aerobench():
    return build()
