"""
Main Entry Point for WDRF Controller
WDRF Controller의 메인 엔트리포인트입니다.
"""

import logging
import sys
import argparse
from pathlib import Path

from .controller import WDRFController
from .config import Config

def setup_logging(log_level: str = None):
    """로깅을 설정합니다."""
    if log_level is None:
        log_level = Config.LOG_LEVEL
    
    # 로그 레벨 설정
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    
    # 로그 포맷 설정
    logging.basicConfig(
        level=numeric_level,
        format=Config.LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/var/log/wdrf-controller.log")
        ]
    )

def parse_arguments():
    """명령행 인수를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="WDRF (Weighted Dominant Resource Fairness) Controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 기본 실행
  python -m controller
  
  # 로그 레벨 지정
  python -m controller --log-level DEBUG
  
  # 설정 파일 지정
  python -m controller --config /path/to/config.yaml
  
  # 헬스 체크 모드
  python -m controller --health-check
        """
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=Config.LOG_LEVEL,
        help="로그 레벨 설정 (기본값: INFO)"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="설정 파일 경로"
    )
    
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="헬스 체크 모드로 실행"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경사항을 적용하지 않고 시뮬레이션만 실행"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="WDRF Controller v1.0.0"
    )
    
    return parser.parse_args()

def load_config_file(config_path: str):
    """설정 파일을 로드합니다."""
    try:
        import yaml
        
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # 설정값들을 Config 클래스에 적용
        for key, value in config_data.items():
            if hasattr(Config, key):
                setattr(Config, key, value)
                logging.info(f"Loaded config: {key} = {value}")
        
        logging.info(f"Configuration loaded from {config_path}")
        
    except Exception as e:
        logging.error(f"Failed to load config file {config_path}: {e}")
        sys.exit(1)

def print_banner():
    """시작 배너를 출력합니다."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    WDRF Controller v1.0.0                    ║
║                                                              ║
║  Weighted Dominant Resource Fairness GPU Scheduler          ║
║  for Kubernetes with Kueue and HAMi                         ║
║                                                              ║
║  Features:                                                   ║
║  • DRF-based resource allocation                            ║
║  • Priority-based scheduling                                ║
║  • Aging mechanism for starvation prevention                ║
║  • GPU fraction support with HAMi                           ║
║  • Gang scheduling with Kueue                               ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)

def health_check_mode():
    """헬스 체크 모드로 실행합니다."""
    try:
        controller = WDRFController()
        if not controller.initialize():
            print("❌ Controller initialization failed")
            sys.exit(1)
        
        health_status = controller.health_check()
        
        if health_status["status"] == "healthy":
            print("✅ WDRF Controller is healthy")
            print(f"   Kubernetes connected: {health_status['kubernetes_connected']}")
            print(f"   Cluster nodes: {health_status['cluster_nodes']}")
            print(f"   GPU nodes: {health_status['gpu_nodes']}")
            print(f"   Uptime: {health_status['controller_stats']['uptime_formatted']}")
        else:
            print("❌ WDRF Controller is unhealthy")
            print(f"   Error: {health_status.get('error', 'Unknown error')}")
            sys.exit(1)
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        sys.exit(1)

def main():
    """메인 함수"""
    # 명령행 인수 파싱
    args = parse_arguments()
    
    # 로깅 설정
    setup_logging(args.log_level)
    
    # 배너 출력
    print_banner()
    
    # 설정 파일 로드
    if args.config:
        load_config_file(args.config)
    
    # 헬스 체크 모드
    if args.health_check:
        health_check_mode()
        return
    
    # Dry run 모드 설정
    if args.dry_run:
        logging.warning("Running in DRY RUN mode - no actual changes will be made")
        # TODO: Dry run 모드 구현
    
    try:
        # 컨트롤러 생성 및 실행
        controller = WDRFController()
        controller.run()
        
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
