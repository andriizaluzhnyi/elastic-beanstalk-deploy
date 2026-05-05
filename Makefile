# ╔══════════════════════════════════════════════════════════╗
# ║   Makefile для вашого проєкту (скопіюйте до себе)       ║
# ╚══════════════════════════════════════════════════════════╝

.PHONY: help deploy deploy-dry status package install

# Виводить довідку
help:
	@echo ""
	@echo "  make deploy        — повний деплой на EB (stage)"
	@echo "  make deploy-dry    — зібрати архів без реального деплою"
	@echo "  make status        — поточний стан EB environment"
	@echo "  make package       — тільки зібрати deploy.zip"
	@echo "  make install       — встановити ebdeploy (pip)"
	@echo ""

# Встановити бібліотеку
install:
	pip install ebdeploy

# Повний деплой
deploy:
	ebdeploy deploy

# Деплой з кастомною версією
deploy-version:
	ebdeploy deploy --version $(VERSION)

# Dry-run (без AWS дзвінків)
deploy-dry:
	ebdeploy deploy --dry-run

# Стан environment
status:
	ebdeploy status

# Тільки запакувати
package:
	ebdeploy package --output deploy.zip

# ── Для розробки самої бібліотеки ebdeploy ──────────────────────────────────
.PHONY: dev-install test lint

dev-install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check ebdeploy/
