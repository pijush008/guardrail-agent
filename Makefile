.PHONY: venv install test eval api web web-dev badge

venv:
	python3 -m venv .venv

install:
	.venv/bin/pip install -r requirements.txt

model:
	.venv/bin/python -m spacy download en_core_web_lg

test:
	.venv/bin/pytest -q

eval:
	.venv/bin/python -m evals.eval_runner --min-pass 80 --outdir reports

api:
	.venv/bin/uvicorn service.main:app --reload --port 8000

web:
	cd web && npm run dev

web-build:
	cd web && npm run build

badge:
	.venv/bin/python scripts/publish_badge.py reports/eval_summary.json results/README.md
