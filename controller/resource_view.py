"""
Resource View Module for WDRF Controller
노드의 용량과 사용량을 계산하여 클러스터 리소스 상태를 파악합니다.
"""

import logging
from typing import Dict, List, Any, Tuple
from collections import defaultdict

from .config import Config

logger = logging.getLogger(__name__)


class ResourceView:
    """클러스터 리소스 상태를 관리하는 클래스"""

    def __init__(self, k8s_client):
        """ResourceView를 초기화합니다."""
        self.k8s_client = k8s_client
        self._cluster_capacity = {}
        self._cluster_usage = {}
        self._node_info = {}

    def refresh_cluster_state(self):
        """클러스터 상태를 새로고침합니다."""
        try:
            nodes = self.k8s_client.get_nodes()
            self._update_cluster_capacity(nodes)
            self._update_cluster_usage()
            logger.info("Cluster state refreshed successfully")
        except Exception as e:
            logger.error(f"Failed to refresh cluster state: {e}")

    def _update_cluster_capacity(self, nodes: List[Dict[str, Any]]):
        """클러스터 전체 용량을 업데이트합니다."""
        self._cluster_capacity = defaultdict(float)
        self._node_info = {}

        for node in nodes:
            node_name = node["name"]
            allocatable = node["allocatable"]

            # 노드 정보 저장
            self._node_info[node_name] = {
                "capacity": node["capacity"],
                "allocatable": allocatable,
                "labels": node["labels"],
                "conditions": node["conditions"],
            }

            # 클러스터 전체 용량 계산
            for resource_name, quantity in allocatable.items():
                if resource_name in Config.RESOURCE_WEIGHTS:
                    try:
                        value = self._parse_quantity(quantity)
                        self._cluster_capacity[resource_name] += value
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Failed to parse quantity for {resource_name}: {quantity}"
                        )

        logger.info(f"Cluster capacity updated: {dict(self._cluster_capacity)}")

    def _update_cluster_usage(self):
        """클러스터 사용량을 업데이트합니다."""
        self._cluster_usage = defaultdict(float)

        # 모든 네임스페이스의 Pod들을 조회하여 사용량 계산
        # 실제 구현에서는 더 효율적인 방법을 사용할 수 있습니다
        try:
            # 주요 네임스페이스들만 조회 (성능 최적화)
            target_namespaces = ["kueue-system", "default", "team-mlops"]

            for namespace in target_namespaces:
                pods = self.k8s_client.get_pods_in_namespace(namespace)
                for pod in pods:
                    if pod["status"] in ["Running", "Pending"]:
                        for resource_name, amount in pod["resources"].items():
                            if resource_name in Config.RESOURCE_WEIGHTS:
                                self._cluster_usage[resource_name] += amount

            logger.info(f"Cluster usage updated: {dict(self._cluster_usage)}")

        except Exception as e:
            logger.error(f"Failed to update cluster usage: {e}")

    def _parse_quantity(self, quantity) -> float:
        """Kubernetes Quantity를 float로 변환합니다."""
        if quantity is None:
            return 0.0

        quantity_str = str(quantity)

        if quantity_str.endswith("m"):  # millicores
            return float(quantity_str[:-1]) / 1000
        elif quantity_str.endswith("Ki"):
            return float(quantity_str[:-2]) * 1024
        elif quantity_str.endswith("Mi"):
            return float(quantity_str[:-2]) * 1024 * 1024
        elif quantity_str.endswith("Gi"):
            return float(quantity_str[:-2]) * 1024 * 1024 * 1024
        elif quantity_str.endswith("Ti"):
            return float(quantity_str[:-2]) * 1024 * 1024 * 1024 * 1024
        else:
            try:
                return float(quantity_str)
            except ValueError:
                return 0.0

    def get_cluster_capacity(self) -> Dict[str, float]:
        """클러스터 전체 용량을 반환합니다."""
        return dict(self._cluster_capacity)

    def get_cluster_usage(self) -> Dict[str, float]:
        """클러스터 전체 사용량을 반환합니다."""
        return dict(self._cluster_usage)

    def get_cluster_utilization(self) -> Dict[str, float]:
        """클러스터 전체 사용률을 반환합니다."""
        utilization = {}

        for resource_name in self._cluster_capacity:
            capacity = self._cluster_capacity[resource_name]
            usage = self._cluster_usage.get(resource_name, 0.0)

            if capacity > 0:
                utilization[resource_name] = (usage / capacity) * 100
            else:
                utilization[resource_name] = 0.0

        return utilization

    def get_available_resources(self) -> Dict[str, float]:
        """사용 가능한 리소스를 반환합니다."""
        available = {}

        for resource_name in self._cluster_capacity:
            capacity = self._cluster_capacity[resource_name]
            usage = self._cluster_usage.get(resource_name, 0.0)
            available[resource_name] = max(0.0, capacity - usage)

        return available

    def can_schedule_workload(self, workload_resources: Dict[str, float]) -> bool:
        """Workload가 스케줄링 가능한지 확인합니다."""
        available = self.get_available_resources()

        for resource_name, required in workload_resources.items():
            if resource_name in Config.RESOURCE_WEIGHTS:
                if available.get(resource_name, 0.0) < required:
                    logger.debug(
                        f"Cannot schedule workload: insufficient {resource_name}"
                    )
                    return False

        return True

    def get_workload_dominant_share(
        self, workload_resources: Dict[str, float]
    ) -> float:
        """Workload의 Dominant Share를 계산합니다."""
        if not workload_resources:
            return 0.0

        dominant_share = 0.0

        for resource_name, amount in workload_resources.items():
            if resource_name in self._cluster_capacity:
                capacity = self._cluster_capacity[resource_name]
                if capacity > 0:
                    share = amount / capacity
                    dominant_share = max(dominant_share, share)

        return dominant_share

    def get_node_info(self, node_name: str) -> Dict[str, Any]:
        """특정 노드의 정보를 반환합니다."""
        return self._node_info.get(node_name, {})

    def get_gpu_nodes(self) -> List[str]:
        """GPU가 있는 노드 목록을 반환합니다."""
        gpu_nodes = []

        for node_name, node_info in self._node_info.items():
            allocatable = node_info.get("allocatable", {})
            if "nvidia.com/gpu" in allocatable:
                gpu_count = self._parse_quantity(allocatable["nvidia.com/gpu"])
                if gpu_count > 0:
                    gpu_nodes.append(node_name)

        return gpu_nodes

    def get_gpu_capacity(self) -> Dict[str, Dict[str, float]]:
        """GPU 노드별 용량 정보를 반환합니다."""
        gpu_capacity = {}

        for node_name, node_info in self._node_info.items():
            allocatable = node_info.get("allocatable", {})

            if "nvidia.com/gpu" in allocatable:
                gpu_count = self._parse_quantity(allocatable["nvidia.com/gpu"])
                if gpu_count > 0:
                    gpu_capacity[node_name] = {
                        "gpu_count": gpu_count,
                        "cpu": self._parse_quantity(allocatable.get("cpu", 0)),
                        "memory": self._parse_quantity(allocatable.get("memory", 0)),
                    }

        return gpu_capacity

    def calculate_resource_efficiency(
        self, workload_resources: Dict[str, float]
    ) -> float:
        """리소스 효율성을 계산합니다 (낮을수록 효율적)."""
        if not workload_resources:
            return 0.0

        total_weighted_usage = 0.0
        total_weight = 0.0

        for resource_name, amount in workload_resources.items():
            if resource_name in Config.RESOURCE_WEIGHTS:
                weight = Config.get_resource_weight(resource_name)
                total_weighted_usage += amount * weight
                total_weight += weight

        if total_weight == 0:
            return 0.0

        return total_weighted_usage / total_weight

    def get_cluster_summary(self) -> Dict[str, Any]:
        """클러스터 상태 요약을 반환합니다."""
        capacity = self.get_cluster_capacity()
        usage = self.get_cluster_usage()
        utilization = self.get_cluster_utilization()
        available = self.get_available_resources()

        return {
            "capacity": capacity,
            "usage": usage,
            "utilization": utilization,
            "available": available,
            "gpu_nodes": self.get_gpu_nodes(),
            "total_nodes": len(self._node_info),
        }
