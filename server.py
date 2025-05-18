#!/usr/bin/env python
"""
간단한 파일 업로드 서버

- localhost:11311에서 실행
- /api/upload 엔드포인트를 통해 파일, description, auto_description 필드를 처리
- 파일을 실제로 저장하지 않고 로그만 출력
"""

from flask import Flask, request, jsonify
import os
import logging
import time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """
    파일 업로드 처리 엔드포인트
    
    처리하는 데이터:
    - file: 업로드된 파일
    - description: 파일 설명
    - auto_description: 메타데이터 전체 (JSON 문자열)
    """
    # 요청 확인
    if 'file' not in request.files:
        logger.error("파일이 요청에 없습니다.")
        return jsonify({"error": "파일이 요청에 없습니다."}), 400
    
    # 파일 정보 추출
    file = request.files['file']
    filename = file.filename
    file_size = len(file.read())
    file.seek(0)  # 파일 포인터 초기화
    
    # 설명 필드 가져오기
    description = request.form.get('description', '')
    auto_description = request.form.get('auto_description', '')
    
    # 로그에 정보 출력
    logger.info(f"===== 파일 업로드 요청 =====")
    logger.info(f"파일명: {filename}")
    logger.info(f"파일 크기: {file_size} 바이트")
    logger.info(f"설명: {description[:100]}{'...' if len(description) > 100 else ''}")

    # auto_description 출력 (JSON 형식이면 파싱)
    logger.info(f"메타데이터 길이: {len(auto_description)} 문자")
    try:
        import json
        auto_desc_json = json.loads(auto_description)
        # 주요 필드만 추출해서 표시
        important_fields = ['title', 'data_id', 'file_format', 'description']
        logger.info("===== 메타데이터 주요 내용 =====")
        for field in important_fields:
            if field in auto_desc_json:
                value = auto_desc_json[field]
                # 긴 값은 잘라서 표시
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                logger.info(f"  {field}: {value}")
        
        # 추가 필드가 있으면 표시
        logger.info("===== 메타데이터 기타 필드 =====")
        other_fields = [k for k in auto_desc_json.keys() if k not in important_fields]
        for i, field in enumerate(other_fields):
            if i >= 10:  # 최대 10개 필드만 표시
                logger.info(f"  ... 외 {len(other_fields) - 10}개 필드")
                break
            value = auto_desc_json[field]
            if isinstance(value, str) and len(value) > 50:
                value = value[:50] + "..."
            logger.info(f"  {field}: {value}")
        
    except Exception as e:
        # JSON 파싱 실패시 일부만 출력
        logger.info("메타데이터 내용(일부):")
        logger.info(auto_description[:200] + ('...' if len(auto_description) > 200 else ''))
    
    # 필요시 파일 내용 일부 로깅
    file_content_preview = file.read(100)
    file_type = "텍스트" if is_text(file_content_preview) else "바이너리"
    logger.info(f"파일 유형: {file_type}")
    
    # 응답 데이터 구성
    response_data = {
        "success": True,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "file_info": {
            "filename": filename,
            "size": file_size,
            "type": file_type
        },
        "message": "파일 업로드가 성공적으로 처리되었습니다."
    }
    
    return jsonify(response_data), 200

def is_text(byte_data):
    """데이터가 텍스트인지 바이너리인지 추정"""
    try:
        byte_data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False

if __name__ == '__main__':
    logger.info("=== 파일 업로드 서버 시작 ===")
    logger.info("주소: http://localhost:11311")
    logger.info("엔드포인트: /api/upload")
    app.run(host='0.0.0.0', port=11311, debug=True) 