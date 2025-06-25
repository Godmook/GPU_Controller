# WDRF Controller

Weighted Dominant Resource Fairness GPU Scheduler for Kubernetes with Kueue and HAMi

## 개요

WDRF Controller는 Kubernetes 환경에서 GPU 자원의 효율적인 스케줄링을 위한 오픈소스 솔루션입니다. Project-HAMi와 Kueue를 결합하여 GPU 할당률과 사용률을 최적화합니다.

## 주요 기능

### 🚀 GPU 스케줄링 최적화
- **DRF (Dominant Resource Fairness)** 기반 리소스 할당
- **가중치 기반 우선순위** 스케줄링
- **Aging 메커니즘**을 통한 Starvation 방지
- **GPU Fraction** 지원 (HAMi 기반)

### 🎯 우선순위 관리
- **긴급**: 관리자 직접 조정 (가중치: 1000)
- **승인**: 팀장급 승인 (가중치: 100)
- **일반**: 기본 우선순위 (가중치: 1)

### 🔧 스케줄링 정책
- **Binpack**: 리소스 사용률 최적화
- **Spread**: 안정성 최적화
- **Gang Scheduling**: 분산 학습 지원

## 아키텍처

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Kubernetes    │    │   Kueue Queue   │    │   HAMi GPU      │
│   Cluster       │◄──►│   Management    │◄──►│   Fraction      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    WDRF Controller                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Priority  │  │  Resource   │  │   K8s       │            │
│  │ Calculator  │  │   View      │  │  Client     │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## 설치 및 실행

### 1. 사전 요구사항

- Kubernetes 1.24+
- Kueue v0.5.0+
- Project-HAMi v0.8.0+
- Python 3.11+

### 2. 로컬 실행

```bash
# 저장소 클론
git clone <repository-url>
cd controller

# 의존성 설치
pip install -r requirements.txt

# 기본 실행
python -m controller

# 로그 레벨 지정
python -m controller --log-level DEBUG

# 헬스 체크
python -m controller --health-check
```

### 3. Docker 실행

```bash
# 이미지 빌드
docker build -t wdrf-controller:latest .

# 컨테이너 실행
docker run -d \
  --name wdrf-controller \
  -v /var/log:/var/log \
  -e KUBECONFIG_PATH=/path/to/kubeconfig \
  wdrf-controller:latest
```

### 4. Kubernetes 배포

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wdrf-controller
  namespace: kueue-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: wdrf-controller
  template:
    metadata:
      labels:
        app: wdrf-controller
    spec:
      serviceAccountName: wdrf-controller
      containers:
      - name: wdrf-controller
        image: wdrf-controller:latest
        env:
        - name: LOG_LEVEL
          value: "INFO"
        - name: LOOP_INTERVAL
          value: "30"
        ports:
        - containerPort: 8080
          name: metrics
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
```

## 설정

### 환경 변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG, INFO, WARNING, ERROR) |
| `LOOP_INTERVAL` | `30` | 스케줄링 사이클 간격 (초) |
| `AGING_COEFFICIENT` | `0.1` | Aging 계수 |
| `MAX_AGING_TIME` | `3600` | 최대 Aging 시간 (초) |
| `KUBECONFIG_PATH` | `""` | kubeconfig 파일 경로 |

### 설정 파일 예제

```yaml
# config.yaml
LOOP_INTERVAL: 30
AGING_COEFFICIENT: 0.1
MAX_AGING_TIME: 3600
LOG_LEVEL: INFO

PRIORITY_WEIGHTS:
  urgent: 1000
  approved: 100
  normal: 1

RESOURCE_WEIGHTS:
  cpu: 1.0
  memory: 1.0
  nvidia.com/gpu: 10.0
  nvidia.com/gpucores: 0.1
  nvidia.com/gpumem-percentage: 0.1
```

## 사용법

### 1. 기본 Workload 생성

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: Workload
metadata:
  name: example-workload
  namespace: team-mlops
  annotations:
    wdrf.x-k8s.io/approved: "true"
spec:
  podSets:
  - name: main
    count: 1
    template:
      spec:
        containers:
        - name: training
          image: nvidia/cuda:11.8-base
          resources:
            requests:
              cpu: "4"
              memory: "8Gi"
              nvidia.com/gpu: "1"
              nvidia.com/gpucores: "50"
              nvidia.com/gpumem-percentage: "50"
            limits:
              nvidia.com/gpu: "1"
              nvidia.com/gpucores: "50"
              nvidia.com/gpumem-percentage: "50"
  queueName: h100-80gb-queue
```

### 2. 긴급 우선순위 설정

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: Workload
metadata:
  name: urgent-workload
  namespace: team-mlops
  annotations:
    wdrf.x-k8s.io/urgent: "true"
    wdrf.x-k8s.io/priority-override: "true"
spec:
  # ... workload spec
```

### 3. Gang Scheduling

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gang-pod-master
  namespace: team-mlops
  labels:
    kueue.x-k8s.io/queue-name: h100-80gb-queue
    kueue.x-k8s.io/pod-group-name: gang-training
  annotations:
    kueue.x-k8s.io/pod-group-total-count: "3"
    hami.io/node-scheduler-policy: "binpack"
    hami.io/gpu-scheduler-policy: "binpack"
spec:
  containers:
  - name: training
    image: nvidia/cuda:11.8-base
    resources:
      limits:
        nvidia.com/gpu: 2
        nvidia.com/gpucores: 80
        nvidia.com/gpumem-percentage: 80
```

## 모니터링

### 1. 로그 확인

```bash
# 컨테이너 로그
kubectl logs -f deployment/wdrf-controller -n kueue-system

# 파일 로그
tail -f /var/log/wdrf-controller.log
```

### 2. 헬스 체크

```bash
# 직접 실행
python -m controller --health-check

# HTTP 엔드포인트 (향후 구현 예정)
curl http://localhost:8080/health
```

### 3. 메트릭스 (향후 구현 예정)

```bash
# Prometheus 메트릭스
curl http://localhost:8080/metrics
```

## 성능 최적화

### 1. GPU 사용률 향상

- **Binpack 정책** 사용으로 리소스 집중 배치
- **GPU Fraction** 적용으로 메모리 효율성 증대
- **Aging 계수** 조정으로 Starvation 방지

### 2. 스케줄링 성능

- **strictFIFO 비활성화**로 유연한 스케줄링
- **주기적 클러스터 상태 새로고침**
- **우선순위 캐싱** (향후 구현 예정)

## 문제 해결

### 1. 일반적인 문제

**Q: Kubernetes 연결 실패**
```bash
# kubeconfig 확인
kubectl config view

# 서비스 계정 권한 확인
kubectl auth can-i get workloads --all-namespaces
```

**Q: 우선순위 업데이트 실패**
```bash
# Kueue API 확인
kubectl get workloads --all-namespaces

# 로그 확인
kubectl logs deployment/wdrf-controller -n kueue-system
```

### 2. 디버깅

```bash
# 디버그 모드 실행
python -m controller --log-level DEBUG

# Dry run 모드
python -m controller --dry-run
```

## 기여하기

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 연락처

- 프로젝트 관리자: AX Technology Group
- 이슈 리포트: [GitHub Issues](https://github.com/your-repo/issues)
- 문서: [Wiki](https://github.com/your-repo/wiki)

## 참고 자료

- [Project-HAMi](https://github.com/Project-HAMi/HAMi)
- [Kueue](https://github.com/kubernetes-sigs/kueue)
- [Dominant Resource Fairness](https://www.usenix.org/conference/nsdi11/dominant-resource-fairness-fair-allocation-multiple-resource-types)
