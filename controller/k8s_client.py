"""
Kubernetes Client for WDRF Controller
Kubernetes API와 상호작용하여 Kueue Workload를 관리합니다.
"""

import logging
from typing import List, Dict, Any, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config import kube_config
import yaml

from .config import Config

logger = logging.getLogger(__name__)


class KubernetesClient:
    """Kubernetes API 클라이언트"""

    def __init__(self):
        """Kubernetes 클라이언트를 초기화합니다."""
        self._init_kubernetes_client()
        self._init_kueue_client()

    def _init_kubernetes_client(self):
        """Kubernetes 클라이언트를 초기화합니다."""
        try:
            if Config.KUBECONFIG_PATH:
                config.load_kube_config(Config.KUBECONFIG_PATH)
                logger.info(f"Kubernetes config loaded from {Config.KUBECONFIG_PATH}")
            else:
                config.load_incluster_config()
                logger.info("Kubernetes config loaded from in-cluster")

            self.core_v1 = client.CoreV1Api()
            self.custom_objects = client.CustomObjectsApi()
            self.scheduling_v1 = client.SchedulingV1Api()
            logger.info("Kubernetes client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise

    def _init_kueue_client(self):
        """Kueue API 클라이언트를 초기화합니다."""
        self.kueue_api_group = Config.KUEUE_API_GROUP
        self.workload_kind = Config.WORKLOAD_KIND

    def get_nodes(self) -> List[Dict[str, Any]]:
        """클러스터의 모든 노드를 조회합니다."""
        try:
            nodes = self.core_v1.list_node()
            return [
                {
                    "name": node.metadata.name,
                    "labels": node.metadata.labels or {},
                    "capacity": node.status.capacity,
                    "allocatable": node.status.allocatable,
                    "conditions": [
                        {"type": condition.type, "status": condition.status}
                        for condition in node.status.conditions
                    ],
                }
                for node in nodes.items
            ]
        except ApiException as e:
            logger.error(f"Failed to get nodes: {e}")
            return []

    def get_pending_workloads(
        self, namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Pending 상태의 Kueue Workload를 조회합니다."""
        try:
            workloads = self.custom_objects.list_cluster_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                plural="workloads",
                field_selector="status.conditions[0].type=Pending",
            )

            pending_workloads = []
            for workload in workloads.get("items", []):
                if self._is_workload_pending(workload):
                    pending_workloads.append(workload)

            logger.info(f"Found {len(pending_workloads)} pending workloads")
            return pending_workloads

        except ApiException as e:
            logger.error(f"Failed to get pending workloads: {e}")
            return []

    def _is_workload_pending(self, workload: Dict[str, Any]) -> bool:
        """Workload가 Pending 상태인지 확인합니다."""
        conditions = workload.get("status", {}).get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "Pending" and condition.get("status") == "True":
                return True
        return False

    def create_priority_class(self, name: str, value: int, description: str) -> bool:
        """Kueue Priority Class를 생성합니다."""
        try:
            priority_class = {
                "apiVersion": "scheduling.k8s.io/v1",
                "kind": "PriorityClass",
                "metadata": {
                    "name": name,
                    "annotations": {
                        "wdrf.x-k8s.io/managed": "true",
                        "wdrf.x-k8s.io/description": description,
                    },
                },
                "value": value,
                "globalDefault": False,
                "description": description,
            }

            self.scheduling_v1.create_priority_class(priority_class)
            logger.info(f"Created Priority Class: {name} with value {value}")
            return True

        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.debug(f"Priority Class {name} already exists")
                return True
            else:
                logger.error(f"Failed to create Priority Class {name}: {e}")
                return False

    def ensure_priority_classes(self) -> bool:
        """필요한 Priority Class들이 존재하는지 확인하고 생성합니다."""
        try:
            for class_name, class_config in Config.KUEUE_PRIORITY_CLASSES.items():
                value = int(class_config["value"])
                description = str(class_config["description"])
                success = self.create_priority_class(class_name, value, description)
                if not success:
                    return False

            logger.info("All Priority Classes ensured")
            return True

        except Exception as e:
            logger.error(f"Failed to ensure Priority Classes: {e}")
            return False

    def update_workload_priority_class(
        self, workload_name: str, namespace: str, priority_class_name: str
    ) -> bool:
        """Workload의 Priority Class를 업데이트합니다."""
        try:
            # 현재 Workload 조회
            current_workload = self.custom_objects.get_namespaced_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="workloads",
                name=workload_name,
            )

            # Priority Class 업데이트
            if "metadata" not in current_workload:
                current_workload["metadata"] = {}
            if "annotations" not in current_workload["metadata"]:
                current_workload["metadata"]["annotations"] = {}

            current_workload["metadata"]["annotations"][
                "wdrf.x-k8s.io/priority-class"
            ] = priority_class_name
            current_workload["metadata"]["annotations"][
                "wdrf.x-k8s.io/priority-updated"
            ] = "true"

            # Workload 업데이트
            self.custom_objects.patch_namespaced_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="workloads",
                name=workload_name,
                body=current_workload,
            )

            logger.info(
                f"Updated Priority Class for workload {workload_name} to {priority_class_name}"
            )
            return True

        except ApiException as e:
            logger.error(f"Failed to update workload priority class: {e}")
            return False

    def get_gang_scheduling_workloads(self) -> List[Dict[str, Any]]:
        """Gang Scheduling이 필요한 Workload들을 조회합니다."""
        try:
            workloads = self.custom_objects.list_cluster_custom_object(
                group="kueue.x-k8s.io", version="v1beta1", plural="workloads"
            )

            gang_workloads = []
            for workload in workloads.get("items", []):
                if self._is_gang_scheduling_workload(workload):
                    gang_workloads.append(workload)

            logger.info(f"Found {len(gang_workloads)} gang scheduling workloads")
            return gang_workloads

        except ApiException as e:
            logger.error(f"Failed to get gang scheduling workloads: {e}")
            return []

    def _is_gang_scheduling_workload(self, workload: Dict[str, Any]) -> bool:
        """Workload가 Gang Scheduling을 사용하는지 확인합니다."""
        try:
            pod_sets = workload.get("spec", {}).get("podSets", [])

            for pod_set in pod_sets:
                template = pod_set.get("template", {})
                labels = template.get("metadata", {}).get("labels", {})
                annotations = template.get("metadata", {}).get("annotations", {})

                # Pod Group 정보 확인
                if labels.get("kueue.x-k8s.io/pod-group-name") and annotations.get(
                    "kueue.x-k8s.io/pod-group-total-count"
                ):
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to check gang scheduling: {e}")
            return False

    def get_workloads_by_pod_group(self, pod_group_name: str) -> List[Dict[str, Any]]:
        """특정 Pod Group에 속한 Workload들을 조회합니다."""
        try:
            workloads = self.custom_objects.list_cluster_custom_object(
                group="kueue.x-k8s.io", version="v1beta1", plural="workloads"
            )

            group_workloads = []
            for workload in workloads.get("items", []):
                if self._workload_belongs_to_pod_group(workload, pod_group_name):
                    group_workloads.append(workload)

            return group_workloads

        except ApiException as e:
            logger.error(f"Failed to get workloads by pod group: {e}")
            return []

    def _workload_belongs_to_pod_group(
        self, workload: Dict[str, Any], pod_group_name: str
    ) -> bool:
        """Workload가 특정 Pod Group에 속하는지 확인합니다."""
        try:
            pod_sets = workload.get("spec", {}).get("podSets", [])

            for pod_set in pod_sets:
                template = pod_set.get("template", {})
                labels = template.get("metadata", {}).get("labels", {})

                if labels.get("kueue.x-k8s.io/pod-group-name") == pod_group_name:
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to check pod group membership: {e}")
            return False

    def update_workload_priority(
        self, workload_name: str, namespace: str, priority: int
    ) -> bool:
        """Workload의 우선순위를 업데이트합니다."""
        try:
            # 현재 Workload 조회
            current_workload = self.custom_objects.get_namespaced_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="workloads",
                name=workload_name,
            )

            # 우선순위 업데이트
            if "metadata" not in current_workload:
                current_workload["metadata"] = {}
            if "annotations" not in current_workload["metadata"]:
                current_workload["metadata"]["annotations"] = {}

            current_workload["metadata"]["annotations"]["wdrf.x-k8s.io/priority"] = str(
                priority
            )
            current_workload["metadata"]["annotations"][
                "wdrf.x-k8s.io/priority-updated"
            ] = "true"

            # Workload 업데이트
            self.custom_objects.patch_namespaced_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="workloads",
                name=workload_name,
                body=current_workload,
            )

            logger.info(f"Updated priority for workload {workload_name} to {priority}")
            return True

        except ApiException as e:
            logger.error(f"Failed to update workload priority: {e}")
            return False

    def get_cluster_queues(self) -> List[Dict[str, Any]]:
        """모든 ClusterQueue를 조회합니다."""
        try:
            cluster_queues = self.custom_objects.list_cluster_custom_object(
                group="kueue.x-k8s.io", version="v1beta1", plural="clusterqueues"
            )

            return cluster_queues.get("items", [])

        except ApiException as e:
            logger.error(f"Failed to get cluster queues: {e}")
            return []

    def get_local_queues(self, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """LocalQueue를 조회합니다."""
        try:
            if namespace:
                local_queues = self.custom_objects.list_namespaced_custom_object(
                    group="kueue.x-k8s.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="localqueues",
                )
            else:
                local_queues = self.custom_objects.list_cluster_custom_object(
                    group="kueue.x-k8s.io", version="v1beta1", plural="localqueues"
                )

            return local_queues.get("items", [])

        except ApiException as e:
            logger.error(f"Failed to get local queues: {e}")
            return []

    def get_pods_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """특정 네임스페이스의 모든 Pod를 조회합니다."""
        try:
            pods = self.core_v1.list_namespaced_pod(namespace=namespace)
            return [
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "labels": pod.metadata.labels or {},
                    "annotations": pod.metadata.annotations or {},
                    "status": pod.status.phase,
                    "resources": self._extract_pod_resources(pod),
                }
                for pod in pods.items
            ]
        except ApiException as e:
            logger.error(f"Failed to get pods in namespace {namespace}: {e}")
            return []

    def _extract_pod_resources(self, pod) -> Dict[str, Any]:
        """Pod의 리소스 요청사항을 추출합니다."""
        resources = {}

        for container in pod.spec.containers:
            if container.resources:
                if container.resources.requests:
                    for resource_name, quantity in container.resources.requests.items():
                        if resource_name not in resources:
                            resources[resource_name] = 0.0
                        resources[resource_name] += self._parse_quantity(quantity)

                if container.resources.limits:
                    for resource_name, quantity in container.resources.limits.items():
                        if resource_name not in resources:
                            resources[resource_name] = 0.0
                        resources[resource_name] += self._parse_quantity(quantity)

        return resources

    def _parse_quantity(self, quantity) -> float:
        """Kubernetes Quantity를 float로 변환합니다."""
        if quantity is None:
            return 0.0

        # 간단한 파싱 (실제로는 더 복잡한 로직이 필요할 수 있음)
        quantity_str = str(quantity)

        if quantity_str.endswith("m"):  # millicores
            return float(quantity_str[:-1]) / 1000
        elif quantity_str.endswith("Ki"):
            return float(quantity_str[:-2]) * 1024
        elif quantity_str.endswith("Mi"):
            return float(quantity_str[:-2]) * 1024 * 1024
        elif quantity_str.endswith("Gi"):
            return float(quantity_str[:-2]) * 1024 * 1024 * 1024
        else:
            try:
                return float(quantity_str)
            except ValueError:
                return 0.0

    def get_workload_pods(self, workload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Workload에 속한 Pod들을 조회합니다."""
        try:
            namespace = workload["metadata"]["namespace"]
            workload_name = workload["metadata"]["name"]

            # Workload의 Pod들을 조회
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"kueue.x-k8s.io/workload-name={workload_name}",
            )

            return [
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "resources": self._extract_pod_resources(pod),
                }
                for pod in pods.items
            ]

        except ApiException as e:
            logger.error(f"Failed to get workload pods: {e}")
            return []

    def get_cluster_nodes(self) -> list:
        # 실제 구현이 없다면 빈 리스트 반환
        return []

    def get_cluster_info(self) -> dict:
        # 실제 구현이 없다면 빈 딕셔너리 반환
        return {}

    def get_priority_class(self, name: str) -> Optional[dict]:
        return None

    def get_priority_class_value(self, name: str) -> Optional[int]:
        return None

    def get_priority_class_names(self) -> list:
        return []

    def get_priority_class_map(self) -> dict:
        return {}

    def get_priority_class_values(self) -> list:
        return []

    def get_priority_class_descriptions(self) -> list:
        return []

    def get_priority_class_objects(self) -> list:
        return []

    def get_priority_class_object(self, name: str) -> Optional[dict]:
        return None

    def get_priority_class_object_by_value(self, value: int) -> Optional[dict]:
        return None

    def get_priority_class_object_by_description(
        self, description: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_name(self, name: str) -> Optional[dict]:
        return None

    def get_priority_class_object_by_value_and_description(
        self, value: int, description: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_name_and_value(
        self, name: str, value: int
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_name_and_description(
        self, name: str, description: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_name_value_and_description(
        self, name: str, value: int, description: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_value_and_name(
        self, value: int, name: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_description_and_value(
        self, description: str, value: int
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_description_and_name(
        self, description: str, name: str
    ) -> Optional[dict]:
        return None

    def get_priority_class_object_by_description_name_and_value(
        self, description: str, name: str, value: int
    ) -> Optional[dict]:
        return None
