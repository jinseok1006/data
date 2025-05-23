"""
파일 서버 업로드 모듈
"""

import os
import glob
import logging
import json
import time
import asyncio
import requests
import functools
from urllib.parse import urljoin, unquote, quote

from .config import FILE_SERVER, DOWNLOAD_BASE_DIR
from .utils import print_progress, save_metadata, load_metadata

# 업로드 결과 저장 파일
UPLOAD_RESULTS_FILE = "upload_results.json"
# 업로드 정보 디렉토리 (원본 다운로드 디렉토리와 분리)
UPLOAD_INFO_DIR = "upload_info"

# 업로드 여부 확인
def is_already_uploaded(data_id):
    """이미 업로드된 항목인지 확인하는 함수"""
    try:
        # 1. 별도 디렉토리의 업로드 정보 파일 확인
        if not os.path.exists(UPLOAD_INFO_DIR):
            os.makedirs(UPLOAD_INFO_DIR, exist_ok=True)
        
        upload_info_file = os.path.join(UPLOAD_INFO_DIR, f"{data_id}.json")
        if os.path.exists(upload_info_file):
            logging.debug(f"항목 {data_id}에 대한 업로드 정보 파일이 존재합니다.")
            upload_info = load_metadata(upload_info_file)
            # 업로드 성공 확인
            return upload_info and upload_info.get('server_response', {}).get('success', False)
        
        # 2. 기존 전체 업로드 결과 파일 확인
        if not os.path.exists(UPLOAD_RESULTS_FILE):
            return False
            
        upload_results = load_metadata(UPLOAD_RESULTS_FILE)
        if not upload_results or 'success_items' not in upload_results:
            return False
        
        # 업로드 성공 항목에 포함되어 있는지 확인
        return any(item.get('data_id') == data_id for item in upload_results.get('success_items', []))
    except Exception as e:
        logging.error(f"업로드 상태 확인 오류: {str(e)}")
        return False

# 단일 파일 업로드
async def upload_item(data_dir, custom_filename=None):
    """단일 항목을 파일 서버에 업로드하는 함수 (requests 사용)
    
    Args:
        data_dir: 데이터 디렉토리 경로
        custom_filename: 업로드 시 사용할 커스텀 파일명 (None인 경우 원본 파일명 사용)
    """
    try:
        # 데이터 ID 추출
        data_id = os.path.basename(data_dir)
        
        # 이미 업로드된 항목인지 확인
        if is_already_uploaded(data_id):
            logging.info(f"항목 {data_id}은(는) 이미 업로드되었습니다. 건너뜁니다.")
            return False, data_id, "이미 업로드됨"
        
        # 메타데이터 파일 경로
        metadata_file = os.path.join(data_dir, "metadata.json")
        
        # 업로드 정보 디렉토리 확인
        if not os.path.exists(UPLOAD_INFO_DIR):
            os.makedirs(UPLOAD_INFO_DIR, exist_ok=True)
        
        # 업로드 정보 파일 경로 (별도 디렉토리에 저장)
        upload_info_file = os.path.join(UPLOAD_INFO_DIR, f"{data_id}.json")
        
        # 메타데이터 로드 (읽기 전용)
        metadata = load_metadata(metadata_file)
        if not metadata:
            return False, data_id, "메타데이터 로드 실패"
        
        # 데이터 파일 찾기
        data_files = glob.glob(os.path.join(data_dir, "data.*"))
        if not data_files:
            return False, data_id, "데이터 파일을 찾을 수 없음"
        
        data_file = data_files[0]  # 첫 번째 데이터 파일 사용
        
        # 파일 확장자 확인 - .zip 파일 필터링
        file_ext = os.path.splitext(data_file)[1].lower()
        if file_ext == '.zip':
            logging.warning(f"ZIP 파일은 업로드하지 않습니다: {data_file}")
            return False, data_id, "ZIP 파일 업로드 제외 (정책상 필터링됨)"
        
        # 메타데이터의 파일 형식과 실제 파일 확장자 비교
        meta_file_format = metadata.get('file_format', '').lower()
        format_mismatch = False
        
        if meta_file_format and not file_ext.endswith(meta_file_format):
            logging.warning(f"메타데이터 파일 형식({meta_file_format})과 실제 파일 확장자({file_ext})가 다릅니다: {data_file}")
            format_mismatch = True
            # 메타데이터는 수정하지 않고 로그만 남김
        
        # 업로드 요청 데이터 구성
        upload_url = FILE_SERVER['api_url']
        
        # 업로드 메타데이터 준비 (필요한 필드만 선택적으로 포함)
        upload_metadata = {
            # 기본 정보
            'title': metadata.get('title', ''),
            'data_id': data_id,
            'provider': metadata.get('provider', ''),
            
            # 파일 정보
            'file_data_name': metadata.get('file_data_name', ''),
            'category': metadata.get('category', ''),
            'extension': metadata.get('extension', ''),
            'update_cycle': metadata.get('update_cycle', ''),
            'register_date': metadata.get('register_date', ''),
            'update_date': metadata.get('update_date', ''),
            
            # 내용 정보
            'keywords': metadata.get('keywords', []),
            'description': metadata.get('description', ''),
            'provision_type': metadata.get('provision_type', ''),
            'license': metadata.get('license', ''),
            
            # 관리 정보
            'department': metadata.get('department', ''),
            'contact_phone': metadata.get('contact_phone', ''),
            
            # 업로드 시간 추가
            'upload_timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 디버깅: 업로드 메타데이터 로깅
        logging.info(f"업로드 메타데이터 필드: {', '.join(upload_metadata.keys())}")
        
        # 업로드 메타데이터를 디버그 파일로 저장
        debug_upload_dir = "debug_uploads"
        if not os.path.exists(debug_upload_dir):
            os.makedirs(debug_upload_dir, exist_ok=True)
        
        debug_file = os.path.join(debug_upload_dir, f"upload_metadata_{data_id}.json")
        with open(debug_file, 'w', encoding='utf-8') as f:
            json.dump(upload_metadata, f, ensure_ascii=False, indent=2)
        logging.info(f"업로드 메타데이터를 {debug_file}에 저장했습니다.")
        
        # 파일과 메타데이터 함께 전송 (requests 스타일로 변경)
        
        # 설명 추출 - description 필드 사용 (없으면 빈 문자열)
        description_str = metadata.get('description', '')
        if not description_str:
            # description이 없으면 title 사용
            description_str = metadata.get('title', '')
        
        # 필수 메타데이터만 auto_description에 추가
        auto_description_str = json.dumps(upload_metadata, ensure_ascii=False)
        
        # 파일 첨부
        with open(data_file, 'rb') as f_content:
            file_content_bytes = f_content.read()
            
            # 파일명 설정 (메타데이터의 파일 이름 또는 커스텀 파일명 사용)
            if custom_filename:
                # 커스텀 파일명을 사용하되, 원본 파일의 확장자 유지
                filename_intermediate = f"{custom_filename}{file_ext}"
            else:
                # 메타데이터에서 파일 이름 찾기 - 여러 가능한 필드 확인
                file_name_from_meta = None
                
                # 가능한 메타데이터 필드들을 우선순위 순으로 확인
                file_name_fields = [
                    'file_data_name',        # 기본 필드
                    'originalFileName',      # 원본 파일명 필드
                    'original_file_name',    # 다른 형식의 원본 파일명
                    'fileName',              # 파일명
                    'file_name',             # 또 다른 형식의 파일명
                    'dataName',              # 데이터 이름
                    'data_name'              # 또 다른 데이터 이름
                ]
                
                # 모든 가능한 필드를 확인
                for field in file_name_fields:
                    if metadata.get(field):
                        file_name_from_meta = metadata[field]
                        logging.debug(f"메타데이터에서 '{field}' 필드로 파일명 '{file_name_from_meta}'을(를) 찾았습니다.")
                        break
                
                if file_name_from_meta:
                    # 찾은 파일 이름에서 안전한 파일명 생성
                    # 이 단계에서는 아직 URL 디코딩 전일 수 있음
                    safe_name_temp = ''.join(c for c in file_name_from_meta if c.isalnum() or c in ' _-.')
                    safe_name_temp = safe_name_temp.replace(' ', '_')
                    
                    # 확장자 처리 - 이미 있으면 그대로 유지, 없으면 현재 파일 확장자 추가
                    if '.' in safe_name_temp:
                        filename_intermediate = safe_name_temp
                    else:
                        filename_intermediate = f"{safe_name_temp}{file_ext}"
                else:
                    # 파일 이름 필드가 없으면 데이터 ID와 제목 조합
                    title_from_meta = metadata.get('title', '') # title도 URL 인코딩되어 있을 수 있음
                    if title_from_meta:
                        # 제목에서 안전한 파일명 생성
                        safe_title_temp = ''.join(c for c in title_from_meta if c.isalnum() or c in ' _-')
                        safe_title_temp = safe_title_temp.replace(' ', '_')
                        safe_title_temp = safe_title_temp[:50]  # 너무 긴 제목 방지
                        filename_intermediate = f"{data_id}_{safe_title_temp}{file_ext}"
                    else:
                        # 제목이 없으면 데이터 ID만 사용
                        filename_intermediate = f"{data_id}{file_ext}"

            # filename_intermediate는 메타데이터와 실제 파일 확장자를 조합한
            # 순수 한글 파일명 + 확장자 (예: "전북특별자치도_임상별_임목축적_20111231.csv")
            final_filename = filename_intermediate

            # 서버에 전달할 파일명: Python 유니코드 문자열 그대로 사용
            # requests는 이 파일명을 Content-Disposition 헤더의 filename 파라미터로 사용 (필요시 인코딩)
            filename_to_send = final_filename

            logging.info(f"최종 한글 파일명 (final_filename): {final_filename}")
            logging.info(f"requests에 전달할 파일명 (filename_to_send): '{filename_to_send}'")

            # 파일 확장자에 따른 Content-Type 결정 (이전 로직 유지)
            content_type = 'application/octet-stream' # 기본값
            if file_ext == '.csv':
                content_type = 'text/csv'
            elif file_ext == '.json':
                content_type = 'application/json'
            elif file_ext == '.xml':
                content_type = 'application/xml'
            elif file_ext in ['.png', '.jpg', '.jpeg', '.gif']:
                content_type = f'image/{file_ext[1:]}'
            elif file_ext == '.pdf':
                content_type = 'application/pdf'

            # requests 페이로드 구성
            files_payload = {
                'file': (filename_to_send, file_content_bytes, content_type)
            }
            data_payload = {
                'description': description_str,
                'auto_description': auto_description_str
            }
            
            logging.info(f"파일 업로드 준비 완료 (파일명: {final_filename}, 서버 전달명: {filename_to_send}, Content-Type: {content_type})")

        # 업로드 요청 (requests 사용, asyncio.to_thread로 래핑)
        try:
            # functools.partial을 사용하여 requests.post 호출을 준비합니다.
            # 이렇게 하면 asyncio.to_thread에 하나의 callable과 해당 인자들만 전달할 수 있습니다.
            blocking_post_call = functools.partial(
                requests.post,
                upload_url,
                files=files_payload,
                data=data_payload,
                headers={}, # 빈 헤더 전달 (기존 코드 유지)
                timeout=FILE_SERVER['timeout']
            )
            response = await asyncio.to_thread(blocking_post_call)
            
            # 응답 상태 코드 확인
            if response.status_code != 200 and response.status_code != 201:
                error_text = response.text
                logging.error(f"업로드 실패: HTTP {response.status_code}, {error_text}")
                return False, data_id, f"업로드 실패: HTTP {response.status_code}"

            # 응답 처리
            response_data = response.json()

            # 업로드 정보 구성 (원본 다운로드 디렉토리는 건드리지 않음)
            upload_info = {
                'data_id': data_id,
                'upload_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'server_response': response_data,
                'uploaded_filename_as_sent': filename_to_send, # requests에 전달한 형태
                'decoded_filename': final_filename,                     # 우리가 의도한 최종 한글 파일명
                'original_filename_in_metadata': filename_intermediate, # 디코딩 전 메타데이터에서 가져온 원본
                'format_mismatch': format_mismatch,
                'original_dir_path': data_dir
            }

            if format_mismatch:
                upload_info['meta_file_format'] = meta_file_format
                upload_info['real_file_ext'] = file_ext

            # 업로드 정보를 별도 디렉토리에 저장
            save_metadata(upload_info, upload_info_file)
            logging.info(f"업로드 정보가 {upload_info_file}에 저장되었습니다.")

            # 성공 처리 - 실제 파일명을 함께 로그에 표시
            title_for_log = metadata.get('title', f"ID:{data_id}") # 로그용 title은 그대로 유지 가능
            logging.info(f"파일명(업로드 시도됨, requests 전달값): {filename_to_send}, 파일명(로깅/메타용): {final_filename}")
            return True, title_for_log, upload_info

        except requests.exceptions.RequestException as e: # requests 관련 예외 처리
            logging.error(f"requests 라이브러리 오류: {str(e)}")
            return False, data_id, f"requests 오류: {str(e)}"
        except Exception as e: # 일반적인 응답 처리 오류 (예: json 파싱 실패)
            logging.error(f"응답 처리 오류: {str(e)}")
            return False, data_id, f"응답 처리 오류: {str(e)}"
        
    except Exception as e:
        logging.error(f"업로드 오류: {str(e)}")
        return False, data_id, str(e)

# 다운로드 결과 기반 업로드
# async def upload_from_download_results(download_results_file=None, selected_ids=None, custom_filename=None):
#     """다운로드 결과에서 성공한 항목들을 업로드하는 함수
#     
#     Args:
#         download_results_file: 다운로드 결과 파일 경로
#         selected_ids: 선택적으로 업로드할 데이터 ID 목록
#         custom_filename: 업로드 시 사용할 커스텀 파일명 (None인 경우 원본 파일명 사용)
#     """
#     # 다운로드 결과 파일이 지정되지 않은 경우 기본값 사용
#     if not download_results_file:
#         download_results_file = "download_results.json"
#     
#     # 다운로드 결과 로드
#     download_results = load_metadata(download_results_file)
#     if not download_results or 'success_items' not in download_results:
#         logging.error(f"다운로드 결과 파일을 로드할 수 없거나 유효하지 않습니다: {download_results_file}")
#         return [], []
#     
#     # 업로드할 항목 선택
#     if selected_ids:
#         # 선택된 ID에 해당하는 항목만 필터링
#         upload_items = [item for item in download_results['success_items'] 
#                         if item.get('data_id') in selected_ids]
#         logging.info(f"선택된 {len(upload_items)}개 항목을 업로드합니다.")
#     else:
#         # 모든 성공 항목 업로드
#         upload_items = download_results['success_items']
#         logging.info(f"다운로드 성공한 모든 {len(upload_items)}개 항목을 업로드합니다.")
#     
#     # 업로드 정보 디렉토리 확인 및 생성
#     if not os.path.exists(UPLOAD_INFO_DIR):
#         os.makedirs(UPLOAD_INFO_DIR, exist_ok=True)
#         
#     # 세션 생성
#     async with aiohttp.ClientSession() as session:
#         print("\n" + "="*70)
#         print(f"업로드 시작: 총 {len(upload_items)}개 항목")
#         print("="*70)
#         
#         uploaded = []
#         failed = []
#         filtered_zip = []  # ZIP 파일 필터링 항목
#         format_mismatch = []  # 형식 불일치 항목
#         
#         for idx, item in enumerate(upload_items):
#             # 진행률 표시
#             data_id = item.get('data_id', '')
#             title = item.get('title', f"ID:{data_id}")
#             dir_path = item.get('dir_path', os.path.join(DOWNLOAD_BASE_DIR, data_id))
#             
#             print_progress(idx+1, len(upload_items), title)
#             
#             # 업로드 시도
#             success, result_title, result = await upload_item(dir_path, custom_filename)
#             
#             if success:
#                 print_progress(idx+1, len(upload_items), result_title, success=True)
#                 logging.debug(f"업로드 성공: {result}")
#                 uploaded.append({
#                     'data_id': data_id,
#                     'title': result_title,
#                     'upload_info': result
#                 })
#             else:
#                 print_progress(idx+1, len(upload_items), title, success=False)
#                 logging.error(f"업로드 실패: {result}")
#                 
#                 # 실패 원인에 따른 분류
#                 if "ZIP 파일 업로드 제외" in str(result):
#                     filtered_zip.append({
#                         'data_id': data_id,
#                         'title': title,
#                         'reason': result
#                     })
#                 else:
#                     failed.append({
#                         'data_id': data_id,
#                         'title': title,
#                         'reason': result
#                     })
#                 
#                 # 형식 불일치 여부 체크 (별도 디렉토리에서)
#                 upload_info_file = os.path.join(UPLOAD_INFO_DIR, f"{data_id}.json")
#                 if os.path.exists(upload_info_file):
#                     upload_info = load_metadata(upload_info_file)
#                     if upload_info and upload_info.get('format_mismatch'):
#                         format_mismatch.append({
#                             'data_id': data_id,
#                             'title': title,
#                             'meta_format': upload_info.get('meta_file_format', ''),
#                             'real_ext': upload_info.get('real_file_ext', '')
#                         })
#             
#             # 과도한 요청 방지를 위한 딜레이
#             await asyncio.sleep(1.0)
#         
#         # 업로드 결과 저장
#         upload_results = {
#             'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
#             'total_attempts': len(upload_items),
#             'success_count': len(uploaded),
#             'failed_count': len(failed),
#             'filtered_zip_count': len(filtered_zip),
#             'format_mismatch_count': len(format_mismatch),
#             'success_items': uploaded,
#             'failed_items': failed,
#             'filtered_zip_items': filtered_zip,
#             'format_mismatch_items': format_mismatch
#         }
#         
#         save_metadata(upload_results, UPLOAD_RESULTS_FILE)
#         logging.info(f"업로드 결과가 '{UPLOAD_RESULTS_FILE}'에 저장되었습니다.")
#         
#         return uploaded, failed

# 디렉토리 기반 업로드
async def upload_from_directory(selected_ids=None, custom_filename=None, retry_failed=False):
    """다운로드 디렉토리에서 직접 항목들을 업로드하는 함수 (requests 사용)
    
    Args:
        selected_ids: 선택적으로 업로드할 데이터 ID 목록
        custom_filename: 업로드 시 사용할 커스텀 파일명 (None인 경우 원본 파일명 사용)
        retry_failed: 이전에 실패한 항목 재시도 여부
    """
    # 다운로드 디렉토리 내 모든 하위 디렉토리 확인
    if not os.path.exists(DOWNLOAD_BASE_DIR):
        logging.error(f"다운로드 디렉토리가 존재하지 않습니다: {DOWNLOAD_BASE_DIR}")
        return [], []
    
    # 이전에 실패한 항목 로드 (retry_failed=True인 경우에만)
    failed_ids = []
    if retry_failed and os.path.exists(UPLOAD_RESULTS_FILE):
        try:
            upload_results = load_metadata(UPLOAD_RESULTS_FILE)
            if upload_results and 'failed_items' in upload_results:
                failed_ids = [item.get('data_id') for item in upload_results.get('failed_items', [])
                              if "ZIP 파일 업로드 제외" not in item.get('reason', '')]
                logging.info(f"이전에 실패한 {len(failed_ids)}개 항목을 재시도합니다.")
        except Exception as e:
            logging.error(f"이전 실패 항목 로드 오류: {str(e)}")
    
    # 모든 데이터 디렉토리 가져오기
    data_dirs = [d for d in glob.glob(os.path.join(DOWNLOAD_BASE_DIR, "*")) 
                 if os.path.isdir(d) and os.path.exists(os.path.join(d, "metadata.json"))]
    
    # 업로드할 항목 선택
    if selected_ids:
        # 선택된 ID에 해당하는 디렉토리만 필터링
        upload_dirs = [d for d in data_dirs if os.path.basename(d) in selected_ids]
        logging.info(f"선택된 {len(upload_dirs)}개 항목을 업로드합니다.")
    elif retry_failed and failed_ids:
        # 이전에 실패한 ID에 해당하는 디렉토리만 필터링
        upload_dirs = [d for d in data_dirs if os.path.basename(d) in failed_ids]
        logging.info(f"이전에 실패한 {len(upload_dirs)}개 항목을 재시도합니다.")
    else:
        # 모든 디렉토리 업로드
        upload_dirs = data_dirs
        logging.info(f"모든 {len(upload_dirs)}개 항목을 업로드합니다.")
    
    # 업로드할 항목이 없으면 종료
    if not upload_dirs:
        logging.info("업로드할 항목이 없습니다.")
        return [], []
    
    # 업로드 정보 디렉토리 확인 및 생성
    if not os.path.exists(UPLOAD_INFO_DIR):
        os.makedirs(UPLOAD_INFO_DIR, exist_ok=True)
    
    # 세션 생성 (aiohttp.ClientSession() 제거)
    # requests는 일반적으로 개별 요청에 세션을 명시적으로 넘기지 않거나,
    # requests.Session() 객체를 만들어 사용할 수 있으나, 여기서는 upload_item 내부에서 직접 처리
    
    print("\n" + "="*70)
    print(f"업로드 시작: 총 {len(upload_dirs)}개 항목 (requests 사용)")
    print("="*70)
    
    uploaded = []
    failed = []
    filtered_zip = []  # ZIP 파일 필터링 항목
    format_mismatch = []  # 형식 불일치 항목
    
    # 병렬 업로드를 위한 세마포어 (동시 요청 제한)
    semaphore = asyncio.Semaphore(3)  # 최대 3개 동시 업로드
    
    # 각 디렉토리 처리를 위한 태스크 생성
    async def process_directory(idx, dir_path):
        async with semaphore:  # 세마포어 사용하여 동시 요청 제한
            # 데이터 ID
            data_id = os.path.basename(dir_path)
            
            # 이미 업로드된 항목인지 확인하고, 업로드된 경우 건너뛰기
            if is_already_uploaded(data_id) and not retry_failed:
                logging.info(f"항목 {data_id}은(는) 이미 업로드되었습니다. 건너뜁니다.")
                return {
                    'status': 'skipped',
                    'idx': idx,
                    'data_id': data_id,
                    'title': f"ID:{data_id}",
                    'reason': "이미 업로드됨"
                }
            
            # 메타데이터 로드 (읽기 전용)
            metadata_file = os.path.join(dir_path, "metadata.json")
            metadata = load_metadata(metadata_file)
            title = metadata.get('title', f"ID:{data_id}") if metadata else f"ID:{data_id}"
            
            # 진행률 표시
            print_progress(idx+1, len(upload_dirs), title)
            
            # 업로드 시도 (session 인자 없이 호출)
            success, result_title, result = await upload_item(dir_path, custom_filename)
            
            if success:
                print_progress(idx+1, len(upload_dirs), result_title, success=True)
                logging.info(f"업로드 성공: {result_title}")
                return {
                    'status': 'success',
                    'idx': idx,
                    'data_id': data_id,
                    'title': result_title,
                    'upload_info': result
                }
            else:
                print_progress(idx+1, len(upload_dirs), title, success=False)
                logging.error(f"업로드 실패: {result}")
                
                # ZIP 파일 필터링 확인
                if "ZIP 파일 업로드 제외" in str(result):
                    return {
                        'status': 'filtered_zip',
                        'idx': idx,
                        'data_id': data_id,
                        'title': title,
                        'reason': result
                    }
                
                # 형식 불일치 확인
                upload_info_file = os.path.join(UPLOAD_INFO_DIR, f"{data_id}.json")
                if os.path.exists(upload_info_file):
                    upload_info = load_metadata(upload_info_file)
                    if upload_info and upload_info.get('format_mismatch'):
                        return {
                            'status': 'format_mismatch',
                            'idx': idx,
                            'data_id': data_id,
                            'title': title,
                            'meta_format': upload_info.get('meta_file_format', ''),
                            'real_ext': upload_info.get('real_file_ext', ''),
                            'reason': result
                        }
                
                # 일반 실패
                return {
                    'status': 'failed',
                    'idx': idx,
                    'data_id': data_id,
                    'title': title,
                    'reason': result
                }
    
    # 모든 디렉토리 동시 처리
    tasks = [process_directory(idx, dir_path) for idx, dir_path in enumerate(upload_dirs)]
    results = await asyncio.gather(*tasks)
    
    # 결과 분류
    for result in sorted(results, key=lambda x: x.get('idx', 0)):
        status = result.get('status')
        if status == 'success':
            uploaded.append({
                'data_id': result.get('data_id'),
                'title': result.get('title'),
                'upload_info': result.get('upload_info')
            })
        elif status == 'filtered_zip':
            filtered_zip.append({
                'data_id': result.get('data_id'),
                'title': result.get('title'),
                'reason': result.get('reason')
            })
        elif status == 'format_mismatch':
            format_mismatch.append({
                'data_id': result.get('data_id'),
                'title': result.get('title'),
                'meta_format': result.get('meta_format', ''),
                'real_ext': result.get('real_ext', ''),
                'reason': result.get('reason')
            })
        elif status == 'failed':
            failed.append({
                'data_id': result.get('data_id'),
                'title': result.get('title'),
                'reason': result.get('reason')
            })
    
    # 업로드 결과 저장
    upload_results = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_attempts': len(upload_dirs),
        'success_count': len(uploaded),
        'failed_count': len(failed),
        'filtered_zip_count': len(filtered_zip),
        'format_mismatch_count': len(format_mismatch),
        'success_items': uploaded,
        'failed_items': failed,
        'filtered_zip_items': filtered_zip,
        'format_mismatch_items': format_mismatch
    }
    
    save_metadata(upload_results, UPLOAD_RESULTS_FILE)
    logging.info(f"업로드 결과가 '{UPLOAD_RESULTS_FILE}'에 저장되었습니다.")
    
    # 결과 요약 출력
    print("\n" + "="*70)
    print(f"업로드 결과 요약")
    print(f"- 성공: {len(uploaded)}개")
    print(f"- 실패: {len(failed)}개")
    if filtered_zip:
        print(f"- ZIP 필터링: {len(filtered_zip)}개")
    if format_mismatch:
        print(f"- 형식 불일치: {len(format_mismatch)}개")
    print("="*70)
    
    return uploaded, failed 