import os
from dataclasses import dataclass
from logging import getLogger
from typing import Literal
from uuid import uuid4

import boto3
import botocore.exceptions
from pydantic import BaseModel, ValidationError

logger = getLogger()


class YoutubeVideo(BaseModel):
    site: Literal["youtube"]
    youtube_video_id: str


class AmaterusCreateDownloadVideoEvent(BaseModel):
    video: YoutubeVideo


class AmaterusCreateDownloadVideoSuccessResponse(BaseModel):
    result: Literal["success"]
    message: str


class AmaterusCreateDownloadVideoErrorResponse(BaseModel):
    result: Literal["error"]
    message: str


@dataclass
class PrepareVideoItemResult:
    item: dict
    expression_attribute_names: dict[str, str]
    condition_expression: str


class PrepareVideoItemError(Exception):
    pass


def prepare_youtube_video_item(
    video_item_id: str,
    youtube_video: YoutubeVideo,
) -> PrepareVideoItemResult:
    return PrepareVideoItemResult(
        item={
            "#VideoId": {"S": video_item_id},
            "#Source": {"S": "youtube"},
            "#Status": {"S": "queuing"},
            "#YoutubeVideoId": {"S": youtube_video.youtube_video_id},
        },
        condition_expression=(
            "attribute_not_exists(#Source) AND attribute_not_exists(#YoutubeVideoId)"
        ),
        expression_attribute_names={
            "#VideoId": "VideoId",
            "#Source": "Source",
            "#Status": "Status",
            "#YoutubeVideoId": "YoutubeVideoId",
        },
    )


def lambda_handler(event: dict, context: dict) -> dict:
    table_name = os.environ.get("AMATERUS_CREATE_DOWNLOAD_VIDEO_TABLE_NAME")
    if table_name is None:
        logger.error(
            "Environment variable 'AMATERUS_CREATE_DOWNLOAD_VIDEO_TABLE_NAME' not set."
        )

        return AmaterusCreateDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    queue_url = os.environ.get("AMATERUS_CREATE_DOWNLOAD_VIDEO_QUEUE_URL")
    if queue_url is None:
        logger.error(
            "Environment variable 'AMATERUS_CREATE_DOWNLOAD_VIDEO_QUEUE_URL' not set."
        )

        return AmaterusCreateDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    try:
        event_data = AmaterusCreateDownloadVideoEvent.model_validate(event)
    except ValidationError as error:
        logger.error("Failed to validate event.")
        logger.exception(error)

        return AmaterusCreateDownloadVideoErrorResponse(
            result="error",
            message="Bad request.",
        ).model_dump()

    video = event_data.video
    video_item_id = str(uuid4())

    dynamodb = boto3.client("dynamodb")
    result: PrepareVideoItemResult | None = None
    try:
        if video.site == "youtube":
            result = prepare_youtube_video_item(
                video_item_id=video_item_id,
                youtube_video=video,
            )
        else:
            raise PrepareVideoItemError("Unsupported site.")
    except PrepareVideoItemError as error:
        logger.error("Failed to prepare video item")
        logger.exception(error)

        return AmaterusCreateDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    try:
        dynamodb.put_item(
            TableName=table_name,
            Item=result.item,
            ExpressionAttributeNames=result.expression_attribute_names,
            ConditionExpression=result.condition_expression,
        )
    except botocore.exceptions.ClientError as error:
        logger.error(f"Failed to create item on DynamoDB table '{table_name}'")
        logger.exception(error)

        return AmaterusCreateDownloadVideoErrorResponse(
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

        return AmaterusCreateDownloadVideoErrorResponse(
            result="error",
            message="Internal server error.",
        ).model_dump()

    return AmaterusCreateDownloadVideoSuccessResponse(
        result="success",
        message="Succeeded.",
    ).model_dump()
