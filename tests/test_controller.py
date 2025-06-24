"""
WDRF Controller 테스트 스크립트
컨트롤러의 주요 기능을 테스트합니다.
"""

import unittest
import time
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from controller.config import Config
from controller.priority import PriorityCalculator, PriorityTier, WorkloadPriority
from controller.resource_view import ResourceView
from controller.k8s_client import KubernetesClient

class TestConfig(unittest.TestCase):
    """설정 테스트"""
    
    def test_priority_weights(self):
        """우선순위 가중치 테스트"""
        self.assertEqual(Config.get_priority_weight("urgent"), 1000)
        self.assertEqual(Config.get_priority_weight("approved"), 100)
        self.assertEqual(Config.get_priority_weight("normal"), 1)
        self.assertEqual(Config.get_priority_weight("unknown"), 1)  # 기본값
    
    def test_resource_weights(self):
        """리소스 가중치 테스트"""
        self.assertEqual(Config.get_resource_weight("cpu"), 1.0)
        self.assertEqual(Config.get_resource_weight("nvidia.com/gpu"), 10.0)
        self.assertEqual(Config.get_resource_weight("unknown"), 1.0)  # 기본값

class TestPriorityCalculator(unittest.TestCase):
    """우선순위 계산기 테스트"""
    
    def setUp(self):
        """테스트 설정"""
        self.mock_resource_view = Mock()
        self.mock_resource_view.get_workload_dominant_share.return_value = 0.5
        self.calculator = PriorityCalculator(self.mock_resource_view)
    
    def test_determine_priority_tier(self):
        """우선순위 계층 결정 테스트"""
        # 긴급 우선순위
        workload_urgent = {
            "metadata": {
                "annotations": {
                    "wdrf.x-k8s.io/urgent": "true"
                }
            }
        }
        tier = self.calculator._determine_priority_tier(workload_urgent)
        self.assertEqual(tier, PriorityTier.URGENT)
        
        # 승인된 우선순위
        workload_approved = {
            "metadata": {
                "annotations": {
                    "wdrf.x-k8s.io/approved": "true"
                }
            }
        }
        tier = self.calculator._determine_priority_tier(workload_approved)
        self.assertEqual(tier, PriorityTier.APPROVED)
        
        # 일반 우선순위
        workload_normal = {
            "metadata": {
                "annotations": {}
            }
        }
        tier = self.calculator._determine_priority_tier(workload_normal)
        self.assertEqual(tier, PriorityTier.NORMAL)
    
    def test_calculate_aging_factor(self):
        """Aging Factor 계산 테스트"""
        # Aging 비활성화
        with patch.object(Config.SCHEDULING_POLICIES, 'get', return_value=False):
            factor = self.calculator._calculate_aging_factor(100)
            self.assertEqual(factor, 0.0)
        
        # Aging 활성화
        with patch.object(Config.SCHEDULING_POLICIES, 'get', return_value=True):
            factor = self.calculator._calculate_aging_factor(100)
            expected = 100 * Config.AGING_COEFFICIENT
            self.assertEqual(factor, expected)
        
        # 최대 Aging 시간 제한
        with patch.object(Config.SCHEDULING_POLICIES, 'get', return_value=True):
            factor = self.calculator._calculate_aging_factor(10000)  # 매우 긴 대기 시간
            expected = Config.MAX_AGING_TIME * Config.AGING_COEFFICIENT
            self.assertEqual(factor, expected)
    
    def test_calculate_final_priority(self):
        """최종 우선순위 계산 테스트"""
        # 긴급 우선순위
        priority = self.calculator._calculate_final_priority(
            PriorityTier.URGENT, 0.5, 10.0
        )
        self.assertGreater(priority, 0)
        
        # 일반 우선순위
        priority = self.calculator._calculate_final_priority(
            PriorityTier.NORMAL, 0.5, 10.0
        )
        self.assertGreater(priority, 0)
        
        # Aging이 높은 경우 우선순위 증가
        priority_with_aging = self.calculator._calculate_final_priority(
            PriorityTier.NORMAL, 0.5, 100.0
        )
        priority_without_aging = self.calculator._calculate_final_priority(
            PriorityTier.NORMAL, 0.5, 0.0
        )
        self.assertGreater(priority_with_aging, priority_without_aging)
    
    def test_extract_workload_resources(self):
        """Workload 리소스 추출 테스트"""
        workload = {
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
                                                "cpu": "4",
                                                "memory": "8Gi",
                                                "nvidia.com/gpu": "1"
                                            },
                                            "limits": {
                                                "nvidia.com/gpu": "1"
                                            }
                                        }
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        }
        
        resources = self.calculator._extract_workload_resources(workload)
        
        # Pod 개수만큼 곱해져야 함
        self.assertEqual(resources["cpu"], 8.0)  # 4 * 2
        self.assertEqual(resources["memory"], 8589934592.0)  # 8Gi * 2
        self.assertEqual(resources["nvidia.com/gpu"], 2.0)  # 1 * 2

class TestResourceView(unittest.TestCase):
    """리소스 뷰 테스트"""
    
    def setUp(self):
        """테스트 설정"""
        self.mock_k8s_client = Mock()
        self.resource_view = ResourceView(self.mock_k8s_client)
    
    def test_parse_quantity(self):
        """Quantity 파싱 테스트"""
        # CPU (millicores)
        self.assertEqual(self.resource_view._parse_quantity("1000m"), 1.0)
        self.assertEqual(self.resource_view._parse_quantity("500m"), 0.5)
        
        # 메모리
        self.assertEqual(self.resource_view._parse_quantity("1Ki"), 1024.0)
        self.assertEqual(self.resource_view._parse_quantity("1Mi"), 1048576.0)
        self.assertEqual(self.resource_view._parse_quantity("1Gi"), 1073741824.0)
        
        # GPU (정수)
        self.assertEqual(self.resource_view._parse_quantity("4"), 4.0)
        
        # None 값
        self.assertEqual(self.resource_view._parse_quantity(None), 0.0)
    
    def test_get_workload_dominant_share(self):
        """Dominant Share 계산 테스트"""
        # 클러스터 용량 설정
        self.resource_view._cluster_capacity = {
            "cpu": 100.0,
            "memory": 1000.0,
            "nvidia.com/gpu": 10.0
        }
        
        # Workload 리소스
        workload_resources = {
            "cpu": 50.0,      # 50%
            "memory": 200.0,  # 20%
            "nvidia.com/gpu": 8.0  # 80%
        }
        
        dominant_share = self.resource_view.get_workload_dominant_share(workload_resources)
        self.assertEqual(dominant_share, 0.8)  # GPU가 dominant resource
    
    def test_can_schedule_workload(self):
        """스케줄링 가능성 테스트"""
        # 사용 가능한 리소스 설정
        self.resource_view._cluster_capacity = {
            "cpu": 100.0,
            "nvidia.com/gpu": 10.0
        }
        self.resource_view._cluster_usage = {
            "cpu": 50.0,
            "nvidia.com/gpu": 5.0
        }
        
        # 스케줄링 가능한 Workload
        schedulable_workload = {
            "cpu": 30.0,
            "nvidia.com/gpu": 3.0
        }
        self.assertTrue(self.resource_view.can_schedule_workload(schedulable_workload))
        
        # 스케줄링 불가능한 Workload
        unschedulable_workload = {
            "cpu": 100.0,  # 용량 초과
            "nvidia.com/gpu": 3.0
        }
        self.assertFalse(self.resource_view.can_schedule_workload(unschedulable_workload))

class TestKubernetesClient(unittest.TestCase):
    """Kubernetes 클라이언트 테스트"""
    
    def setUp(self):
        """테스트 설정"""
        with patch('controller.k8s_client.config') as mock_config:
            with patch('controller.k8s_client.client') as mock_client:
                self.client = KubernetesClient()
    
    def test_is_workload_pending(self):
        """Workload Pending 상태 확인 테스트"""
        # Pending 상태
        pending_workload = {
            "status": {
                "conditions": [
                    {
                        "type": "Pending",
                        "status": "True"
                    }
                ]
            }
        }
        self.assertTrue(self.client._is_workload_pending(pending_workload))
        
        # Non-Pending 상태
        non_pending_workload = {
            "status": {
                "conditions": [
                    {
                        "type": "Admitted",
                        "status": "True"
                    }
                ]
            }
        }
        self.assertFalse(self.client._is_workload_pending(non_pending_workload))

def run_tests():
    """테스트 실행"""
    # 테스트 스위트 생성
    test_suite = unittest.TestSuite()
    
    # 테스트 클래스들 추가
    test_suite.addTest(unittest.makeSuite(TestConfig))
    test_suite.addTest(unittest.makeSuite(TestPriorityCalculator))
    test_suite.addTest(unittest.makeSuite(TestResourceView))
    test_suite.addTest(unittest.makeSuite(TestKubernetesClient))
    
    # 테스트 실행
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1) 