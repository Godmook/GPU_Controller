"""
WDRF Controller Configuration
GPU 스케줄링 최적화를 위한 설정값들을 정의합니다.
"""

import os
from typing import Dict, Any

class Config:
    """WDRF Controller 설정 클래스"""
    
    # Kubernetes 관련 설정
    KUBECONFIG_PATH = os.getenv("KUBECONFIG_PATH", "")
    NAMESPACE = os.getenv("NAMESPACE", "kueue-system")
    
    # 컨트롤러 실행 주기 (초)
    LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "30"))
    
    # Aging 관련 설정
    AGING_COEFFICIENT = float(os.getenv("AGING_COEFFICIENT", "0.1"))
    MAX_AGING_TIME = int(os.getenv("MAX_AGING_TIME", "3600"))  # 1시간
    
    # 우선순위 가중치 설정 (2개 Tier로 변경)
    PRIORITY_WEIGHTS = {
        "high": 100,      # 높은 우선순위 (승인된 작업, 긴급 작업)
        "normal": 1       # 일반 우선순위 (기본 작업)
    }
    
    # Kueue Priority Class 설정
    KUEUE_PRIORITY_CLASSES = {
        "wdrf-high": {
            "value": 100,
            "description": "WDRF High Priority Class for approved/urgent workloads"
        },
        "wdrf-normal": {
            "value": 1,
            "description": "WDRF Normal Priority Class for regular workloads"
        }
    }
    
    # 리소스 타입별 가중치 (Dominant Resource 계산용)
    RESOURCE_WEIGHTS = {
        "cpu": 1.0,
        "memory": 1.0,
        "nvidia.com/gpu": 10.0,           # GPU 카드
        "nvidia.com/gpucores": 0.1,       # GPU 코어 (1/100 단위)
        "nvidia.com/gpumem-percentage": 0.1  # GPU 메모리 (1/100 단위)
    }
    
    # Kueue 관련 설정
    KUEUE_API_GROUP = "kueue.x-k8s.io/v1beta1"
    WORKLOAD_KIND = "Workload"
    PRIORITY_CLASS_KIND = "PriorityClass"
    
    # 로깅 설정
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # 스케줄링 정책 설정
    SCHEDULING_POLICIES = {
        "default_node_policy": "binpack",    # 기본 노드 스케줄링 정책
        "default_gpu_policy": "binpack",     # 기본 GPU 스케줄링 정책
        "enable_strict_fifo": False,         # strictFIFO 비활성화
        "enable_aging": True,                # Aging 활성화
        "enable_drf": True,                  # DRF 활성화
        "enable_gang_scheduling": True       # Gang Scheduling 활성화
    }
    
    # Gang Scheduling 설정
    GANG_SCHEDULING = {
        "max_wait_time": 300,  # Gang이 완성될 때까지 최대 대기 시간 (초)
        "min_pod_count": 1,    # 최소 Pod 개수
        "max_pod_count": 100   # 최대 Pod 개수
    }
    
    # GPU 타입별 설정
    GPU_TYPES = {
        "H100-80GB": {
            "memory_gb": 80,
            "cores": 100,
            "priority_weight": 1.0
        },
        "A100-80GB": {
            "memory_gb": 80,
            "cores": 100,
            "priority_weight": 0.8
        },
        "A100-40GB": {
            "memory_gb": 40,
            "cores": 100,
            "priority_weight": 0.6
        }
    }
    
    # 모니터링 설정
    METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
    METRICS_PORT = int(os.getenv("METRICS_PORT", "8080"))
    
    @classmethod
    def get_resource_weight(cls, resource_name: str) -> float:
        """리소스 타입별 가중치를 반환합니다."""
        return cls.RESOURCE_WEIGHTS.get(resource_name, 1.0)
    
    @classmethod
    def get_priority_weight(cls, priority_tier: str) -> int:
        """우선순위 계층별 가중치를 반환합니다."""
        return cls.PRIORITY_WEIGHTS.get(priority_tier, cls.PRIORITY_WEIGHTS["normal"])
    
    @classmethod
    def get_gpu_config(cls, gpu_type: str) -> Dict[str, Any]:
        """GPU 타입별 설정을 반환합니다."""
        return cls.GPU_TYPES.get(gpu_type, cls.GPU_TYPES["A100-40GB"])
    
    @classmethod
    def get_priority_class_name(cls, tier: str) -> str:
        """Tier에 해당하는 Priority Class 이름을 반환합니다."""
        return f"wdrf-{tier}"
    
    @classmethod
    def get_priority_class_value(cls, tier: str) -> int:
        """Tier에 해당하는 Priority Class 값을 반환합니다."""
        return cls.KUEUE_PRIORITY_CLASSES.get(f"wdrf-{tier}", {}).get("value", 1)
