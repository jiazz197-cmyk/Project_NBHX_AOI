# Default dev entry: Django dev server + Celery worker together（D5 导入必须有 worker；
# Ctrl+C 同时退出两条进程；日志会交错输出）。Redis 需另行可用（见 .env.example 的 CELERY_BROKER_URL）。
run-dev:
	$(MAKE) -j2 run-django run-celery

# Run Django dev server only（不带 worker；导入不可用，仅供单进程调试）
# 端口固定 8082：本机 8000/8080/8081 被 Dify / SearXNG 等其它服务占用
run-django:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py runserver 0.0.0.0:8082

# Run Celery worker for aoi async tasks (D5 import package; needs Redis on CELERY_BROKER_URL)
# PYTHONPATH 必须指向 label_studio（celery -A aoi 不像 manage.py 会自带工程路径）；
# 开发用 --pool=solo 单进程池：本地导入量级足够，且不依赖 /dev/shm（prefork 在受限环境会 PermissionError）。
run-celery:
	PYTHONPATH=label_studio DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run celery -A aoi worker --queues=default --pool=solo --concurrency=1 --loglevel=info

# Run Django dev migrations with Sqlite
migrate-dev:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py migrate

# Run Django dev make migrations with Sqlite
makemigrations-dev:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py makemigrations

# Run Django dev shell environment with Sqlite
shell-dev:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py shell_plus

env-dev-setup:
	if [ ! -f .env ]; then \
		cp .env.development .env; \
	fi

docker-dev-override:
	if [ ! -f docker-compose.override.yml ]; then \
		cp docker-compose.override.example.yml docker-compose.override.yml; \
	fi

# Configure Django dev server with Hot Module Replacement in docker
docker-dev-setup: env-dev-setup docker-dev-override

docker-run-dev:
	docker compose up --build

docker-migrate-dev:
	docker compose run app python3 /label-studio/label_studio/manage.py migrate

docker-collectstatic-dev:
	docker compose run app python3 /label-studio/label_studio/manage.py collectstatic

# Install modules
frontend-install:
	cd web && bun install --frozen-lockfile;

# Alias for backward compatibility
frontend-setup: frontend-install

# Run frontend dev server in Hot Module Replacement mode
# For more information on HMR, see the "Environment Configuration" section in:
# web/README.md
frontend-dev:
	cd web && bun run dev

# Build frontend continuously on files changes
frontend-watch:
	cd web && bun run watch

# Build production-ready optimized bundle
frontend-build: frontend-setup
	cd web && bun run build

# Build frontend + refresh the manifest Django actually reads (STATIC_ROOT/js/manifest.json,
# populated only by collectstatic — web/dist's own manifest.json is never read at runtime).
# Django loads the manifest once at process start: restart the backend afterwards.
frontend-build-collect: frontend-build
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py collectstatic --noinput

frontend-storybook-serve: frontend-setup
	cd web && bun run ui:serve

# Run tests
test:
	DJANGO_DB=default uv run pytest label_studio -v -m "not integration_tests"

# Build image which includes test dependencies, for unit testing within docker
build-testing-image:
	docker build -t heartexlabs/label-studio:latest . && docker build -t heartexlabs/label-studio:latest-testing -f Dockerfile.testing .

# Run an interactive shell inside a testing container. Label studio dir will be mounted as a volume
# to avoid need for rebuilds. Run `make build-testing-image` first.
docker-testing-shell:
	docker run --volume ./label_studio:/label-studio/label_studio --volume ./mydata:/label-studio/data:rw -it heartexlabs/label-studio:latest-testing /bin/bash

# Update urls
update-urls:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py show_urls --format pretty-json > ./label_studio/core/all_urls.json

# Format changed files on branch
fmt:
	pre-commit run --config .pre-commit-dev.yaml --hook-stage manual

# Format all files in repo
fmt-all:
	pre-commit run --config .pre-commit-dev.yaml --hook-stage manual --all-files

# Check for lint issues on this branch
fmt-check:
	pre-commit run --hook-stage pre-push

# Check for lint issues in entire repo
fmt-check-all:
	pre-commit run --hook-stage pre-push --all-files

# Configure pre-push hook using pre-commit
configure-hooks:
	pre-commit install --hook-type pre-push

# Generate swagger.json
generate-swagger:
	DJANGO_DB=default LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio uv run python label_studio/manage.py generate_swagger swagger.json
