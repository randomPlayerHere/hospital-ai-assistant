import io
import urllib.request
from urllib.error import URLError
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from app.core.config import get_settings
from app.services.storage import LocalStorage, S3Storage, get_storage
from tests.conftest import login_headers
from tests.helpers import by_email

PDF_DATA = b"%PDF-1.4\n%test\n" + b"0" * 100
STAFF_EMAIL = "staff@hospital.example.com"
PATIENT_EMAIL = "patient1@example.com"


@pytest.fixture
def s3_storage_instance():
    s = get_settings()
    old_backend, old_bucket, old_endpoint = (
        s.storage_backend,
        s.s3_bucket,
        s.s3_endpoint_url,
    )
    s.storage_backend = "s3"
    s.s3_bucket = "hospital-test-bucket"
    s.s3_endpoint_url = "https://s3.us-east-1.amazonaws.com"
    storage = S3Storage()
    yield storage
    s.storage_backend = old_backend
    s.s3_bucket = old_bucket
    s.s3_endpoint_url = old_endpoint


async def test_s3_storage_put_unit(s3_storage_instance):
    storage = s3_storage_instance
    with Stubber(storage.client) as stubber:
        expected_params = {
            "Bucket": "hospital-test-bucket",
            "Key": "folder/test.pdf",
            "Body": PDF_DATA,
            "ContentType": "application/pdf",
            "ServerSideEncryption": "AES256",
        }
        stubber.add_response("put_object", {}, expected_params)
        await storage.put("folder/test.pdf", PDF_DATA, "application/pdf")
        stubber.assert_no_pending_responses()


async def test_s3_storage_get_unit(s3_storage_instance):
    storage = s3_storage_instance
    with Stubber(storage.client) as stubber:
        expected_params = {
            "Bucket": "hospital-test-bucket",
            "Key": "folder/test.pdf",
        }
        response = {
            "Body": io.BytesIO(PDF_DATA),
            "ContentLength": len(PDF_DATA),
            "ContentType": "application/pdf",
        }
        stubber.add_response("get_object", response, expected_params)
        data = await storage.get("folder/test.pdf")
        assert data == PDF_DATA
        stubber.assert_no_pending_responses()


async def test_s3_storage_get_not_found(s3_storage_instance):
    storage = s3_storage_instance
    with Stubber(storage.client) as stubber:
        stubber.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            service_message="The specified key does not exist.",
            expected_params={"Bucket": "hospital-test-bucket", "Key": "missing.pdf"},
        )
        with pytest.raises(FileNotFoundError):
            await storage.get("missing.pdf")
        stubber.assert_no_pending_responses()


async def test_s3_storage_delete_unit(s3_storage_instance):
    storage = s3_storage_instance
    with Stubber(storage.client) as stubber:
        expected_params = {
            "Bucket": "hospital-test-bucket",
            "Key": "folder/test.pdf",
        }
        stubber.add_response("delete_object", {}, expected_params)
        await storage.delete("folder/test.pdf")
        stubber.assert_no_pending_responses()


def test_get_storage_factory():
    s = get_settings()
    old_backend = s.storage_backend
    try:
        s.storage_backend = "local"
        get_storage.cache_clear()
        storage_local = get_storage()
        assert isinstance(storage_local, LocalStorage)

        s.storage_backend = "s3"
        get_storage.cache_clear()
        storage_s3 = get_storage()
        assert isinstance(storage_s3, S3Storage)
    finally:
        s.storage_backend = old_backend
        get_storage.cache_clear()


async def test_minio_live_roundtrip():
    """If MinIO is running locally on port 9000, test live bucket creation, upload, get, and delete."""
    endpoint = "http://127.0.0.1:9000"
    try:
        urllib.request.urlopen(f"{endpoint}/minio/health/live", timeout=1)
    except (URLError, OSError):
        pytest.skip("MinIO is not running on localhost:9000; skipping live integration test")

    s = get_settings()
    old_backend, old_bucket, old_endpoint, old_key, old_secret = (
        s.storage_backend,
        s.s3_bucket,
        s.s3_endpoint_url,
        s.s3_access_key,
        s.s3_secret_key,
    )
    bucket = "hospital-live-test"
    try:
        s.storage_backend = "s3"
        s.s3_bucket = bucket
        s.s3_endpoint_url = endpoint
        s.s3_access_key = "minioadmin"
        s.s3_secret_key = "minioadminpassword"
        get_storage.cache_clear()

        storage = S3Storage()
        try:
            storage.client.head_bucket(Bucket=bucket)
        except Exception:
            storage.client.create_bucket(Bucket=bucket)

        key = "live-tests/document.pdf"
        await storage.put(key, PDF_DATA, "application/pdf")

        downloaded = await storage.get(key)
        assert downloaded == PDF_DATA

        await storage.delete(key)
        with pytest.raises(FileNotFoundError):
            await storage.get(key)
    finally:
        s.storage_backend = old_backend
        s.s3_bucket = old_bucket
        s.s3_endpoint_url = old_endpoint
        s.s3_access_key = old_key
        s.s3_secret_key = old_secret
        get_storage.cache_clear()


async def test_document_api_with_s3_backend(client):
    """If MinIO is running, verify full document upload and download HTTP roundtrip using S3."""
    endpoint = "http://127.0.0.1:9000"
    try:
        urllib.request.urlopen(f"{endpoint}/minio/health/live", timeout=1)
    except (URLError, OSError):
        pytest.skip("MinIO is not running on localhost:9000; skipping live API test")

    from app.models import Patient

    pid = (await by_email(Patient, PATIENT_EMAIL)).id
    h = await login_headers(client, STAFF_EMAIL)

    s = get_settings()
    old_backend, old_bucket, old_endpoint, old_key, old_secret = (
        s.storage_backend,
        s.s3_bucket,
        s.s3_endpoint_url,
        s.s3_access_key,
        s.s3_secret_key,
    )
    bucket = "hospital-live-test"
    try:
        s.storage_backend = "s3"
        s.s3_bucket = bucket
        s.s3_endpoint_url = endpoint
        s.s3_access_key = "minioadmin"
        s.s3_secret_key = "minioadminpassword"
        get_storage.cache_clear()

        storage = S3Storage()
        try:
            storage.client.head_bucket(Bucket=bucket)
        except Exception:
            storage.client.create_bucket(Bucket=bucket)

        up = await client.post(
            f"/api/patients/{pid}/documents",
            headers=h,
            files={"file": ("report_s3.pdf", PDF_DATA, "application/pdf")},
            data={"doc_type": "lab_report"},
        )
        assert up.status_code == 201, up.text
        doc = up.json()

        link = (await client.get(f"/api/documents/{doc['id']}/link", headers=h)).json()
        dl = await client.get(link["url"])
        assert dl.status_code == 200
        assert dl.content == PDF_DATA

        del_res = await client.delete(f"/api/documents/{doc['id']}", headers=h)
        assert del_res.status_code == 204
    finally:
        s.storage_backend = old_backend
        s.s3_bucket = old_bucket
        s.s3_endpoint_url = old_endpoint
        s.s3_access_key = old_key
        s.s3_secret_key = old_secret
        get_storage.cache_clear()
