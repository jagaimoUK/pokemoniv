#!/usr/bin/env python3
"""S3-compatible -> PRIVATE staging prefix, with conditional copy and readback.

No delete or overwrite operation exists. Plan first; do not run copy until cost
and data transfer approval. The existing Android object/API contract is retained
by preserving relative keys, metadata and content types. Publishing the staging
prefix is a separate, explicitly approved cutover operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def plan(source, bucket, prefix=''):
    items = []
    for page in source.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            items.append({'key': obj['Key'], 'bytes': obj['Size'], 'etag': obj['ETag']})
    items.sort(key=lambda item: item['key'])
    proposal = {'format': 'pokemoniv-object-migration-v1', 'source_bucket': bucket,
                'source_prefix': prefix, 'items': items, 'bytes': sum(x['bytes'] for x in items)}
    return {**proposal, 'plan_sha256': hashlib.sha256(canonical(proposal)).hexdigest()}


def _readback(client, bucket, key, expected_size):
    body = client.get_object(Bucket=bucket, Key=key)['Body']
    checksum, count = hashlib.sha256(), 0
    try:
        while chunk := body.read(1024 * 1024):
            count += len(chunk)
            if count > expected_size:
                raise ValueError('Destination has unexpected size')
            checksum.update(chunk)
    finally:
        body.close()
    if count != expected_size:
        raise ValueError('Destination has incomplete data')
    return checksum.hexdigest()


def copy(source, target, proposal, target_bucket, target_prefix, approved_sha256,
         max_bytes=1024 * 1024 * 1024):
    if (not isinstance(target_prefix, str) or not target_prefix.startswith('migration-')
            or not target_prefix.endswith('/') or '..' in target_prefix or '\\' in target_prefix):
        raise ValueError('Destination must use a dedicated migration-.../ staging prefix')
    if source is target and proposal['source_bucket'] == target_bucket:
        raise ValueError('Source and destination must be isolated')
    check = {k: v for k, v in proposal.items() if k != 'plan_sha256'}
    if (proposal.get('format') != 'pokemoniv-object-migration-v1'
            or hashlib.sha256(canonical(check)).hexdigest() != approved_sha256
            or proposal.get('plan_sha256') != approved_sha256):
        raise ValueError('Unapproved or modified transfer plan')
    if (proposal['bytes'] != sum(x['bytes'] for x in proposal['items']) or proposal['bytes'] > max_bytes
            or len({x['key'] for x in proposal['items']}) != len(proposal['items'])
            or any(x['bytes'] < 0 or x['bytes'] > 5 * 1024**3 for x in proposal['items'])):
        raise ValueError('Object migration exceeds reviewed byte limit or is invalid')
    if plan(source, proposal['source_bucket'], proposal['source_prefix']) != proposal:
        raise ValueError('Source changed since plan; create and review a fresh plan')
    verified = []
    for item in proposal['items']:
        response = source.get_object(Bucket=proposal['source_bucket'], Key=item['key'], IfMatch=item['etag'])
        body = response['Body']
        with tempfile.TemporaryFile() as payload:
            checksum, count = hashlib.sha256(), 0
            try:
                while chunk := body.read(1024 * 1024):
                    count += len(chunk)
                    if count > item['bytes']:
                        raise ValueError('Source size changed during transfer')
                    checksum.update(chunk)
                    payload.write(chunk)
            finally:
                body.close()
            if count != item['bytes']:
                raise ValueError('Source is incomplete')
            sha = checksum.hexdigest()
            destination_key = target_prefix + item['key']
            payload.seek(0)
            metadata = {**response.get('Metadata', {}), 'pokemoniv-sha256': sha}
            extra = {key: response[key] for key in ('ContentType', 'CacheControl', 'ContentDisposition')
                     if key in response}
            try:
                # Conditional create is essential: HEAD then PUT is a race.
                target.put_object(Bucket=target_bucket, Key=destination_key, Body=payload,
                                  ContentLength=count, Metadata=metadata, IfNoneMatch='*', **extra)
            except Exception as exc:
                status = getattr(exc, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode')
                if status not in (409, 412):
                    raise
                # The common readback below also verifies resumable collisions.
            if _readback(target, target_bucket, destination_key, count) != sha:
                raise ValueError('Destination checksum mismatch; staging must NOT be published')
            verified.append({'source_key': item['key'], 'staged_key': destination_key,
                             'bytes': count, 'sha256': sha})
    if plan(source, proposal['source_bucket'], proposal['source_prefix']) != proposal:
        raise ValueError('Source changed during copy; staging must NOT be published')
    return {'format': 'pokemoniv-object-verification-v1', 'plan_sha256': approved_sha256,
            'verified': True, 'published': False, 'objects': verified}


def client_from_env(prefix):
    import boto3
    from botocore.config import Config
    endpoint = os.environ[prefix + '_ENDPOINT']
    if urlparse(endpoint).scheme != 'https' or urlparse(endpoint).username or urlparse(endpoint).password:
        raise ValueError('Storage endpoint must use HTTPS without embedded credentials')
    return boto3.client('s3', endpoint_url=endpoint,
                        aws_access_key_id=os.environ[prefix + '_ACCESS_KEY_ID'],
                        aws_secret_access_key=os.environ[prefix + '_SECRET_ACCESS_KEY'],
                        region_name=os.environ.get(prefix + '_REGION', 'auto'),
                        config=Config(connect_timeout=10, read_timeout=60,
                                      retries={'max_attempts': 2},
                                      s3={'addressing_style': os.environ.get(prefix + '_STYLE', 'path')}))


def private_json(path, data):
    path = Path(path)
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        json.dump(data, output, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'copy'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--source-prefix', default='')
    parser.add_argument('--target-prefix')
    parser.add_argument('--approved-plan-sha256')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--max-bytes', type=int, default=1024 * 1024 * 1024)
    args = parser.parse_args()
    source = client_from_env('SOURCE_S3')
    if args.action == 'plan':
        proposal = plan(source, os.environ['SOURCE_S3_BUCKET'], args.source_prefix)
        private_json(args.plan, proposal)
        print(json.dumps({'objects': len(proposal['items']), 'bytes': proposal['bytes'],
                          'plan_sha256': proposal['plan_sha256'], 'writes': 0}))
    else:
        if not args.report or args.report.exists() or not args.approved_plan_sha256 or not args.target_prefix:
            parser.error('copy requires a NEW --report, --target-prefix and --approved-plan-sha256')
        result = copy(source, client_from_env('TARGET_S3'), json.loads(args.plan.read_text()),
                      os.environ['TARGET_S3_BUCKET'], args.target_prefix,
                      args.approved_plan_sha256, args.max_bytes)
        private_json(args.report, result)
        print(json.dumps({'objects': len(result['objects']), 'verified': True, 'published': False}))


if __name__ == '__main__':
    main()
