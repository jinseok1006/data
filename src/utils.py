"""
공통 유틸리티 함수 모음
"""

import os
import logging
import json
import re
import time
from .config import PROGRESS_BAR_WIDTH

# 로깅 설정
def setup_logger(level=logging.INFO, log_format=None):
    """로깅 설정 함수"""
    if log_format is None:
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    logging.basicConfig(level=level, format=log_format)
    return logging.getLogger()

# 진행률 표시 함수
def print_progress(current, total, title='', success=None):
    """진행률을 시각적으로 표시하는 함수"""
    percent = int(100 * current / total)
    filled_width = int(PROGRESS_BAR_WIDTH * current / total)
    bar = '■' * filled_width + '□' * (PROGRESS_BAR_WIDTH - filled_width)
    
    status = ""
    if success is not None:
        status = "✓" if success else "✗"
    
    if title:
        title_display = f" - {title}"
        # 타이틀이 너무 길면 자르기
        if len(title_display) > 40:
            title_display = title_display[:37] + "..."
    else:
        title_display = ""
    
    progress_text = f"\r진행률: [{bar}] {percent}% ({current}/{total}){title_display} {status}"
    print(progress_text, end='', flush=True)
    
    # 완료되면 줄바꿈
    if current == total:
        print()

# 파일명 정리 함수
def sanitize_filename(filename):
    """파일명에서 금지된 문자를 제거하고 정리하는 함수"""
    # 파일명에 금지된 문자 제거 (Windows 파일명으로 사용할 수 없는 문자들)
    filename = re.sub(r'[\\/*?:"<>|,]', '_', filename)
    # 연속된 언더스코어 제거 및 공백 정리
    filename = re.sub(r'_+', '_', filename)  # 연속된 언더스코어를 하나로
    filename = re.sub(r'\s+', ' ', filename)  # 연속된 공백을 하나로
    return filename.strip()

# 인코딩 변환 함수
def convert_encoding(file_path, from_encoding='euc-kr', to_encoding='utf-8'):
    """파일의 인코딩을 변환하는 함수"""
    try:
        # 원본 파일 내용 읽기
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # 먼저 원래 인코딩으로 디코딩 시도
        try:
            decoded_content = content.decode(from_encoding)
            
            # 새 인코딩으로 저장
            with open(file_path, 'w', encoding=to_encoding) as f:
                f.write(decoded_content)
            
            logging.debug(f"파일 인코딩 변환 성공: {file_path} ({from_encoding} -> {to_encoding})")
            return True
        except UnicodeDecodeError:
            # 다른 인코딩 시도
            try:
                decoded_content = content.decode('cp949')  # CP949도 시도
                
                # 새 인코딩으로 저장
                with open(file_path, 'w', encoding=to_encoding) as f:
                    f.write(decoded_content)
                
                logging.debug(f"파일 인코딩 변환 성공: {file_path} (cp949 -> {to_encoding})")
                return True
            except UnicodeDecodeError:
                logging.warning(f"인코딩 변환 실패: {file_path}. 파일이 예상된 인코딩이 아닙니다.")
                return False
    
    except Exception as e:
        logging.error(f"인코딩 변환 오류: {str(e)}")
        return False

# 메타데이터 저장 함수
def save_metadata(data, file_path):
    """메타데이터를 파일로 저장하는 함수"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"메타데이터 저장 오류: {str(e)}")
        return False

# 메타데이터 로드 함수
def load_metadata(file_path):
    """메타데이터 파일을 로드하는 함수"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"메타데이터 로드 오류: {str(e)}")
        return None

# 실패 목록 기록 함수
def record_failed_item(file_path, title, reason):
    """실패한 항목을 파일에 기록하는 함수"""
    try:
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(f"{title}: {reason}\n")
        return True
    except Exception as e:
        logging.error(f"실패 항목 기록 오류: {str(e)}")
        return False

# 결과 요약 출력 함수
def print_summary(title, success_count, fail_count, skip_count=0, detail_file=None):
    """처리 결과 요약을 출력하는 함수"""
    print("\n" + "="*70)
    print(f"{title} 결과 요약")
    print("-"*70)
    print(f"- 성공: {success_count}개")
    print(f"- 실패: {fail_count}개" + (f" (상세 내용: {detail_file})" if detail_file else ""))
    if skip_count > 0:
        print(f"- 건너뜀: {skip_count}개")
    print("="*70) 