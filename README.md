# 전라북도 공공데이터 수집기

## 소개
[data.go.kr](https://www.data.go.kr)에서 전라북도 관련 공공데이터를 수집, 다운로드, 업로드하는 도구입니다.

## 기능
- 전라북도 관련 공공데이터 검색 및 목록화
- 메타데이터 수집 및 저장
- 파일 다운로드
- 파일 서버 업로드

## 설치
```bash
pip install -r requirements.txt
```

## 프로세스 흐름
이 프로그램은 다음 4단계로 구성되어 있습니다:

1. **목록화** (list): 공공데이터포털에서 기본 데이터만 빠르게 수집
2. **세부정보** (detail): 목록화된 데이터 필터링 및 세부 페이지 접근
3. **다운로드** (download): 필터링된 데이터 파일 다운로드
4. **업로드** (upload): 다운로드된 파일을 외부 서버에 업로드

## 사용법

### 기본 사용
```bash
# 모든 단계 순차 실행 (기본값)
python run.py

# 개별 단계만 실행
python run.py --mode list
python run.py --mode detail
python run.py --mode download
python run.py --mode upload
```

### 단계별 사용법 및 옵션

#### 1. 목록화 (list)
페이지네이션 화면에서 기본 정보만 수집하는 단계입니다.

```bash
python run.py --mode list -k "전북특별자치도" -p 5
```

**옵션:**
- `-k`, `--keyword`: 검색 키워드 (기본값: "전라북도")
- `-p`, `--pages`: 수집할 최대 페이지 수 (기본값: 1, 0: 모든 페이지)

**입출력:**
- 출력: `data_list.json` (목록화된 데이터)

#### 2. 세부정보 수집 (detail)
목록화된 데이터를 필터링하고 세부 페이지에 접근하여 상세 정보를 수집합니다.

```bash
python run.py --mode detail -n 10 --list-file my_list.json
```

**옵션:**
- `-n`, `--num-process`: 처리할 최대 항목 수 (기본값: 2, 0: 모든 항목)
- `--list-file`: 목록 데이터 파일 경로 (기본값: data_list.json)

**필터링 기준:**
- 제목에 '전북', '전라북도', '전북특별자치도' 포함 여부
- 지원되는 파일 형식 (CSV, XLSX, DOCX, HWPX, PDF, XLS, HWP)
- 다운로드 버튼 유무

**입출력:**
- 입력: `data_list.json` (목록화된 데이터)
- 출력: `data_filtered.json` (필터링 및 세부정보가 추가된 데이터)

#### 3. 다운로드 (download)
필터링된 항목을 다운로드하는 단계입니다.

```bash
python run.py --mode download -n 5 --data-ids 15014782 15014790
```

**옵션:**
- `-n`, `--num-process`: 다운로드할 최대 항목 수 (기본값: 2, 0: 모든 항목)
- `--data-ids`: 특정 데이터 ID만 다운로드 (선택사항)
- `--filtered-file`: 필터링된 데이터 파일 경로 (기본값: data_filtered.json)

**입출력:**
- 입력: `data_filtered.json` (필터링된 데이터)
- 출력: 
  - `downloaded_data/` 디렉토리 (데이터 ID별 하위 폴더)
  - `download_results.json` (다운로드 결과 정보)
  - `failed_downloads.txt` (실패한 다운로드 목록)

**저장 구조:**
```
downloaded_data/
  └── {데이터_ID}/
       ├── data.{확장자}    # 실제 데이터 파일
       └── metadata.json   # 메타데이터 파일
```

#### 4. 업로드 (upload)
다운로드된 파일을 외부 서버에 업로드하는 단계입니다.

```bash
python run.py --mode upload --data-ids 15014782 --upload-source directory
```

**옵션:**
- `--data-ids`: 특정 데이터 ID만 업로드 (선택사항)
- `--upload-source`: 업로드 소스 선택
  - `download_results`: 다운로드 결과 기반 (기본값)
  - `directory`: 디렉토리 기반
- `--results-file`: 다운로드 결과 파일 경로 (기본값: download_results.json)

**입출력:**
- 입력: 
  - `download_results.json` 또는 
  - `downloaded_data/` 디렉토리
- 출력: `upload_results.json` (업로드 결과 정보)

### 기타 옵션
- `--debug`: 디버그 모드 활성화 (상세 로그 출력)
- `-h`, `--help`: 도움말 표시

## 예시 사용 시나리오

### 1. 특정 키워드로 모든 과정 실행
```bash
python run.py -k "전북특별자치도 공공시설" -p 3 -n 10
```

### 2. 목록화 후 세부정보 수집만 실행
```bash
# 먼저 목록화 실행
python run.py --mode list -k "전북 관광" -p 5

# 그 다음 세부정보 수집만 실행
python run.py --mode detail -n 0
```

### 3. 특정 데이터 ID만 다운로드
```bash
python run.py --mode download --data-ids 15014782 15014790
```

### 4. 다운로드 실패한 항목 확인 후 재시도
```bash
# 실패 목록 확인
cat failed_downloads.txt

# 특정 ID만 다시 다운로드
python run.py --mode download --data-ids 15014782
``` 