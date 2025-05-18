"""
페이지네이션 기반 데이터 목록화 모듈
- 페이지네이션에서 나타나는 기본 정보만 빠르게 수집합니다.
- 세부 페이지 접근 없이 표면적 정보만 수집합니다.
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

from .config import BASE_URL, LIST_URL, REQUEST_HEADERS
from .utils import print_progress, save_metadata

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

# 단일 데이터 항목 파싱 (목록화 단계: 간단한 정보만 추출)
def parse_data_item(item):
    """검색 결과의 단일 항목에서 기본 정보만 파싱하는 함수"""
    try:
        # 제목 요소 찾기 - dt > a 요소
        title_element = item.select_one('dl dt a')
        if not title_element:
            return None
        
        # 제목 텍스트 추출
        full_title = title_element.get_text(strip=True)
        
        # 기본 제목 처리
        title_text = full_title.strip()
        
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
        
        # 파일 형식 추출 (간단히)
        format_spans = item.select('dl dt a span.data-format, dl dt a span.tagset, dl dt span.data-format, dl dt span.tagset')
        format_types = [span.get_text(strip=True) for span in format_spans if span.get_text(strip=True)]
        
        # 제공기관 정보 추출
        provider_elem = item.select_one('p:contains("제공기관") > span.data')
        provider = provider_elem.get_text(strip=True) if provider_elem else None
        
        # 다운로드 버튼 유무 확인 - 목록에서 대략적으로만 판단
        has_download_btn = False
        download_btn = item.select_one('a:contains("다운로드"), a.download-btn, a.btn-download, a[onclick*="download"]')
        if download_btn:
            has_download_btn = True
        
        # 간략 데이터 항목 정보 수집 (목록화 단계에 필요한 최소 정보)
        data_item = {
            'title': title_text,
            'detail_url': detail_url,
            'data_id': data_id,
            'format_types': format_types,
            'provider': provider,
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

# 데이터 목록화 함수
async def collect_list_data(keyword, max_pages=0):
    """페이지네이션 화면에서 기본 데이터만 수집하는 함수"""
    # 세션 생성
    async with aiohttp.ClientSession(headers=REQUEST_HEADERS) as session:
        # 검색 파라미터 설정
        params = {
            "dType": "FILE",
            "keyword": keyword,
            "operator": "AND",
            "perPage": 10
        }
        
        # 총 페이지 수 가져오기
        total_pages = await get_page_count(session, params)
        
        # max_pages가 0이면 모든 페이지 탐색
        if max_pages == 0:
            pages_to_fetch = total_pages
            logging.info(f"모든 페이지를 탐색합니다. (총 {total_pages} 페이지)")
        else:
            pages_to_fetch = min(total_pages, max_pages)
            logging.info(f"총 {total_pages} 페이지 중 {pages_to_fetch} 페이지까지 처리합니다.")
        
        # 모든 페이지 순회하며 데이터 수집
        all_items = []
        
        print("\n" + "="*70)
        print(f"데이터 목록화 시작: 총 {pages_to_fetch}개 페이지 탐색")
        print("="*70)
        
        for page_num in range(1, pages_to_fetch + 1):
            # 진행률 표시
            print_progress(page_num, pages_to_fetch, f"페이지 {page_num}")
            
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
        
        # 메타데이터 저장
        if all_items:
            metadata_file = "data_list.json"  # 목록화 결과 저장 파일
            save_metadata(all_items, metadata_file)
            logging.info(f"모든 목록 데이터가 '{metadata_file}'에 저장되었습니다.")
        
        return all_items 