"""
공공데이터 수집 및 업로드 프로젝트 설정
"""

# 기본 URL 설정
BASE_URL = "https://www.data.go.kr"
LIST_URL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"

# 디렉토리 설정
DOWNLOAD_BASE_DIR = "downloaded_data"  # 다운로드 기본 디렉토리

# 로그 설정
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

# 파일 확장자 매핑
EXT_MAP = {
    'CSV': 'csv', 
    'XLSX': 'xlsx', 
    'XLS': 'xls',
    'DOCX': 'docx',
    'HWP': 'hwp',
    'HWPX': 'hwpx',
    'JSON': 'json', 
    'XML': 'xml', 
    'JPG': 'jpg', 
    'PNG': 'png',
    'GIF': 'gif',
    'ZIP': 'zip',
    'PDF': 'pdf',
    'SHP': 'zip'  # SHP 파일은 보통 ZIP으로 압축되어 제공됨
}

# 진행률 표시 설정
PROGRESS_BAR_WIDTH = 50  # 진행률 바 너비

# 검색 필터 설정
REQUIRED_TITLE_KEYWORDS = ['전북', '전라북도', '전북특별자치도']  # 제목에 포함되어야 하는 키워드

# HTTP 요청 설정
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# 파일 서버 설정
FILE_SERVER = {
    "api_url": "http://localhost:11311/api/upload",
    "auth_token": "",  # 인증 토큰이 필요 없는 경우 빈 문자열
    "timeout": 60  # 업로드 타임아웃 (초)
} 