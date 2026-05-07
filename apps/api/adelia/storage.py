import asyncio
from typing import BinaryIO

import boto3
from botocore.client import Config

from adelia.config import settings


class S3Storage:
    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self._bucket = settings.s3_bucket

    async def put_object(self, key: str, body: BinaryIO, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def get_object(self, key: str) -> BinaryIO:
        response = await asyncio.to_thread(
            self._client.get_object, Bucket=self._bucket, Key=key
        )
        return response["Body"]

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
