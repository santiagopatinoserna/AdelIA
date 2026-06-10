import io
import pytest
from adelia.storage import S3Storage


@pytest.fixture
def s3_storage():
    return S3Storage()


async def test_put_and_get_object(s3_storage):
    key = "test/sample.txt"
    body = b"hello adelia"
    await s3_storage.put_object(key, io.BytesIO(body), content_type="text/plain")

    retrieved = await s3_storage.get_object(key)
    assert retrieved.read() == body

    await s3_storage.delete_object(key)


async def test_generate_presigned_url(s3_storage):
    key = "test/presigned.txt"
    await s3_storage.put_object(key, io.BytesIO(b"x"), content_type="text/plain")

    url = await s3_storage.generate_presigned_url(key, expires_in=60)
    assert "test/presigned.txt" in url
    assert "X-Amz-Signature" in url

    await s3_storage.delete_object(key)
