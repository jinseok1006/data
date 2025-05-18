#!/usr/bin/env python
"""
전라북도 공공데이터 다운로더 실행 파일

- 공공데이터포털(data.go.kr)에서 전라북도 관련 데이터를 수집, 다운로드, 업로드하는 도구입니다.
- 4단계 프로세스: 목록화 -> 세부정보 수집 -> 다운로드 -> 업로드
"""

import asyncio
import sys
import os

# 필요한 디렉토리 생성
os.makedirs("downloaded_data", exist_ok=True)

def show_usage():
    """사용법 출력"""
    print("""
전라북도 공공데이터 다운로더 사용법:

기본 사용법:
    python run.py                          # 기본 설정으로 모든 단계 실행
    python run.py --mode list              # 목록화만 실행
    python run.py --mode detail            # 세부정보 수집 및 필터링만 실행
    python run.py --mode download          # 다운로드만 실행
    python run.py --mode upload            # 업로드만 실행
    python run.py --mode quick_upload      # 다운로드된 모든 데이터 즉시 업로드
    
검색 옵션:
    python run.py -k "전북특별자치도"       # 검색 키워드 지정
    python run.py -p 5                     # 최대 5페이지까지 검색 (0: 모든 페이지)
    
처리 옵션:
    python run.py -n 10                    # 최대 10개 항목 처리 (0: 모든 항목)
    python run.py --data-ids 15014782      # 특정 데이터 ID만 처리
    
파일 옵션:
    python run.py --list-file custom.json  # 목록 파일 지정
    python run.py --filtered-file filt.json # 필터링된 데이터 파일 지정
    
업로드 옵션:
    python run.py --custom-filename data2023 # 업로드 시 파일명 지정 (확장자는 유지)
    python run.py --retry-failed            # 이전에 실패한 업로드 항목 재시도
    
디버그 모드:
    python run.py --debug                  # 상세 로그 출력
    """)

if __name__ == "__main__":
    # 사용자가 --help 또는 -h를 입력했을 때 도움말 표시
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        show_usage()
        sys.exit(0)
    
    # 모듈 import는 여기서 수행 (초기 도움말 표시를 빠르게 하기 위함)
    try:
        from src.main import main
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n프로그램이 사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n오류 발생: {str(e)}")
        sys.exit(1) 