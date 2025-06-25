"""
pytest 공통 설정 및 Fixture 정의
"""

import pytest
import tempfile
import os
import sys
from unittest.mock import Mock, patch
from typing import Dict, Any

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from controller.config import Config
from controller.priority import PriorityCalculator, PriorityTier
from controller.resource_view import ResourceView
from controller.k8s_client import KubernetesClient


@pytest.fixture(scope="session")
def sample_workloads():
    """테스트용 샘플 워크로드 데이터"""
    return {
        "urgent_workload": {
            "metadata": {
                "name": "urgent-job",
                "namespace": "default",
                "annotations": {"wdrf.x-k8s.io/urgent": "true"},
            },
            "spec": {
                "podSets": [
                    {
                        "count": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "resources": {
                                            "requests": {
                                                "cpu": "4",
                                                "memory": "8Gi",
                                                "nvidia.com/gpu": "2",
                                            }
                                        }
                                    }
                                ]
                            }
                        },
                    }
                ]
            },
            "status": {"conditions": [{"type": "Pending", "status": "True"}]},
        },
        "normal_workload": {
            "metadata": {
                "name": "normal-job",
                "namespace": "default",
                "annotations": {},
            },
            "spec": {
                "podSets": [
                    {
                        "count": 2,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "resources": {
                                            "requests": {
                                                "cpu": "2",
                                                "memory": "4Gi",
                                                "nvidia.com/gpu": "1",
                                            }
                                        }
                                    }
                                ]
                            }
                        },
                    }
                ]
            },
            "status": {"conditions": [{"type": "Pending", "status": "True"}]},
        },
        "gang_workload": {
            "metadata": {
                "name": "gang-job",
                "namespace": "default",
                "annotations": {"kueue.x-k8s.io/queue-name": "default"},
            },
            "spec": {
                "podSets": [
                    {
                        "count": 4,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "resources": {
                                            "requests": {
                                                "cpu": "1",
                                                "memory": "2Gi",
                                                "nvidia.com/gpu": "1",
                                            }
                                        }
                                    }
                                ]
                            }
                        },
                    }
                ]
            },
            "status": {"conditions": [{"type": "Pending", "status": "True"}]},
        },
    }


@pytest.fixture(scope="session")
def sample_cluster_resources():
    """테스트용 클러스터 리소스 데이터"""
    return {
        "capacity": {"cpu": 100.0, "memory": 1000.0, "nvidia.com/gpu": 20.0},
        "usage": {"cpu": 30.0, "memory": 300.0, "nvidia.com/gpu": 8.0},
    }


@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes 클라이언트"""
    with patch("controller.k8s_client.config") as mock_config:
        with patch("controller.k8s_client.client") as mock_client:
            client = KubernetesClient()
            client.api_client = Mock()
            client.core_v1_api = Mock()
            client.custom_objects_api = Mock()
            client.scheduling_v1_api = Mock()
            yield client


@pytest.fixture
def mock_resource_view(mock_k8s_client):
    """Mock 리소스 뷰"""
    resource_view = ResourceView(mock_k8s_client)
    resource_view._cluster_capacity = {
        "cpu": 100.0,
        "memory": 1000.0,
        "nvidia.com/gpu": 20.0,
    }
    resource_view._cluster_usage = {"cpu": 30.0, "memory": 300.0, "nvidia.com/gpu": 8.0}
    return resource_view


@pytest.fixture
def priority_calculator(mock_resource_view):
    """우선순위 계산기 인스턴스"""
    return PriorityCalculator(mock_resource_view)


@pytest.fixture
def temp_config_file():
    """임시 설정 파일"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(
            """
LOG_LEVEL: DEBUG
SCAN_INTERVAL: 30
AGING_COEFFICIENT: 0.1
MAX_AGING_TIME: 3600
PRIORITY_WEIGHTS:
  urgent: 1000
  approved: 100
  normal: 1
RESOURCE_WEIGHTS:
  cpu: 1.0
  memory: 1.0
  nvidia.com/gpu: 10.0
SCHEDULING_POLICIES:
  enable_aging: true
  enable_gang_scheduling: true
        """
        )
        temp_file = f.name

    yield temp_file

    # 정리
    os.unlink(temp_file)


@pytest.fixture(autouse=True)
def reset_config():
    """각 테스트 후 설정 초기화"""
    yield
    # Config 클래스의 기본값으로 복원
    Config.LOG_LEVEL = "INFO"
    Config.SCAN_INTERVAL = 60
    Config.AGING_COEFFICIENT = 0.05
    Config.MAX_AGING_TIME = 1800


@pytest.fixture
def mock_kubernetes_api():
    """Kubernetes API Mock"""
    with patch("kubernetes.client.CoreV1Api") as mock_core:
        with patch("kubernetes.client.CustomObjectsApi") as mock_custom:
            with patch("kubernetes.client.SchedulingV1Api") as mock_scheduling:
                mock_core.return_value.list_node.return_value.items = []
                mock_custom.return_value.list_namespaced_custom_object.return_value = {
                    "items": []
                }
                mock_scheduling.return_value.list_priority_class.return_value.items = []
                yield {
                    "core": mock_core,
                    "custom": mock_custom,
                    "scheduling": mock_scheduling,
                }


@pytest.fixture
def sample_priority_classes():
    """테스트용 PriorityClass 데이터"""
    return [
        {"metadata": {"name": "wdrf-urgent"}, "value": 1000},
        {"metadata": {"name": "wdrf-approved"}, "value": 100},
        {"metadata": {"name": "wdrf-normal"}, "value": 1},
    ]


# 테스트 마커 등록
def pytest_configure(config):
    """pytest 설정"""
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "kubernetes: mark test as requiring kubernetes")


# 테스트 결과 요약
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """테스트 결과 요약 출력"""
    print("\n" + "=" * 50)
    print("WDRF Controller Test Summary")
    print("=" * 50)

    # 테스트 통계
    stats = terminalreporter.stats
    if "passed" in stats:
        print(f"✅ Passed: {len(stats['passed'])}")
    if "failed" in stats:
        print(f"❌ Failed: {len(stats['failed'])}")
    if "skipped" in stats:
        print(f"⏭️  Skipped: {len(stats['skipped'])}")

    print("=" * 50)
