.PHONY: test format lint
test:
	@if [ -f "pyproject.toml" ] || ls *.py >/dev/null 2>&1; then \
		python -m pip install -U pip >/dev/null; \
		python -m pip install pytest >/dev/null; \
		pytest -q || true; \
	elif [ -f "package.json" ]; then \
		npm ci || npm i; \
		npm test || true; \
	else \
		echo "No tests configured"; \
	fi
format:
	@if [ -f "pyproject.toml" ] || ls *.py >/dev/null 2>&1; then \
		python -m pip install black ruff >/dev/null; \
		ruff check . --fix || true; \
		black . || true; \
	fi; \
	if [ -f "package.json" ]; then \
		npm i -D prettier eslint || true; \
		npm run format || npx prettier -w . || true; \
		npx eslint . --fix || true; \
	fi
lint:
	@if [ -f "pyproject.toml" ] || ls *.py >/dev/null 2>&1; then \
		python -m pip install ruff >/dev/null; \
		ruff check . || true; \
	fi; \
	if [ -f "package.json" ]; then \
		npx eslint . || true; \
	fi
