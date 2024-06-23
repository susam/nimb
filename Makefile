help:
	@echo 'Usage: make [target]'
	@echo
	@echo 'Development Targets:'
	@echo '  venv      Create virtual Python environment for development.'
	@echo '  checks    Run linters and tests.'
	@echo
	@echo 'Distribution Targets:'
	@echo '  dist         Create distribution.'
	@echo '  test-upload  Upload distribution to test PyPI.'
	@echo '  uplaod       Upload distribution to PyPI.'
	@echo
	@echo 'Deployment Targets:'
	@echo '  service   Remove, install, configure, and run NIMB.'
	@echo '  rm        Remove NIMB.'
	@echo '  help      Show this help message.'


# Development Targets
# -------------------

VENV = ~/.venv/nimb

venv: FORCE
	rm -rf $(VENV)/
	python3 -m venv $(VENV)/
	$(VENV)/bin/pip3 install -U build twine
	$(VENV)/bin/pip3 install ruff mypy

lint:
	$(VENV)/bin/ruff check
	$(VENV)/bin/ruff format --diff
	$(VENV)/bin/mypy .

test:
	$(VENV)/bin/python3 -m unittest -v

coverage:
	$(VENV)/bin/coverage run --branch -m unittest -v
	$(VENV)/bin/coverage report --show-missing
	$(VENV)/bin/coverage html

check-password:
	! grep -r '"password":' . | grep -vE '^\./[^/]*.json|Makefile|\.\.\.'

checks: lint test check-password

clean:
	rm -rf *.pyc __pycache__
	rm -rf .coverage htmlcov
	rm -rf dist nimb.egg-info


# Distribution Targets
# --------------------

dist: clean
	. ./venv && python3 -m build
	. ./venv && twine check dist/*
	unzip -c dist/*.whl '*/METADATA'
	unzip -t dist/*.whl
	tar -tvf dist/*.tar.gz

upload:
	. ./venv && twine upload dist/*

user-venv: FORCE
	rm -rf ~/.venv/user-nimb user-venv
	python3 -m venv ~/.venv/user-nimb
	echo . ~/.venv/user-nimb/bin/activate > user-venv

verify-upload:
	$(MAKE) verify-sdist
	$(MAKE) verify-bdist

verify-sdist: user-venv
	. ./user-venv && pip3 install --no-binary :all: nimb
	. ./user-venv && command -v nimb

verify-bdist: user-venv
	. ./user-venv && pip3 install nimb
	. ./user-venv && command -v nimb


# Deployment Targets
# ------------------

service: rmservice
	adduser --system --group --home / nimb
	chown -R nimb:nimb .
	chmod 600 nimb.json
	systemctl enable "$$PWD/etc/nimb.service"
	systemctl daemon-reload
	systemctl start nimb
	@echo Done; echo

rmservice:
	-systemctl stop nimb
	-systemctl disable nimb
	systemctl daemon-reload
	-deluser nimb
	@echo Done; echo

FORCE:
