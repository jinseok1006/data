"""
데이터 파일 다운로드 모듈
"""

import asyncio
import aiohttp
import os
import logging
import json
import time
import random
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .config import BASE_URL, REQUEST_HEADERS, DOWNLOAD_BASE_DIR, EXT_MAP
from .utils import print_progress, save_metadata, convert_encoding, sanitize_filename, record_failed_item, load_metadata

# 실패 항목 기록 파일
FAILED_LIST_FILE = "failed_downloads.txt"

# 파일 확장자 결정 함수
def determine_file_extension(data_item):
    """데이터 항목에서 파일 확장자를 결정하는 함수"""
    # 기본 파일 형식 설정
    file_ext = 'csv'  # 기본값
    
    # 1. 매체유형 기반 파일 형식 힌트 (이미지/사진인 경우 jpg로 가정)
    media_type = data_item.get('media_type')
    if media_type in ['이미지', '사진']:
        file_ext = 'jpg'  # 이미지/사진인 경우 기본값을 jpg로 설정
    
    # 2. 포맷 태그 기반
    format_types = data_item.get('format_types', [])
    if format_types:
        for fmt in format_types:
            if fmt.upper() in EXT_MAP:
                file_ext = EXT_MAP[fmt.upper()]
                logging.debug(f"형식 태그에서 형식 확인: {fmt} -> {file_ext}")
                break
    
    # 3. 세부 페이지에서 획득한 정보 활용
    if 'file_detail_id' in data_item:
        # 일반적으로 파일명에서 확장자를 추출할 수 있음
        file_id = data_item.get('file_detail_id', '')
        if '.' in file_id:
            ext = file_id.split('.')[-1].lower()
            if ext in ['csv', 'xlsx', 'xls', 'json', 'xml', 'hwp', 'pdf', 'docx', 'hwpx']:
                file_ext = ext
                logging.debug(f"파일 ID에서 확장자 추출: {ext}")
    
    return file_ext

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
            
            # Content-Disposition 헤더에서 파일명 추출 시도
            original_ext = None
            if content_disp and 'filename=' in content_disp:
                filename_match = re.search(r'filename=["\'](.*?)["\']', content_disp)
                if not filename_match:
                    filename_match = re.search(r'filename=(.*?)(;|$)', content_disp)
                
                if filename_match:
                    original_filename = filename_match.group(1).strip()
                    logging.debug(f"서버 제공 파일명: {original_filename}")
                    
                    # 파일명에서 확장자만 추출
                    if '.' in original_filename:
                        original_ext = original_filename.split('.')[-1].lower()
                        logging.info(f"서버 제공 확장자 추출: {original_ext}")
            
            # 서버에서 확장자를 추출했다면 파일 경로 업데이트
            if original_ext:
                # 기존 경로에서 디렉토리 부분 추출
                dir_path = os.path.dirname(file_path)
                # "data.확장자" 형식으로 새 파일 경로 구성
                new_file_path = os.path.join(dir_path, f"data.{original_ext}")
                logging.info(f"서버 제공 확장자 사용: data.{original_ext}")
                file_path = new_file_path
            
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
            
            # 디렉토리 생성 (혹시 모를 누락 방지)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
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
async def download_item(session, data_item):
    """데이터 항목 하나를 다운로드하는 함수"""
    try:
        # 필수 정보 확인
        data_id = data_item.get('data_id')
        if not data_id:
            return False, data_item['title'], "데이터 ID 없음"
        
        # 다운로드 버튼 확인
        if not data_item.get('has_download_btn', False):
            return False, data_item['title'], "다운로드 버튼 없음"
        
        # detail_url은 리퍼러로 사용하기 위해 보존
        detail_url = data_item.get('detail_url')
        if not detail_url:
            detail_url = f"https://www.data.go.kr/data/{data_id}/fileData.do"
        
        # 파일 확장자 결정
        file_ext = determine_file_extension(data_item)
        
        # 데이터 별 디렉토리 생성
        data_dir = os.path.join(DOWNLOAD_BASE_DIR, data_id)
        os.makedirs(data_dir, exist_ok=True)
        
        # 데이터 파일 경로 설정
        data_file_path = os.path.join(data_dir, f"data.{file_ext}")
        
        # 메타데이터 파일 경로 설정
        metadata_file_path = os.path.join(data_dir, "metadata.json")
        
        # 1. 파일 다운로드 정보 URL
        file_info_url = f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataPk={data_id}&fileDetailSn=1"
        logging.debug(f"파일 메타정보 URL: {file_info_url}")
        
        # 2. 파일 ID 가져오기
        atch_file_id = None
        file_detail_sn = "1"  # 기본값
        
        # 1단계: API 호출로 파일 ID 정보 획득 시도 (우선 처리)
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
        
        # 2단계: API에서 정보를 얻지 못한 경우, 메타데이터의 file_detail_id에서 추출 시도
        if not atch_file_id and 'file_detail_id' in data_item:
            file_id_info = data_item.get('file_detail_id', '')
            logging.debug(f"메타데이터에서 파일 상세 ID: {file_id_info}")
            
            if file_id_info:
                # 'uddi:' 접두사 제거
                clean_id = file_id_info.replace('uddi:', '')
                
                # '_' 기준으로 분리
                parts = clean_id.split('_')
                
                if len(parts) >= 2:
                    # 첫 번째 부분을 atch_file_id로, 두 번째 부분을 file_detail_sn으로 처리
                    atch_file_id = parts[0]
                    second_part = parts[1]
                    
                    # 두 번째 부분에 '.' 포함 여부 확인 (확장자가 있는 경우)
                    file_detail_sn = second_part.split('.')[0] if '.' in second_part else second_part
                else:
                    # '_'가 없으면 전체를 atch_file_id로 사용
                    atch_file_id = clean_id
                    # file_detail_sn은 기본값(1) 유지
                
                logging.debug(f"메타데이터에서 추출한 파일 정보: ID={atch_file_id}, SN={file_detail_sn}")
        
        # 3단계: 이전 단계에서도 파일 ID를 얻지 못한 경우 기본 형식으로 생성
        if not atch_file_id:
            # FILE_000000000{data_id} 형식으로 생성 (전체 길이 20자리)
            atch_file_id = f"FILE_{data_id.zfill(15)}"
            # 길이 조정 (최대 20자)
            atch_file_id = atch_file_id[-20:]
            logging.debug(f"자동 구성된 파일 ID: {atch_file_id}")
        else:
            logging.debug(f"획득한 파일 ID: {atch_file_id}, 파일 상세 일련번호: {file_detail_sn}")
        
        # 3. 실제 다운로드 URL 생성 및 다운로드 시도
        download_url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}&fileDetailSn={file_detail_sn}"
        logging.debug(f"다운로드 URL: {download_url}")
        
        # 4. 파일 다운로드
        success, result = await download_file(session, download_url, detail_url, data_file_path)
        
        # 첫 번째 시도가 실패하면 다양한 file_detail_sn 값으로 재시도
        if not success:
            # 첫 번째 시도가 실패한 경우 다른 file_detail_sn 값으로 재시도
            retry_sns = ["0", "2", "3"]
            if file_detail_sn in retry_sns:
                # 이미 시도한 값이면 목록에서 제거
                retry_sns.remove(file_detail_sn)
            # 아직 시도하지 않은 "1"도 추가
            if file_detail_sn != "1":
                retry_sns.append("1")
                
            logging.debug(f"다운로드 실패, 다른 fileDetailSn 값으로 재시도: {retry_sns}")
            
            # 다양한 fileDetailSn 값으로 재시도
            for retry_sn in retry_sns:
                retry_url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch_file_id}&fileDetailSn={retry_sn}"
                logging.debug(f"재시도 URL: {retry_url}")
                success, result = await download_file(session, retry_url, detail_url, data_file_path)
                if success:
                    logging.info(f"fileDetailSn={retry_sn}로 다운로드 성공")
                    break
        
        if not success:
            # 모든 시도가 실패한 경우 API 구조가 변경되었을 수 있음
            logging.error(f"모든 다운로드 시도 실패: {result}")
            
            # 데이터 ID로 직접 다운로드 URL 시도 (마지막 수단)
            last_resort_url = f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?publicDataPk={data_id}&file_detail_sn=1"
            logging.debug(f"최종 시도 URL: {last_resort_url}")
            success, result = await download_file(session, last_resort_url, detail_url, data_file_path)
            
            if not success:
                return False, data_item['title'], result
        
        # CSV 파일인 경우 인코딩 변환 시도
        if file_ext.lower() in ['csv']:
            convert_encoding(data_file_path)
        
        # 메타데이터 저장
        download_info = {
            'download_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'file_path': data_file_path,
            'file_size': os.path.getsize(data_file_path),
            'file_ext': file_ext,
            'atch_file_id': atch_file_id,
            'file_detail_sn': file_detail_sn
        }
        
        # 기존 메타데이터와 다운로드 정보 결합
        metadata = data_item.copy()
        metadata['download_info'] = download_info
        
        # 메타데이터 저장
        save_metadata(metadata, metadata_file_path)
        
        return True, data_item['title'], data_dir
    
    except Exception as e:
        logging.error(f"다운로드 오류: {str(e)}")
        return False, data_item['title'], str(e)

# 필터링된 데이터 기반 다운로드
async def download_filtered_data(filtered_file="data_detail.json", num_downloads=0, selected_ids=None):
    """상세정보 데이터 파일에서 항목을 로드하여 다운로드하는 함수"""
    # 상세정보 데이터 파일 로드
    items = load_metadata(filtered_file)
    if not items:
        logging.error(f"세부정보 데이터 파일을 로드할 수 없습니다: {filtered_file}")
        return [], [], []
    
    logging.info(f"세부정보 데이터 파일에서 {len(items)}개 항목을 로드했습니다.")
    
    # 다운로드할 항목 선택
    if selected_ids:
        # 선택된 ID에 해당하는 항목만 필터링
        download_items = [item for item in items if item.get('data_id') in selected_ids]
        logging.info(f"선택된 {len(download_items)}개 항목을 다운로드합니다.")
    else:
        # 개수 제한
        if num_downloads > 0:
            download_items = items[:min(len(items), num_downloads)]
            logging.info(f"처음 {len(download_items)}개 항목을 다운로드합니다.")
        else:
            download_items = items
            logging.info(f"모든 {len(download_items)}개 항목을 다운로드합니다.")
    
    # 다운로드 디렉토리 생성
    os.makedirs(DOWNLOAD_BASE_DIR, exist_ok=True)
    
    # 세션 생성
    async with aiohttp.ClientSession(headers=REQUEST_HEADERS) as session:
        print("\n" + "="*70)
        print(f"다운로드 시작: 총 {len(download_items)}개 항목")
        print("="*70)
        
        downloaded = []
        failed = []
        skipped = []
        
        for idx, item in enumerate(download_items):
            # 진행률 표시
            title = item.get('title', '')
            print_progress(idx+1, len(download_items), title)
            
            # 다운로드 버튼이 없는 항목은 건너뛰기
            if not item.get('has_download_btn', True):
                logging.debug(f"다운로드 버튼 없음: {title} - 건너뜁니다")
                skipped.append({
                    'title': title,
                    'data_id': item.get('data_id', ''),
                    'reason': '다운로드 버튼 없음'
                })
                continue
            
            # 다운로드 시도
            success, title, result = await download_item(session, item)
            
            if success:
                print_progress(idx+1, len(download_items), title, success=True)
                logging.debug(f"다운로드 성공: {result}")
                downloaded.append({
                    'data_id': item.get('data_id', ''),
                    'title': title,
                    'dir_path': result
                })
            else:
                print_progress(idx+1, len(download_items), title, success=False)
                logging.error(f"다운로드 실패: {result}")
                record_failed_item(FAILED_LIST_FILE, title, result)
                failed.append({
                    'data_id': item.get('data_id', ''),
                    'title': title,
                    'reason': result
                })
            
            # 과도한 요청 방지를 위한 딜레이
            await asyncio.sleep(random.uniform(1.0, 2.0))
        
        # 다운로드 결과 저장
        download_results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_attempts': len(download_items),
            'success_count': len(downloaded),
            'failed_count': len(failed),
            'skipped_count': len(skipped),
            'success_items': downloaded,
            'failed_items': failed,
            'skipped_items': skipped
        }
        
        download_results_file = "download_results.json"
        save_metadata(download_results, download_results_file)
        logging.info(f"다운로드 결과가 '{download_results_file}'에 저장되었습니다.")
        
        return downloaded, failed, skipped 