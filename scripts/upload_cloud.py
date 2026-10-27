#!/usr/bin/env python3
"""Upload an immutable file to S3 with resumable parts and integrity checks.

Requires boto3. Credentials come from the usual SDK environment/profile, or an
explicit private JSON file. Never commit that file or the upload state.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output, indent=2)
        output.write('\n')
    os.replace(temporary, path)


def verify(client, path, bucket, key, size, digest):
    head = client.head_object(Bucket=bucket, Key=key)
    if head['ContentLength'] != size or head.get('Metadata', {}).get('sha256') != digest:
        raise ValueError('Existing object does not match size/SHA-256 metadata; refusing overwrite')
    length = min(65536, size)
    with path.open('rb') as source:
        for offset in sorted({0, max(0, size // 2 - length // 2), size - length}):
            end = offset + length - 1
            response = client.get_object(Bucket=bucket, Key=key, Range=f'bytes={offset}-{end}')
            try:
                if response.get('ContentRange') != f'bytes {offset}-{end}/{size}':
                    raise ValueError('Invalid verification range')
                data = response['Body'].read(length + 1)
            finally:
                response['Body'].close()
            source.seek(offset)
            if data != source.read(length):
                raise ValueError('Remote verification range differs from local file')


def upload_part_with_retry(client, *, sleep=time.sleep, **parameters):
    for attempt in range(6):
        try:
            return client.upload_part(**parameters)
        except Exception as error:
            # Cloud.ru's nonstandard 499 is not retried by the SDK. Reusing a
            # part number replaces only that part, with the same checked bytes.
            status = getattr(error, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode')
            if status != 499 or attempt == 5:
                raise
            number = parameters['PartNumber']
            print(f'Part {number}: server closed request; retry {attempt + 1}/5', flush=True)
            sleep(min(20, 2 ** attempt) + number % 3)


def main():
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', type=Path)
    p.add_argument('--key', required=True)
    p.add_argument('--bucket', default='nuray-scenes')
    p.add_argument('--endpoint', default='https://s3.cloud.ru')
    p.add_argument('--region', default='ru-central-1')
    p.add_argument('--addressing-style', choices=('path', 'virtual'), default='path')
    p.add_argument('--credentials-file', type=Path)
    p.add_argument('--state-dir', type=Path, default=Path('.local/uploads'))
    p.add_argument('--part-mib', type=int, default=8)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--content-type', default='application/octet-stream')
    p.add_argument('--sha256', help='Expected local checksum, if already recorded')
    args = p.parse_args()
    if not 5 <= args.part_mib <= 64 or not 1 <= args.workers <= 64:
        p.error('Use parts of 5–64 MiB and 1–64 workers')
    path = args.file.resolve()
    size = path.stat().st_size
    if size <= 0:
        p.error('File must not be empty')
    digest = sha256(path)
    if args.sha256 and args.sha256 != digest:
        raise ValueError('Local file checksum differs from the release manifest')
    credentials = {}
    if args.credentials_file:
        if args.credentials_file.stat().st_mode & 0o077:
            raise ValueError('Credentials file must be private (chmod 600)')
        secret = json.loads(args.credentials_file.read_text())
        key_id = secret['accessKeyId']
        if secret.get('tenantId') and not key_id.startswith(secret['tenantId']):
            key_id = secret['tenantId'] + ':' + key_id
        credentials = {'aws_access_key_id': key_id, 'aws_secret_access_key': secret['secretAccessKey']}
    client = boto3.client('s3', endpoint_url=args.endpoint, region_name=args.region,
        config=Config(signature_version='s3v4', s3={'addressing_style': args.addressing_style},
                      connect_timeout=20, read_timeout=120, max_pool_connections=args.workers + 2,
                      retries={'mode': 'standard', 'max_attempts': 5},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'), **credentials)
    try:
        client.head_object(Bucket=args.bucket, Key=args.key)
    except ClientError as error:
        if error.response['Error']['Code'] not in ('404', 'NoSuchKey', 'NotFound'):
            raise
    else:
        verify(client, path, args.bucket, args.key, size, digest)
        print('Already uploaded and verified:', args.key, flush=True)
        return

    part_size = args.part_mib * 1024 * 1024
    identity = {'endpoint': args.endpoint, 'bucket': args.bucket, 'key': args.key,
                'bytes': size, 'sha256': digest, 'partSize': part_size}
    state_path = args.state_dir / (hashlib.sha256((args.bucket + '/' + args.key).encode()).hexdigest() + '.json')
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if any(state.get(k) != value for k, value in identity.items()):
            raise ValueError('Upload state belongs to a different file or configuration')
    else:
        result = client.create_multipart_upload(Bucket=args.bucket, Key=args.key,
            ContentType=args.content_type, StorageClass='SINGLE', Metadata={'sha256': digest})
        state = {**identity, 'uploadId': result['UploadId']}
        save_state(state_path, state)
    upload_id = state['uploadId']
    completed = {}
    paginator = client.get_paginator('list_parts')
    for page in paginator.paginate(Bucket=args.bucket, Key=args.key, UploadId=upload_id):
        for part in page.get('Parts', []):
            completed[part['PartNumber']] = part
    count = (size + part_size - 1) // part_size
    # ETags of these explicit Content-MD5 uploads must match the source parts.
    pending = []
    with path.open('rb') as source:
        for number in range(1, count + 1):
            data = source.read(part_size)
            prior = completed.get(number)
            if prior and prior['Size'] == len(data) and prior['ETag'].strip('"') == hashlib.md5(data).hexdigest():
                continue
            pending.append(number)
    print(f'{args.key}: {size / 1e6:.1f} MB, {count - len(pending)}/{count} parts already verified', flush=True)

    def send(number):
        with path.open('rb') as source:
            source.seek((number - 1) * part_size)
            data = source.read(part_size)
        md5 = hashlib.md5(data).digest()
        result = upload_part_with_retry(client, Bucket=args.bucket, Key=args.key, UploadId=upload_id,
            PartNumber=number, Body=data, ContentLength=len(data), ContentMD5=base64.b64encode(md5).decode())
        if result['ETag'].strip('"') != md5.hex():
            raise ValueError(f'Part {number} checksum mismatch')
        return {'PartNumber': number, 'ETag': result['ETag'], 'Size': len(data)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(send, number) for number in pending]
        failures = []
        for future in concurrent.futures.as_completed(futures):
            try:
                part = future.result()
            except Exception as error:
                failures.append(error)
                print(f'A part exhausted retries ({type(error).__name__}); continuing other parts', flush=True)
                continue
            completed[part['PartNumber']] = part
            print(f'{len(completed)}/{count} parts verified', flush=True)
    if failures:
        raise RuntimeError(f'{len(failures)} parts still missing; rerun the same command to resume') from failures[0]
    client.complete_multipart_upload(Bucket=args.bucket, Key=args.key, UploadId=upload_id,
        MultipartUpload={'Parts': [{'PartNumber': n, 'ETag': completed[n]['ETag']} for n in range(1, count + 1)]})
    verify(client, path, args.bucket, args.key, size, digest)
    state_path.unlink()
    print('Uploaded and verified:', args.key, flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        raise SystemExit(1)
