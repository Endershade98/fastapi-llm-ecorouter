PYTHON_BOOTSTRAP ?= python3
PYTHON ?= .venv/bin/python

.PHONY: install check-venv

install:
ifeq ($(origin PYTHON),file)
	@test -x "$(PYTHON)" || "$(PYTHON_BOOTSTRAP)" -m venv .venv
endif
	@$(MAKE) check-venv
	"$(PYTHON)" -m pip install -r requirements-dev.txt
	"$(PYTHON)" -m pip install -e .
	"$(PYTHON)" -m pip check

check-venv:
	@test -x "$(PYTHON)" || { echo 'Interprete assente. Esegui make install.' >&2; exit 1; }
	@"$(PYTHON)" -c 'import sys; sys.exit("Serve un virtualenv") if sys.prefix == sys.base_prefix else print(sys.executable)'
