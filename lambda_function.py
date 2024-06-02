import sys


def handler(event: dict, context: dict) -> str:
    return 'Hello from AWS Lambda using Python' + sys.version + '!'
