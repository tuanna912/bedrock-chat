"""
Techfest Document Processor for Bedrock Knowledge Base
Small files (<300KB): Extract text → Save to processed_docs/small/ → S3 datasource (NONE chunking)
Large files (>=300KB): Move to original_docs/large/ → Parse with Claude → Split by main headers (#) → Save to processed_docs/small/ → S3 datasource (NONE chunking)
"""

import sys
import boto3
import json
import time
import os
import io
import csv
from datetime import datetime
from awsglue.utils import getResolvedOptions
from botocore.exceptions import ClientError
import logging

from docx import Document
from docx.table import Table
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
import openpyxl

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = 'us-east-1'

s3_client = boto3.client('s3', region_name=REGION)
bedrock_agent_client = boto3.client('bedrock-agent', region_name=REGION)
bedrock_runtime_client = boto3.client('bedrock-runtime', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)

required_args = ['BUCKET_NAME']
args = getResolvedOptions(sys.argv, required_args)
BUCKET_NAME = args['BUCKET_NAME']

REGISTRY_TABLE = 'KnowledgeBaseRegistry'
EMBEDDING_MODEL = 'amazon.titan-embed-text-v2:0'
FILE_SIZE_THRESHOLD = 300 * 1024  # 300KB
CLAUDE_MODEL = 'us.anthropic.claude-3-5-sonnet-20241022-v2:0'
MAX_RETRIES = 3
BASE_DELAY = 2
ACCOUNT_ID = boto3.client('sts').get_caller_identity()['Account']
CLAUDE_MODEL_ARN = f'arn:aws:bedrock:us-east-1:{ACCOUNT_ID}:inference-profile/{CLAUDE_MODEL}'

class RetryableError(Exception):
    pass


def exponential_backoff_retry(func, max_retries=MAX_RETRIES, base_delay=BASE_DELAY):
    for attempt in range(max_retries):
        try:
            return func()
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['ThrottlingException', 'TooManyRequestsException', 'ServiceUnavailable', 'RequestTimeout']:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Retryable error: {error_code}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
            logger.error(f"Non-retryable error: {error_code}")
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Error: {e}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise
    raise RetryableError(f"Max retries ({max_retries}) exceeded")


def extract_table_as_markdown(table):
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace('|', '\\|') for cell in row.cells]
        rows.append(cells)
    if not rows:
        return ""
    result = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(["---" for _ in rows[0]]) + "|"]
    for row in rows[1:]:
        result.append("| " + " | ".join(row) + " |")
    return "\n".join(result)


def process_docx_from_s3(bucket, key):
    logger.info(f"Processing DOCX: s3://{bucket}/{key}")
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    doc = Document(io.BytesIO(obj['Body'].read()))
    output = []
    for element in doc.element.body:
        if isinstance(element, CT_P):
            text = element.text.strip()
            if text:
                output.append(text)
        elif isinstance(element, CT_Tbl):
            table = Table(element, doc)
            table_text = extract_table_as_markdown(table)
            if table_text:
                output.append("\n" + table_text + "\n")
    return "\n\n".join(output)


def process_csv_from_s3(bucket, key):
    logger.info(f"Processing CSV: s3://{bucket}/{key}")
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    csv_content = obj['Body'].read().decode('utf-8-sig')
    csv_reader = csv.reader(io.StringIO(csv_content))
    rows = list(csv_reader)
    if not rows:
        return ""
    result = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(["---" for _ in rows[0]]) + "|"]
    for row in rows[1:]:
        if row:
            result.append("| " + " | ".join(row) + " |")
    return "\n".join(result)


def process_excel_from_s3(bucket, key):
    logger.info(f"Processing Excel: s3://{bucket}/{key}")
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    workbook = openpyxl.load_workbook(io.BytesIO(obj['Body'].read()), data_only=True)
    output = []
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        output.append(f"## Sheet: {sheet_name}\n")
        rows = []
        for row in sheet.iter_rows(values_only=True):
            if any(cell is not None and str(cell).strip() for cell in row):
                rows.append([str(cell) if cell is not None else "" for cell in row])
        if rows:
            output.append("| " + " | ".join(rows[0]) + " |")
            output.append("|" + "|".join(["---" for _ in rows[0]]) + "|")
            for row in rows[1:]:
                output.append("| " + " | ".join(row) + " |")
            output.append("")
    return "\n".join(output)


def process_pdf_from_s3(bucket, key):
    """Process small PDF - simple text extraction"""
    logger.info(f"Processing small PDF: s3://{bucket}/{key}")
    try:
        import PyPDF2
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(obj['Body'].read()))
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text() + '\n'
        logger.info(f"Extracted {len(text)} characters from PDF")
        return text
    except Exception as e:
        logger.warning(f"PyPDF2 failed, using placeholder: {e}")
        return f"[PDF content]"


def extract_metadata_from_path(file_path):
    parts = file_path.split('/')
    filename = parts[-1] if parts else file_path
    category = parts[-2] if len(parts) >= 2 else 'default'
    file_extension = os.path.splitext(filename)[1].lstrip('.').lower()
    basename = os.path.splitext(filename)[0]
    return {
        'category': category,
        'filename': filename,
        'basename': basename,
        'file_extension': file_extension,
        'folder_path': '/'.join(parts[:-1]) if len(parts) > 1 else '',
        'full_path': file_path
    }


def read_and_preprocess_small_file(bucket, key):
    """Process small files (<300KB) for S3 datasource"""
    logger.info(f"Processing small file: s3://{bucket}/{key}")
    
    path_metadata = extract_metadata_from_path(key)
    file_extension = path_metadata['file_extension']
    
    head_response = s3_client.head_object(Bucket=bucket, Key=key)
    file_size = head_response['ContentLength']
    
    if file_extension in ['docx', 'doc']:
        text_content = process_docx_from_s3(bucket, key)
        processing_method = 'docx_extraction'
    elif file_extension == 'csv':
        text_content = process_csv_from_s3(bucket, key)
        processing_method = 'csv_to_markdown'
    elif file_extension in ['xlsx', 'xls']:
        text_content = process_excel_from_s3(bucket, key)
        processing_method = 'excel_to_markdown'
    elif file_extension in ['txt', 'md', 'text']:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        text_content = obj['Body'].read().decode('utf-8')
        processing_method = 'text_file'
    elif file_extension == 'pdf':
        text_content = process_pdf_from_s3(bucket, key)
        processing_method = 'pdf_simple'
    else:
        logger.warning(f"Unsupported file type: {file_extension}")
        return None
    
    metadata = {
        'logical_doc_id': key,
        'source_uri': f's3://{bucket}/{key}',
        'file_size': file_size,
        'category': path_metadata['category'],
        'filename': path_metadata['filename'],
        'processing_strategy': 'small_file_s3_datasource',
        'processing_method': processing_method,
        'upload_date': datetime.utcnow().isoformat()
    }
    
    return {'doc_id': key, 'content': text_content, 'metadata': metadata}


def split_text_content_by_size(content, max_chars=50000):
    """Split text content into chunks by character count"""
    if len(content) <= max_chars:
        return [content]
    
    chunks = []
    lines = content.split('\n')
    current_chunk = []
    current_size = 0
    
    for line in lines:
        line_size = len(line) + 1  # +1 for newline
        if current_size + line_size > max_chars and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_size = line_size
        else:
            current_chunk.append(line)
            current_size += line_size
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks


def save_processed_document_to_s3(bucket, original_key, content, metadata):
    """Save file to processed_docs/small/ - split if too large"""
    base_key = original_key.replace('original_docs/', 'processed_docs/small/', 1)
    base_key = os.path.splitext(base_key)[0]
    
    # Split if content too large (>50K chars ~ 12K tokens)
    chunks = split_text_content_by_size(content, max_chars=60000)
    
    if len(chunks) == 1:
        # Single file
        processed_key = base_key + '.txt'
        logger.info(f"Saving: s3://{bucket}/{processed_key}")
        
        metadata_header = "---METADATA---\n" + json.dumps(metadata, indent=2, ensure_ascii=False) + "\n---CONTENT---\n"
        full_content = metadata_header + content
        
        s3_client.put_object(
            Bucket=bucket,
            Key=processed_key,
            Body=full_content.encode('utf-8'),
            ContentType='text/plain; charset=utf-8'
        )
        logger.info(f"✓ Saved to S3")
        return processed_key
    else:
        # Multiple chunks
        logger.info(f"Content too large, splitting into {len(chunks)} chunks")
        saved_keys = []
        
        for idx, chunk_content in enumerate(chunks, 1):
            processed_key = f"{base_key}_part{idx}.txt"
            
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_index'] = idx
            chunk_metadata['total_chunks'] = len(chunks)
            chunk_metadata['processing_method'] = f"{metadata.get('processing_method', 'text')}_chunked"
            
            metadata_header = "---METADATA---\n" + json.dumps(chunk_metadata, indent=2, ensure_ascii=False) + "\n---CONTENT---\n"
            full_content = metadata_header + chunk_content
            
            s3_client.put_object(
                Bucket=bucket,
                Key=processed_key,
                Body=full_content.encode('utf-8'),
                ContentType='text/plain; charset=utf-8'
            )
            saved_keys.append(processed_key)
        
        logger.info(f"✓ Saved {len(saved_keys)} chunks to S3")
        return saved_keys


def move_large_file_to_large_folder(bucket, original_key):
    """Move large file from original_docs/ to original_docs/large/"""
    large_key = original_key.replace('original_docs/', 'original_docs/large/', 1)
    
    logger.info(f"Moving large file: {original_key} → {large_key}")
    
    s3_client.copy_object(
        Bucket=bucket,
        CopySource={'Bucket': bucket, 'Key': original_key},
        Key=large_key
    )
    
    s3_client.delete_object(Bucket=bucket, Key=original_key)
    
    logger.info(f"✓ Moved to original_docs/large/")
    return large_key


def split_pdf_by_pages(file_bytes, pages_per_chunk=1):
    """Split PDF into smaller chunks by pages"""
    import PyPDF2
    from io import BytesIO
    
    pdf_reader = PyPDF2.PdfReader(BytesIO(file_bytes))
    total_pages = len(pdf_reader.pages)
    logger.info(f"PDF has {total_pages} pages, splitting into chunks of {pages_per_chunk} pages")
    
    chunks = []
    for start_page in range(0, total_pages, pages_per_chunk):
        end_page = min(start_page + pages_per_chunk, total_pages)
        
        pdf_writer = PyPDF2.PdfWriter()
        for page_num in range(start_page, end_page):
            pdf_writer.add_page(pdf_reader.pages[page_num])
        
        chunk_bytes = BytesIO()
        pdf_writer.write(chunk_bytes)
        chunk_data = chunk_bytes.getvalue()
        chunks.append(chunk_data)
        
        logger.info(f"Chunk {len(chunks)}: pages {start_page+1}-{end_page} ({len(chunk_data)/1024/1024:.1f}MB)")
    
    return chunks


def parse_large_file_with_claude(bucket, key):
    """Parse large file using Claude and return markdown content"""
    logger.info(f"Parsing large file with Claude: s3://{bucket}/{key}")
    
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    file_bytes = obj['Body'].read()
    file_size_mb = len(file_bytes) / 1024 / 1024
    logger.info(f"File size: {file_size_mb:.1f}MB")
    
    # Check if file is PDF - fallback to PyPDF2 if Claude not available
    file_ext = os.path.splitext(key)[1].lower()
    if file_ext == '.pdf':
        try:
            # Try Claude first
            return _parse_with_claude(file_bytes, key, file_size_mb)
        except ClientError as e:
            if 'ResourceNotFoundException' in str(e) or 'Model use case details' in str(e):
                logger.warning(f"Claude not available: {e}")
                logger.info("Falling back to PyPDF2 parser...")
                return _parse_pdf_with_pypdf2(file_bytes)
            raise
    else:
        # Non-PDF must use Claude
        return _parse_with_claude(file_bytes, key, file_size_mb)


def _parse_pdf_with_pypdf2(file_bytes):
    """Fallback parser using PyPDF2"""
    import PyPDF2
    from io import BytesIO
    
    logger.info("Parsing PDF with PyPDF2...")
    pdf_reader = PyPDF2.PdfReader(BytesIO(file_bytes))
    text_parts = []
    
    for page_num, page in enumerate(pdf_reader.pages, 1):
        text = page.extract_text()
        if text.strip():
            text_parts.append(f"# Page {page_num}\n\n{text}")
    
    combined = '\n\n'.join(text_parts)
    logger.info(f"✓ Extracted {len(combined)} characters from {len(pdf_reader.pages)} pages")
    return combined


def _parse_with_claude(file_bytes, key, file_size_mb):
    """Parse file with Claude"""
    file_ext = os.path.splitext(key)[1].lower()
    
    prompt = '''Trích xuất nội dung từ một trang hình ảnh và xuất ra theo cú pháp Markdown. Bao toàn bộ nội dung trong thẻ <markdown></markdown> và không sử dụng khối mã (code block). Nếu hình ảnh trống thì xuất ra <markdown></markdown> mà không có gì bên trong.
        LƯU Ý: Giữ nguyên tất cả các thông tin của tài liệu bằng tiếng Việt, không được xóa bất kì trang và nội dung nào trong tài liệu gốc.
        Thực hiện theo các bước sau:
        1.Kiểm tra kỹ trang được cung cấp.

        2.Xác định tất cả các thành phần có trong trang, bao gồm tiêu đề, nội dung chính, chú thích cuối trang, bảng, hình ảnh, mô tả ảnh, số trang, v.v.

        3.Sử dụng cú pháp Markdown để định dạng đầu ra:
            -Tiêu đề: # cho tiêu đề chính, ## cho tiêu đề mục, ### cho tiêu đề nhỏ, v.v.
            -Danh sách: * hoặc - cho danh sách gạch đầu dòng, 1. 2. 3. cho danh sách đánh số.
            -Không lặp lại nội dung.
        
        4.Nếu phần tử là bảng:

            -Tạo bảng Markdown, đảm bảo mỗi hàng có cùng số cột.
            -Giữ căn lề của các ô càng giống càng tốt.
            -Không chia nhỏ bảng thành nhiều bảng.
            -Nếu một ô gộp nhiều hàng hoặc nhiều cột, đặt nội dung vào ô đầu tiên (góc trên bên trái) và ghi ' ' cho các ô còn lại.
            -Dùng | để phân cách cột, dùng |-|-| cho hàng tiêu đề.
            -Nếu một ô chứa nhiều mục, liệt kê trên các dòng riêng.
            -Nếu bảng có tiêu đề phụ, tách chúng thành một hàng riêng.

        5.Nếu phần tử là hình ảnh có chứa bảng:

            -Nếu hình ảnh có thể chuyển đổi thành bảng rõ ràng, hãy tạo bảng Markdown như hướng dẫn ở trên.
        
        6.Nếu phần tử là hình ảnh không phải bảng:

            -Nếu ảnh chứa các đoạn văn bản, hãy trích xuất và chép lại chính xác từng nội dung văn bản.
            -Nếu ảnh chỉ chứa các đối tượng hình ảnh, hãy chuyển các thành phần hình ảnh thành thẻ hình ảnh Markdown với mô tả thích hợp.

        7.Nếu phần tử là đoạn văn:

            -Chép lại chính xác từng nội dung văn bản đang có.
            -Nếu phần tử là header, footer, chú thích cuối trang hoặc số trang:
            -Chép lại chính xác từng nội dung văn bản.
        
        8. Nếu trong 1 trang không thể hiện đủ nội dung của bảng, thì gộp các trang tiếp theo của bảng đó thành 1 block để tạo thành bảng hoàn chỉnh.

        Ví dụ đầu ra khi xử lí bảng hoặc trích xuất bảng từ ảnh:
        <markdown>
        | STT | Nội dung công việc | Đơn vị thực hiện | Đơn vị phối hợp | Sản phẩm | Thời gian | Người thực hiện | Nguồn kinh phí | Ghi chú |
        |---|---|---|---|---|---|---|---|---|
        | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN | TRƯỚC SỰ KIỆN |
        | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện | 1.  Cơ sở vật chất, hậu cần, trang thiết bị phục vụ sự kiện |
        | 1.1 | Thiết kế phòng Hội thảo:
        - Sân khấu, Backdrop, 
        - 04 Standee và sơ đồ chỉ dẫn phòng Hội thảo; | Tiểu ban Lễ tân hậu cần (Cục KN) |  | Được lãnh đạo Cục KN
        phê duyệt |  |  |  |  |
        | 1.2 | Thư mời tham dự chuỗi sự kiện (có mã QR về chương trình tổng thể kèm theo và thông tin về hậu cần) | Tiểu ban nội dung (Cục KN) | Tiểu ban Lễ tân hậu cần (VP Bộ, Cục KN) | Được lãnh đạo Bộ phê duyệt |  |  |  |  |
        | 1.3 | Thư mời diễn giả Hội thảo | Tiểu ban Lễ tân hậu cần (Cục KN) |  |  |  |  |  |  |
        | 1.4 | Thi công sân khấu; lắp đặt trang thiết bị âm thanh, ánh sáng... | Tiểu ban Lễ tân hậu cần (Cục KN) |  | Đã lắp đặt xong |  |  |  |  |
        </markdown>'''
    
    import base64
    
    file_ext = os.path.splitext(key)[1].lower()
    content_type_map = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg'
    }
    content_type = content_type_map.get(file_ext, 'application/pdf')
    
    # Split if too large (>15MB to account for base64 overhead)
    if file_size_mb > 15:
        logger.info(f"File too large ({file_size_mb:.1f}MB), splitting...")
        if file_ext == '.pdf':
            file_chunks = split_pdf_by_pages(file_bytes, pages_per_chunk=1)
        else:
            # For non-PDF (images), cannot split - log error
            logger.error(f"Non-PDF file too large: {file_size_mb:.1f}MB. Max 15MB for images.")
            raise Exception(f"Image file too large: {file_size_mb:.1f}MB. Please reduce size or convert to PDF.")
    else:
        file_chunks = [file_bytes]
    
    all_markdown = []
    
    for idx, chunk_bytes in enumerate(file_chunks, 1):
        logger.info(f"Processing chunk {idx}/{len(file_chunks)} ({len(chunk_bytes)/1024/1024:.1f}MB)...")
        
        file_base64 = base64.b64encode(chunk_bytes).decode('utf-8')
        
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": file_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        try:
            response = bedrock_runtime_client.invoke_model(
                modelId=CLAUDE_MODEL,
                body=json.dumps(body)
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body['content'][0]['text']
            
            all_markdown.append(content)
            logger.info(f"✓ Chunk {idx} parsed: {len(content)} characters")
            
        except Exception as e:
            logger.error(f"Error parsing chunk {idx}: {e}")
            all_markdown.append(f"[Error parsing chunk {idx}]")
    
    # Combine all chunks
    combined_markdown = '\n\n'.join(all_markdown)
    logger.info(f"✓ Total parsed: {len(combined_markdown)} characters from {len(file_chunks)} chunks")
    return combined_markdown


def split_markdown_by_main_headers(markdown_content, original_key):
    """Split markdown content by main headers (#) with context (2 sentences before/after)"""
    logger.info("Splitting markdown by main headers (#) with context")
    
    # Clean content: remove <markdown>, </markdown> tags and empty lines
    lines = markdown_content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in ['<markdown>', '</markdown>']:
            cleaned_lines.append(line)
    
    lines = cleaned_lines
    header_indices = []
    
    # Find all main header positions
    for i, line in enumerate(lines):
        if line.startswith('# ') and not line.startswith('## ') and not line.startswith('### '):
            header_indices.append(i)
    
    if not header_indices:
        return [{'header': 'content', 'content': '\n'.join(lines)}]
    
    chunks = []
    
    for idx, header_pos in enumerate(header_indices):
        # Determine chunk boundaries
        start_pos = header_pos
        end_pos = header_indices[idx + 1] if idx + 1 < len(header_indices) else len(lines)
        
        # Add 2 sentences before (if not first chunk)
        if idx > 0:
            context_start = max(0, header_pos - 2)
            start_pos = context_start
        
        # Add 2 sentences after (if not last chunk)
        if idx < len(header_indices) - 1:
            context_end = min(len(lines), end_pos + 2)
            end_pos = context_end
        
        chunk_lines = lines[start_pos:end_pos]
        header = lines[header_pos][2:].strip()
        
        chunks.append({
            'header': header,
            'content': '\n'.join(chunk_lines).strip(),
            'line_count': len(chunk_lines)
        })
    
    # Step 1: Merge consecutive small chunks
    merged_chunks = []
    i = 0
    while i < len(chunks):
        if chunks[i]['line_count'] >= 10:
            merged_chunks.append(chunks[i])
            i += 1
        else:
            # Found small chunk, collect all consecutive small chunks
            small_group = [chunks[i]]
            j = i + 1
            while j < len(chunks) and chunks[j]['line_count'] < 10:
                small_group.append(chunks[j])
                j += 1
            
            # Merge small chunks in group
            merged_content = '\n\n'.join([c['content'] for c in small_group])
            merged_header = ' + '.join([c['header'] for c in small_group])
            total_lines = sum([c['line_count'] for c in small_group])
            
            merged_chunks.append({
                'header': merged_header,
                'content': merged_content,
                'line_count': total_lines
            })
            i = j
    
    # Step 2: Handle remaining small chunks (after merging)
    final_chunks = []
    for idx, chunk in enumerate(merged_chunks):
        if chunk['line_count'] >= 10:
            final_chunks.append(chunk)
        else:
            # Small chunk - check if between two large chunks
            prev_large_idx = None
            next_large_idx = None
            
            for i in range(idx - 1, -1, -1):
                if merged_chunks[i]['line_count'] >= 10:
                    prev_large_idx = i
                    break
            
            for i in range(idx + 1, len(merged_chunks)):
                if merged_chunks[i]['line_count'] >= 10:
                    next_large_idx = i
                    break
            
            if prev_large_idx is not None and next_large_idx is not None:
                # Between two large chunks - add to both
                for fc in final_chunks:
                    if fc['header'] == merged_chunks[prev_large_idx]['header']:
                        fc['content'] += '\n\n' + chunk['content']
                        break
                merged_chunks[next_large_idx]['content'] = chunk['content'] + '\n\n' + merged_chunks[next_large_idx]['content']
            elif prev_large_idx is not None:
                for fc in final_chunks:
                    if fc['header'] == merged_chunks[prev_large_idx]['header']:
                        fc['content'] += '\n\n' + chunk['content']
                        break
            elif next_large_idx is not None:
                merged_chunks[next_large_idx]['content'] = chunk['content'] + '\n\n' + merged_chunks[next_large_idx]['content']
            else:
                final_chunks.append(chunk)
    
    logger.info(f"✓ Split into {len(chunks)} chunks, merged to {len(final_chunks)} chunks")
    return final_chunks


def save_large_file_chunks_to_s3(bucket, original_key, chunks):
    """Save parsed chunks to processed_docs/small/"""
    logger.info(f"Saving {len(chunks)} chunks to processed_docs/small/")
    
    base_name = os.path.splitext(os.path.basename(original_key))[0]
    saved_keys = []
    
    for idx, chunk in enumerate(chunks, 1):
        processed_key = f"processed_docs/small/{base_name}_part{idx}.txt"
        
        metadata = {
            'logical_doc_id': original_key,
            'source_uri': f's3://{bucket}/{original_key}',
            'chunk_index': idx,
            'total_chunks': len(chunks),
            'header': chunk['header'],
            'processing_strategy': 'large_file_claude_parsed',
            'processing_method': 'claude_parser_header_split',
            'upload_date': datetime.utcnow().isoformat()
        }
        
        metadata_header = "---METADATA---\n" + json.dumps(metadata, indent=2, ensure_ascii=False) + "\n---CONTENT---\n"
        full_content = metadata_header + chunk['content']
        
        s3_client.put_object(
            Bucket=bucket,
            Key=processed_key,
            Body=full_content.encode('utf-8'),
            ContentType='text/plain; charset=utf-8'
        )
        
        saved_keys.append(processed_key)
    
    logger.info(f"✓ Saved {len(saved_keys)} chunks")
    return saved_keys


def get_account_id():
    return boto3.client('sts').get_caller_identity()['Account']


def create_opensearch_index_for_bedrock(collection_arn, index_name):
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth
    
    collection_id = collection_arn.split('/')[-1]
    aoss_client = boto3.client('opensearchserverless', region_name=REGION)
    response = aoss_client.batch_get_collection(ids=[collection_id])
    endpoint = response['collectionDetails'][0]['collectionEndpoint'].replace('https://', '')
    
    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, REGION, 'aoss', session_token=credentials.token)
    
    client = OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30
    )
    
    if client.indices.exists(index=index_name):
        logger.info(f"Index exists: {index_name}")
        return True
    
    logger.info(f"Creating index: {index_name}")
    try:
        index_body = {
            "settings": {"index.knn": True},
            "mappings": {
                "properties": {
                    "bedrock-knowledge-base-default-vector": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {"name": "hnsw", "engine": "faiss", "parameters": {}}
                    },
                    "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text"},
                    "AMAZON_BEDROCK_METADATA": {"type": "text"}
                }
            }
        }
        
        client.indices.create(index=index_name, body=index_body)
        logger.info(f"✓ Created index: {index_name}")
        time.sleep(5)
        return True
    except Exception as e:
        logger.error(f"Failed to create index: {e}")
        logger.warning("Index may already exist or permissions issue. Continuing...")
        return False


def wait_for_kb_ready(kb_id, max_wait=300, check_interval=10):
    logger.info(f"Waiting for KB {kb_id}...")
    elapsed = 0
    while elapsed < max_wait:
        try:
            response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=kb_id)
            if response['knowledgeBase']['status'] == 'ACTIVE':
                logger.info(f"KB {kb_id} is ACTIVE")
                return True
            time.sleep(check_interval)
            elapsed += check_interval
        except Exception as e:
            logger.warning(f"Error checking KB: {e}")
            time.sleep(check_interval)
            elapsed += check_interval
    raise Exception(f"KB not ready after {max_wait}s")


def get_opensearch_collection_arn():
    aoss_client = boto3.client('opensearchserverless')
    response = aoss_client.batch_get_collection(names=['kb-collection-1'])
    if response['collectionDetails']:
        return response['collectionDetails'][0]['arn']
    raise Exception("OpenSearch collection 'kb-collection-1' not found")


def get_or_create_kb(bucket_name):
    """Get or create KB with single S3 datasource (processed_docs/small/)"""
    table = dynamodb.Table(REGISTRY_TABLE)
    
    try:
        response = table.get_item(Key={'bucket_name': bucket_name})
        if 'Item' in response:
            kb_id = response['Item']['kb_id']
            ds_small_id = response['Item']['ds_small_id']
            logger.info(f"Found KB: {kb_id}, DS: {ds_small_id}")
            return kb_id, ds_small_id
    except ClientError as e:
        logger.error(f"Error checking registry: {e}")
        raise
    
    logger.info("Creating KB with single S3 datasource (processed_docs/small/)")
    
    timestamp = int(time.time())
    kb_name = f"kb-{bucket_name.replace('techfest-documents-', 'techfest')}-{timestamp}"
    
    collection_arn = get_opensearch_collection_arn()
    index_name = 'bedrock-knowledge-base-default-index'
    
    logger.info("Creating OpenSearch index...")
    create_opensearch_index_for_bedrock(collection_arn, index_name)
    
    logger.info("Waiting for index to be ready...")
    time.sleep(30)
    
    logger.info(f"Creating KB: {kb_name}")
    
    def create_kb():
        return bedrock_agent_client.create_knowledge_base(
            name=kb_name,
            description=f"KB for {bucket_name} - Single datasource (all files in processed_docs/small/)",
            roleArn=f'arn:aws:iam::{get_account_id()}:role/BedrockKnowledgeBaseRole',
            knowledgeBaseConfiguration={
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': f'arn:aws:bedrock:us-east-1::foundation-model/{EMBEDDING_MODEL}'
                }
            },
            storageConfiguration={
                'type': 'OPENSEARCH_SERVERLESS',
                'opensearchServerlessConfiguration': {
                    'collectionArn': collection_arn,
                    'vectorIndexName': index_name,
                    'fieldMapping': {
                        'vectorField': 'bedrock-knowledge-base-default-vector',
                        'textField': 'AMAZON_BEDROCK_TEXT_CHUNK',
                        'metadataField': 'AMAZON_BEDROCK_METADATA'
                    }
                }
            }
        )
    
    kb_response = exponential_backoff_retry(create_kb)
    kb_id = kb_response['knowledgeBase']['knowledgeBaseId']
    logger.info(f"✓ Created KB: {kb_id}")
    
    wait_for_kb_ready(kb_id)
    
    logger.info("Creating S3 datasource for processed_docs/small/...")
    
    def create_ds_small():
        return bedrock_agent_client.create_data_source(
            knowledgeBaseId=kb_id,
            name=f"ds-{bucket_name}-all",
            description="S3 datasource for all processed files - NONE chunking",
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': f'arn:aws:s3:::{bucket_name}',
                    'inclusionPrefixes': ['processed_docs/small/']
                }
            },
            vectorIngestionConfiguration={
                'chunkingConfiguration': {
                    'chunkingStrategy': 'NONE'
                }
            }
        )
    
    ds_small_response = exponential_backoff_retry(create_ds_small)
    ds_small_id = ds_small_response['dataSource']['dataSourceId']
    logger.info(f"✓ Created datasource: {ds_small_id}")
    
    table.put_item(
        Item={
            'bucket_name': bucket_name,
            'kb_id': kb_id,
            'ds_small_id': ds_small_id,
            'index_name': index_name,
            'created_at': datetime.utcnow().isoformat(),
            'kb_name': kb_name,
            'strategy': 'single_datasource_claude_split',
            'processed_path': f's3://{bucket_name}/processed_docs/small/',
            'large_staging_path': f's3://{bucket_name}/original_docs/large/',
            'file_size_threshold': FILE_SIZE_THRESHOLD,
            'claude_parser_model': CLAUDE_MODEL
        }
    )
    
    logger.info("✓ KB saved to registry")
    return kb_id, ds_small_id


def get_unprocessed_files(bucket):
    """Get files in original_docs/ (excluding large subfolder) not yet processed"""
    logger.info(f"Scanning: s3://{bucket}/original_docs/")
    
    original_files = set()
    paginator = s3_client.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=bucket, Prefix='original_docs/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                # Exclude files already in large subfolder
                if not key.startswith('original_docs/large/') and not key.endswith('/') and not key.endswith('.placeholder'):
                    original_files.add(key)
    
    # Check processed small files
    processed_files = set()
    for page in paginator.paginate(Bucket=bucket, Prefix='processed_docs/small/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if not key.endswith('/') and not key.endswith('.placeholder'):
                    original_key = key.replace('processed_docs/small/', 'original_docs/', 1)
                    base_key = os.path.splitext(original_key)[0]
                    for ext in ['.txt', '.pdf', '.docx', '.doc', '.csv', '.xlsx', '.xls', '.md']:
                        processed_files.add(base_key + ext)
    
    # Check large files already moved
    for page in paginator.paginate(Bucket=bucket, Prefix='original_docs/large/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if not key.endswith('/') and not key.endswith('.placeholder'):
                    original_key = key.replace('original_docs/large/', 'original_docs/', 1)
                    processed_files.add(original_key)
    
    unprocessed = original_files - processed_files
    logger.info(f"Original: {len(original_files)}, Processed: {len(processed_files)}, Unprocessed: {len(unprocessed)}")
    return list(unprocessed)


def wait_for_ingestion_job(kb_id, ds_id, job_id, max_wait=600, check_interval=10):
    """Wait for ingestion job to complete"""
    logger.info(f"Waiting for ingestion job {job_id}...")
    elapsed = 0
    while elapsed < max_wait:
        try:
            response = bedrock_agent_client.get_ingestion_job(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id,
                ingestionJobId=job_id
            )
            status = response['ingestionJob']['status']
            if status == 'COMPLETE':
                logger.info(f"✓ Ingestion job {job_id} completed")
                return True
            elif status == 'FAILED':
                logger.error(f"✗ Ingestion job {job_id} failed")
                return False
            time.sleep(check_interval)
            elapsed += check_interval
            logger.info(f"Job status: {status} ({elapsed}s elapsed)")
        except Exception as e:
            logger.warning(f"Error checking job: {e}")
            time.sleep(check_interval)
            elapsed += check_interval
    logger.warning(f"Job did not complete after {max_wait}s")
    return False


def trigger_ingestion_job(kb_id, ds_id, description):
    """Trigger KB sync for datasource"""
    logger.info(f"Triggering KB sync: {description}")
    try:
        response = bedrock_agent_client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            description=description
        )
        logger.info(f"✓ Sync job started: {response['ingestionJob']['ingestionJobId']}")
        return response['ingestionJob']['ingestionJobId']
    except Exception as e:
        logger.error(f"Error starting sync: {e}")
        return None


def get_large_files_to_process(bucket):
    """Get large files in original_docs/large/ not yet processed"""
    logger.info(f"Scanning: s3://{bucket}/original_docs/large/")
    
    large_files = set()
    paginator = s3_client.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=bucket, Prefix='original_docs/large/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if not key.endswith('/') and not key.endswith('.placeholder'):
                    large_files.add(key)
    
    # Check if already processed (check for _part1.txt in processed_docs/small/)
    processed_large_files = set()
    for page in paginator.paginate(Bucket=bucket, Prefix='processed_docs/small/'):
        if 'Contents' in page:
            for obj in page['Contents']:
                key = obj['Key']
                if '_part1.txt' in key:
                    base_name = os.path.basename(key).replace('_part1.txt', '')
                    for ext in ['.pdf', '.png', '.jpg', '.jpeg', '.docx', '.doc']:
                        processed_large_files.add(f"original_docs/large/{base_name}{ext}")
    
    unprocessed = large_files - processed_large_files
    logger.info(f"Large files: {len(large_files)}, Processed: {len(processed_large_files)}, Unprocessed: {len(unprocessed)}")
    return list(unprocessed)


def main():
    logger.info("=== Techfest KB Processor Started ===")
    logger.info(f"Bucket: {BUCKET_NAME}")
    logger.info(f"Threshold: {FILE_SIZE_THRESHOLD / 1024} KB")
    logger.info(f"Small files: Extract → processed_docs/small/")
    logger.info(f"Large files: Move to original_docs/large/ → Claude parse → Split by # → processed_docs/small/")
    
    kb_id, ds_small_id = get_or_create_kb(BUCKET_NAME)
    
    # Process new files in original_docs/
    unprocessed_files = get_unprocessed_files(BUCKET_NAME)
    
    small_files_processed = 0
    large_files_moved = 0
    
    if unprocessed_files:
        logger.info(f"Processing {len(unprocessed_files)} new files...")
        
        for file_key in unprocessed_files:
            try:
                head_response = s3_client.head_object(Bucket=BUCKET_NAME, Key=file_key)
                file_size = head_response['ContentLength']
                
                if file_size < FILE_SIZE_THRESHOLD:
                    logger.info(f"Small file ({file_size / 1024:.2f} KB): {file_key}")
                    document = read_and_preprocess_small_file(BUCKET_NAME, file_key)
                    if document:
                        save_processed_document_to_s3(BUCKET_NAME, file_key, document['content'], document['metadata'])
                        small_files_processed += 1
                else:
                    logger.info(f"Large file ({file_size / 1024:.2f} KB): {file_key}")
                    move_large_file_to_large_folder(BUCKET_NAME, file_key)
                    large_files_moved += 1
                    
            except Exception as e:
                logger.error(f"Error processing {file_key}: {e}")
                continue
        
        logger.info(f"✓ Processed: {small_files_processed} small, {large_files_moved} large moved")
    
    # Process large files in original_docs/large/ with Claude
    large_files_to_parse = get_large_files_to_process(BUCKET_NAME)
    large_files_parsed = 0
    
    if large_files_to_parse:
        logger.info(f"Parsing {len(large_files_to_parse)} large files with Claude...")
        
        for large_file_key in large_files_to_parse:
            try:
                logger.info(f"Processing: {large_file_key}")
                
                # Parse with Claude
                markdown_content = parse_large_file_with_claude(BUCKET_NAME, large_file_key)
                
                # Split by main headers
                chunks = split_markdown_by_main_headers(markdown_content, large_file_key)
                
                # Save chunks to processed_docs/small/
                save_large_file_chunks_to_s3(BUCKET_NAME, large_file_key, chunks)
                
                large_files_parsed += 1
                
            except Exception as e:
                logger.error(f"Error parsing {large_file_key}: {e}")
                continue
        
        logger.info(f"✓ Parsed: {large_files_parsed} large files")
    
    # Trigger sync if any files were processed
    total_processed = small_files_processed + large_files_parsed
    
    if total_processed > 0:
        logger.info(f"Starting KB sync for {total_processed} files...")
        job_id = trigger_ingestion_job(kb_id, ds_small_id, f"Auto-sync: {small_files_processed} small + {large_files_parsed} large parsed")
        if job_id:
            wait_for_ingestion_job(kb_id, ds_small_id, job_id)
    else:
        logger.info("No new files to process")
    
    logger.info("=== Processing Complete ===")


if __name__ == '__main__':
    main()
