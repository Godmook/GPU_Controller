# WDRF Controller Makefile
# 프로젝트 빌드, 테스트, 배포를 위한 명령어들

.PHONY: help build test clean docker-build docker-run deploy install-deps lint format ci-cd

# 기본 변수들
PYTHON := python3
PIP := pip3
DOCKER_IMAGE := wdrf-controller
DOCKER_TAG := latest
NAMESPACE := wdrf-system

# 도움말
help:
	@echo "WDRF Controller - Available Commands:"
	@echo ""
	@echo "Development:"
	@echo "  install-deps    Install Python dependencies"
	@echo "  install-dev     Install development dependencies"
	@echo "  test           Run unit tests"
	@echo "  test-integration Run integration tests"
	@echo "  test-all       Run all tests with coverage"
	@echo "  lint           Run code linting"
	@echo "  type-check     Run type checking with mypy"
	@echo "  quality        Run linting and type checking"
	@echo "  format         Format code with black"
	@echo "  pre-commit     Run pre-commit hooks"
	@echo ""
	@echo "Build:"
	@echo "  build          Build the application"
	@echo "  docker-build   Build Docker image"
	@echo ""
	@echo "Run:"
	@echo "  run            Run the controller locally"
	@echo "  docker-run     Run the controller in Docker"
	@echo "  health-check   Run health check"
	@echo ""
	@echo "Deploy:"
	@echo "  deploy         Deploy to Kubernetes"
	@echo "  undeploy       Remove from Kubernetes"
	@echo ""
	@echo "CI/CD:"
	@echo "  ci-cd          Run full CI/CD pipeline"
	@echo "  security-scan  Run security scan"
	@echo "  performance    Run performance tests"
	@echo ""
	@echo "Clean:"
	@echo "  clean          Clean build artifacts"
	@echo "  docker-clean   Clean Docker images"

# 의존성 설치
install-deps:
	@echo "Installing Python dependencies..."
	$(PIP) install -r requirements.txt
	@echo "Dependencies installed successfully!"

install-dev: install-deps
	@echo "Installing development dependencies..."
	$(PIP) install -r requirements-dev.txt
	pre-commit install
	@echo "Development environment setup completed!"

# 코드 포맷팅
format:
	@echo "Formatting code with black..."
	black controller/ tests/
	isort controller/ tests/
	@echo "Code formatting completed!"

# 코드 린팅
lint:
	@echo "Running code linting..."
	flake8 controller/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
	black --check controller/ tests/
	@echo "Linting completed!"

# 타입 체크
type-check:
	@echo "Running type checking with mypy..."
	mypy controller/ --install-types
	@echo "Type checking completed!"

# 전체 코드 품질 검사
quality: lint type-check
	@echo "Code quality check completed!"

# pre-commit 훅 실행
pre-commit:
	@echo "Running pre-commit hooks..."
	pre-commit run --all-files
	@echo "Pre-commit hooks completed!"

# 테스트 실행
test:
	@echo "Running unit tests..."
	$(PYTHON) -m pytest tests/ -v --cov=controller --cov-report=html --cov-report=term-missing -m "not integration"

test-integration:
	@echo "Running integration tests..."
	$(PYTHON) -m pytest tests/test_integration.py -v -m integration

test-all: test test-integration
	@echo "All tests completed!"

# 성능 테스트
performance:
	@echo "Running performance tests..."
	$(PYTHON) -m pytest tests/test_integration.py -v -m "slow" --benchmark-only

# 보안 스캔
security-scan:
	@echo "Running security scan..."
	bandit -r controller/ -f json -o bandit-report.json
	safety check
	@echo "Security scan completed!"

# 빌드
build: install-deps quality test-all security-scan
	@echo "Building WDRF Controller..."
	$(PYTHON) -m controller --health-check
	@echo "Build completed successfully!"

# 로컬 실행
run:
	@echo "Running WDRF Controller locally..."
	$(PYTHON) -m controller

# 헬스 체크
health-check:
	@echo "Running health check..."
	$(PYTHON) -m controller --health-check

# Docker 빌드
docker-build:
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	@echo "Docker image built successfully!"

# Docker 실행
docker-run:
	@echo "Running WDRF Controller in Docker..."
	docker run -d \
		--name wdrf-controller \
		-v /var/log:/var/log \
		-e LOG_LEVEL=INFO \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

# Docker 정리
docker-clean:
	@echo "Cleaning Docker images..."
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG) 2>/dev/null || true
	docker system prune -f
	@echo "Docker cleanup completed!"

# Kubernetes 배포
deploy:
	@echo "Deploying to Kubernetes..."
	kubectl apply -f k8s/
	@echo "Deployment completed!"
	@echo "Check status with: kubectl get pods -n $(NAMESPACE)"

# Kubernetes 제거
undeploy:
	@echo "Removing from Kubernetes..."
	kubectl delete -f k8s/
	@echo "Undeployment completed!"

# 배포 상태 확인
deploy-status:
	@echo "Checking deployment status..."
	kubectl get pods -n $(NAMESPACE)
	kubectl get services -n $(NAMESPACE)
	kubectl get deployments -n $(NAMESPACE)

# 로그 확인
logs:
	@echo "Showing controller logs..."
	kubectl logs -f deployment/wdrf-controller -n $(NAMESPACE)

# 예제 Workload 배포
deploy-examples:
	@echo "Deploying example workloads..."
	kubectl apply -f examples/
	@echo "Example workloads deployed!"

# 예제 Workload 제거
undeploy-examples:
	@echo "Removing example workloads..."
	kubectl delete -f examples/
	@echo "Example workloads removed!"

# 전체 정리
clean: docker-clean
	@echo "Cleaning build artifacts..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf bandit-report.json
	@echo "Cleanup completed!"

# 개발 환경 설정
dev-setup: install-dev
	@echo "Setting up development environment..."
	pre-commit install
	@echo "Development environment setup completed!"

# 릴리스 빌드
release: clean build docker-build
	@echo "Release build completed!"
	@echo "Docker image: $(DOCKER_IMAGE):$(DOCKER_TAG)"

# 전체 CI/CD 파이프라인
ci-cd: install-dev lint test-all security-scan docker-build
	@echo "CI/CD pipeline completed successfully!"

# 프로덕션 배포
prod-deploy: ci-cd
	@echo "Deploying to production..."
	kubectl apply -f k8s/ -n $(NAMESPACE)
	kubectl rollout status deployment/wdrf-controller -n $(NAMESPACE)
	@echo "Production deployment completed!"

# 백업
backup:
	@echo "Creating backup..."
	tar -czf wdrf-controller-backup-$(shell date +%Y%m%d-%H%M%S).tar.gz \
		controller/ k8s/ examples/ tests/ requirements*.txt Dockerfile README.md
	@echo "Backup created!"

# 복원
restore:
	@echo "Restoring from backup..."
	@read -p "Enter backup file name: " backup_file; \
	tar -xzf $$backup_file
	@echo "Restore completed!"

# 문서 생성
docs:
	@echo "Generating documentation..."
	sphinx-apidoc -o docs/source controller/
	cd docs && make html
	@echo "Documentation generated!"

# 커버리지 리포트 열기
coverage-report:
	@echo "Opening coverage report..."
	open htmlcov/index.html

# 테스트 결과 요약
test-summary:
	@echo "Test Summary:"
	@echo "============="
	@$(PYTHON) -m pytest tests/ --tb=no -q | tail -n 1

# 개발 서버 실행
dev-server:
	@echo "Starting development server..."
	$(PYTHON) -m controller --log-level DEBUG --dry-run

# 모니터링
monitor:
	@echo "Starting monitoring..."
	watch -n 5 'kubectl get pods -n $(NAMESPACE) && echo "---" && kubectl get workloads -A'

# 디버그 모드
debug:
	@echo "Starting in debug mode..."
	$(PYTHON) -m pdb -m controller

# 프로파일링
profile:
	@echo "Running profiler..."
	$(PYTHON) -m cProfile -o profile.stats -m controller --dry-run
	@echo "Profile data saved to profile.stats"

# 벤치마크
benchmark:
	@echo "Running benchmarks..."
	$(PYTHON) -m pytest tests/test_integration.py -v -m "slow" --benchmark-only --benchmark-sort=mean

# 코드 복잡도 분석
complexity:
	@echo "Analyzing code complexity..."
	radon cc controller/ -a
	radon mi controller/ -a

# 의존성 업데이트
update-deps:
	@echo "Updating dependencies..."
	pip-compile --upgrade requirements.in
	pip-compile --upgrade requirements-dev.in
	@echo "Dependencies updated!"

# 가상환경 생성
venv:
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv venv
	@echo "Virtual environment created. Activate with: source venv/bin/activate"

# 전체 개발 워크플로우
dev-workflow: venv install-dev pre-commit test-all
	@echo "Development workflow completed!"

# 간단한 커밋 전 검사
pre-commit-simple:
	@echo "Running simple pre-commit checks..."
	black --check controller/ tests/
	isort --check-only controller/ tests/
	@echo "Simple checks completed!"

# 전체 검사 (커밋 전에 수동으로 실행)
full-check: quality test-all security-scan
	@echo "Full check completed!"
