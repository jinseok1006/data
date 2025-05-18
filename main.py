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
logger = logging.getLogger()

# 진행률 표시용 변수 및 함수
PROGRESS_BAR_WIDTH = 50  # 진행률 바 너비

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
        
        # 방법 1: '마지막 페이지' 버튼에서 직접 페이지 번호 추출
        last_page_button = soup.select_one('nav.pagination a.control.last')
        if last_page_button:
            onclick_attr = last_page_button.get('onclick', '')
            page_match = re.search(r'updatePage\((\d+)\)', onclick_attr)
            if page_match:
                max_page = int(page_match.group(1))
                logging.info(f"마지막 페이지 버튼에서 총 페이지 수 확인: {max_page}")
                return max_page
        
        # 방법 2: 검색 결과 수에서 페이지 수 계산
        count_text = soup.select_one('.result-count strong')
        if not count_text:
            count_text = soup.select_one('strong')  # 다른 위치의 strong 태그 확인
        
        if count_text:
            count_text = count_text.text
            count_match = re.search(r'총\s*([0-9,]+)\s*건', count_text)
            if count_match:
                total_count = int(count_match.group(1).replace(',', ''))
                per_page = int(params.get('perPage', 10))
                max_page = (total_count + per_page - 1) // per_page  # 올림 나눗셈
                logging.info(f"검색 결과 총 {total_count}건, 페이지당 {per_page}개, 총 페이지 수: {max_page}")
                return max_page
        
        # 방법 3: 페이지네이션에서 숫자 찾기
        pagination = soup.select('nav.pagination a')
        max_page = 1
        
        for page_link in pagination:
            onclick_attr = page_link.get('onclick', '')
            page_match = re.search(r'updatePage\((\d+)\)', onclick_attr)
            if page_match:
                try:
                    page_num = int(page_match.group(1))
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
        
        # 페이지네이션에서 보이는 포맷 태그 추출
        format_tag = None
        format_tag_elem = title_element.select_one('span.data-format')
        if format_tag_elem:
            format_tag = format_tag_elem.get_text(strip=True)
            
        # 페이지네이션에서 직접 파일 형식 확인
        if format_tag:
            logging.debug(f"페이지네이션에서 발견한 형식 태그: {format_tag}")
        
        # 제목 처리 전에 먼저 제목에서 형식 힌트 추출 (제목에 형식이 앞에 붙어있는 경우 처리)
        title_format = None
        format_types = ['CSV', 'JSON', 'XML', 'XLSX', 'XLS', 'PDF', 'HWP', 'JPG', 'PNG', 'ZIP', 'SHP']
        
        # 1. 제목 앞에 형식이 붙어있는 경우 확인 (예: "JPG전북특별자치도 전주시_음식점 사진")
        for fmt in format_types:
            if full_title.startswith(fmt):
                title_format = fmt
                # 제목에서 형식 제거
                full_title = full_title[len(fmt):].strip()
                break
        
        # 2. 제목 중간에 형식이 있는 경우도 확인
        title_text = full_title
        for fmt in format_types:
            if fmt in title_text:
                if not title_format:  # 앞에서 이미 형식을 찾지 않았을 경우에만
                    title_format = fmt
                title_text = title_text.replace(fmt, '')
        
        # 제목 정리 - 특수문자 및 불필요한 공백 제거
        title_text = title_text.replace('+', '')  # '+' 기호 제거
        title_text = title_text.strip(',')  # 앞뒤 쉼표 제거
        title_text = re.sub(r'\s+', ' ', title_text)  # 연속된 공백을 하나로
        title_text = title_text.strip()  # 앞뒤 공백 제거
        
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
        format_types_from_spans = [span.get_text(strip=True) for span in format_spans if span.get_text(strip=True)]
        
        # 매체유형 추출 - 페이지네이션에서 직접 추출
        media_type_elem = item.select_one('p:contains("매체유형") > span')
        media_type = media_type_elem.get_text(strip=True) if media_type_elem else None
        
        # 기본 파일 형식 설정을 위한 매핑
        ext_map = {
            'CSV': 'csv', 
            'XLSX': 'xlsx', 
            'XLS': 'xls',
            'JSON': 'json', 
            'XML': 'xml', 
            'HWP': 'hwp',
            'JPG': 'jpg', 
            'PNG': 'png',
            'GIF': 'gif',
            'ZIP': 'zip',
            'PDF': 'pdf',
            'SHP': 'zip'  # SHP 파일은 보통 ZIP으로 압축되어 제공됨
        }
        
        # 파일 형식 결정 로직 (우선순위) - 명확한 확장자만 사용
        file_ext = 'csv'  # 기본값
        
        # 1. 매체유형 기반 파일 형식 힌트 (이미지/사진인 경우 jpg로 가정)
        if media_type in ['이미지', '사진']:
            file_ext = 'jpg'  # 이미지/사진인 경우 기본값을 jpg로 설정
        
        # 2. 포맷 태그 기반
        if format_tag and format_tag.upper() in ext_map:
            file_ext = ext_map[format_tag.upper()]
            logging.debug(f"포맷 태그에서 형식 확인: {format_tag} -> {file_ext}")
        
        # 3. 제목에서 추출한 형식
        elif title_format and title_format.upper() in ext_map:
            file_ext = ext_map[title_format.upper()]
            logging.debug(f"제목에서 추출한 형식 사용: {title_format} -> {file_ext}")
        
        # 4. 형식 스팬에서 추출
        elif format_types_from_spans:
            for fmt in format_types_from_spans:
                if fmt.upper() in ext_map:
                    file_ext = ext_map[fmt.upper()]
                    logging.debug(f"형식 스팬에서 형식 확인: {fmt} -> {file_ext}")
                    break
        
        # 다운로드 버튼 찾기 (더 정확한 체크)
        has_download_btn = False
        
        # 1. 직접적인 다운로드 버튼 확인
        download_btn = item.select_one('a:contains("다운로드"), a.download-btn, a.btn-download, a[onclick*="download"]')
        if download_btn:
            has_download_btn = True
        
        # 2. 다운로드 텍스트가 있는지 확인 (더 정확한 검사)
        if not has_download_btn:
            # 화면에 "다운로드" 텍스트만 있는 것으론 충분하지 않고, 실제 클릭 가능한 요소여야 함
            download_links = [elem for elem in item.select('a, button') 
                           if '다운로드' in elem.get_text(strip=True)]
            has_download_btn = len(download_links) > 0
        
        # 3. 추가 확인: 형식 태그나 포맷 정보가 있으면 다운로드 가능할 확률이 높음
        if not has_download_btn and (format_tag or format_types_from_spans):
            # 하지만 여전히 조심스럽게 접근
            logging.debug(f"다운로드 버튼은 찾지 못했지만, 형식 정보가 있어 다운로드 가능성 있음: {title_text}")
            has_download_btn = True
        
        # 카테고리 정보 추출
        category_elem = item.select_one('p > span:first-child')
        category = category_elem.get_text(strip=True) if category_elem else None
        
        # 제공기관 정보 추출
        provider_elem = item.select_one('p:contains("제공기관") > span')
        provider = provider_elem.get_text(strip=True) if provider_elem else None
        
        # 키워드 정보 추출
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
        
        # 데이터 항목 정보 수집
        data_item = {
            'title': title_text,
            'full_title': full_title,
            'detail_url': detail_url,
            'data_id': data_id,
            'file_ext': file_ext,
            'format_types': format_types_from_spans,
            'format_tag': format_tag,
            'title_format': title_format,
            'media_type': media_type,
            'category': category,
            'provider': provider,
            'keywords': keywords,
            'update_cycle': update_cycle,
            'update_date': update_date,
            'view_count': view_count,
            'download_count': download_count,
            'has_download_btn': has_download_btn
        }
        
        return data_item
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

# 실제 파일 다운로드
async def download_file(session, download_url, detail_url, file_path):
    """실제 파일을 다운로드하는 함수"""
    try:
        async with session.get(download_url, headers={
            "Referer": detail_url,
            "Accept": "*/*"
        }) as download_response:
            status = download_response.status
            logging.debug(f"다운로드 응답 상태: {status}")
            
            if status != 200:
                return False, f"다운로드 실패: HTTP 에러 {status}"
            
            # Content-Type 및 Content-Disposition 확인
            content_type = download_response.headers.get('Content-Type', '')
            content_disp = download_response.headers.get('Content-Disposition', '')
            
            logging.debug(f"응답 Content-Type: {content_type}")
            logging.debug(f"응답 Content-Disposition: {content_disp}")
            
            # 파일 데이터 가져오기
            file_data = await download_response.read()
            logging.debug(f"수신된 데이터 크기: {len(file_data)} 바이트")
            
            # HTML 응답 검사 (에러 또는 리다이렉트 페이지)
            is_html = False
            if content_type and ('text/html' in content_type or 'application/xhtml' in content_type):
                is_html = True
            elif len(file_data) > 10 and (file_data[:10].lower().find(b'<!doctype') != -1 or file_data[:10].lower().find(b'<html') != -1):
                is_html = True
            
            if is_html:
                # HTML 응답 내용 확인하여 오류 메시지 추출 시도
                try:
                    html_text = file_data.decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html_text, 'html.parser')
                    error_msg = soup.get_text()[:200]  # 첫 200자만 추출
                    logging.error(f"HTML 응답 수신: {error_msg}...")
                    return False, "다운로드 실패: HTML 페이지가 반환됨"
                except:
                    logging.error("HTML 응답이 반환됨. 예상되는 파일 형식이 아님")
                    return False, "다운로드 실패: HTML 페이지가 반환됨"
            
            # 파일 저장
            with open(file_path, 'wb') as f:
                f.write(file_data)
            
            size = os.path.getsize(file_path)
            logging.debug(f"파일 다운로드 완료: {os.path.basename(file_path)} ({size} 바이트)")
            
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
        
        # 다운로드 버튼 확인
        if not data_item.get('has_download_btn', False):
            return False, data_item['title'], "다운로드 버튼 없음"
        
        # 제목 필터링 (전북, 전라북도, 전북특별자치도 중 하나 포함 확인)
        title = data_item.get('title', '')
        full_title = data_item.get('full_title', '')
        title_keywords = ['전북', '전라북도', '전북특별자치도']
        
        if not any(kw in title for kw in title_keywords) and not any(kw in full_title for kw in title_keywords):
            return False, title, "제목에 필요한 키워드가 포함되지 않음"
            
        # detail_url은 리퍼러로 사용하기 위해 보존
        detail_url = data_item.get('detail_url')
        if not detail_url:
            detail_url = f"https://www.data.go.kr/data/{data_id}/fileData.do"
        
        # 파일명 설정 및 경로 생성
        filename = f"{data_item['title']}.{data_item['file_ext']}"
        # 파일명에 금지된 문자 제거 (Windows 파일명으로 사용할 수 없는 문자들)
        filename = re.sub(r'[\\/*?:"<>|,]', '_', filename)  # 쉼표도 포함하여 제거
        # 연속된 언더스코어 제거 및 공백 정리
        filename = re.sub(r'_+', '_', filename)  # 연속된 언더스코어를 하나로
        filename = re.sub(r'\s+', ' ', filename)  # 연속된 공백을 하나로
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        
        # 1. 파일 다운로드 정보 URL
        file_info_url = f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataPk={data_id}&fileDetailSn=1"
        logging.debug(f"파일 메타정보 URL: {file_info_url}")
        
        # 2. 파일 ID 가져오기
        atch_file_id = None
        file_detail_sn = "1"  # 기본값
        
        try:
            async with session.get(file_info_url, headers={
                "Referer": detail_url,
                "Accept": "application/json, text/plain, */*"
            }) as info_response:
                if info_response.status != 200:
                    logging.warning(f"메타 정보 요청 실패: HTTP {info_response.status}")
                else:
                    content_type = info_response.headers.get('Content-Type', '')
                    
                    # JSON 응답인 경우
                    if 'application/json' in content_type:
                        try:
                            info_json = await info_response.json()
                            logging.debug(f"메타 정보 응답: {info_json}")
                            
                            if 'fileDataRegistVO' in info_json and info_json['fileDataRegistVO']:
                                atch_file_id = info_json['fileDataRegistVO'].get('atchFileId')
                                file_detail_sn = str(info_json['fileDataRegistVO'].get('fileDetailSn', "1"))
                            elif 'atchFileId' in info_json:
                                atch_file_id = info_json['atchFileId']
                                file_detail_sn = str(info_json.get('fileDetailSn', "1"))
                        except json.JSONDecodeError:
                            logging.warning("JSON 파싱 실패")
                    else:
                        # HTML 또는 다른 형식의 응답
                        html_content = await info_response.text()
                        logging.debug(f"비JSON 응답: {html_content[:200]}...")
        except Exception as e:
            logging.error(f"메타 정보 요청 중 오류: {str(e)}")
        
        # 파일 ID가 없으면 기본 형식으로 구성
        if not atch_file_id:
            # FILE_000000000{data_id} 형식으로 생성 (전체 길이 20자리)
            atch_file_id = f"FILE_{data_id.zfill(15)}"
            # 길이 조정 (최대 20자)
            atch_file_id = atch_file_id[-20:]
            logging.debug(f"자동 구성된 파일 ID: {atch_file_id}")
        else:
            logging.debug(f"API에서 획득한 파일 ID: {atch_file_id}, 파일 상세 일련번호: {file_detail_sn}")
        
        # 3. 실제 다운로드 URL 생성 및 다운로드 시도
        download_url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}&fileDetailSn={file_detail_sn}"
        logging.debug(f"다운로드 URL: {download_url}")
        
        # 4. 파일 다운로드
        success, result = await download_file(session, download_url, detail_url, file_path)
        
        # 첫 번째 시도가 실패하고 file_detail_sn이 "1"이면 다른 값으로 재시도
        if not success and file_detail_sn == "1":
            for retry_sn in ["0", "2", "3"]:
                logging.debug(f"첫 번째 다운로드 실패, fileDetailSn={retry_sn}로 재시도합니다.")
                retry_url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}&fileDetailSn={retry_sn}"
                success, result = await download_file(session, retry_url, detail_url, file_path)
                if success:
                    break
        
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

# 실패한 다운로드 기록
async def record_failed_download(title, reason):
    with open(FAILED_LIST_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{title}: {reason}\n")

# 필터링 함수 - 특정 조건에 맞는 데이터만 선택
def filter_data_items(items, keywords=None, formats=None, providers=None):
    """데이터 항목을 필터링하는 함수"""
    filtered_items = []
    
    # 제목에서 검색할 키워드들 (이 키워드 중 하나라도 포함되어야 함)
    title_keywords = ['전북', '전라북도', '전북특별자치도']
    
    for item in items:
        # 제목 필터링 - 제목에 주요 키워드('전북', '전라북도', '전북특별자치도')가 포함되어 있는지 확인
        if 'title' in item:
            item_title = item['title'].lower()
            item_full_title = item.get('full_title', '').lower()
            
            # 제목이나 전체 제목에 키워드가 포함되어 있는지 확인
            if not any(kw.lower() in item_title for kw in title_keywords) and \
               not any(kw.lower() in item_full_title for kw in title_keywords):
                logging.debug(f"제목 필터링: '{item['title']}' - 키워드를 포함하지 않아 제외")
                continue
        else:
            # 제목 정보가 없는 항목은 제외
            continue
        
        # 키워드 필터링 (주어진 경우)
        if keywords and 'keywords' in item and item['keywords']:
            item_keywords = ' '.join(item['keywords']).lower()
            if not any(kw.lower() in item_keywords for kw in keywords):
                logging.debug(f"키워드 필터링: '{item['title']}' - 지정된 키워드를 포함하지 않아 제외")
                continue
        
        # 형식 필터링 (주어진 경우)
        if formats and 'format_types' in item and item['format_types']:
            item_formats = [f.upper() for f in item['format_types']]
            if not any(fmt.upper() in item_formats for fmt in formats):
                logging.debug(f"형식 필터링: '{item['title']}' - 지정된 형식이 아니라 제외")
                continue
        
        # 제공기관 필터링 (주어진 경우)
        if providers and 'provider' in item and item['provider']:
            provider = item['provider'].lower()
            if not any(prov.lower() in provider for prov in providers):
                logging.debug(f"제공기관 필터링: '{item['title']}' - 지정된 제공기관이 아니라 제외")
                continue
        
        # 다운로드 버튼 확인 (다운로드 버튼이 없는 항목은 명시적으로 표시)
        if 'has_download_btn' in item and not item['has_download_btn']:
            item['_note'] = "다운로드 버튼 없음"
            logging.debug(f"다운로드 버튼 없음: '{item['title']}' - 다운로드 불가능")
        
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
    
    parser.add_argument('--debug', action='store_true',
                        help='디버그 모드 활성화 (상세 로그 출력)')
    
    return parser.parse_args()

# 데이터 수집 함수
async def collect_data(session, args):
    """페이지네이션 화면에서만 데이터를 수집하는 함수 (세부 페이지 접근 없음)"""
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
    
    print("\n" + "="*70)
    print(f"데이터 수집 시작: 총 {max_pages}개 페이지 탐색")
    print("="*70)
    
    for page_num in range(1, max_pages + 1):
        # 진행률 표시
        print_progress(page_num, max_pages, f"페이지 {page_num}")
        
        data_items = await extract_page_data(session, page_num, params)
        
        if data_items:
            logging.debug(f"페이지 {page_num}에서 {len(data_items)}개 항목 발견")
            all_items.extend(data_items)
        else:
            logging.warning(f"페이지 {page_num}에서 데이터를 찾을 수 없습니다.")
        
        # 과도한 요청 방지를 위한 딜레이
        await asyncio.sleep(random.uniform(0.5, 1.0))
    
    print("\n")  # 진행률 표시 후 줄바꿈
    
    if not all_items:
        logging.error("검색 결과가 없습니다.")
        return []
    
    logging.info(f"총 {len(all_items)}개 항목을 수집했습니다.")
    
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
    
    logging.info(f"필터링 후 {len(filtered_items)}개 항목이 남았습니다.")
    
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
    
    logging.info(f"총 {len(download_items)}개 항목 다운로드를 시작합니다.")
    print("\n" + "="*70)
    print(f"다운로드 시작: 총 {len(download_items)}개 항목")
    print("="*70)
    
    downloaded_count = 0
    skipped_count = 0
    failed_count = 0
    
    for idx, item in enumerate(download_items):
        # 진행률 표시
        title = item.get('title', '')
        print_progress(idx+1, len(download_items), title)
        
        # 다운로드 버튼이 없는 항목은 건너뛰기
        if not item.get('has_download_btn', True):
            logging.debug(f"다운로드 버튼 없음: {title} - 건너뜁니다")
            skipped_count += 1
            continue
        
        # 다운로드 시도
        success, title, result = await download_data(session, item)
        
        if success:
            print_progress(idx+1, len(download_items), title, success=True)
            logging.debug(f"다운로드 성공: {result}")
            downloaded_count += 1
        else:
            print_progress(idx+1, len(download_items), title, success=False)
            logging.error(f"다운로드 실패: {result}")
            await record_failed_download(title, result)
            failed_count += 1
        
        # 과도한 요청 방지를 위한 딜레이
        await asyncio.sleep(random.uniform(1.0, 2.0))
    
    print("\n" + "="*70)
    print(f"다운로드 결과 요약")
    print("-"*70)
    print(f"- 성공: {downloaded_count}개")
    print(f"- 실패: {failed_count}개 (상세 내용: {FAILED_LIST_FILE})")
    print(f"- 건너뜀: {skipped_count}개 (다운로드 버튼 없음)")
    print(f"- 저장 위치: '{args.download_dir}' 디렉토리")
    print("="*70)
    
    logging.info(f"다운로드 완료. 총 {downloaded_count}개 성공, {failed_count}개 실패, {skipped_count}개 건너뜀.")
    
    # 인코딩 관련 안내
    if any(item.get('file_ext', '').lower() in ['csv'] for item in download_items):
        print("* CSV 파일은 자동으로 EUC-KR/CP949 인코딩에서 UTF-8로 변환을 시도했습니다.")

# 메인 함수
async def main():
    """메인 함수 - 전체 흐름 제어"""
    # 명령행 인수 파싱
    args = parse_arguments()
    
    # 설정 변수 업데이트
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = args.download_dir
    
    # 로깅 레벨 설정 (디버그 모드 지원)
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logging.debug("디버그 모드가 활성화되었습니다.")
    else:
        logger.setLevel(logging.INFO)
    
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