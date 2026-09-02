# CYCLOPS — task runner.
# Self-documenting: `make` or `make help` lists every target.

SHELL := /bin/bash
PY    := .venv/bin/python
PIP   := .venv/bin/pip
EXPORT := PYTHONPATH=src

.DEFAULT_GOAL := help

.PHONY: help
help:  ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
.PHONY: setup
setup:  ## create the venv and install python + node dependencies
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	cd console && npm install

# ---------------------------------------------------------------- data
.PHONY: data
data:  ## download IBTrACS and build the vision dataset
	$(EXPORT) $(PY) -c "from cyclops.data.ibtracs import download; print(download())"
	$(EXPORT) $(PY) -m cyclops.data.build_dataset

# ---------------------------------------------------------------- train
.PHONY: train
train: nowcast intensity  ## train everything

.PHONY: nowcast
nowcast:  ## train the quantile nowcast and write the baseline table
	$(EXPORT) $(PY) -W ignore -m cyclops.train.train_nowcast

.PHONY: intensity
intensity:  ## train the fusion intensity model and run the ablation
	$(EXPORT) $(PY) -W ignore -m cyclops.train.train_intensity

# ---------------------------------------------------------------- eval
.PHONY: fani
fani:  ## fetch real MODIS scenes for Fani and run identification + Dvorak
	$(EXPORT) $(PY) -W ignore -u -m cyclops.analysis.run_fani
	$(EXPORT) $(PY) -W ignore -m cyclops.analysis.fani_figures

.PHONY: eval
eval:  ## print the results table from artifacts/
	$(EXPORT) $(PY) -m cyclops.eval.report

.PHONY: figures
figures: qc case-study  ## regenerate every figure in artifacts/

.PHONY: qc
qc:  ## sample audit, renderer physics check, class balance
	$(EXPORT) $(PY) -W ignore -m cyclops.eval.qc_sheet

.PHONY: case-study
case-study:  ## replay the hero case and score it frame by frame
	$(EXPORT) $(PY) -W ignore -m cyclops.eval.case_study

.PHONY: onnx
onnx:  ## export the intensity model to ONNX and verify parity
	$(EXPORT) $(PY) -W ignore -m cyclops.export.to_onnx

# ---------------------------------------------------------------- test
.PHONY: test
test:  ## run the protective tests
	PYTHONPATH=src:. .venv/bin/python -m pytest tests -q
	@$(MAKE) --no-print-directory validate-map

.PHONY: test-critical
test-critical:  ## run only the three tests that protect credibility
	PYTHONPATH=src:. .venv/bin/python -m pytest -q \
	  tests/test_split_integrity.py \
	  tests/test_replay_causality.py \
	  tests/test_preprocess_parity.py

# ---------------------------------------------------------------- serve
.PHONY: api
api:  ## run the API on :8000
	$(EXPORT) .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

.PHONY: console
console:  ## run the console on :5180
	cd console && npm run dev

.PHONY: demo
demo:  ## run API + console together (the demo-day command)
	@bash scripts/demo.sh

.PHONY: stop
stop:  ## stop anything started by `make demo`
	-@pkill -f "uvicorn api.main:app" 2>/dev/null || true
	-@pkill -f "vite" 2>/dev/null || true
	@echo "stopped"

# ---------------------------------------------------------------- checks
.PHONY: smoke
smoke:  ## verify a running stack end to end
	@bash scripts/smoke.sh

.PHONY: validate-map
validate-map:  ## validate the map style + bundled basemap without a browser
	cd console && npm run validate:map

.PHONY: offline-check
offline-check:  ## assert the console makes no external network requests
	@grep -rniE "https?://(?!localhost|127\.0\.0\.1)" console/src console/index.html \
	  --include='*.ts' --include='*.tsx' --include='*.html' -P \
	  && (echo "FAIL: external URL found in console source" && exit 1) \
	  || echo "OK: console references no external hosts"
