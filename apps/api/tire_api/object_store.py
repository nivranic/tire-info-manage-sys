"""Content-addressed immutable writes with verified reads; no caller-controlled paths."""
import base64
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

MAX_OBJECT_BYTES = 8 * 1024 * 1024


class ObjectStoreError(Exception):
    """Sanitized storage failures; provider credentials/paths must not be returned."""


def object_key(digest: str) -> str:
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise ObjectStoreError('invalid_object_digest')
    return f'sha256/{digest[:2]}/{digest}'


def checked(data: bytes, digest: str, size: int) -> bytes:
    object_key(digest)
    if not 0 < size <= MAX_OBJECT_BYTES or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ObjectStoreError('object_integrity_failed')
    return data


def comparable_path(path: Path) -> Path:
    # Windows realpath may retain the extended namespace during a concurrent
    # create/unlink. Normalize only equivalent drive/UNC spellings for comparison;
    # keep the actual resolved target and all containment checks.
    if os.name == 'nt':
        value = path.as_posix()
        if value.startswith('//?/UNC/'):
            return Path('//' + value[8:])
        if re.match(r'^//\?/[A-Za-z]:/', value):
            return Path(value[4:])
    return path


class FileObjectStore:
    backend = 'filesystem'

    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, digest: str) -> Path:
        path = self.root / object_key(digest)
        if not comparable_path(path.resolve()).is_relative_to(comparable_path(self.root)):
            raise ObjectStoreError('object_path_not_allowed')
        return path

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        checked(data, digest, len(data))
        temporary = None
        try:
            target = self.path(digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Resolve again after creating the parent; never follow an existing
            # redirect outside the configured root.
            target = self.path(digest)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.receiving-', delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target)  # Atomic no-overwrite publication.
            except FileExistsError:
                pass
            self.get(digest, len(data))
            return digest
        except ObjectStoreError:
            raise
        except OSError:
            raise ObjectStoreError('object_write_failed') from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Unreferenced temporary files are never exposed as evidence.

    def get(self, digest: str, size: int) -> bytes:
        try:
            with self.path(digest).open('rb') as source:
                return checked(source.read(MAX_OBJECT_BYTES + 1), digest, size)
        except ObjectStoreError:
            raise
        except OSError:
            raise ObjectStoreError('object_unavailable') from None


class S3ObjectStore:
    backend = 's3'

    def __init__(self, client, bucket: str, prefix: str = 'tire-evidence'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
            raise ObjectStoreError('invalid_object_bucket')
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', prefix):
            raise ObjectStoreError('invalid_object_prefix')
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def key(self, digest):
        return self.prefix + '/' + object_key(digest)

    def put(self, data: bytes) -> str:
        from botocore.exceptions import ClientError
        digest = hashlib.sha256(data).hexdigest()
        checked(data, digest, len(data))
        try:
            self.client.put_object(Bucket=self.bucket, Key=self.key(digest), Body=data, IfNoneMatch='*',
                ContentType='application/octet-stream', ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode('ascii'))
        except ClientError as error:
            if error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 412:
                raise ObjectStoreError('object_write_failed') from None
        except Exception:
            raise ObjectStoreError('object_write_failed') from None
        # Also verify existing data after the conditional-write collision.
        self.get(digest, len(data))
        return digest

    def get(self, digest: str, size: int) -> bytes:
        body = None
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=self.key(digest))
            body = result['Body']
            return checked(body.read(MAX_OBJECT_BYTES + 1), digest, size)
        except ObjectStoreError:
            raise
        except Exception:
            raise ObjectStoreError('object_unavailable') from None
        finally:
            if body is not None:
                body.close()


def configured_store(default_root: Path):
    backend = os.getenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    if backend == 'filesystem':
        return FileObjectStore(Path(os.getenv('TI_OBJECT_STORE_ROOT') or default_root))
    if backend != 's3':
        raise ObjectStoreError('unsupported_object_backend')
    access, secret = os.getenv('TI_S3_ACCESS_KEY_ID'), os.getenv('TI_S3_SECRET_ACCESS_KEY')
    if not access or not secret:
        raise ObjectStoreError('object_credentials_required')
    endpoint = os.getenv('TI_S3_ENDPOINT_URL') or None
    if endpoint:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ObjectStoreError('object_endpoint_requires_https')
    import boto3
    from botocore.config import Config
    client = boto3.client('s3', endpoint_url=endpoint, region_name=os.getenv('TI_S3_REGION', 'us-east-1'),
        aws_access_key_id=access, aws_secret_access_key=secret,
        config=Config(connect_timeout=5, read_timeout=10, retries={'max_attempts': 2, 'mode': 'standard'}))
    return S3ObjectStore(client, os.getenv('TI_S3_BUCKET', ''), os.getenv('TI_S3_PREFIX', 'tire-evidence'))
