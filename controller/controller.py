"""
Main Controller for WDRF Controller
전체 Workload를 순회하고 우선순위를 업데이트하는 메인 컨트롤러입니다.
"""

import logging
import time
import signal
import sys
from typing import Dict, List, Any
from datetime import datetime

from .config import Config
from .k8s_client import KubernetesClient
from .resource_view import ResourceView
from .priority import PriorityCalculator, WorkloadPriority

logger = logging.getLogger(__name__)


class WDRFController:
    """WDRF (Weighted Dominant Resource Fairness) Controller"""

    def __init__(self):
        """WDRF Controller를 초기화합니다."""
        self.running = False
        self.k8s_client = None
        self.resource_view = None
        self.priority_calculator = None

        # 통계 정보
        self.stats = {
            "total_cycles": 0,
            "total_workloads_processed": 0,
            "total_priority_updates": 0,
            "total_priority_class_updates": 0,
            "total_gang_scheduling_processed": 0,
            "last_cycle_time": 0,
            "start_time": time.time(),
        }

        # 시그널 핸들러 설정
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def initialize(self):
        """컨트롤러를 초기화합니다."""
        try:
            logger.info("Initializing WDRF Controller...")

            # Kubernetes 클라이언트 초기화
            self.k8s_client = KubernetesClient()
            logger.info("Kubernetes client initialized")

            # Priority Class 생성
            if not self.k8s_client.ensure_priority_classes():
                logger.error("Failed to ensure Priority Classes")
                return False
            logger.info("Priority Classes ensured")

            # 리소스 뷰 초기화
            self.resource_view = ResourceView(self.k8s_client)
            logger.info("Resource view initialized")

            # 우선순위 계산기 초기화
            self.priority_calculator = PriorityCalculator(self.resource_view)
            logger.info("Priority calculator initialized")

            # 초기 클러스터 상태 새로고침
            self.resource_view.refresh_cluster_state()
            logger.info("Initial cluster state refreshed")

            logger.info("WDRF Controller initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize WDRF Controller: {e}")
            return False

    def run(self):
        """컨트롤러를 실행합니다."""
        if not self.initialize():
            logger.error("Failed to initialize controller, exiting...")
            return

        self.running = True
        logger.info("WDRF Controller started")

        try:
            while self.running:
                cycle_start_time = time.time()

                try:
                    self._run_cycle()
                    self.stats["total_cycles"] += 1
                    self.stats["last_cycle_time"] = time.time() - cycle_start_time

                    logger.info(
                        f"Cycle {self.stats['total_cycles']} completed in "
                        f"{self.stats['last_cycle_time']:.2f}s"
                    )

                except Exception as e:
                    logger.error(f"Error in cycle {self.stats['total_cycles']}: {e}")

                # 다음 사이클까지 대기
                if self.running:
                    time.sleep(Config.LOOP_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self.shutdown()

    def _run_cycle(self):
        """단일 사이클을 실행합니다."""
        # 1. 클러스터 상태 새로고침
        self.resource_view.refresh_cluster_state()

        # 2. Pending Workload 조회
        pending_workloads = self.k8s_client.get_pending_workloads()

        if not pending_workloads:
            logger.debug("No pending workloads found")
            return

        logger.info(f"Found {len(pending_workloads)} pending workloads")

        # 3. 모든 Pending Workload를 우선순위 산정 기준에 따라 정렬 및 처리
        self._process_regular_workloads(pending_workloads)

        # 4. 통계 업데이트
        self.stats["total_workloads_processed"] += len(pending_workloads)

        # 5. 로그 출력
        self._log_cycle_summary(pending_workloads, [])

    def _process_regular_workloads(self, workloads: List[Dict[str, Any]]):
        """일반 Workload들을 처리합니다."""
        if not workloads:
            return

        # 우선순위 계산 및 정렬
        workload_priorities = self.priority_calculator.sort_workloads_by_priority(
            workloads
        )

        # 우선순위 업데이트
        self._update_workload_priorities(workload_priorities)

    def _update_workload_priorities(self, workload_priorities: List[WorkloadPriority]):
        """Workload 우선순위를 업데이트합니다."""
        updates_count = 0
        priority_class_updates = 0

        for i, workload_priority in enumerate(workload_priorities):
            try:
                # Priority Class 업데이트 (새로운 방식)
                success = self.k8s_client.update_workload_priority_class(
                    workload_priority.workload_name,
                    workload_priority.namespace,
                    workload_priority.priority_class_name,
                )

                if success:
                    priority_class_updates += 1
                    logger.debug(
                        f"Updated Priority Class for {workload_priority.workload_name} "
                        f"to {workload_priority.priority_class_name} (rank: {i+1})"
                    )

                # 기존 우선순위 업데이트 (호환성을 위해 유지)
                priority_value = int(workload_priority.final_priority * 1000)
                success = self.k8s_client.update_workload_priority(
                    workload_priority.workload_name,
                    workload_priority.namespace,
                    priority_value,
                )

                if success:
                    updates_count += 1

            except Exception as e:
                logger.error(
                    f"Error updating priority for {workload_priority.workload_name}: {e}"
                )

        self.stats["total_priority_updates"] += updates_count
        self.stats["total_priority_class_updates"] += priority_class_updates
        logger.info(
            f"Updated priorities for {updates_count}/{len(workload_priorities)} workloads"
        )
        logger.info(
            f"Updated Priority Classes for {priority_class_updates}/{len(workload_priorities)} workloads"
        )

    def _log_cycle_summary(
        self, all_workloads: List[Dict[str, Any]], gang_workloads: List[Dict[str, Any]]
    ):
        """사이클 요약을 로그로 출력합니다."""
        if not all_workloads:
            return

        # 우선순위 요약
        workload_priorities = self.priority_calculator.sort_workloads_by_priority(
            all_workloads
        )
        priority_summary = self.priority_calculator.get_priority_summary(
            workload_priorities
        )

        # 클러스터 상태 요약
        cluster_summary = self.resource_view.get_cluster_summary()

        logger.info("=== Cycle Summary ===")
        logger.info(f"Total workloads processed: {len(all_workloads)}")
        logger.info(f"Gang scheduling workloads: {len(gang_workloads)}")
        logger.info(
            f"Priority distribution: {priority_summary['priority_distribution']}"
        )
        logger.info(
            f"Average waiting time: {priority_summary['average_waiting_time']:.1f}s"
        )
        logger.info(
            f"Average dominant share: {priority_summary['average_dominant_share']:.3f}"
        )

        # GPU 사용률 출력
        gpu_utilization = cluster_summary["utilization"].get("nvidia.com/gpu", 0.0)
        logger.info(f"GPU utilization: {gpu_utilization:.1f}%")

        # 상위 3개 Workload 정보
        if workload_priorities:
            logger.info("Top 3 workloads by priority:")
            for i, wp in enumerate(workload_priorities[:3]):
                logger.info(
                    f"  {i+1}. {wp.workload_name} "
                    f"(priority: {wp.final_priority:.3f}, "
                    f"tier: {wp.priority_tier.value}, "
                    f"waiting: {wp.waiting_time:.1f}s)"
                )

    def get_controller_stats(self) -> Dict[str, Any]:
        """컨트롤러 통계를 반환합니다."""
        uptime = time.time() - self.stats["start_time"]

        return {
            "uptime_seconds": uptime,
            "uptime_formatted": self._format_uptime(uptime),
            "total_cycles": self.stats["total_cycles"],
            "total_workloads_processed": self.stats["total_workloads_processed"],
            "total_priority_updates": self.stats["total_priority_updates"],
            "total_priority_class_updates": self.stats["total_priority_class_updates"],
            "total_gang_scheduling_processed": self.stats[
                "total_gang_scheduling_processed"
            ],
            "last_cycle_time": self.stats["last_cycle_time"],
            "average_cycle_time": (
                (uptime / self.stats["total_cycles"])
                if self.stats["total_cycles"] > 0
                else 0
            ),
            "start_time": datetime.fromtimestamp(self.stats["start_time"]).isoformat(),
            "running": self.running,
        }

    def _format_uptime(self, seconds: float) -> str:
        """업타임을 사람이 읽기 쉬운 형태로 포맷합니다."""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m {secs}s"
        elif hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def shutdown(self):
        """컨트롤러를 종료합니다."""
        logger.info("Shutting down WDRF Controller...")
        self.running = False

        # 최종 통계 출력
        stats = self.get_controller_stats()
        logger.info("=== Final Statistics ===")
        logger.info(f"Total uptime: {stats['uptime_formatted']}")
        logger.info(f"Total cycles: {stats['total_cycles']}")
        logger.info(f"Total workloads processed: {stats['total_workloads_processed']}")
        logger.info(f"Total priority updates: {stats['total_priority_updates']}")
        logger.info(
            f"Total priority class updates: {stats['total_priority_class_updates']}"
        )
        logger.info(
            f"Total gang scheduling processed: {stats['total_gang_scheduling_processed']}"
        )
        logger.info("WDRF Controller shutdown complete")

    def health_check(self) -> Dict[str, Any]:
        """헬스 체크를 수행합니다."""
        try:
            # Kubernetes 연결 확인
            nodes = self.k8s_client.get_nodes()

            # 클러스터 상태 확인
            cluster_summary = self.resource_view.get_cluster_summary()

            # Priority Class 확인
            priority_classes_ok = self.k8s_client.ensure_priority_classes()

            return {
                "status": "healthy" if priority_classes_ok else "degraded",
                "kubernetes_connected": len(nodes) > 0,
                "cluster_nodes": len(nodes),
                "gpu_nodes": len(cluster_summary["gpu_nodes"]),
                "priority_classes_ok": priority_classes_ok,
                "controller_stats": self.get_controller_stats(),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
