import os
from logging import getLogger
from typing import Literal
from urllib.parse import urlencode
from uuid import uuid4

import boto3
import botocore.exceptions
from pydantic import BaseModel, ValidationError, computed_field

logger = getLogger()


class YoutubeVideoOptions(BaseModel):
    video_id: str


class YoutubeVideo(BaseModel):
    site: Literal["youtube"]
    options: YoutubeVideoOptions

    @computed_field
    @property
    def url(self) -> str:
        qs = urlencode(
            {
                "v": self.options.video_id,
            },
        )
        return f"https://www.youtube.com/watch?{qs}"


class AmaterusEnqueueDownloadVideoEvent(BaseModel):
    video: YoutubeVideo


class AmaterusEnqueueDownloadVideoSuccessResponse(BaseModel):
    result: Literal["success"]
    message: str


class AmaterusEnqueueDownloadVideoErrorResponse(BaseModel):
    result: Literal["error"]
    message: str


def handler(event: dict, context: dict) -> dict:
    table_name = os.environ.get("AMATERUS_ENQUEUE_DOWNLOAD_VIDEO_TABLE_NAME")
    if table_name is None:
        logger.error(
            "Environment variable 'AMATERUS_ENQUEUE_DOWNLOAD_VIDEO_TABLE_NAME' not set."
        )

        return AmaterusEnqueueDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    queue_url = os.environ.get("AMATERUS_ENQUEUE_DOWNLOAD_VIDEO_QUEUE_URL")
    if queue_url is None:
        logger.error(
            "Environment variable 'AMATERUS_ENQUEUE_DOWNLOAD_VIDEO_QUEUE_URL' not set."
        )

        return AmaterusEnqueueDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    try:
        event_data = AmaterusEnqueueDownloadVideoEvent.model_validate(event)
    except ValidationError as error:
        logger.error("Failed to validate event.")
        logger.exception(error)

        return AmaterusEnqueueDownloadVideoErrorResponse(
            result="error",
            message="Bad request.",
        ).model_dump()

    video = event_data.video

    video_item_id = str(uuid4())
    video_url = video.url

    dynamodb = boto3.client("dynamodb")
    try:
        dynamodb.put_item(
            TableName=table_name,
            Item={
                "Id": {"S", video_item_id},
                "Site": {"S", video.site},
                "Status": {"S", "queuing"},
                "Url": {
                    "S",
                    video_url,
                },
            },
            ConditionExpression="attribute_not_exists(Site) AND attribute_not_exists(Url)",
        )
    except botocore.exceptions.ClientError as error:
        logger.error(f"Failed to create item on DynamoDB table '{table_name}'")
        logger.exception(error)

        return AmaterusEnqueueDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    sqs = boto3.client("sqs")
    try:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=video_item_id,
        )
    except botocore.exceptions.ClientError as error:
        logger.error(f"Failed to send message to SQS queue '{queue_url}'")
        logger.exception(error)

        return AmaterusEnqueueDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    return AmaterusEnqueueDownloadVideoSuccessResponse(
        result="success",
        message="Succeeded.",
    ).model_dump()
