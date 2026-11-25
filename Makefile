# .env (copy .env.example) feeds gold2psql and pytest; in deployment inject real env vars instead.
-include .env
export

DBT = cd dbt && uv run dbt

.PHONY: data deps seed build test run clean up down sync pytest

data:
	uv run python scripts/gen_synthetic_data.py

deps:
	mkdir -p .data
	$(DBT) deps --profiles-dir .

seed: deps
	$(DBT) seed --profiles-dir .

build: seed
	$(DBT) build --profiles-dir . --exclude resource_type:seed

test:
	$(DBT) test --profiles-dir .

run: up build test sync

up:
	docker compose up -d --wait

down:
	docker compose down -v

sync:
	uv run gold2psql

pytest:
	uv run pytest

clean:
	rm -rf .data dbt/target dbt/logs dbt/dbt_packages
