import asyncio
import aiohttp
from bs4 import BeautifulSoup
import os
import logging
import re
import time
import random
import argparse
import json
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 기본 URL 및 경로 설정
BASE_URL = "https://www.data.go.kr"
LIST_URL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"
DOWNLOAD_DIR = "downloaded_data"
FAILED_LIST_FILE = "failed_downloads.txt"

# 세션 생성 함수
async def create_session():
    """aiohttp 세션을 생성하는 함수"""
    return aiohttp.ClientSession(headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    })

# 페이지 목록 가져오기
async def get_page_count(session, params):
    """검색 결과의 총 페이지 수를 가져오는 함수"""
    async with session.get(LIST_URL, params=params) as response:
        if response.status != 200:
            logging.error(f"페이지 정보 조회 실패: HTTP {response.status}")
            return 1
            
        html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        
        # 검색 결과 수에서 페이지 수 계산
        count_text = soup.select_one('strong')
        if count_text:
            count_text = count_text.text
            count_match = re.search(r'총\s*([0-9,]+)\s*건', count_text)
            if count_match:
                total_count = int(count_match.group(1).replace(',', ''))
                per_page = int(params.get('perPage', 10))
                max_page = (total_count + per_page - 1) // per_page  # 올림 나눗셈
                logging.info(f"검색 결과 총 {total_count}건, 페이지당 {per_page}개, 페이지 수: {max_page}")
                return max_page
        
        # 페이지네이션에서 숫자 찾기
        pagination = soup.select('nav.pagination a')
        max_page = 1
        for page_link in pagination:
            try:
                # 페이지 번호를 추출
                page_num = int(page_link.get_text().strip())
                if page_num > max_page:
                    max_page = page_num
            except (ValueError, TypeError):
                continue
        
        logging.info(f"페이지네이션에서 찾은 최대 페이지 번호: {max_page}")
        return max_page

# 단일 데이터 항목 파싱
def parse_data_item(item):
    """검색 결과의 단일 항목을 파싱하는 함수"""
    try:
        # 제목 요소 찾기 - dt > a 요소
        title_element = item.select_one('dl dt a')
        if not title_element:
            return None
        
        # 제목 텍스트 추출
        full_title = title_element.get_text(strip=True)
        
        # 파일 형식 정보(CSV, JSON, XML 등)를 제거
        title_text = full_title
        format_types = ['CSV', 'JSON', 'XML', 'XLSX', 'XLS', 'PDF', 'HWP', 'JPG']
        for format_type in format_types:
            title_text = title_text.replace(format_type, '')
        
        # '+' 기호와 앞뒤 공백 제거
        title_text = title_text.replace('+', '').strip()
        
        # 상세 페이지 URL 추출
        detail_url = None
        if title_element.has_attr('href'):
            detail_url = urljoin(BASE_URL, title_element['href'])
        
        # 상세 페이지 URL에서 데이터 ID 추출
        data_id = None
        if detail_url:
            data_id_match = re.search(r'/data/(\d+)/fileData', detail_url)
            if data_id_match:
                data_id = data_id_match.group(1)
        
        # 파일 형식 추출
        format_spans = item.select('dl dt a span.data-format, dl dt span.data-format')
        format_types = [span.get_text(strip=True) for span in format_spans if span.get_text(strip=True)]
        
        # 기본 파일 형식 설정
        file_ext = 'csv'  # 기본값
        if format_types:
            ext_map = {
                'CSV': 'csv', 
                'XLSX': 'xlsx', 
                'XLS': 'xls',
                'JSON': 'json', 
                'XML': 'xml', 
                'HWP': 'hwp',
                'JPG': 'jpg', 
                'PDF': 'pdf'
            }
            
            for fmt in format_types:
                if fmt in ext_map:
                    file_ext = ext_map[fmt]
                    break
        
        # 카테고리 정보 추출
        category_elem = item.select_one('p > span:first-child')
        category = category_elem.get_text(strip=True) if category_elem else None
        
        # 제공기관 정보 추출 - 페이지네이션에서 직접 추출
        provider_elem = item.select_one('p:contains("제공기관") > span')
        provider = provider_elem.get_text(strip=True) if provider_elem else None
        
        # 키워드 정보 추출 - 페이지네이션에서 직접 추출
        keywords_elem = item.select_one('p:contains("키워드")')
        keywords = []
        if keywords_elem:
            keywords_text = keywords_elem.get_text(strip=True)
            if '키워드' in keywords_text:
                keywords_text = keywords_text.replace('키워드', '', 1).strip()
                keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
        
        # 업데이트 주기 정보 추출
        update_cycle_elem = item.select_one('p:contains("주기성 데이터")')
        update_cycle = None
        if update_cycle_elem:
            update_cycle_text = update_cycle_elem.get_text(strip=True)
            if '주기성 데이터' in update_cycle_text:
                update_cycle = update_cycle_text.replace('주기성 데이터', '', 1).strip()
        
        # 수정일 정보 추출
        update_date_elem = item.select_one('p:contains("수정일") > span')
        update_date = update_date_elem.get_text(strip=True) if update_date_elem else None
        
        # 조회수 및 다운로드 수 추출
        view_count_elem = item.select_one('p:contains("조회수") > span')
        view_count = view_count_elem.get_text(strip=True) if view_count_elem else None
        
        download_count_elem = item.select_one('p:contains("다운로드") > span')
        download_count = download_count_elem.get_text(strip=True) if download_count_elem else None
        
        # 다운로드 버튼 찾기
        download_btn = item.select_one('a:contains("다운로드")')
        has_download_btn = bool(download_btn)
        
        # 데이터 항목 정보 수집
        return {
            'title': title_text,
            'full_title': full_title,
            'detail_url': detail_url,
            'data_id': data_id,
            'file_ext': file_ext,
            'format_types': format_types,
            'category': category,
            'provider': provider,
            'keywords': keywords,
            'update_cycle': update_cycle,
            'update_date': update_date,
            'view_count': view_count,
            'download_count': download_count,
            'has_download_btn': has_download_btn
        }
    except Exception as e:
        logging.error(f"데이터 항목 추출 오류: {e}")
        return None

# 페이지 데이터 추출
async def extract_page_data(session, page_num, params):
    """특정 페이지의 데이터 항목들을 추출하는 함수"""
    # 페이지 번호 설정
    current_params = params.copy()
    current_params['currentPage'] = page_num
    
    async with session.get(LIST_URL, params=current_params) as response:
        if response.status != 200:
            logging.error(f"페이지 {page_num} 접근 실패: HTTP {response.status}")
            return []
            
        html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        
        # 데이터셋 목록의 각 항목 찾기
        list_items = soup.select('div.result-list > ul > li')
        
        # 각 항목 파싱
        data_items = []
        for item in list_items:
            data_item = parse_data_item(item)
            if data_item:
                data_items.append(data_item)
        
        return data_items

# 데이터 상세 정보 추출
async def get_data_detail(session, data_item):
    """데이터 항목의 상세 정보를 가져오는 함수"""
    detail_url = data_item.get('detail_url')
    if not detail_url:
        return data_item
    
    try:
        async with session.get(detail_url) as response:
            if response.status != 200:
                logging.error(f"상세 페이지 접속 실패: HTTP {response.status}")
                return data_item
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 메타데이터 테이블에서 정보 추출
            meta_table = soup.select_one('table.file-meta-table')
            if meta_table:
                # 키워드 추출
                keywords_elem = meta_table.select_one('th:contains("키워드") + td')
                if keywords_elem:
                    data_item['keywords'] = [kw.strip() for kw in keywords_elem.get_text(strip=True).split(',')]
                
                # 업데이트 주기 추출
                update_cycle_elem = meta_table.select_one('th:contains("업데이트 주기") + td')
                if update_cycle_elem:
                    data_item['update_cycle'] = update_cycle_elem.get_text(strip=True)
                
                # 제공기관 추출 (상세 페이지에서 더 정확한 정보)
                provider_elem = meta_table.select_one('th:contains("제공기관") + td')
                if provider_elem:
                    data_item['provider'] = provider_elem.get_text(strip=True)
            
            # 미리보기 테이블의 첫 행에서 컬럼 정보 추출
            preview_table = soup.select_one('div.data-meta-preview table')
            if preview_table:
                header_cells = preview_table.select('thead th')
                if header_cells:
                    data_item['columns'] = [cell.get_text(strip=True) for cell in header_cells]
    
    except Exception as e:
        logging.error(f"상세 정보 추출 오류: {e} - {detail_url}")
    
    return data_item

# 파일 ID 가져오기
async def get_file_id(session, data_id, detail_url):
    """파일 ID를 가져오는 함수"""
    file_info_url = f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataPk={data_id}&fileDetailSn=1"
    logging.info(f"파일 정보 URL: {file_info_url}")
    
    try:
        async with session.get(file_info_url, headers={
            "Referer": detail_url,
            "Accept": "application/json"
        }) as info_response:
            html_content = await info_response.text()
            json_data = None
            
            try:
                json_data = json.loads(html_content)
            except json.JSONDecodeError:
                logging.warning("JSON 파싱 실패")
            
            # 응답에서 atchFileId 추출
            atch_file_id = None
            if json_data:
                if 'fileDataRegistVO' in json_data and json_data['fileDataRegistVO']:
                    atch_file_id = json_data['fileDataRegistVO'].get('atchFileId')
                elif 'atchFileId' in json_data:
                    atch_file_id = json_data['atchFileId']
            
            if not atch_file_id:
                # 기본값 사용
                atch_file_id = f"FILE_000000000{data_id}"[-20:]
                logging.warning(f"파일 ID를 찾을 수 없어 기본값 사용: {atch_file_id}")
            else:
                logging.info(f"파일 ID: {atch_file_id}")
            
            return atch_file_id
    except Exception as e:
        logging.error(f"파일 ID 가져오기 오류: {str(e)}")
        return f"FILE_000000000{data_id}"[-20:]

# 실제 파일 다운로드
async def download_file(session, download_url, detail_url, file_path):
    """실제 파일을 다운로드하는 함수"""
    try:
        async with session.get(download_url, headers={
            "Referer": detail_url
        }) as download_response:
            status = download_response.status
            logging.info(f"다운로드 응답 상태: {status}")
            
            if status != 200:
                return False, f"다운로드 실패: HTTP 에러 {status}"
            
            # Content-Type 확인
            content_type = download_response.headers.get('Content-Type', '')
            content_disp = download_response.headers.get('Content-Disposition', '')
            
            # 파일 데이터 가져오기
            file_data = await download_response.read()
            logging.info(f"수신된 데이터 크기: {len(file_data)} 바이트")
            
            # 파일이 HTML이면 오류
            if b"<!DOCTYPE html>" in file_data[:100]:
                logging.error("HTML 응답이 반환됨. 예상되는 파일 형식이 아님")
                return False, "다운로드 실패: HTML 페이지가 반환됨"
            
            # 파일 저장
            with open(file_path, 'wb') as f:
                f.write(file_data)
            
            size = os.path.getsize(file_path)
            logging.info(f"파일 다운로드 완료: {os.path.basename(file_path)} ({size} 바이트)")
            
            if size == 0:
                logging.error("다운로드된 파일이 비어 있습니다.")
                return False, "다운로드 실패: 파일이 비어 있습니다."
            
            return True, file_path
    except Exception as e:
        logging.error(f"파일 다운로드 오류: {str(e)}")
        return False, str(e)

# 데이터 다운로드
async def download_data(session, data_item):
    """데이터를 다운로드하는 함수"""
    try:
        # 필수 정보 확인
        data_id = data_item.get('data_id')
        if not data_id:
            return False, data_item['title'], "데이터 ID 없음"
        
        # detail_url은 리퍼러로 사용하기 위해 보존
        detail_url = data_item.get('detail_url')
        if not detail_url:
            detail_url = f"https://www.data.go.kr/data/{data_id}/fileData.do"
        
        # 파일명 설정 및 경로 생성
        filename = f"{data_item['title']}.{data_item['file_ext']}"
        filename = re.sub(r'[\\/*?:"<>|]', '_', filename)  # 파일명에 금지된 문자 제거
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        
        # 실제 다운로드에 사용할 URL 구성
        # 1. 우선 메타 정보 URL 확인 (첫 단계) - 파일 ID 얻기용
        file_info_url = f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataPk={data_id}&fileDetailSn=1"
        logging.info(f"파일 메타정보 URL: {file_info_url}")
        
        # 2. 파일 ID 가져오기
        atch_file_id = None
        try:
            async with session.get(file_info_url, headers={
                "Referer": detail_url,
                "Accept": "application/json"
            }) as info_response:
                # JSON 응답인 경우 처리
                try:
                    info_json = await info_response.json()
                    if 'fileDataRegistVO' in info_json and info_json['fileDataRegistVO']:
                        atch_file_id = info_json['fileDataRegistVO'].get('atchFileId')
                    elif 'atchFileId' in info_json:
                        atch_file_id = info_json['atchFileId']
                except:
                    logging.warning("JSON 파싱 실패, HTML 응답 확인")
                    html_content = await info_response.text()
                    # HTML에서 필요한 정보를 추출할 수 있다면 여기서 처리
        except Exception as e:
            logging.error(f"메타 정보 요청 중 오류: {str(e)}")
        
        # 파일 ID가 없으면 기본 형식으로 구성
        if not atch_file_id:
            # FILE_000000000{data_id} 형식으로 생성 (전체 길이 20자리)
            file_id_prefix = "FILE_000000000"
            pad_length = 20 - len(file_id_prefix)
            padded_data_id = data_id.zfill(pad_length)
            atch_file_id = file_id_prefix + padded_data_id[-pad_length:]
            logging.info(f"자동 구성된 파일 ID: {atch_file_id}")
        else:
            logging.info(f"API에서 획득한 파일 ID: {atch_file_id}")
        
        # 3. 실제 다운로드 URL 생성
        download_url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}&fileDetailSn=1"
        logging.info(f"다운로드 URL: {download_url}")
        
        # 4. 파일 다운로드
        success, result = await download_file(session, download_url, detail_url, file_path)
        
        if not success:
            return False, data_item['title'], result
        
        # CSV 파일인 경우 인코딩 변환 시도
        if data_item['file_ext'].lower() in ['csv']:
            convert_encoding(file_path)
        
        return True, data_item['title'], file_path
    
    except Exception as e:
        logging.error(f"다운로드 오류: {str(e)}")
        return False, data_item['title'], str(e)

# EUC-KR 인코딩 파일을 UTF-8로 변환하는 함수
def convert_encoding(file_path, from_encoding='euc-kr', to_encoding='utf-8'):
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
            
            logging.info(f"파일 인코딩 변환 성공: {file_path} ({from_encoding} -> {to_encoding})")
            return True
        except UnicodeDecodeError:
            # 다른 인코딩 시도
            try:
                decoded_content = content.decode('cp949')  # CP949도 시도
                
                # 새 인코딩으로 저장
                with open(file_path, 'w', encoding=to_encoding) as f:
                    f.write(decoded_content)
                
                logging.info(f"파일 인코딩 변환 성공: {file_path} (cp949 -> {to_encoding})")
                return True
            except UnicodeDecodeError:
                logging.warning(f"인코딩 변환 실패: {file_path}. 파일이 예상된 인코딩이 아닙니다.")
                return False
    
    except Exception as e:
        logging.error(f"인코딩 변환 오류: {str(e)}")
        return False

# 실패한 다운로드 기록
async def record_failed_download(title, reason):
    with open(FAILED_LIST_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{title}: {reason}\n")

# 필터링 함수 - 특정 조건에 맞는 데이터만 선택
def filter_data_items(items, keywords=None, formats=None, providers=None):
    """데이터 항목을 필터링하는 함수"""
    filtered_items = []
    
    # 제목에서 검색할 키워드들
    title_keywords = ['전북', '전라북도', '전북특별자치도']
    
    for item in items:
        # 제목 필터링 - 제목에 주요 키워드('전북', '전라북도', '전북특별자치도')가 포함되어 있는지 확인
        if 'title' in item:
            item_title = item['title'].lower()
            if not any(kw.lower() in item_title for kw in title_keywords):
                continue
        
        # 키워드 필터링
        if keywords and 'keywords' in item:
            item_keywords = ' '.join(item['keywords']).lower()
            if not any(kw.lower() in item_keywords for kw in keywords):
                continue
        
        # 형식 필터링
        if formats and 'format_types' in item:
            item_formats = [f.upper() for f in item['format_types']]
            if not any(fmt.upper() in item_formats for fmt in formats):
                continue
        
        # 제공기관 필터링
        if providers and 'provider' in item:
            provider = item['provider'].lower() if item['provider'] else ''
            if not any(prov.lower() in provider for prov in providers):
                continue
        
        filtered_items.append(item)
    
    return filtered_items

# 명령행 인수 파싱
def parse_arguments():
    parser = argparse.ArgumentParser(description='공공데이터포털 데이터 수집 도구')
    
    # 모드 선택 (수집, 다운로드, 모두)
    parser.add_argument('--mode', choices=['collect', 'download', 'all'], default='all',
                        help='실행 모드 선택 (collect: 데이터 수집만, download: 다운로드만, all: 모두 실행) (기본값: all)')
    
    parser.add_argument('-k', '--keyword', default='전라북도', 
                        help='검색 키워드 (기본값: 전라북도)')
    
    parser.add_argument('-p', '--pages', type=int, default=1,
                        help='처리할 최대 페이지 수 (기본값: 1, 0 입력 시 모든 페이지 탐색)')
    
    parser.add_argument('-n', '--num-downloads', type=int, default=2,
                        help='다운로드할 최대 항목 수 (기본값: 2, 0 입력 시 모든 항목 다운로드)')
    
    parser.add_argument('-f', '--formats', nargs='+',
                        help='필터링할 파일 형식 (예: CSV JSON)')
    
    parser.add_argument('--filter-keywords', nargs='+',
                        help='필터링할 키워드 (데이터 항목의 키워드에 포함되어야 함)')
    
    parser.add_argument('--filter-providers', nargs='+',
                        help='필터링할 제공기관 (예: 전북특별자치도)')
    
    parser.add_argument('-d', '--download-dir', default=DOWNLOAD_DIR,
                        help=f'다운로드 디렉토리 (기본값: {DOWNLOAD_DIR})')
    
    parser.add_argument('--json-file', default='data_titles.json',
                        help='JSON 데이터 파일 경로 (다운로드 모드에서 사용)')
    
    parser.add_argument('--item-ids', nargs='+', type=int, 
                        help='다운로드할 항목의 인덱스 목록 (1부터 시작, 다운로드 모드에서 사용)')
    
    return parser.parse_args()

# 데이터 수집 함수
async def collect_data(session, args):
    """페이지네이션 화면에서 데이터를 수집하는 함수"""
    # 검색 파라미터 설정
    params = {
        "dType": "FILE",
        "keyword": args.keyword,
        "operator": "AND",
        "perPage": 10
    }
    
    # 총 페이지 수 가져오기
    total_pages = await get_page_count(session, params)
    
    # pages가 0이면 모든 페이지 탐색
    if args.pages == 0:
        max_pages = total_pages
        logging.info(f"모든 페이지를 탐색합니다. (총 {total_pages} 페이지)")
    else:
        max_pages = min(total_pages, args.pages)
        logging.info(f"총 {total_pages} 페이지 중 {max_pages} 페이지까지 처리합니다.")
    
    # 모든 페이지 순회하며 데이터 수집
    all_items = []
    
    for page_num in range(1, max_pages + 1):
        logging.info(f"페이지 {page_num}/{max_pages} 처리 중...")
        data_items = await extract_page_data(session, page_num, params)
        
        if data_items:
            logging.info(f"페이지 {page_num}에서 {len(data_items)}개 항목 발견")
            all_items.extend(data_items)
        else:
            logging.warning(f"페이지 {page_num}에서 데이터를 찾을 수 없습니다.")
        
        # 과도한 요청 방지를 위한 딜레이
        await asyncio.sleep(random.uniform(0.5, 1.0))
    
    if not all_items:
        logging.error("검색 결과가 없습니다.")
        return []
    
    # 필터링
    filtered_items = filter_data_items(
        all_items, 
        keywords=args.filter_keywords, 
        formats=args.formats, 
        providers=args.filter_providers
    )
    
    if not filtered_items:
        logging.warning("필터링 후 남은 항목이 없습니다.")
        return []
    
    # 항상 JSON 파일로 메타데이터 저장 (다운로드 모드에서 사용)
    json_file = "data_titles.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(filtered_items, f, ensure_ascii=False, indent=2)
    logging.info(f"모든 메타데이터가 '{json_file}'에 저장되었습니다.")
    
    return filtered_items

# 데이터 다운로드 함수
async def download_items(session, items, args):
    """JSON 데이터를 기반으로 항목들을 다운로드하는 함수"""
    # 다운로드 디렉토리 생성
    os.makedirs(args.download_dir, exist_ok=True)
    
    # 다운로드할 항목 선택
    if args.item_ids:
        # 인덱스 목록이 제공된 경우 해당 항목들만 선택
        download_items = []
        for idx in args.item_ids:
            if 1 <= idx <= len(items):
                download_items.append(items[idx-1])
            else:
                logging.warning(f"인덱스 {idx}는 유효하지 않습니다. 무시합니다.")
    else:
        # 인덱스가 제공되지 않은 경우
        if args.num_downloads == 0:
            # num_downloads가 0이면 모든 항목 다운로드
            download_items = items
            logging.info(f"모든 항목({len(items)}개)을 다운로드합니다.")
        else:
            # 지정된 개수만큼 선택
            download_items = items[:min(len(items), args.num_downloads)]
    
    if not download_items:
        logging.warning("다운로드할 항목이 없습니다.")
        return
    
    logging.info(f"선택된 {len(download_items)}개 항목 다운로드를 시작합니다.")
    
    downloaded_count = 0
    skipped_count = 0
    
    for idx, item in enumerate(download_items):
        # 다운로드 버튼이 없는 항목은 건너뛰기
        if not item.get('has_download_btn', True):
            logging.info(f"다운로드 버튼 없음 ({idx+1}/{len(download_items)}): {item['title']} - 건너뜁니다")
            skipped_count += 1
            continue
            
        logging.info(f"다운로드 중 ({idx+1}/{len(download_items)}): {item['title']}")
        success, title, result = await download_data(session, item)
        
        if success:
            logging.info(f"다운로드 성공: {result}")
            downloaded_count += 1
        else:
            logging.error(f"다운로드 실패: {result}")
            await record_failed_download(title, result)
        
        # 과도한 요청 방지를 위한 딜레이
        await asyncio.sleep(random.uniform(1.0, 2.0))
    
    logging.info(f"다운로드 완료. 총 {downloaded_count}개 성공, {skipped_count}개 건너뜀. 결과는 '{args.download_dir}' 디렉토리에 저장되었습니다.")
    
    # 인코딩 관련 안내
    if any(item.get('file_ext', '').lower() in ['csv'] for item in download_items):
        logging.info("CSV 파일은 자동으로 EUC-KR/CP949 인코딩에서 UTF-8로 변환을 시도했습니다.")
        logging.info("한글이 깨져 보인다면 Excel에서 열 때 적절한 인코딩을 선택하세요.")

# 메인 함수
async def main():
    """메인 함수 - 전체 흐름 제어"""
    # 명령행 인수 파싱
    args = parse_arguments()
    
    # 설정 변수 업데이트
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = args.download_dir
    
    async with await create_session() as session:
        if args.mode in ['collect', 'all']:
            # 데이터 수집 모드
            items = await collect_data(session, args)
            
            if not items and args.mode == 'all':
                logging.error("수집된 데이터가 없어 다운로드를 진행할 수 없습니다.")
                return
                
            if args.mode == 'all':
                # 수집 후 바로 다운로드 모드
                await download_items(session, items, args)
                
        elif args.mode == 'download':
            # 다운로드 전용 모드 - 저장된 JSON 파일에서 데이터 로드
            try:
                with open(args.json_file, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                logging.info(f"'{args.json_file}'에서 {len(items)}개 항목을 로드했습니다.")
                
                # 다운로드 실행
                await download_items(session, items, args)
                
            except FileNotFoundError:
                logging.error(f"JSON 파일을 찾을 수 없습니다: {args.json_file}")
            except json.JSONDecodeError:
                logging.error(f"JSON 파일 형식이 올바르지 않습니다: {args.json_file}")
            except Exception as e:
                logging.error(f"데이터 로드 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())