import json
import logging
import boto3
import requests
from langchain_aws import ChatBedrock
from langchain_aws.retrievers import AmazonKnowledgeBasesRetriever
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client('ssm')

# 最後に処理したメッセージのタイムスタンプを保存する変数
last_processed_ts = 0.0

# Slackのメッセージに「モモンガくん」が含まれているか
def is_reaction_message(body: dict) -> bool:
    return 'モモンガくん' in body['event']['text']

def invoke_bedrock(prompt: str):
    retriever = AmazonKnowledgeBasesRetriever(
        knowledge_base_id="MDQPVNFIVK",  # ナレッジベースID
        retrieval_config={"vectorSearchConfiguration": {"numberOfResults": 10}},
    )
    
    # ナレッジベースから情報を取得
    retrieved_docs = retriever.get_relevant_documents(prompt)
    relevant_info = " ".join(doc.page_content for doc in retrieved_docs)
    
    # プロンプトのテンプレートを定義
    formatted_prompt = ChatPromptTemplate.from_template(
        """
        #役割
        あなたは、とても親しみやすいモモンガです。
        
        #命令文
        以下の「制約条件」に従って、「入力」に対して最高の返答をしてください。
        #制約条件
        ・一人称は「僕」である
        ・丁寧語は使わない
        ・愛嬌がある
        ・正確性より可愛げを重視する

        # 入力:
        {user_input}

        # 情報:
        {relevant_info}
        """
    ).format(user_input=prompt, relevant_info=relevant_info)

    # LLMを指定
    model = ChatBedrock(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        model_kwargs={"max_tokens": 400},
    )

    response = model.invoke([HumanMessage(content=formatted_prompt)])
    return response.content

    
def get_token() -> str:
    res = ssm.get_parameter(
        Name='/Slack/Token/MOMONGAgent',
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
        'text': result,
        'thread_ts': body['event']['event_ts']
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
    
    # APIリクエストを再実行させない魔法の呪文
    if 'headers' in event and 'X-Slack-Retry-Num' in event['headers']:
        return {
            'statusCode': 200
        }

    if is_reaction_message(body) is False:
        return

    token = get_token()
    message_slack(body, token, 'message')

    return {
        'statusCode': 200,
    }
