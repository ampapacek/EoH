PYTHON ?= python3.11
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
EOH_DIR ?= EoH
EOH_REPO ?= https://github.com/FeiLiu36/EoH.git

.PHONY: build venv clone-eoh install dirs clean-venv clean-eoh

build: dirs install

dirs:
	mkdir -p results logs notes

venv: $(VENV_PYTHON)

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV_DIR)

clone-eoh: $(EOH_DIR)/.git

$(EOH_DIR)/.git:
	git clone $(EOH_REPO) $(EOH_DIR)

install: $(VENV_DIR)/.bootstrap-complete

$(VENV_DIR)/.bootstrap-complete: $(VENV_PYTHON) $(EOH_DIR)/.git
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e $(EOH_DIR)/eoh
	$(VENV_PIP) install requests
	touch $(VENV_DIR)/.bootstrap-complete

clean-venv:
	rm -rf $(VENV_DIR)

clean-eoh:
	rm -rf $(EOH_DIR)
