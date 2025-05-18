"""
공공데이터 수집, 다운로드, 업로드 통합 프로세스
"""

import asyncio
import argparse
import logging
import os
from .config import LOG_LEVEL, LOG_FORMAT, DOWNLOAD_BASE_DIR
from .utils import setup_logger, print_summary

# 모듈 임포트
from . import list_crawler
from . import detail_crawler
from . import downloader
from . import uploader

def parse_arguments():
    """명령행 인수 파싱 함수"""
    parser = argparse.ArgumentParser(description='공공데이터포털 전라북도 데이터 수집/다운로드/업로드 도구')
    
    # 모드 선택
    parser.add_argument('--mode', choices=['list', 'detail', 'download', 'upload', 'quick_upload', 'all'], default='all',
                        help='실행 모드 선택 (list: 목록화만, detail: 세부정보 수집 및 필터링, download: 다운로드만, upload: 업로드만, quick_upload: 바로 모든 폴더 업로드, all: 전체과정) (기본값: all)')
    
    # 검색 옵션
    parser.add_argument('-k', '--keyword', default='전라북도', 
                        help='검색 키워드 (기본값: 전라북도)')
    
    parser.add_argument('-p', '--pages', type=int, default=1,
                        help='처리할 최대 페이지 수 (기본값: 1, 0 입력 시 모든 페이지 탐색)')
    
    # 필터링 및 다운로드 옵션
    parser.add_argument('-n', '--num-process', type=int, default=2,
                        help='처리할 최대 항목 수 (세부페이지/다운로드) (기본값: 2, 0 입력 시 모든 항목 처리)')
    
    parser.add_argument('--data-ids', nargs='+',
                        help='처리/다운로드/업로드할 데이터 ID 목록')
    
    # 파일 경로 옵션
    parser.add_argument('--list-file', default='data_list.json',
                        help='목록 데이터 파일 경로 (세부정보 수집 모드에서 사용)')
    
    parser.add_argument('--detail-file', default='data_detail.json',
                        help='상세정보 데이터 파일 경로 (다운로드 모드에서 사용)')
    
    parser.add_argument('--results-file', default='download_results.json',
                        help='다운로드 결과 파일 경로 (업로드 모드에서 사용)')
    
    # 업로드 옵션
    parser.add_argument('--custom-filename', 
                        help='업로드 시 사용할 커스텀 파일명 (지정하지 않으면 원본 파일명 사용)')
    
    parser.add_argument('--retry-failed', action='store_true',
                        help='이전에 실패한 업로드 항목 재시도 (기본값: False)')
    
    # 디버그 옵션
    parser.add_argument('--debug', action='store_true',
                        help='디버그 모드 활성화 (상세 로그 출력)')
    
    parser.add_argument('--debug-html-dir', type=str, default='debug_html',
                        help='HTML 파일 저장 디렉토리 (기본값: debug_html)')
    
    return parser.parse_args()

async def main():
    """메인 함수"""
    # 명령행 인수 파싱
    args = parse_arguments()
    
    # 로깅 설정
    log_level = logging.DEBUG if args.debug else getattr(logging, LOG_LEVEL)
    logger = setup_logger(level=log_level, log_format=LOG_FORMAT)
    
    # 디버그 모드 설정이 활성화되면 HTML 저장 디렉토리 생성
    if args.debug and args.debug_html_dir:
        os.makedirs(args.debug_html_dir, exist_ok=True)
        logger.info(f"디버그 HTML 파일 저장 디렉토리: {args.debug_html_dir}")
    
    # 다운로드 디렉토리 생성
    os.makedirs(DOWNLOAD_BASE_DIR, exist_ok=True)
    
    # 빠른 업로드 모드 - 다운로드 디렉토리의 모든 폴더를 즉시 업로드
    if args.mode == 'quick_upload':
        if args.retry_failed:
            logger.info("빠른 업로드 모드 (실패 항목 재시도)를 시작합니다.")
        else:
            logger.info("빠른 업로드 모드를 시작합니다. 다운로드 디렉토리의 모든 폴더를 업로드합니다.")
        
        # 시작 시간 기록
        import time
        start_time = time.time()
        
        # 디렉토리 기반 업로드 (모든 폴더)
        uploaded, failed = await uploader.upload_from_directory(
            selected_ids=args.data_ids,
            custom_filename=args.custom_filename,
            retry_failed=args.retry_failed
        )
        
        # 소요 시간 계산
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        time_str = f"{int(minutes)}분 {int(seconds)}초"
        
        # 결과 요약
        print_summary(
            f"빠른 데이터 업로드 (소요시간: {time_str})", 
            len(uploaded), 
            len(failed)
        )
        
        # 실패 항목이 있으면 재시도 방법 안내
        if failed:
            logger.info(f"실패한 {len(failed)}개 항목이 있습니다. 재시도하려면 --retry-failed 옵션을 사용하세요.")
            logger.info("명령어 예시: python run.py --mode quick_upload --retry-failed")
        
        logger.info("빠른 업로드 작업이 완료되었습니다.")
        return
    
    # 기존 모드에 따른 처리
    if args.mode in ['list', 'all']:
        # 목록화 모드
        logger.info("데이터 목록화 모드를 시작합니다.")
        collected_items = await list_crawler.collect_list_data(
            keyword=args.keyword,
            max_pages=args.pages
        )
        
        if not collected_items:
            logger.error("수집된 데이터가 없습니다. 프로세스를 종료합니다.")
            return
            
        logger.info(f"총 {len(collected_items)}개 항목이 목록화되었습니다.")
        print_summary("데이터 목록화", len(collected_items), 0)
    
    if args.mode in ['detail', 'all']:
        # 세부정보 수집 모드
        logger.info("데이터 세부정보 수집 및 필터링 모드를 시작합니다.")
        
        # 세부정보 수집 및 필터링 실행 (디버그 옵션 전달)
        filtered_items = await detail_crawler.collect_detail_data(
            list_file=args.list_file,
            limit=args.num_process,
            debug=args.debug,
            debug_html_dir=args.debug_html_dir
        )
        
        if not filtered_items:
            logger.error("세부정보 수집 및 필터링 후 남은 데이터가 없습니다. 프로세스를 종료합니다.")
            if args.mode == 'all':  # 전체 모드인 경우 다음 단계 실행 X
                return
        else:
            logger.info(f"총 {len(filtered_items)}개 항목이 세부정보 수집 및 필터링되었습니다.")
            print_summary("데이터 세부정보 수집", len(filtered_items), 0)
            
            # all 모드에서 다음 단계로 파일 경로 전달 (data_detail.json 파일 경로 저장)
            if args.mode == 'all':
                args.detail_file = "data_detail.json"
                logger.info(f"다운로드 단계에서 사용할 세부정보 데이터 파일: {args.detail_file}")
    
    if args.mode in ['download', 'all']:
        # 다운로드 모드
        logger.info("데이터 다운로드 모드를 시작합니다.")
        
        # 다운로드 실행
        downloaded, failed, skipped = await downloader.download_filtered_data(
            filtered_file=args.detail_file,
            num_downloads=args.num_process,
            selected_ids=args.data_ids
        )
        
        # 결과 요약
        print_summary(
            "데이터 다운로드", 
            len(downloaded), 
            len(failed), 
            len(skipped), 
            "failed_downloads.txt"
        )
    
    if args.mode in ['upload', 'all']:
        # 업로드 모드 (모두 quick_upload 방식으로 변경)
        logger.info("데이터 업로드 모드를 시작합니다.")
        
        # 시작 시간 기록
        import time
        start_time = time.time()
        
        # 이전 upload_source 옵션은 무시하고 항상 디렉토리 기반 업로드 사용
        if args.retry_failed:
            logger.info("업로드 모드 (실패 항목 재시도)를 시작합니다.")
        else:
            logger.info("업로드 모드를 시작합니다. 다운로드 디렉토리의 모든 폴더를 업로드합니다.")
        
        # 디렉토리 기반 업로드 (모든 폴더) - quick_upload와 동일한 방식
        uploaded, failed = await uploader.upload_from_directory(
            selected_ids=args.data_ids,
            custom_filename=args.custom_filename,
            retry_failed=args.retry_failed
        )
        
        # 소요 시간 계산
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        time_str = f"{int(minutes)}분 {int(seconds)}초"
        
        # 결과 요약
        print_summary(
            f"데이터 업로드 (소요시간: {time_str})", 
            len(uploaded), 
            len(failed)
        )
        
        # 실패 항목이 있으면 재시도 방법 안내
        if failed:
            logger.info(f"실패한 {len(failed)}개 항목이 있습니다. 재시도하려면 --retry-failed 옵션을 사용하세요.")
            logger.info("명령어 예시: python run.py --mode upload --retry-failed")
    
    logger.info("모든 작업이 완료되었습니다.")

if __name__ == "__main__":
    asyncio.run(main()) 