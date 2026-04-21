# function/AzureAIClient.py
import base64
import mimetypes
import json
import requests  # 新增: 用于发送 HTTP 请求
from openai import AzureOpenAI

# --- 核心改动：为不同类型的响应创建专门的流式处理器 ---

def _stream_processor_sdk(response):
    """处理来自 OpenAI Python SDK 的流式响应。"""
    if response:
        for chunk in response:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

def _stream_processor_rest(response):
    """处理来自原生 REST API 的流式响应 (SSE)。"""
    if response:
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data: '):
                    json_str = decoded_line[6:]
                    if json_str.strip() == '[DONE]':
                        return
                    try:
                        data = json.loads(json_str)
                        if data.get('choices'):
                            delta = data['choices'][0].get('delta', {})
                            content = delta.get('content')
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        # 忽略无法解析的行 (例如注释或空行)
                        continue

# --- 公开给 Streamlit 页面的统一流式处理器 ---

def stream_processor(response_object):
    """
    统一的流式处理器。自动检测响应类型并选择正确的解析器。
    这使得 Streamlit 页面可以用同样的方式处理所有模型的流。
    """
    # 如果是 requests 的 Response 对象，则使用 REST 处理器
    if isinstance(response_object, requests.Response):
        yield from _stream_processor_rest(response_object)
    # 否则，假定是 OpenAI SDK 的对象
    else:
        yield from _stream_processor_sdk(response_object)

class AzureAiClient:
    """
    一个封装了 Azure OpenAI 客户端的类，
    支持标准的文本聊天和多模态（文本+图片）聊天。
    【已更新】能自动根据模型名称选择使用 SDK 或 REST API 进行调用。
    """
    def __init__(self, api_key: str, azure_endpoint: str, rest_endpoint: str, api_version: str = "2025-01-01-preview"):
        """
        初始化 Azure OpenAI 客户端。

        参数:
        - api_key (str): 你的 Azure OpenAI API 密钥 (同时用作 REST API 的 Bearer Token)。
        - azure_endpoint (str): 你的 Azure OpenAI 服务端点 (用于 GPT 等模型)。
        - rest_endpoint (str): 你的 Azure AI Studio 模型服务终端节点 (用于 Grok 等模型)。
        - api_version (str): 你想要使用的 OpenAI SDK API 版本。
        """
        if not api_key or not azure_endpoint or not rest_endpoint:
            raise ValueError("Azure API Key, Endpoint, 和 REST Endpoint 不能为空。")
        
        # 1. 初始化用于 GPT 等模型的 OpenAI SDK 客户端
        self.sdk_client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )

        # 2. 存储用于 REST API 调用的凭据和信息
        self.api_key = api_key
        self.rest_endpoint = rest_endpoint
        self.rest_api_version = "2024-05-01-preview" # Grok 模型使用的 API 版本
        self.rest_only_models = ["grok-3", "grok-3-mini"] # 需要通过 REST API 调用的模型列表

    def _get_chat_completion_sdk(self, messages: list, model: str, stream: bool, **kwargs):
        """【内部方法】使用 OpenAI Python SDK 获取聊天响应。"""
        return self.sdk_client.chat.completions.create(
            model=model,
            messages=messages,
            stream=stream,
            **kwargs
        )

# function/AzureAIClient.py

    def _get_chat_completion_rest(self, messages: list, model: str, stream: bool, **kwargs):
        """
        【最终版本】使用 requests 库，并根据您提供的 cURL 命令为不同模型精确设置参数。
        """
        url = f"{self.rest_endpoint}/models/chat/completions?api-version={self.rest_api_version}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # 1. 定义基础载荷
        payload = {
            "messages": messages,
            "model": model,
            "stream": stream,
        }

        # 2. 【核心】根据模型名称，添加其精确支持的参数和默认值
        if model == "grok-3-mini":
            # 参数来自 grok-3-mini 的 cURL 命令
            mini_params = {
                "max_completion_tokens": kwargs.get('max_tokens', 16000), # 默认值为 16000
                "temperature": kwargs.get('temperature', 1.0),
                "top_p": kwargs.get('top_p', 1.0)
            }
            payload.update(mini_params)

        elif model == "grok-3":
            # 参数来自 grok-3 的 cURL 命令
            full_params = {
                "max_completion_tokens": kwargs.get('max_tokens', 2048), # 默认值为 2048
                "temperature": kwargs.get('temperature', 1.0),
                "top_p": kwargs.get('top_p', 1.0),
                "frequency_penalty": kwargs.get('frequency_penalty', 0), # 支持
                "presence_penalty": kwargs.get('presence_penalty', 0)    # 支持
            }
            payload.update(full_params)
            
        else:
            # 为其他未明确指定的 REST 模型提供一个最通用的默认参数集
            default_params = {
                "max_completion_tokens": kwargs.get('max_tokens', 2048),
                "temperature": kwargs.get('temperature', 1.0),
                "top_p": kwargs.get('top_p', 1.0)
            }
            payload.update(default_params)


        # # 调试输出
        # print(f"--- Sending REST API Request for model: {model} ---")
        # print(f"URL: {url}")
        # print(f"Payload: {json.dumps(payload, indent=2)}")
        # print("---------------------------------")
        
        try:
            response = requests.post(url, headers=headers, json=payload, stream=stream)
            response.raise_for_status() 
            return response
        except requests.exceptions.HTTPError as err:
            print(f"HTTP Error Response: {err.response.text}")
            raise err

    def get_chat_completion(self, messages: list, model: str, stream: bool = True, **kwargs):
        """
        获取聊天模型的响应。
        【核心改动】此方法现在是一个分发器，会根据模型名称自动选择正确的调用方式。

        返回:
        - 一个 OpenAI Stream 对象 (来自 SDK)，或一个 requests.Response 对象 (来自 REST API)。
        """
        try:
            if model in self.rest_only_models:
                # 如果是 Grok 模型，调用 REST API 方法
                return self._get_chat_completion_rest(messages, model, stream, **kwargs)
            else:
                # 否则，使用原来的 SDK 方法
                return self._get_chat_completion_sdk(messages, model, stream, **kwargs)
        except Exception as e:
            st.error(f"调用 Azure AI 服务时出错 ({model}): {e}")
            return None

# --- 工具函数 (保持不变) ---
def get_image_base64(uploaded_file) -> str:
    """将 Streamlit 上传的文件对象转换为 Base64 编码的 data URI。"""
    image_bytes = uploaded_file.getvalue()
    mime_type, _ = mimetypes.guess_type(uploaded_file.name)
    if mime_type is None:
        mime_type = "application/octet-stream"  # 默认类型
    base64_encoded_data = base64.b64encode(image_bytes).decode('utf-8')
    return f"data:{mime_type};base64,{base64_encoded_data}"

# 非流式处理器保持原样，但实践中对于 REST API 需要一个新的处理器。
# 为保持简洁，此处省略了非流式 REST 处理器的实现，因为当前应用主要使用流式。
def non_stream_processor(response):
    """处理非流式响应 (仅限 SDK)。"""
    if response and response.choices:
        return response.choices[0].message.content
    return None