import asyncio

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosClientError, CosServiceError

logger = get_logger(__name__)


class CosClient:
    def __init__(self):
        if not settings.cos_configured:
            raise ConfigurationError("腾讯云 COS 未配置，请在 .env 中填写 COS_* 变量")

        config = CosConfig(
            Region=settings.cos_region,
            SecretId=settings.cos_secret_id,
            SecretKey=settings.cos_secret_key,
        )

        self._client = CosS3Client(config)
        self._bucket = settings.cos_bucket

    async def ping(self) -> bool:
        """通过 head_bucket 验证凭据与桶的可达性"""
        try:
            await asyncio.to_thread(self._client.head_bucket, self._bucket)
            return True
        except (CosClientError, CosServiceError) as exc:
            logger.warning("COS ping failed : %s", exc)
            return False

    @property
    def bucket(self):
        return self._bucket

    @property
    def region(self):
        return settings.cos_region

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )

    async def get_object(self, key: str) -> bytes:
        def _read() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].get_raw_stream().read()

        return await asyncio.to_thread(_read)


_cos_client: CosClient | None = None


def get_cos_client() -> CosClient:
    """lazy init"""
    global _cos_client
    if _cos_client is None:
        _cos_client = CosClient()
    return _cos_client
