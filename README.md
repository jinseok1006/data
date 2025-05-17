# 공공데이터포털 데이터 수집 도구

이 프로그램은 공공데이터포털(data.go.kr)에서 데이터를 검색하고 다운로드하는 도구입니다.

## 주요 기능

- 키워드 검색을 통한 데이터 수집
- 페이지네이션 처리로 다량의 데이터 탐색
- 필터링을 통한 원하는 항목만 선택
- 데이터 자동 다운로드
- UTF-8 인코딩 자동 변환

## 빠른 시작 가이드

### 기본 사용법

```bash
# 가장 기본적인 사용법 - '전라북도' 키워드로 검색하고 첫 페이지에서 2개 항목 다운로드
python main.py

# '전북' 키워드로 검색하고 첫 페이지에서 5개 항목 다운로드
python main.py -k 전북 -n 5

# '전북' 키워드로 검색하고 모든 페이지를 탐색한 후 모든 항목 다운로드
python main.py -k 전북 -p 0 -n 0

# 데이터 수집 후 JSON 파일만 저장 (다운로드 없음)
python main.py --mode collect -k 전북 -p 0

# 이전에 수집한 데이터 중 선택한 항목만 다운로드
python main.py --mode download --item-ids 1 3 5
```

### 일반 사용자를 위한 추천 설정

코드를 모르는 일반 사용자라면 다음 설정을 권장합니다:

1. **전체 데이터 수집 및 다운로드**:
   ```
   python main.py -k 키워드 -p 0 -n 0
   ```
   - `-k`: 검색할 키워드 (원하는 주제)
   - `-p 0`: 모든 페이지 탐색
   - `-n 0`: 검색된 모든 항목 다운로드

2. **데이터 먼저 살펴보기**:
   ```
   python main.py -k 키워드 --mode collect -p 0
   ```
   이후 data_titles.json 파일을 확인한 다음 필요한 항목만 다운로드:
   ```
   python main.py --mode download --item-ids 1 3 5
   ```

## 상세 옵션

| 옵션 | 설명 |
|------|------|
| --mode | 실행 모드 (collect: 데이터 수집만, download: 다운로드만, all: 모두 실행) |
| -k, --keyword | 검색 키워드 (기본값: 전라북도) |
| -p, --pages | 처리할 최대 페이지 수 (0 입력 시 모든 페이지 탐색) |
| -n, --num-downloads | 다운로드할 최대 항목 수 (0 입력 시 모든 항목 다운로드) |
| -f, --formats | 필터링할 파일 형식 (예: CSV JSON) |
| --filter-keywords | 필터링할 키워드 |
| --filter-providers | 필터링할 제공기관 |
| -d, --download-dir | 다운로드 디렉토리 (기본값: downloaded_data) |
| --json-file | JSON 데이터 파일 경로 (다운로드 모드에서 사용) |
| --item-ids | 다운로드할 항목의 인덱스 목록 (1부터 시작) | 