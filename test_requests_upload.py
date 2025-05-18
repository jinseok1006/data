import requests
import os

# 업로드할 파일 정보
# 실제 파일이 없어도, requests는 파일명과 내용을 튜플로 전달하면 multipart/form-data 요청을 생성합니다.
file_name_korean = "한글파일테스트.txt"
file_content = b"This is a test file content." # 파일 내용은 바이트 스트링

# 업로드 대상 URL (현재 실행 중인 server.py의 엔드포인트)
upload_url = "http://localhost:11311/api/upload"

# 파일 준비 (files 딕셔너리 형태)
# 튜플의 첫 번째 요소가 파일명, 두 번째가 파일 객체(또는 내용)
# 파일 객체 대신 파일 내용을 직접 전달할 수도 있습니다.
files_to_upload = {
    'file': (file_name_korean, file_content, 'text/plain') # (파일명, 파일내용, Content-Type)
}

# 추가적인 폼 데이터 (선택 사항)
# server.py가 description과 auto_description을 받을 수 있으므로 추가해봅니다.
form_data = {
    'description': 'requests 라이브러리를 사용한 파일 업로드 테스트입니다.',
    'auto_description': '{"test_client": "requests", "purpose": "filename_encoding_check"}'
}

print(f"'{file_name_korean}' 파일을 '{upload_url}' 로 업로드합니다...")

try:
    # requests를 사용하여 파일 업로드 요청
    response = requests.post(upload_url, files=files_to_upload, data=form_data)

    # 응답 상태 코드 확인
    print(f"서버 응답 코드: {response.status_code}")

    # 응답 내용 (JSON 형식일 경우)
    try:
        response_json = response.json()
        print("서버 응답 내용 (JSON):")
        import json
        print(json.dumps(response_json, indent=2, ensure_ascii=False))
    except requests.exceptions.JSONDecodeError:
        print("서버 응답 내용 (텍스트):")
        print(response.text)

except requests.exceptions.RequestException as e:
    print(f"업로드 중 오류 발생: {e}")

print("\n업로드 시도 완료. Flask 서버(server.py)의 로그를 확인하여 파일명이 어떻게 기록되었는지 확인하세요.")
print(f"특히 '수신된 원본 파일명'이 '{file_name_korean}'으로 나오는지, 아니면 URL 인코딩된 형태로 나오는지 주목하세요.") 