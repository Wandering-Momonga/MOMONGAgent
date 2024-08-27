import json
import logging
import boto3
import requests
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client('ssm')

# 最後に処理したメッセージのタイムスタンプを保存する変数
last_processed_ts = 0.0

def invoke_bedrock(prompt: str):
    chat = ChatBedrock(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        model_kwargs={"max_tokens": 500},
    )
    messages = [
        SystemMessage(content="""
                      #役割
                      あなたは、可愛いモモンガです。以下の{制約条件}に従って、最高の返答をしてください。
                      #制約条件
                      ・一人称は「僕」であること
                      ・丁寧語は使わないこと
                      ・愛嬌を持って答えること
                      ・正確性より穏やかさを重視すること
                      """),
        HumanMessage(content=prompt),
    ]
    response = chat.invoke(messages)
    return response.content
    
def get_token() -> str:
    res = ssm.get_parameter(
        Name='/Slack/Token/BetaMOMONGA',
        WithDecryption=True
    )
    return res['Parameter']['Value']
    
def message_slack(body: dict, token: str, message: str) -> None:
    global last_processed_ts
    
    channel = body['event']['channel']
    text = body['event']['text']
    timestamp = float(body['event']['event_ts'])
    
    if 'bot_id' in body['event']:
        logger.info("Ignoring message from bot")
        return

    if timestamp <= last_processed_ts:
        logger.info("Ignoring duplicate or old message")
        return
    
    last_processed_ts = timestamp

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    url = 'https://slack.com/api/chat.postMessage'
    
    result = invoke_bedrock(text)
    data = {
        'channel': channel,
        'text': result
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise an error for bad responses
    except requests.exceptions.RequestException as e:
        logger.error(e)
    else:
        logger.info(response.status_code)
        logger.info(response.text)

def lambda_handler(event: dict, context: dict):
    if 'body' in event:
        logger.info(event['body'])
        body = json.loads(event['body'])
    else:
        logger.error("Event does not contain body")
        return {
            'statusCode': 400,
            'body': 'Bad Request'
        }
    
    if 'headers' in event and 'X-Slack-Retry-Num' in event['headers']:
        return {
            'statusCode': 200
        }

    token = get_token()
    message_slack(body, token, 'message')

    return {
        'statusCode': 200,
    }
