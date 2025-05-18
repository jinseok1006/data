"""
세부 데이터 수집 모듈
- 목록화된 데이터를 필터링하고 필요 시 세부 페이지에 접근하여 상세 정보를 수집합니다.
- 타이틀 키워드 필터링 및 확장자 필터링을 담당합니다.
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
import json
import logging
import os
import random
from urllib.parse import urljoin

from .config import BASE_URL, REQUEST_HEADERS, REQUIRED_TITLE_KEYWORDS
from .utils import print_progress, save_metadata, load_metadata

# 브라우저와 유사한 요청 헤더 추가
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive'
}

# 디버그 설정 (모듈 변수)
_DEBUG_ENABLED = False
_DEBUG_HTML_DIR = "debug_html"  # 디버그 HTML 저장 디렉토리

def set_debug_mode(enabled=True, html_dir=None):
    """디버그 모드 설정을 변경하는 함수
    
    Args:
        enabled (bool): 디버그 모드 활성화 여부 (기본값: True)
        html_dir (str, optional): HTML 파일 저장 디렉토리 (기본값: "debug_html")
    
    Returns:
        dict: 현재 디버그 설정 정보
    """
    global _DEBUG_ENABLED, _DEBUG_HTML_DIR
    _DEBUG_ENABLED = enabled
    
    if html_dir is not None:
        _DEBUG_HTML_DIR = html_dir
    
    # 디버그 모드가 활성화되면 디버그 디렉토리 생성
    if _DEBUG_ENABLED and not os.path.exists(_DEBUG_HTML_DIR):
        os.makedirs(_DEBUG_HTML_DIR, exist_ok=True)
    
    logging.info(f"디버그 모드 {'활성화' if _DEBUG_ENABLED else '비활성화'}, HTML 저장 디렉토리: {_DEBUG_HTML_DIR}")
    
    return {
        "debug_enabled": _DEBUG_ENABLED,
        "html_directory": _DEBUG_HTML_DIR
    }

def get_debug_settings():
    """현재 디버그 설정 정보를 반환하는 함수
    
    Returns:
        dict: 현재 디버그 설정 정보
    """
    return {
        "debug_enabled": _DEBUG_ENABLED,
        "html_directory": _DEBUG_HTML_DIR
    }

# 지원하는 파일 확장자 목록
SUPPORTED_EXTENSIONS = ['CSV', 'XLSX', 'DOCX', 'HWPX', 'PDF', 'XLS', 'HWP']

# 목록 데이터 로드
def load_list_data(list_file="data_list.json"):
    """저장된 목록 데이터를 로드하는 함수"""
    data = load_metadata(list_file)
    if not data:
        logging.error(f"목록 데이터 파일을 로드할 수 없습니다: {list_file}")
        return []
    
    logging.info(f"목록 데이터 파일에서 {len(data)}개 항목을 로드했습니다.")
    return data

# 제목 또는 제공기관 기반 필터링
def filter_by_title_or_provider(items):
    """제목이나 제공기관에 필요한 키워드가 포함된 항목만 필터링하는 함수"""
    filtered_items = []
    
    for item in items:
        title = item.get('title', '')
        provider = item.get('provider', '')
        
        # 키워드 확인 (전북, 전라북도, 전북특별자치도 중 하나 포함)
        if any(keyword in title for keyword in REQUIRED_TITLE_KEYWORDS) or \
           any(keyword in provider for keyword in REQUIRED_TITLE_KEYWORDS):
            filtered_items.append(item)
        else:
            logging.debug(f"키워드 필터링: 제외 '{title}' (제공기관: {provider})")
    
    logging.info(f"제목/제공기관 필터링 결과: {len(filtered_items)}/{len(items)}개 항목 선택")
    return filtered_items

# 파일 형식 기반 필터링
def filter_by_format(items):
    """지원되는 파일 형식인 항목만 필터링하는 함수"""
    filtered_items = []
    
    for item in items:
        format_types = item.get('format_types', [])
        
        # 형식이 명시되지 않은 경우 일단 포함 (세부 페이지에서 확인)
        if not format_types:
            filtered_items.append(item)
            continue
        
        # 지원하는 형식인지 확인
        if any(ext in SUPPORTED_EXTENSIONS for ext in format_types):
            filtered_items.append(item)
        else:
            logging.debug(f"형식 필터링: 제외 '{item.get('title')}' (형식: {format_types})")
    
    logging.info(f"형식 필터링 결과: {len(filtered_items)}/{len(items)}개 항목 선택")
    return filtered_items

# 다운로드 버튼 유무 확인
def filter_by_download_button(items):
    """다운로드 버튼이 있는 항목만 필터링하는 함수"""
    filtered_items = []
    
    for item in items:
        if item.get('has_download_btn', False):
            filtered_items.append(item)
        else:
            logging.debug(f"다운로드 버튼 필터링: 제외 '{item.get('title')}'")
    
    logging.info(f"다운로드 버튼 필터링 결과: {len(filtered_items)}/{len(items)}개 항목 선택")
    return filtered_items

# 세부 페이지에서 정보 수집
async def fetch_detail_page(session, data_item, debug=None):
    """세부 페이지에서 추가 정보를 수집하는 함수
    
    Args:
        session: HTTP 세션
        data_item: 데이터 항목
        debug: 디버그 모드 활성화 여부 (None일 경우 전역 설정 사용)
    """
    # 디버그 설정 확인 (None이면 전역 설정 사용)
    use_debug = _DEBUG_ENABLED if debug is None else debug
    
    detail_url = data_item.get('detail_url')
    if not detail_url:
        logging.error(f"세부 페이지 URL 없음: {data_item.get('title')}")
        return data_item
    
    try:
        # 브라우저와 유사한 헤더 추가
        headers = {**REQUEST_HEADERS, **BROWSER_HEADERS}
        logging.info(f"요청 URL: {detail_url}")
        
        async with session.get(detail_url, headers=headers) as response:
            if response.status != 200:
                logging.error(f"세부 페이지 접근 실패: HTTP {response.status}")
                return data_item
            
            html = await response.text(encoding='utf-8')
            
            # 디버깅용: HTML 저장 (디버그 모드일 때만)
            if use_debug:
                debug_file = os.path.join(_DEBUG_HTML_DIR, f"debug_{data_item['data_id']}.html")
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(html)
                logging.info(f"HTML 저장됨: {debug_file}")
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # 데이터 테이블에서 메타데이터 추출 - 디버깅 로그 추가
            meta_tables = soup.select('.dataset-table.fileDataDetail')
            logging.info(f"URL: {detail_url}, 찾은 테이블 수: {len(meta_tables)}")
            
            # 테이블이 없으면 모든 테이블 확인
            if not meta_tables:
                all_tables = soup.select('table')
                logging.info(f"모든 테이블 수: {len(all_tables)}")
                
                # 디버그 모드일 때만 상세 로그 출력
                if use_debug:
                    for idx, table in enumerate(all_tables):
                        class_names = table.get('class', [])
                        logging.info(f"테이블 {idx+1} 클래스: {class_names}")
                
                # 테이블이 있으면 첫 번째 테이블로 시도
                if all_tables:
                    logging.info("테이블 클래스가 다른 형식이어서 첫 번째 테이블을 사용합니다.")
                    meta_tables = [all_tables[0]]
            
            # 헤더 텍스트로 값을 찾는 더 견고한 방식 사용
            if meta_tables and len(meta_tables) >= 2:  # 최소 2개 이상의 테이블이 있는지 확인
                # 수정: 두 번째 테이블 사용 (인덱스 1)
                meta_table = meta_tables[1]  # 두 번째 테이블 사용
                logging.info("두 번째 테이블을 찾았습니다. 내용 파싱 시작")
                
                # 테이블의 모든 행을 가져와서 처리
                rows = meta_table.select('tr')
                logging.info(f"테이블 행 수: {len(rows)}")
                
                # 디버깅: 모든 행의 헤더 텍스트 출력 (디버그 모드일 때만)
                if use_debug:
                    for row_idx, row in enumerate(rows):
                        headers = row.select('th')
                        if headers:
                            header_texts = [h.get_text(strip=True) for h in headers]
                            logging.debug(f"행 {row_idx+1} 헤더: {header_texts}")
                
                for row in rows:
                    # 각 행의 헤더(th)와 값(td) 가져오기
                    headers = row.select('th')
                    values = row.select('td')
                    
                    # 로깅 추가 (디버그 모드일 때만)
                    if use_debug and headers and values:
                        header_texts = [h.get_text(strip=True) for h in headers]
                        logging.debug(f"행 헤더: {header_texts}")
                    
                    # 헤더와 값이 모두 있는 경우에만 처리
                    for i, header in enumerate(headers):
                        header_text = header.get_text(strip=True)
                        
                        # 해당 헤더에 대응하는 값이 있는지 확인
                        if i < len(values):
                            value_text = values[i].get_text(strip=True)
                            
                            # 헤더 텍스트에 따라 적절한 키로 데이터 저장 - 필요한 필드만 유지
                            if '파일데이터명' in header_text:
                                data_item['file_data_name'] = value_text
                                logging.info(f"파일데이터명 찾음: {value_text}")
                            elif '분류체계' in header_text:
                                data_item['category'] = value_text
                                logging.info(f"분류체계 찾음: {value_text}")
                            elif '제공기관' in header_text:
                                data_item['provider'] = value_text
                            elif '관리부서명' in header_text:
                                data_item['department'] = value_text
                                logging.info(f"관리부서명 찾음: {value_text}")
                            elif '관리부서 전화번호' in header_text:
                                data_item['contact_phone'] = value_text
                            elif '수집방법' in header_text:
                                data_item['collection_method'] = value_text
                            elif '업데이트 주기' in header_text:
                                data_item['update_cycle'] = value_text
                            elif '차기 등록 예정일' in header_text:
                                data_item['next_update_date'] = value_text
                            elif '확장자' in header_text:
                                data_item['extension'] = value_text
                                logging.info(f"확장자 찾음: {value_text}")
                            elif '키워드' in header_text:
                                data_item['keywords'] = value_text.split(',')
                                logging.info(f"키워드 찾음: {value_text}")
                            elif '등록일' in header_text:
                                data_item['register_date'] = value_text
                                logging.info(f"등록일 찾음: {value_text}")
                            elif '수정일' in header_text:
                                data_item['update_date'] = value_text
                                logging.info(f"수정일 찾음: {value_text}")
                            elif '제공형태' in header_text:
                                data_item['provision_type'] = value_text
                                logging.info(f"제공형태 찾음: {value_text}")
                            elif '설명' in header_text:
                                data_item['description'] = value_text
                                logging.info(f"설명 찾음: 길이 {len(value_text)} 문자")
                            elif '기타 유의사항' in header_text:
                                data_item['note'] = value_text
                                logging.info(f"기타 유의사항 찾음: {value_text}")
                            elif '이용허락범위' in header_text:
                                # 이용허락범위는 텍스트 추출이 복잡할 수 있음
                                license_text = value_text
                                if not license_text and values[i].select_one('a'):
                                    license_text = values[i].select_one('a').get_text(strip=True)
                                data_item['license'] = license_text
                                logging.info(f"이용허락범위 찾음: {license_text}")
            else:
                logging.warning(f"메타데이터 테이블을 찾을 수 없습니다: {detail_url}")
            
            # 다운로드 버튼 확인 - 디버깅 로그 추가
            download_btns = []
            for elem in soup.select('a, button'):
                text = elem.get_text(strip=True)
                if '다운로드' in text and 'meta' not in text.lower():
                    download_btns.append(elem)
            
            logging.info(f"다운로드 버튼 수: {len(download_btns)}")
            
            if download_btns:
                data_item['has_download_btn'] = True
                
                # 첫 번째 다운로드 버튼의 onclick 속성에서 다운로드 정보 추출
                download_btn = download_btns[0]
                onclick_attr = download_btn.get('onclick', '')
                logging.info(f"다운로드 버튼 onclick: {onclick_attr}")
                
                # fileDetailObj.fn_fileDataDown('15104486', 'uddi:4ef35411-d007-426b-8ee7-9fdc1252c80f', '','1', '1')
                # 위 형식에서 파라미터 추출
                file_id_matches = re.findall(r"'([^']*)'", onclick_attr)
                if file_id_matches and len(file_id_matches) >= 2:
                    data_item['file_id'] = file_id_matches[0]
                    data_item['file_detail_id'] = file_id_matches[1]
                    
                    # 추가 파라미터가 있다면 저장
                    if len(file_id_matches) > 2:
                        data_item['download_params'] = file_id_matches[2:]
                    
                    logging.info(f"파일 ID: {data_item['file_id']}, 상세 ID: {data_item['file_detail_id']}")
                
                # 다운로드 버튼 텍스트 저장
                data_item['download_btn_text'] = download_btn.get_text(strip=True)
            else:
                data_item['has_download_btn'] = False
                logging.warning("다운로드 버튼을 찾을 수 없습니다.")
            
            # 세부 페이지 접근 완료 표시 (필요 없는 필드는 삭제)
            if 'list_page_only' in data_item:
                del data_item['list_page_only']
            
            return data_item
    
    except Exception as e:
        logging.error(f"세부 페이지 처리 오류: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())  # 상세 오류 스택트레이스 출력
        return data_item

# 모든 항목의 세부 페이지 접근
async def enrich_items_with_details(items, limit=0, debug=None):
    """필터링된 항목들의 세부 페이지에 접근하여 추가 정보 수집
    
    Args:
        items: 수집할 항목 목록
        limit: 처리할 최대 항목 수 (0=모두)
        debug: 디버그 모드 활성화 여부 (None일 경우 전역 설정 사용)
    """
    # 디버그 설정 확인 (None이면 전역 설정 사용)
    use_debug = _DEBUG_ENABLED if debug is None else debug
    
    if limit > 0:
        items_to_process = items[:limit]
        logging.info(f"첫 {len(items_to_process)}개 항목의 세부 정보를 수집합니다.")
    else:
        items_to_process = items
        logging.info(f"모든 {len(items_to_process)}개 항목의 세부 정보를 수집합니다.")
    
    enriched_items = []
    
    print("\n" + "="*70)
    print(f"세부 정보 수집 시작: 총 {len(items_to_process)}개 항목")
    print("="*70)
    
    # 브라우저와 유사한 헤더 적용
    headers = {**REQUEST_HEADERS, **BROWSER_HEADERS}
    async with aiohttp.ClientSession(headers=headers) as session:
        for idx, item in enumerate(items_to_process):
            title = item.get('title', f"ID:{item.get('data_id', 'unknown')}")
            print_progress(idx+1, len(items_to_process), title)
            
            # 세부 페이지 접근 (디버그 옵션 전달)
            enriched_item = await fetch_detail_page(session, item, debug=debug)
            enriched_items.append(enriched_item)
            
            # 과도한 요청 방지를 위한 딜레이
            await asyncio.sleep(random.uniform(1.0, 2.0))
    
    print("\n")  # 진행률 표시 후 줄바꿈
    
    # 세부 정보가 추가된 항목들 저장
    metadata_file = "data_detail.json"  # 원래 파일명으로 되돌림
    save_metadata(enriched_items, metadata_file)
    logging.info(f"필터링 및 상세정보가 추가된 {len(enriched_items)}개 항목이 '{metadata_file}'에 저장되었습니다.")
    
    # 디버깅: 메타데이터 필드 통계 (디버그 모드일 때만)
    if use_debug:
        field_stats = {}
        for item in enriched_items:
            for key in item.keys():
                if key not in field_stats:
                    field_stats[key] = 0
                field_stats[key] += 1
        
        logging.info("수집된 메타데이터 필드 통계:")
        for key, count in field_stats.items():
            logging.info(f"  - {key}: {count}/{len(enriched_items)}개 항목에 존재")
    
    return enriched_items

# 목록 데이터 기반 필터링 및 세부 데이터 수집 함수
async def collect_detail_data(list_file="data_list.json", limit=0, debug=None, debug_html_dir=None):
    """목록 데이터를 로드하고 필터링한 후 세부 정보 수집
    
    Args:
        list_file: 목록 데이터 파일 경로
        limit: 처리할 최대 항목 수
        debug: 디버그 모드 활성화 여부 (None일 경우 전역 설정 사용)
        debug_html_dir: HTML 파일 저장 디렉토리 (None일 경우 기본값 사용)
    """
    # 디버그 설정 적용 (main.py에서 전달 받은 설정 적용)
    if debug is not None or debug_html_dir is not None:
        set_debug_mode(
            enabled=debug if debug is not None else _DEBUG_ENABLED,
            html_dir=debug_html_dir if debug_html_dir is not None else _DEBUG_HTML_DIR
        )
    
    # 목록 데이터 로드
    list_data = load_list_data(list_file)
    if not list_data:
        return []
    
    # 1. 제목 또는 제공기관 기반 필터링
    title_or_provider_filtered = filter_by_title_or_provider(list_data)
    if not title_or_provider_filtered:
        logging.warning("제목/제공기관 필터링 후 남은 항목이 없습니다.")
        return []
    
    # 2. 파일 형식 기반 필터링
    format_filtered = filter_by_format(title_or_provider_filtered)
    if not format_filtered:
        logging.warning("형식 필터링 후 남은 항목이 없습니다.")
        return []
    
    # 3. 다운로드 버튼 유무 확인
    download_filtered = filter_by_download_button(format_filtered)
    if not download_filtered:
        logging.warning("다운로드 버튼 필터링 후 남은 항목이 없습니다.")
        return []
    
    # 4. 세부 페이지에서 추가 정보 수집 (디버그 옵션 전달)
    detailed_items = await enrich_items_with_details(download_filtered, limit, debug=_DEBUG_ENABLED)
    
    return detailed_items 