"""
Priority Calculator for WDRF Controller
Workload의 우선순위를 계산하는 모듈입니다.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from .config import Config

logger = logging.getLogger(__name__)


class PriorityTier(Enum):
    """우선순위 계층을 정의합니다 (2개로 변경)."""

    HIGH = "high"
    NORMAL = "normal"


@dataclass
class WorkloadPriority:
    """Workload 우선순위 정보를 담는 데이터 클래스"""

    workload_name: str
    namespace: str
    priority_tier: PriorityTier
    dominant_share: float
    aging_factor: float
    final_priority: float
    resources: Dict[str, float]
    creation_time: float
    waiting_time: float
    priority_class_name: str
    is_gang_scheduling: bool
    pod_group_name: str
    pod_group_total_count: int
    pod_group_current_count: int


class PriorityCalculator:
    """우선순위 계산을 담당하는 클래스"""

    def __init__(self, resource_view):
        """PriorityCalculator를 초기화합니다."""
        self.resource_view = resource_view

    def calculate_workload_priority(self, workload: Dict[str, Any]) -> WorkloadPriority:
        """Workload의 우선순위를 계산합니다."""
        try:
            # 기본 정보 추출
            workload_name = workload["metadata"]["name"]
            namespace = workload["metadata"]["namespace"]
            creation_time = self._get_creation_time(workload)
            waiting_time = time.time() - creation_time

            # 리소스 요구사항 추출
            resources = self._extract_workload_resources(workload)

            # 우선순위 계층 결정
            priority_tier = self._determine_priority_tier(workload)

            # Dominant Share 계산
            dominant_share = self.resource_view.get_workload_dominant_share(resources)

            # Aging Factor 계산
            aging_factor = self._calculate_aging_factor(waiting_time)

            # Gang Scheduling 정보 추출
            gang_info = self._extract_gang_scheduling_info(workload)

            # 최종 우선순위 계산
            final_priority = self._calculate_final_priority(
                priority_tier, dominant_share, aging_factor
            )

            # Priority Class 이름 생성
            priority_class_name = Config.get_priority_class_name(priority_tier.value)

            return WorkloadPriority(
                workload_name=workload_name,
                namespace=namespace,
                priority_tier=priority_tier,
                dominant_share=dominant_share,
                aging_factor=aging_factor,
                final_priority=final_priority,
                resources=resources,
                creation_time=creation_time,
                waiting_time=waiting_time,
                priority_class_name=priority_class_name,
                is_gang_scheduling=gang_info["is_gang_scheduling"],
                pod_group_name=gang_info["pod_group_name"],
                pod_group_total_count=gang_info["pod_group_total_count"],
                pod_group_current_count=gang_info["pod_group_current_count"],
            )

        except Exception as e:
            logger.error(
                f"Failed to calculate priority for workload {workload.get('metadata', {}).get('name', 'unknown')}: {e}"
            )
            # 기본값 반환
            return WorkloadPriority(
                workload_name=workload.get("metadata", {}).get("name", "unknown"),
                namespace=workload.get("metadata", {}).get("namespace", "default"),
                priority_tier=PriorityTier.NORMAL,
                dominant_share=1.0,
                aging_factor=0.0,
                final_priority=0.0,
                resources={},
                creation_time=time.time(),
                waiting_time=0.0,
                priority_class_name="wdrf-normal",
                is_gang_scheduling=False,
                pod_group_name="",
                pod_group_total_count=0,
                pod_group_current_count=0,
            )

    def _get_creation_time(self, workload: Dict[str, Any]) -> float:
        """Workload의 생성 시간을 추출합니다."""
        try:
            # creationTimestamp가 있으면 사용
            if "creationTimestamp" in workload["metadata"]:
                import datetime

                creation_str = workload["metadata"]["creationTimestamp"]
                creation_dt = datetime.datetime.fromisoformat(
                    creation_str.replace("Z", "+00:00")
                )
                return creation_dt.timestamp()

            # 없으면 현재 시간 사용
            return time.time()

        except Exception as e:
            logger.warning(f"Failed to parse creation time: {e}")
            return time.time()

    def _extract_workload_resources(self, workload: Dict[str, Any]) -> Dict[str, float]:
        """Workload의 리소스 요구사항을 추출합니다."""
        resources = {}

        try:
            # PodSets에서 리소스 추출
            pod_sets = workload.get("spec", {}).get("podSets", [])

            for pod_set in pod_sets:
                template = pod_set.get("template", {})
                containers = template.get("spec", {}).get("containers", [])

                for container in containers:
                    container_resources = container.get("resources", {})

                    # Requests 처리
                    requests = container_resources.get("requests", {})
                    for resource_name, quantity in requests.items():
                        if resource_name in Config.RESOURCE_WEIGHTS:
                            if resource_name not in resources:
                                resources[resource_name] = 0.0
                            resources[resource_name] += self._parse_quantity(quantity)

                    # Limits 처리
                    limits = container_resources.get("limits", {})
                    for resource_name, quantity in limits.items():
                        if resource_name in Config.RESOURCE_WEIGHTS:
                            if resource_name not in resources:
                                resources[resource_name] = 0.0
                            resources[resource_name] += self._parse_quantity(quantity)

                # Pod 개수만큼 리소스 곱하기
                count = pod_set.get("count", 1)
                for resource_name in resources:
                    resources[resource_name] *= count

            logger.debug(f"Extracted resources for workload: {resources}")
            return resources

        except Exception as e:
            logger.error(f"Failed to extract workload resources: {e}")
            return {}

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

    def _determine_priority_tier(self, workload: Dict[str, Any]) -> PriorityTier:
        """Workload의 우선순위 계층을 결정합니다 (2개 Tier)."""
        annotations = workload.get("metadata", {}).get("annotations", {})

        # 높은 우선순위 조건들
        if (
            annotations.get("wdrf.x-k8s.io/urgent", "false").lower() == "true"
            or annotations.get("wdrf.x-k8s.io/approved", "false").lower() == "true"
            or annotations.get("wdrf.x-k8s.io/high-priority", "false").lower() == "true"
        ):
            return PriorityTier.HIGH

        # 기본값
        return PriorityTier.NORMAL

    def _extract_gang_scheduling_info(self, workload: Dict[str, Any]) -> Dict[str, Any]:
        """Gang Scheduling 정보를 추출합니다."""
        gang_info = {
            "is_gang_scheduling": False,
            "pod_group_name": "",
            "pod_group_total_count": 0,
            "pod_group_current_count": 0,
        }

        try:
            # PodSets에서 Gang Scheduling 정보 추출
            pod_sets = workload.get("spec", {}).get("podSets", [])

            for pod_set in pod_sets:
                template = pod_set.get("template", {})
                labels = template.get("metadata", {}).get("labels", {})
                annotations = template.get("metadata", {}).get("annotations", {})

                # Pod Group 정보 확인
                pod_group_name = labels.get("kueue.x-k8s.io/pod-group-name")
                pod_group_total_count = annotations.get(
                    "kueue.x-k8s.io/pod-group-total-count"
                )

                if pod_group_name and pod_group_total_count:
                    gang_info["is_gang_scheduling"] = True
                    gang_info["pod_group_name"] = pod_group_name
                    gang_info["pod_group_total_count"] = int(pod_group_total_count)
                    gang_info["pod_group_current_count"] = pod_set.get("count", 0)
                    break

            logger.debug(f"Gang scheduling info: {gang_info}")
            return gang_info

        except Exception as e:
            logger.error(f"Failed to extract gang scheduling info: {e}")
            return gang_info

    def _calculate_aging_factor(self, waiting_time: float) -> float:
        """Aging Factor를 계산합니다."""
        if not Config.SCHEDULING_POLICIES["enable_aging"]:
            return 0.0

        # 대기 시간이 최대 aging 시간을 초과하지 않도록 제한
        capped_waiting_time = min(waiting_time, Config.MAX_AGING_TIME)

        # Aging 계수를 적용하여 factor 계산
        aging_factor = capped_waiting_time * Config.AGING_COEFFICIENT

        logger.debug(
            f"Aging factor calculated: {aging_factor} (waiting time: {waiting_time}s)"
        )
        return aging_factor

    def _calculate_final_priority(
        self, priority_tier: PriorityTier, dominant_share: float, aging_factor: float
    ) -> float:
        # 중요도(Tier)별로 Priority Class를 이미 부여
        # 동일 Tier 내에서는 dominant_share - aging_factor가 작을수록 우선
        return dominant_share - aging_factor

    def sort_workloads_by_priority(
        self, workloads: List[Dict[str, Any]]
    ) -> List[WorkloadPriority]:
        workload_priorities = []
        for workload in workloads:
            priority = self.calculate_workload_priority(workload)
            workload_priorities.append(priority)
        # 중요도(Tier) 우선, 동일 Tier 내에서는 dominant_share - aging_factor 오름차순
        workload_priorities.sort(
            key=lambda x: (x.priority_tier.value, x.final_priority)
        )
        logger.info(f"Sorted {len(workload_priorities)} workloads by priority")
        return workload_priorities

    def get_priority_summary(
        self, workload_priorities: List[WorkloadPriority]
    ) -> Dict[str, Any]:
        """우선순위 계산 결과 요약을 반환합니다."""
        if not workload_priorities:
            return {
                "total_workloads": 0,
                "priority_distribution": {},
                "average_waiting_time": 0.0,
                "average_dominant_share": 0.0,
                "gang_scheduling_count": 0,
            }

        # 우선순위 계층별 분포
        tier_distribution = {}
        for tier in PriorityTier:
            tier_distribution[tier.value] = len(
                [wp for wp in workload_priorities if wp.priority_tier == tier]
            )

        # 평균 대기 시간
        total_waiting_time = sum(wp.waiting_time for wp in workload_priorities)
        average_waiting_time = total_waiting_time / len(workload_priorities)

        # 평균 Dominant Share
        total_dominant_share = sum(wp.dominant_share for wp in workload_priorities)
        average_dominant_share = total_dominant_share / len(workload_priorities)

        # Gang Scheduling 개수
        gang_scheduling_count = len(
            [wp for wp in workload_priorities if wp.is_gang_scheduling]
        )

        return {
            "total_workloads": len(workload_priorities),
            "priority_distribution": tier_distribution,
            "average_waiting_time": average_waiting_time,
            "average_dominant_share": average_dominant_share,
            "highest_priority": max(wp.final_priority for wp in workload_priorities),
            "lowest_priority": min(wp.final_priority for wp in workload_priorities),
            "gang_scheduling_count": gang_scheduling_count,
        }

    def should_override_priority(self, workload: Dict[str, Any]) -> bool:
        """우선순위 오버라이드가 필요한지 확인합니다."""
        annotations = workload.get("metadata", {}).get("annotations", {})
        override_value = annotations.get(
            "wdrf.x-k8s.io/priority-override", "false"
        ).lower()
        return override_value == "true"

    def get_manual_priority(self, workload: Dict[str, Any]) -> int:
        """수동으로 설정된 우선순위를 가져옵니다."""
        annotations = workload.get("metadata", {}).get("annotations", {})
        try:
            return int(annotations.get("wdrf.x-k8s.io/manual-priority", "0"))
        except (ValueError, TypeError):
            return 0
