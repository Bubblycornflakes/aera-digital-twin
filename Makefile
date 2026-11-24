.PHONY: setup fetch test baselines report demo
setup:
	uv venv --python 3.13 && uv pip install -r requirements.txt && npm ci --prefix frontend
fetch:
	.venv/bin/python scripts/fetch_bsm1.py
test:
	.venv/bin/python -m pytest -q
baselines:
	.venv/bin/python -m aera.run_benchmark && .venv/bin/python -m aera.leaderboard
report:
	.venv/bin/python -m aera.report results/report.html
demo:
	./start.sh
